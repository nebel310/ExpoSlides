"use strict";

(() => {
  const API = window.EXPOSLIDES_API || "";
  const MAX_TEMPLATE_BYTES = 50 * 1024 * 1024;
  const MAX_SCRIPT_LENGTH = 100_000;
  const POLL_INTERVAL_MS = 15_000;

  const SCRIPT_SAMPLE =
    "Квартальный обзор команды продукта. За квартал мы упростили первый запуск, " +
    "обновили справочный раздел и собрали обратную связь от клиентов.\n\n" +
    "Что изменилось. В продукте появился короткий вводный сценарий. " +
    "Инструкции собраны в одном разделе, а заявки поддержки теперь проходят " +
    "через единый список приоритетов.\n\n" +
    "Ключевые результаты. Команда выпустила обновлённый первый запуск, " +
    "подготовила базу знаний и провела интервью с клиентами. " +
    "Основной запрос клиентов — понятный путь от знакомства до первого результата.\n\n" +
    "Следующий квартал. Проверим новый вводный сценарий с клиентами, " +
    "дополним базу знаний и настроим сбор обратной связи внутри продукта.\n\n" +
    "Главное. Сосредоточимся на понятном первом опыте и будем выбирать " +
    "следующие изменения на основе обратной связи от клиентов.";

  const STATUS_LABELS = {
    queued: "В очереди",
    generating_content: "Готовим текст",
    building: "Собираем PPTX",
    done: "Готово",
    failed: "Ошибка",
  };

  const STATUS_DESCRIPTIONS = {
    queued: "Задача принята, ждёт обработки.",
    generating_content: "Модель готовит текст слайдов.",
    building: "Собираем презентацию из шаблона и текста.",
    done: "Все выбранные форматы готовы к скачиванию.",
    failed: "Не удалось собрать презентацию.",
  };

  const WORKFLOW_STEP = {
    queued: 1,
    generating_content: 1,
    building: 1,
    done: 2,
    failed: 0,
  };

  const $ = (id) => document.getElementById(id);

  const els = {
    dropzone: $("dropzone"),
    templateInput: $("template-input"),
    selectedTemplate: $("selected-template"),
    templateName: $("template-name"),
    templateMeta: $("template-meta"),
    removeTemplate: $("remove-template"),
    uploadTitle: $("upload-title"),
    uploadSubtitle: $("upload-subtitle"),
    script: $("script"),
    scriptCount: $("script-count"),
    scriptSource: $("script-source"),
    scriptInput: $("script-input"),
    importButton: $("import-button"),
    maxSlides: $("max-slides"),
    formatPdf: $("format-pdf"),
    formatHtml: $("format-html"),
    form: $("presentation-form"),
    generate: $("generate-button"),
    generateLabel: $("generate-label"),
    actionHint: $("action-hint"),
    errorMessage: $("error-message"),
    taskList: $("task-list"),
    emptyPreview: $("empty-preview"),
    tasksCounter: $("tasks-counter"),
    refreshTasks: $("refresh-tasks"),
    helpButton: $("help-button"),
    helpDialog: $("help-dialog"),
    closeHelp: $("close-help"),
    helpDone: $("help-done"),
    toast: $("toast"),
    viewMaterials: $("view-materials"),
    viewPreview: $("view-preview"),
    mobileTaskCount: $("mobile-task-count"),
    workspace: document.querySelector(".workspace"),
    workflow: document.querySelectorAll(".workflow li"),
    generationView: $("generation-view"),
  };

  const state = {
    sid: null,
    socket: null,
    templateFileId: null,
    templateName: null,
    templateMeta: null,
    tasks: new Map(),
    busy: false,
    uploading: false,
    focusedTaskId: null,
  };

  let toastTimer = null;
  let pollTimer = null;

  function plural(number, forms) {
    const n = Math.abs(number) % 100;
    if (n > 10 && n < 20) return forms[2];
    const last = n % 10;
    if (last === 1) return forms[0];
    if (last > 1 && last < 5) return forms[1];
    return forms[2];
  }

  function escapeHtml(value) {
    return String(value ?? "").replace(/[&<>"']/g, (c) => ({
      "&": "&amp;",
      "<": "&lt;",
      ">": "&gt;",
      '"': "&quot;",
      "'": "&#39;",
    }[c]));
  }

  function fmtBytes(bytes) {
    if (!bytes) return "0 Б";
    if (bytes < 1024) return `${bytes} Б`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} КБ`;
    return `${(bytes / 1024 / 1024).toFixed(1)} МБ`;
  }

  function notify(message) {
    if (!els.toast) return;
    els.toast.textContent = message;
    els.toast.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { els.toast.hidden = true; }, 4000);
  }

  function showError(message, focus = false) {
    if (!els.errorMessage) return;
    els.errorMessage.textContent = message;
    els.errorMessage.hidden = false;
    if (focus) els.errorMessage.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }

  function clearError() {
    if (!els.errorMessage) return;
    els.errorMessage.hidden = true;
    els.errorMessage.textContent = "";
  }

  async function request(path, options = {}) {
    const response = await fetch(API + path, {
      credentials: "include",
      ...options,
    });
    if (response.status === 204) return null;
    let data = null;
    const contentType = response.headers.get("content-type") || "";
    if (contentType.includes("application/json")) {
      try { data = await response.json(); } catch (_) { data = null; }
    }
    if (!response.ok) {
      const detail = (data && (data.detail || data.error)) || `HTTP ${response.status}`;
      const error = new Error(detail);
      error.status = response.status;
      throw error;
    }
    return data;
  }

  async function bootstrapSession() {
    try {
      const data = await request("/api/session/bootstrap", { method: "POST" });
      state.sid = data.sid;
      return true;
    } catch (error) {
      showError("Не удалось создать сессию. Проверьте, что gateway запущен.");
      return false;
    }
  }

  async function uploadFile(file) {
    const form = new FormData();
    form.append("file", file, file.name);
    const response = await fetch(API + "/api/files/upload", {
      method: "POST",
      credentials: "include",
      body: form,
    });
    let data = null;
    try { data = await response.json(); } catch (_) { data = null; }
    if (!response.ok) {
      const detail = (data && (data.detail || data.error)) || `HTTP ${response.status}`;
      const error = new Error(detail);
      error.status = response.status;
      throw error;
    }
    return data;
  }

  async function downloadFile(fileId, filename) {
    try {
      const response = await fetch(`${API}/api/files/${encodeURIComponent(fileId)}`, {
        credentials: "include",
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = filename;
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      setTimeout(() => URL.revokeObjectURL(url), 2000);
    } catch (error) {
      notify("Не удалось скачать файл: " + error.message);
    }
  }

  function setWorkflowStep(step) {
    els.workflow.forEach((element, index) => {
      element.classList.toggle("is-current", index === step);
      element.classList.toggle("is-done", index < step);
      if (index === step) element.setAttribute("aria-current", "step");
      else element.removeAttribute("aria-current");
    });
  }

  function computeWorkflowStep() {
    const tasks = Array.from(state.tasks.values());
    if (!tasks.length) return 0;
    const active = tasks.find((t) => t.status === "queued"
      || t.status === "generating_content" || t.status === "building");
    if (active) return WORKFLOW_STEP[active.status] ?? 1;
    const done = tasks.some((t) => t.status === "done");
    if (done) return 2;
    return 0;
  }

  function updateWorkflow() {
    setWorkflowStep(computeWorkflowStep());
  }

  function updateGenerateState() {
    const hasTemplate = Boolean(state.templateFileId);
    const hasScript = els.script.value.trim().length > 0;
    const ready = hasTemplate && hasScript && !state.busy && !state.uploading;
    els.generate.disabled = !ready;
    if (state.uploading) els.actionHint.textContent = "Читаем файл шаблона…";
    else if (state.busy) els.actionHint.textContent = "Создаём задачу…";
    else if (!hasTemplate && !hasScript) els.actionHint.textContent = "Добавьте шаблон и текст, чтобы начать";
    else if (!hasTemplate) els.actionHint.textContent = "Добавьте PPTX-шаблон";
    else if (!hasScript) els.actionHint.textContent = "Добавьте текст доклада";
    else els.actionHint.textContent = "Готово к запуску";
  }

  function updateScriptCount() {
    const count = els.script.value.length;
    els.scriptCount.textContent = `${count.toLocaleString("ru-RU")} ${plural(count, ["символ", "символа", "символов"])}`;
  }

  function setUploading(flag) {
    state.uploading = flag;
    els.dropzone.disabled = flag;
    updateGenerateState();
  }

  async function handleTemplateFile(file) {
    if (!file || state.busy || state.uploading) return;
    if (!file.name.toLowerCase().endsWith(".pptx")) {
      showError("Нужен файл с расширением .pptx.");
      return;
    }
    if (file.size > MAX_TEMPLATE_BYTES) {
      showError("Шаблон больше 50 МБ. Загрузите файл меньшего размера.");
      return;
    }
    if (!file.size) {
      showError("Файл пуст. Выберите другой шаблон.");
      return;
    }
    clearError();
    setUploading(true);
    els.uploadTitle.textContent = "Читаем ваш шаблон…";
    try {
      const result = await uploadFile(file);
      state.templateFileId = result.file_id;
      state.templateName = file.name;
      state.templateMeta = `${fmtBytes(file.size)} · PowerPoint`;
      els.templateName.textContent = state.templateName;
      els.templateMeta.textContent = state.templateMeta;
      els.selectedTemplate.hidden = false;
      els.dropzone.hidden = true;
      notify("Шаблон загружен");
    } catch (error) {
      showError("Не удалось загрузить шаблон: " + error.message);
    } finally {
      setUploading(false);
      els.uploadTitle.textContent = "Выберите файл";
      els.templateInput.value = "";
      updateGenerateState();
    }
  }

  function clearTemplate() {
    if (state.busy || state.uploading) return;
    state.templateFileId = null;
    state.templateName = null;
    state.templateMeta = null;
    els.selectedTemplate.hidden = true;
    els.dropzone.hidden = false;
    els.templateInput.value = "";
    clearError();
    updateGenerateState();
  }

  function importScriptFile(file) {
    if (!file) return;
    if (!file.name.toLowerCase().endsWith(".txt")) {
      showError("Нужен файл с расширением .txt.");
      return;
    }
    if (file.size > 400_000) {
      showError("Файл слишком большой. Используйте до 100 000 символов.");
      return;
    }
    const reader = new FileReader();
    reader.onerror = () => showError("Не удалось прочитать файл.");
    reader.onload = () => {
      let text;
      try {
        text = new TextDecoder("utf-8", { fatal: true }).decode(reader.result);
      } catch (_) {
        showError("Не удалось прочитать текст. Сохраните файл в кодировке UTF-8.");
        return;
      }
      if (!text.trim()) {
        showError("Этот текстовый файл пуст.");
        return;
      }
      if (text.length > MAX_SCRIPT_LENGTH) {
        showError("Текст слишком большой. Используйте до 100 000 символов.");
        return;
      }
      if (els.script.value.trim() && !confirm("Заменить текущий текст содержимым файла?")) return;
      clearError();
      els.script.value = text;
      if (els.scriptSource) els.scriptSource.textContent = file.name;
      updateScriptCount();
      updateGenerateState();
      notify("Текст загружен");
    };
    reader.readAsArrayBuffer(file);
  }

  function loadScriptExample() {
    if (els.script.value.trim() && !confirm("Заменить текущий текст примером?")) return;
    clearError();
    els.script.value = SCRIPT_SAMPLE;
    if (els.scriptSource) els.scriptSource.textContent = "Пример · квартальный обзор";
    updateScriptCount();
    updateGenerateState();
    notify("Пример текста открыт. Загрузите PPTX-шаблон, чтобы начать.");
  }

  function updateMaxSlidesOptions() {
    if (!els.maxSlides) return;
    els.maxSlides.replaceChildren(new Option("Автоматически", ""));
    els.maxSlides.disabled = true;
  }

  function collectFormats() {
    const formats = ["pptx"];
    if (els.formatPdf && els.formatPdf.checked) formats.push("pdf");
    if (els.formatHtml && els.formatHtml.checked) formats.push("html");
    return formats;
  }

  async function uploadScriptAsFile() {
    const text = els.script.value.trim();
    if (!text) throw new Error("Текст пуст");
    const blob = new Blob([text], { type: "text/plain;charset=utf-8" });
    const file = new File([blob], "script.txt", { type: "text/plain" });
    const result = await uploadFile(file);
    return result.file_id;
  }

  async function createTask(event) {
    if (event) event.preventDefault();
    if (state.busy || state.uploading) return;
    clearError();
    if (!state.templateFileId) {
      showError("Сначала добавьте PPTX-шаблон.", true);
      els.dropzone.focus();
      return;
    }
    if (!els.script.value.trim()) {
      showError("Добавьте текст для презентации.", true);
      els.script.focus();
      return;
    }

    state.busy = true;
    els.generateLabel.textContent = "Отправляем…";
    updateGenerateState();

    try {
      const scriptFileId = await uploadScriptAsFile();
      const formats = collectFormats();
      const data = await request("/api/tasks", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          template_file_id: state.templateFileId,
          script_file_id: scriptFileId,
          formats,
        }),
      });
      if (data && data.task_id) {
        state.tasks.set(data.task_id, {
          task_id: data.task_id,
          status: "queued",
          template_file_id: state.templateFileId,
          script_file_id: scriptFileId,
          formats,
          extra_files: {},
          created_at: Date.now() / 1000,
          updated_at: Date.now() / 1000,
        });
        state.focusedTaskId = data.task_id;
        renderTasks();
        clearTemplate();
        els.script.value = "";
        if (els.scriptSource) els.scriptSource.textContent = "Текст доклада";
        updateScriptCount();
        notify("Задача создана");
        await loadTasks();
      }
    } catch (error) {
      showError("Не удалось создать задачу: " + error.message);
    } finally {
      state.busy = false;
      els.generateLabel.textContent = "Создать презентацию";
      updateGenerateState();
    }
  }

  async function loadTasks() {
    try {
      const data = await request("/api/tasks");
      const incoming = new Map();
      for (const task of data.tasks || []) {
        incoming.set(task.task_id, task);
      }
      state.tasks = incoming;
      renderTasks();
    } catch (error) {
      if (error.status === 401) {
        state.sid = null;
        await bootstrapSession();
        return;
      }
      if (!state.tasks.size) {
        showError("Не удалось получить список задач.");
      }
    }
  }

  function renderTasks() {
    const tasks = Array.from(state.tasks.values())
      .sort((a, b) => (b.created_at || 0) - (a.created_at || 0));

    if (els.tasksCounter) els.tasksCounter.textContent = String(tasks.length);
    if (els.mobileTaskCount) {
      els.mobileTaskCount.textContent = tasks.length ? String(tasks.length) : "";
    }

    if (!tasks.length) {
      if (els.emptyPreview) els.emptyPreview.hidden = false;
      if (els.taskList) {
        els.taskList.hidden = true;
        els.taskList.innerHTML = "";
      }
      updateWorkflow();
      return;
    }

    if (els.emptyPreview) els.emptyPreview.hidden = true;
    if (els.taskList) {
      els.taskList.hidden = false;
      els.taskList.innerHTML = tasks.map(renderTask).join("");
      attachDownloadHandlers();
    }
    updateWorkflow();
  }

  function renderTask(task) {
    const status = task.status || "queued";
    const label = STATUS_LABELS[status] || status;
    const desc = STATUS_DESCRIPTIONS[status] || "";
    const shortId = task.task_id ? task.task_id.slice(0, 8) : "—";
    const isActive = status === "queued"
      || status === "generating_content"
      || status === "building";
    const extras = task.extra_files || {};
    const downloads = [];

    if (status === "done" && task.result_file_id) {
      downloads.push(
        `<a href="#" class="task-download" data-download="${escapeHtml(task.result_file_id)}" data-name="presentation.pptx">PPTX</a>`
      );
    }
    for (const [fmt, fileId] of Object.entries(extras)) {
      if (!fileId) continue;
      downloads.push(
        `<a href="#" class="task-download" data-download="${escapeHtml(fileId)}" data-name="presentation.${escapeHtml(fmt)}">${escapeHtml(fmt.toUpperCase())}</a>`
      );
    }

    const errorBlock = status === "failed" && task.error
      ? `<div class="task-error">${escapeHtml(task.error)}</div>`
      : "";
    const progress = isActive ? `<div class="task-progress"></div>` : "";
    const actions = downloads.length
      ? `<div class="task-actions">${downloads.join("")}</div>`
      : "";

    return `
      <li class="task-card" data-status="${escapeHtml(status)}" data-task-id="${escapeHtml(task.task_id || "")}">
        <div class="task-head">
          <span class="task-id">${escapeHtml(shortId)}</span>
          <span class="task-status">${escapeHtml(label)}</span>
        </div>
        <p class="task-desc">${escapeHtml(desc)}</p>
        ${progress}
        ${errorBlock}
        ${actions}
      </li>
    `;
  }

  function attachDownloadHandlers() {
    if (!els.taskList) return;
    els.taskList.querySelectorAll("[data-download]").forEach((link) => {
      link.addEventListener("click", (event) => {
        event.preventDefault();
        const fileId = link.getAttribute("data-download");
        const name = link.getAttribute("data-name") || "result";
        if (fileId) downloadFile(fileId, name);
      });
    });
  }

  function handleTaskEvent(event, payload) {
    if (!payload || !payload.task_id) return;
    const current = state.tasks.get(payload.task_id) || {
      task_id: payload.task_id,
      created_at: Date.now() / 1000,
    };
    current.status = payload.status || current.status;
    current.updated_at = Date.now() / 1000;
    const inner = payload.payload || {};
    if (inner.structure_file_id) current.structure_file_id = inner.structure_file_id;
    if (inner.content_file_id) current.content_file_id = inner.content_file_id;
    if (inner.result_file_id) current.result_file_id = inner.result_file_id;
    if (inner.extra_files) current.extra_files = inner.extra_files;
    if (inner.error) current.error = inner.error;
    state.tasks.set(payload.task_id, current);
    renderTasks();
    if (event === "task.built") notify("Готово. Файлы можно скачать.");
    if (event === "task.failed") notify("Задача завершилась с ошибкой.");
  }

  function connectSocket() {
    if (!state.sid || typeof io !== "function") return;
    if (state.socket) {
      state.socket.disconnect();
      state.socket = null;
    }
    const socket = io(API || undefined, {
      path: "/ws/",
      transports: ["websocket", "polling"],
      auth: { sid: state.sid },
      withCredentials: true,
    });
    state.socket = socket;
    for (const event of ["task.parsed", "task.content_ready", "task.built", "task.failed"]) {
      socket.on(event, (payload) => handleTaskEvent(event, payload));
    }
    socket.on("connect_error", (error) => {
      console.warn("WebSocket connect_error", error && error.message);
    });
  }

  function setMobileView(view) {
    if (!els.workspace) return;
    els.workspace.dataset.view = view;
    if (els.viewMaterials) els.viewMaterials.setAttribute("aria-pressed", String(view === "materials"));
    if (els.viewPreview) els.viewPreview.setAttribute("aria-pressed", String(view === "preview"));
  }

  function bindEvents() {
    if (els.dropzone) {
      els.dropzone.addEventListener("click", () => els.templateInput && els.templateInput.click());
      els.dropzone.addEventListener("dragenter", (event) => {
        event.preventDefault();
        if (!state.busy && !state.uploading) els.dropzone.classList.add("is-dragging");
      });
      els.dropzone.addEventListener("dragover", (event) => event.preventDefault());
      els.dropzone.addEventListener("dragleave", () => els.dropzone.classList.remove("is-dragging"));
      els.dropzone.addEventListener("drop", (event) => {
        event.preventDefault();
        els.dropzone.classList.remove("is-dragging");
        const file = event.dataTransfer && event.dataTransfer.files[0];
        if (file) handleTemplateFile(file);
      });
    }
    if (els.templateInput) {
      els.templateInput.addEventListener("change", (event) => {
        const file = event.target.files && event.target.files[0];
        if (file) handleTemplateFile(file);
      });
    }
    if (els.removeTemplate) els.removeTemplate.addEventListener("click", clearTemplate);

    if (els.script) {
      els.script.addEventListener("input", () => {
        if (els.scriptSource) els.scriptSource.textContent = "Текст доклада";
        updateScriptCount();
        updateGenerateState();
      });
    }

    if (els.importButton && els.scriptInput) {
      els.importButton.addEventListener("click", () => els.scriptInput.click());
      els.scriptInput.addEventListener("change", (event) => {
        const file = event.target.files && event.target.files[0];
        if (file) importScriptFile(file);
        event.target.value = "";
      });
    }

    const exampleButton = document.getElementById("example-button");
    if (exampleButton) exampleButton.addEventListener("click", loadScriptExample);

    if (els.form) els.form.addEventListener("submit", createTask);
    if (els.refreshTasks) els.refreshTasks.addEventListener("click", loadTasks);

    if (els.helpButton && els.helpDialog) els.helpButton.addEventListener("click", () => els.helpDialog.showModal());
    if (els.closeHelp && els.helpDialog) els.closeHelp.addEventListener("click", () => els.helpDialog.close());
    if (els.helpDone && els.helpDialog) els.helpDone.addEventListener("click", () => els.helpDialog.close());

    if (els.viewMaterials) els.viewMaterials.addEventListener("click", () => setMobileView("materials"));
    if (els.viewPreview) els.viewPreview.addEventListener("click", () => setMobileView("preview"));

    window.addEventListener("online", () => { clearError(); loadTasks(); });
    window.addEventListener("offline", () => showError("Нет подключения к интернету."));
  }

  async function start() {
    bindEvents();
    updateScriptCount();
    updateMaxSlidesOptions();
    updateGenerateState();
    setWorkflowStep(0);

    const ok = await bootstrapSession();
    if (!ok) return;

    await loadTasks();
    connectSocket();

    pollTimer = setInterval(loadTasks, POLL_INTERVAL_MS);
    window.addEventListener("beforeunload", () => {
      if (pollTimer) clearInterval(pollTimer);
      if (state.socket) state.socket.disconnect();
    });
  }

  document.addEventListener("DOMContentLoaded", start);
})();