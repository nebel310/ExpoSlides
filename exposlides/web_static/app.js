"use strict";

const $ = (id) => document.getElementById(id);
const state = { token: null, template: null, result: null, resultLoading: false, resultError: null, slide: 0, busy: false, uploading: false, job: null };
const activity = { inspectTemplate: false, paused: false, connectionLost: false };
const script = $("script");
const form = $("presentation-form");
const stageOrder = ["parser", "content", "builder"];
let toastTimeout;
let pollTimer;
let previewPollTimer;
let previewRevision = 0;
let resultPollTimer;
let resultRevision = 0;
let thumbnailRevision = "";
const failedPreviewImages = new Set();
const library = { persistent: null, templates: [], jobs: [], loading: false, error: null };
let libraryRevision = 0;
let selectionRevision = 0;
const libraryButtons = [];

function updateLibraryControls() {
  $("library-refresh").disabled = library.loading;
  $("library-panel").setAttribute("aria-busy", String(library.loading));
  for (const { button, kind, id } of libraryButtons) {
    button.disabled = state.busy || state.uploading;
    const selected = kind === "template" ? state.template?.id === id && !state.job
      : state.job?.id === id;
    button.setAttribute("aria-pressed", String(selected));
  }
}

function openSavedResult(job) {
  if (state.busy || state.uploading) return;
  selectionRevision++;
  clearError();
  clearTimeout(pollTimer);
  sessionStorage.setItem("exposlides-job", job.id);
  renderJob(job);
  setWorkspaceView("preview");
}

function renderLibrary() {
  $("library-panel").hidden = library.persistent !== true;
  $("library-status").textContent = library.error || (library.loading ? "Обновляем список…" : "");
  $("library-status").hidden = !library.error && !library.loading;
  if (library.persistent !== null) {
    $("help-storage").textContent = library.persistent
      ? "Шаблоны и готовые презентации сохраняются в хранилище и доступны в разделе «Сохранённые файлы» после перезапуска приложения."
      : "Файлы доступны до остановки локального приложения. Скачайте результат перед закрытием сервера.";
  }
  libraryButtons.length = 0;
  for (const [kind, items, listId, emptyText] of [
    ["template", library.templates, "library-templates", "Загруженные шаблоны появятся здесь."],
    ["job", library.jobs, "library-results", "Готовые презентации появятся здесь."],
  ]) {
    $(listId).replaceChildren(...items.map((item) => {
      const row = document.createElement("li");
      row.className = "library-item";
      const button = document.createElement("button");
      button.type = "button";
      button.className = "library-open";
      const title = document.createElement("strong");
      title.textContent = item.name || "Презентация";
      const description = document.createElement("span");
      description.textContent = `${item.slide_count} ${plural(item.slide_count, ["слайд", "слайда", "слайдов"])} · ${kind === "template" ? "Выбрать шаблон" : "Открыть результат"}`;
      button.append(title, description);
      button.addEventListener("click", () => {
        if (state.busy || state.uploading) return;
        if (kind === "template") {
          clearError();
          applyTemplate(item);
          if (item.preview?.status !== "pending") pollTemplatePreview(item.id);
        } else openSavedResult(item);
      });
      libraryButtons.push({ button, kind, id: item.id });
      row.append(button);
      if (kind === "job") {
        const download = document.createElement("a");
        download.className = "library-download";
        download.href = `/api/jobs/${encodeURIComponent(item.id)}/download`;
        download.setAttribute("download", "presentation.pptx");
        download.setAttribute("aria-label", `Скачать ${item.name || "презентацию"}`);
        download.textContent = "↓";
        row.append(download);
      }
      return row;
    }));
    const empty = $(`${listId}-empty`);
    empty.textContent = emptyText;
    empty.hidden = items.length > 0;
  }
  updateLibraryControls();
}

async function refreshLibrary() {
  const revision = ++libraryRevision;
  library.loading = true;
  library.error = null;
  renderLibrary();
  try {
    const saved = await request("/api/library");
    if (revision !== libraryRevision) return;
    library.persistent = saved.persistent === true;
    library.templates = saved.templates || [];
    library.jobs = saved.jobs || [];
  } catch {
    if (revision !== libraryRevision) return;
    library.error = "Не удалось обновить сохранённые файлы. Попробуйте ещё раз.";
  } finally {
    if (revision === libraryRevision) { library.loading = false; renderLibrary(); }
  }
}

function previewPresentation() {
  return state.job?.status === "completed" ? state.result : state.template;
}

function previewHeading() {
  if (state.job?.status === "completed") return "Готовая презентация";
  return ["pending", "ready"].includes(state.template?.preview?.status)
    ? "Предпросмотр шаблона" : "Структура шаблона";
}

function generationCopy(job = state.job) {
  if (job?.stage === "content") {
    const progress = job.progress || {};
    let copy = ({
      analysis: ["Разбираем исходный текст", "Выделяем основные мысли и факты для презентации."],
      planning: ["Составляем план слайдов", "Подбираем макеты и распределяем материал."],
      slides: ["Наполняем слайды", "Готовим текст для выбранных макетов."],
      validation: ["Проверяем содержание", "Проверяем факты, длину текста и соответствие плану."],
    })[progress.phase] || ["Подготавливаем содержание", "Анализируем текст, составляем план и заполняем слайды. Ответы модели могут занимать несколько минут."];
    if (progress.phase === "slides" && Number.isInteger(progress.current) && Number.isInteger(progress.total)
      && progress.current > 0 && progress.current <= progress.total) {
      copy = [`Заполняем слайд ${progress.current} из ${progress.total}`, "Готовим текст и проверяем его для этого слайда."];
    }
    if (progress.retrying) copy = [copy[0], "Повторяем запрос к модели. Предыдущая попытка не завершилась успешно или ответ не прошёл проверку."];
    return copy;
  }
  return ({
    parser: ["Изучаем ваш шаблон", "Разбираем макеты и структуру слайдов."],
    builder: ["Собираем презентацию", "Сохраняем оформление и проверяем готовый PowerPoint."],
  })[job?.stage] || ["Готовим презентацию", "Подготавливаем материалы для слайдов."];
}

function beginActivity({ showPreview = false } = {}) {
  activity.inspectTemplate = false;
  activity.paused = false;
  activity.connectionLost = false;
  $("toast").hidden = true;
  if (showPreview) {
    setWorkspaceView("preview");
    if (window.matchMedia("(max-width: 760px)").matches) {
      $("view-preview").focus({ preventScroll: true });
    }
  }
}

function renderActivity() {
  const active = state.busy || state.uploading;
  const visible = active && !activity.inspectTemplate;
  $("generation-view").hidden = !visible;
  $("slide-preview").hidden = visible;
  $("canvas-footer").hidden = visible;
  $("activity-toggle").hidden = !active || !state.template;
  $("activity-toggle").textContent = visible ? "Показать шаблон" : "Вернуться к сборке";
  $("preview-heading").textContent = visible
    ? state.uploading ? "Загрузка шаблона" : "Создание презентации"
    : previewHeading();
  const completed = state.job?.status === "completed";
  $("result-download").hidden = !completed;
  if (completed) $("result-download").href = `/api/jobs/${encodeURIComponent(state.job.id)}/download`;
  $("generation-view").classList.toggle("is-paused", activity.paused);
  $("motion-toggle").setAttribute("aria-pressed", String(activity.paused));
  $("motion-label").textContent = activity.paused ? "Продолжить анимацию" : "Приостановить анимацию";
  if (active) {
    let copy;
    if (activity.connectionLost) copy = ["Проверяем соединение", "Ждём ответа приложения. Состояние сборки обновится, когда связь восстановится."];
    else if (state.uploading) copy = ["Открываем ваш шаблон", "Читаем слайды и находим текстовые блоки."];
    else copy = generationCopy();
    if ($("generation-title").textContent !== copy[0]) $("generation-title").textContent = copy[0];
    if ($("generation-description").textContent !== copy[1]) $("generation-description").textContent = copy[1];
  }
  requestAnimationFrame(fitSlide);
}

function setWorkspaceView(view) {
  $("workspace").dataset.view = view;
  $("view-materials").setAttribute("aria-pressed", String(view === "materials"));
  $("view-preview").setAttribute("aria-pressed", String(view === "preview"));
  requestAnimationFrame(fitSlide);
}

function fitSlide() {
  const stage = document.querySelector(".canvas-stage");
  if (!stage.clientWidth) return;
  const style = getComputedStyle(stage);
  const width = stage.clientWidth - parseFloat(style.paddingLeft) - parseFloat(style.paddingRight);
  const height = stage.clientHeight - parseFloat(style.paddingTop) - parseFloat(style.paddingBottom);
  const presentation = previewPresentation();
  const ratio = presentation?.width > 0 && presentation?.height > 0
    ? presentation.width / presentation.height : 16 / 9;
  const maxWidth = window.matchMedia("(max-width: 760px)").matches ? width : Math.min(width, height * ratio);
  $("slide-preview").style.width = `${Math.max(1, Math.min(maxWidth, 1120))}px`;
}

function plural(number, forms) {
  const n = Math.abs(number) % 100;
  return forms[n > 10 && n < 20 ? 2 : n % 10 === 1 ? 0 : n % 10 > 1 && n % 10 < 5 ? 1 : 2];
}

function notify(message) {
  $("toast").textContent = message;
  $("toast").hidden = false;
  clearTimeout(toastTimeout);
  toastTimeout = setTimeout(() => { $("toast").hidden = true; }, 4500);
}

function showError(message, focus = false) {
  $("error-message").textContent = message;
  $("error-message").hidden = false;
  if (focus) $("error-message").scrollIntoView({ block: "nearest", behavior: "smooth" });
}

function clearError() { $("error-message").hidden = true; }

async function request(path, body) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 45000);
  try {
    const response = await fetch(path, {
      method: body === undefined ? "GET" : "POST",
      headers: body === undefined ? {} : { "Content-Type": "application/json", "X-ExpoSlides-Token": state.token },
      body: body === undefined ? undefined : JSON.stringify(body),
      signal: controller.signal,
    });
    if (response.status === 403) state.token = null;
    const data = await response.json();
    if (!response.ok) {
      const error = new Error(data.error || "Не удалось выполнить запрос. Попробуйте ещё раз.");
      error.status = response.status;
      throw error;
    }
    return data;
  } catch (error) {
    if (error.name === "AbortError") throw new Error("Сервер долго не отвечает. Проверьте подключение к интернету и попробуйте ещё раз.");
    if (error instanceof TypeError) throw new Error("Не удалось связаться с сервером. Проверьте подключение к интернету и попробуйте ещё раз.");
    throw error;
  } finally { clearTimeout(timeout); }
}

async function ensureSession({ refresh = false } = {}) {
  if (refresh || !state.token) state.token = (await request("/api/session")).token;
}

function setWorkflow(step) {
  ["materials", "generation", "result"].forEach((name, index) => {
    const element = $(`step-${name}`);
    element.classList.toggle("is-current", index === step);
    element.classList.toggle("is-done", index < step);
    if (index === step) element.setAttribute("aria-current", "step");
    else element.removeAttribute("aria-current");
  });
}

function updateControls() {
  const locked = state.busy || state.uploading;
  const ready = Boolean(state.template && script.value.trim());
  $("generate-button").disabled = locked || !ready;
  ["dropzone", "remove-template", "import-button", "example-button", "max-slides", "template-input", "script-input"].forEach((id) => { $(id).disabled = locked; });
  script.readOnly = locked;
  form.setAttribute("aria-busy", String(locked));
  $("generate-label").textContent = state.busy ? "Создаём презентацию…" : state.job?.status === "failed" ? "Попробовать снова" : state.job?.status === "completed" ? "Создать ещё раз" : "Создать презентацию";
  $("action-hint").textContent = state.busy ? "Можно просматривать шаблон, пока идёт сборка" : state.uploading ? "Читаем файл шаблона…" : ready ? "Текст и структура шаблона будут отправлены модели Qwen" : !state.template && !script.value.trim() ? "Добавьте шаблон и текст, чтобы начать" : !state.template ? "Добавьте шаблон презентации" : "Добавьте текст для слайдов";
  const count = script.value.length;
  $("script-count").textContent = `${count.toLocaleString("ru-RU")} ${plural(count, ["символ", "символа", "символов"])}`;
  updateLibraryControls();
  renderActivity();
}

function clearFinishedJob() {
  if (!state.busy && state.job) {
    clearTimeout(resultPollTimer);
    resultRevision++;
    state.result = null;
    state.resultLoading = false;
    state.resultError = null;
    state.slide = 0;
    state.job = null;
    sessionStorage.removeItem("exposlides-job");
    $("job-panel").hidden = true;
    $("download-button").hidden = true;
    setWorkflow(0);
    renderPreview();
  }
}

async function loadResultPresentation(jobId, revision = ++resultRevision, failures = 0) {
  const current = () => state.job?.id === jobId && state.job.status === "completed" && revision === resultRevision;
  if (!current()) return;
  try {
    const presentation = await request(`/api/jobs/${encodeURIComponent(jobId)}/presentation`);
    if (!current()) return;
    state.result = presentation;
    state.resultLoading = false;
    state.resultError = null;
    renderPreview();
    renderActivity();
    if (presentation.preview?.status === "pending") pollResultPreview(jobId, revision);
  } catch {
    if (!current()) return;
    if (failures < 3) {
      resultPollTimer = setTimeout(() => loadResultPresentation(jobId, revision, failures + 1), 2000);
    } else {
      state.resultLoading = false;
      state.resultError = "Не удалось открыть просмотр. Готовую презентацию можно скачать.";
      renderPreview();
      renderActivity();
    }
  }
}

async function pollResultPreview(jobId, revision, failures = 0) {
  const current = () => state.job?.id === jobId && state.job.status === "completed" && state.result?.id === jobId && revision === resultRevision;
  if (!current()) return;
  try {
    const preview = await request(`/api/jobs/${encodeURIComponent(jobId)}/preview`);
    if (!current()) return;
    state.result.preview = preview;
    renderPreview();
    renderActivity();
    if (preview.status === "pending") resultPollTimer = setTimeout(() => pollResultPreview(jobId, revision), 1200);
  } catch {
    if (!current()) return;
    if (failures < 3) {
      resultPollTimer = setTimeout(() => pollResultPreview(jobId, revision, failures + 1), 2000);
    } else {
      state.result.preview = { status: "failed", message: "Не удалось загрузить изображения. Показан текст готовой презентации." };
      renderPreview();
      renderActivity();
    }
  }
}

function applyTemplate(template) {
  selectionRevision++;
  clearTimeout(previewPollTimer);
  previewRevision++;
  failedPreviewImages.clear();
  clearFinishedJob();
  state.template = template;
  state.slide = 0;
  $("dropzone").hidden = true;
  $("selected-template").hidden = false;
  $("template-name").textContent = template.name;
  $("template-meta").textContent = `${template.slide_count} ${plural(template.slide_count, ["слайд", "слайда", "слайдов"])} · PowerPoint`;
  $("max-slides").replaceChildren(new Option("Автоматически", ""));
  for (let i = 1; i <= template.slide_count; i++) $("max-slides").add(new Option(`Не больше ${i}`, String(i)));
  renderPreview();
  updateControls();
  if (template.preview?.status === "pending") pollTemplatePreview(template.id);
}

async function pollTemplatePreview(templateId, revision = previewRevision, failures = 0) {
  if (state.template?.id !== templateId || revision !== previewRevision) return;
  try {
    const preview = await request(`/api/templates/${encodeURIComponent(templateId)}/preview`);
    if (state.template?.id !== templateId || revision !== previewRevision) return;
    const changed = JSON.stringify(state.template.preview) !== JSON.stringify(preview);
    state.template.preview = preview;
    if (changed) { renderPreview(); renderActivity(); }
    if (preview.status === "pending") {
      previewPollTimer = setTimeout(() => pollTemplatePreview(templateId, revision), 1200);
    }
  } catch {
    if (state.template?.id !== templateId || revision !== previewRevision) return;
    if (failures < 3) {
      previewPollTimer = setTimeout(() => pollTemplatePreview(templateId, revision, failures + 1), 2000);
    } else {
      state.template.preview = { status: "failed", message: "Не удалось загрузить изображения слайдов. Пока показываем текстовую схему." };
      renderPreview();
      renderActivity();
    }
  }
}

function renderPreview() {
  const completed = state.job?.status === "completed";
  const template = previewPresentation();
  const pending = completed && state.resultLoading || template?.preview?.status === "pending";
  const imageUrl = template?.preview?.status === "ready" ? template.preview.slides?.[state.slide] : null;
  const showImage = Boolean(imageUrl && !failedPreviewImages.has(imageUrl));
  $("empty-preview").hidden = Boolean(template) || pending;
  $("empty-preview-title").textContent = completed ? "Презентация готова" : "Здесь будут ваши слайды";
  $("empty-preview-description").textContent = completed ? state.resultError || "Открываем готовую презентацию…" : "Добавьте PPTX в панели материалов или откройте пример.";
  $("preview-loading-description").textContent = completed
    ? "Подготавливаем изображения готовой презентации. PPTX уже можно скачать."
    : "Фон, изображения и оформление появятся здесь. Вы уже можете добавить текст для презентации.";
  $("slide-content").hidden = !template || pending || showImage;
  $("preview-loading").hidden = !pending;
  $("rendered-slide").hidden = !showImage;
  if (!showImage) $("rendered-slide").removeAttribute("src");
  $("preview-navigation").hidden = !template;
  $("thumbnails").hidden = !template;
  const count = template?.slide_count ?? (completed ? state.job.slide_count : 0);
  $("preview-counter").textContent = count ? `${count} ${plural(count, ["слайд", "слайда", "слайдов"])}` : "Нет шаблона";
  $("mobile-slide-count").textContent = count || "";
  $("thumbnails").setAttribute("aria-label", completed ? "Слайды готовой презентации" : "Слайды шаблона");
  if (!template) {
    thumbnailRevision = "";
    $("thumbnails").replaceChildren();
    $("preview-caption").textContent = completed
      ? state.resultError || "Открываем готовую презентацию…"
      : "Оформление исходного PPTX сохранится при сборке";
    requestAnimationFrame(fitSlide);
    return;
  }
  const slides = template.slides;
  state.slide = Math.max(0, Math.min(state.slide, slides.length - 1));
  const slide = slides[state.slide];
  if (showImage) {
    $("rendered-slide").alt = `Слайд ${slide.index}: ${slide.title || "Без заголовка"}`;
    if ($("rendered-slide").getAttribute("src") !== imageUrl) $("rendered-slide").src = imageUrl;
  }
  $("preview-caption").textContent = pending
    ? completed ? "Подготавливаем изображения готовой презентации" : "Подготавливаем изображения слайдов · Можно продолжать работу с материалами"
    : showImage ? `${completed ? "Готовая презентация" : "Предпросмотр исходного шаблона"} · Шрифты могут немного отличаться от PowerPoint`
    : imageUrl ? "Изображение не загрузилось. Показана текстовая схема слайда."
    : template.preview?.message ? `Текстовая схема · ${template.preview.message}`
    : completed ? "Текст готовой презентации · Полное оформление доступно в PPTX"
    : "Текстовая схема · Оформление исходного PPTX сохранится при сборке";
  $("slide-number").textContent = String(slide.index).padStart(2, "0");
  $("slide-title").textContent = slide.title || `Слайд ${slide.index}`;
  const paragraphs = slide.texts.filter((text) => text.trim() && text.trim() !== (slide.title || "").trim());
  $("slide-texts").replaceChildren(...paragraphs.slice(0, 3).map((text) => {
    const paragraph = document.createElement("p");
    paragraph.textContent = text;
    return paragraph;
  }));
  $("slide-type").textContent = slide.placeholder_count ? `${slide.placeholder_count} ${plural(slide.placeholder_count, ["текстовый блок", "текстовых блока", "текстовых блоков"])}` : "Без текстовых заполнителей";
  $("slide-position").textContent = `${state.slide + 1} из ${slides.length}`;
  $("previous-slide").disabled = state.slide === 0;
  $("next-slide").disabled = state.slide === slides.length - 1;
  if (template.width > 0 && template.height > 0) $("slide-preview").style.aspectRatio = `${template.width} / ${template.height}`;
  const nextThumbnailRevision = `${completed ? "result" : "template"}/${template.id}/${template.preview?.status}`;
  if (thumbnailRevision !== nextThumbnailRevision) {
    const focusedThumbnail = $("thumbnails").contains(document.activeElement)
      ? Array.from($("thumbnails").children).indexOf(document.activeElement) : -1;
    $("thumbnails").replaceChildren(...slides.map((item, index) => {
      const button = document.createElement("button");
      button.className = "thumbnail";
      button.type = "button";
      button.setAttribute("aria-label", `Слайд ${item.index}: ${item.title || "Без заголовка"}`);
      button.setAttribute("aria-pressed", String(index === state.slide));
      const number = document.createElement("span");
      number.className = "thumbnail-number";
      number.textContent = String(item.index).padStart(2, "0");
      const title = document.createElement("span");
      title.className = "thumbnail-title";
      title.textContent = item.title || `Слайд ${item.index}`;
      const thumbnailUrl = template.preview?.status === "ready" ? template.preview.slides?.[index] : null;
      if (thumbnailUrl && !failedPreviewImages.has(thumbnailUrl)) {
        const thumbnail = document.createElement("img");
        thumbnail.className = "thumbnail-image";
        thumbnail.alt = "";
        thumbnail.loading = "lazy";
        thumbnail.src = thumbnailUrl;
        button.classList.add("has-image");
        button.style.aspectRatio = `${template.width} / ${template.height}`;
        thumbnail.addEventListener("error", () => {
          failedPreviewImages.add(thumbnailUrl);
          button.classList.remove("has-image");
          button.replaceChildren(number, title);
        }, { once: true });
        button.append(thumbnail, number);
      } else {
        button.append(number, title);
      }
      button.addEventListener("click", () => { state.slide = index; renderPreview(); $("thumbnails").children[index].focus({ preventScroll: true }); });
      return button;
    }));
    thumbnailRevision = nextThumbnailRevision;
    if (focusedThumbnail >= 0) $("thumbnails").children[focusedThumbnail]?.focus({ preventScroll: true });
  }
  Array.from($("thumbnails").children).forEach((button, index) => button.setAttribute("aria-pressed", String(index === state.slide)));
  $("thumbnails").children[state.slide]?.scrollIntoView({ block: "nearest", inline: "nearest" });
  requestAnimationFrame(fitSlide);
}

$("rendered-slide").addEventListener("error", () => {
  const url = $("rendered-slide").getAttribute("src");
  if (!url) return;
  failedPreviewImages.add(url);
  renderPreview();
});

async function uploadTemplate(file) {
  if (!file || state.busy || state.uploading) return;
  clearError();
  if (!file.name.toLowerCase().endsWith(".pptx")) { showError("Нужен файл PowerPoint в формате .pptx."); return; }
  if (file.size > 25 * 1024 * 1024) { showError("Шаблон слишком большой. Максимальный размер — 25 МБ."); return; }
  if (!file.size) { showError("Этот файл пуст. Выберите другой шаблон."); return; }
  state.uploading = true;
  selectionRevision++;
  beginActivity();
  $("upload-title").textContent = "Читаем ваш шаблон…";
  updateControls();
  try {
    const data = await new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(reader.result.split(",")[1]);
      reader.onerror = () => reject(new Error("Не удалось прочитать файл. Выберите его ещё раз."));
      reader.readAsDataURL(file);
    });
    await ensureSession({ refresh: true });
    applyTemplate(await request("/api/templates", { name: file.name, data }));
    refreshLibrary();
    notify("Шаблон загружен");
  } catch (error) { setWorkspaceView("materials"); showError(error.message); }
  finally {
    state.uploading = false;
    $("upload-title").textContent = "Выберите файл";
    $("template-input").value = "";
    updateControls();
  }
}

async function loadExample() {
  if (state.busy || state.uploading) return;
  if ((state.template || script.value.trim()) && !confirm("Заменить текущий шаблон и текст встроенным примером?")) return;
  state.uploading = true;
  selectionRevision++;
  beginActivity();
  clearError();
  updateControls();
  try {
    const example = await request("/api/example");
    applyTemplate(example);
    script.value = example.script;
    $("script-source").textContent = "Пример · квартальный обзор";
    refreshLibrary();
    notify("Пример открыт. Текст можно изменить.");
  } catch (error) { setWorkspaceView("materials"); showError(error.message); }
  finally { state.uploading = false; updateControls(); }
}

const sessionJobs = new Map();
const backgroundTimers = new Map();

function rememberJob(job) {
  sessionJobs.set(job.id, job);
  sessionStorage.setItem("exposlides-jobs", JSON.stringify([...sessionJobs.keys()]));
  $("parallel-panel").hidden = false;
  $("parallel-jobs").replaceChildren();
  for (const item of sessionJobs.values()) {
    const row = document.createElement("li");
    const button = document.createElement("button");
    button.type = "button";
    const label = item.status === "completed" ? "Готово" : item.status === "failed" ? "Ошибка" : "Создаётся";
    button.textContent = `Презентация ${[...sessionJobs.keys()].indexOf(item.id) + 1} · ${label}`;
    button.addEventListener("click", () => {
      if (state.uploading || (state.busy && !state.job)) return;
      const previous = state.job;
      selectionRevision++;
      clearTimeout(pollTimer);
      if (previous && previous.id !== item.id) watchBackgroundJob(previous.id);
      sessionStorage.setItem("exposlides-job", item.id);
      renderJob(item);
      if (state.busy) pollJob(item.id);
    });
    row.append(button);
    $("parallel-jobs").append(row);
  }
}

async function watchBackgroundJob(id) {
  clearTimeout(backgroundTimers.get(id));
  try {
    const job = await request(`/api/jobs/${encodeURIComponent(id)}`);
    rememberJob(job);
    if (job.status !== "running" && job.status !== "queued") return;
  } catch (error) {
    if (error.status >= 400 && error.status < 500) return;
  }
  backgroundTimers.set(id, setTimeout(() => watchBackgroundJob(id), 2000));
}

$("new-presentation").addEventListener("click", () => {
  if (state.uploading || (state.busy && !state.job)) return;
  const previous = state.job;
  selectionRevision++;
  clearTimeout(pollTimer);
  state.busy = false;
  clearFinishedJob();
  setWorkspaceView("materials");
  updateControls();
  if (previous) watchBackgroundJob(previous.id);
});

function renderJob(job) {
  rememberJob(job);
  const changed = state.job?.id !== job.id || state.job?.stage !== job.stage || state.job?.status !== job.status;
  state.job = job;
  state.busy = job.status === "running" || job.status === "queued";
  $("job-panel").hidden = false;
  $("job-panel").classList.toggle("is-failed", job.status === "failed");
  $("activity-indicator").classList.toggle("is-complete", job.status === "completed");
  $("download-button").hidden = job.status !== "completed";
  if (job.status === "completed") {
    setWorkflow(2);
    $("job-title").textContent = "Презентация готова";
    $("job-description").textContent = `${job.slide_count} ${plural(job.slide_count, ["слайд", "слайда", "слайдов"])} в редактируемом PowerPoint. Проверьте результат перед выступлением.`;
    $("download-button").href = `/api/jobs/${encodeURIComponent(job.id)}/download`;
    $("download-button").setAttribute("download", "presentation.pptx");
    if (changed) {
      clearTimeout(resultPollTimer);
      state.result = null;
      state.resultLoading = true;
      state.resultError = null;
      state.slide = 0;
      renderPreview();
      setWorkspaceView("preview");
      loadResultPresentation(job.id);
      refreshLibrary();
    }
  } else if (job.status === "failed") {
    setWorkflow(0);
    $("job-title").textContent = "Сборка остановилась";
    $("job-description").textContent = job.error || "Не удалось создать презентацию. Проверьте материалы и попробуйте ещё раз.";
  } else {
    setWorkflow(1);
    const [title, description] = generationCopy(job);
    if ($("job-title").textContent !== title) $("job-title").textContent = title;
    if ($("job-description").textContent !== description) $("job-description").textContent = description;
  }
  const activeIndex = stageOrder.indexOf(job.stage);
  document.querySelectorAll(".job-stages li").forEach((item, index) => {
    item.classList.toggle("active", index === activeIndex && state.busy);
    item.classList.toggle("done", job.status === "completed" || index < activeIndex);
  });
  updateControls();
  if (changed) {
    if (job.status === "failed") setWorkspaceView("materials");
    if (job.status !== "completed") $("job-panel").scrollIntoView({ block: "nearest" });
  }
}

async function pollJob(id) {
  try {
    const job = await request(`/api/jobs/${encodeURIComponent(id)}`);
    if (state.job?.id !== id) return;
    activity.connectionLost = false;
    clearError();
    renderJob(job);
    if (state.busy) pollTimer = setTimeout(() => pollJob(id), 1600);
    else if (job.status === "completed") notify("Готово. Презентацию можно скачать.");
  } catch (error) {
    if (state.job?.id !== id) return;
    if (error.status >= 400 && error.status < 500) {
      state.busy = false;
      state.job = null;
      state.token = null;
      sessionStorage.removeItem("exposlides-job");
      $("job-panel").hidden = true;
      setWorkspaceView("materials");
      removeTemplate();
      updateControls();
      setWorkflow(0);
      showError("Сессия завершена. Добавьте шаблон заново; ваш текст остался в форме.");
      return;
    }
    showError(`${error.message} Проверяем подключение…`);
    activity.connectionLost = true;
    renderActivity();
    // Не запускаем вторую генерацию при временной потере соединения.
    pollTimer = setTimeout(() => pollJob(id), 5000);
  }
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (state.busy || state.uploading) return;
  clearError();
  if (!state.template) { showError("Сначала добавьте PPTX-шаблон.", true); $("dropzone").focus(); return; }
  if (!script.value.trim()) { showError("Добавьте текст для презентации.", true); script.focus(); return; }
  clearFinishedJob();
  selectionRevision++;
  state.busy = true;
  beginActivity({ showPreview: true });
  updateControls();
  try {
    await ensureSession();
    const maxSlides = $("max-slides").value;
    const job = await request("/api/jobs", { template_id: state.template.id, script: script.value.trim(), max_slides: maxSlides ? Number(maxSlides) : null });
    sessionStorage.setItem("exposlides-job", job.id);
    renderJob(job);
    clearTimeout(pollTimer);
    pollJob(job.id);
  } catch (error) {
    state.busy = false;
    setWorkspaceView("materials");
    if (error.status === 403) state.token = null;
    showError(error.message, true);
    updateControls();
  }
});

$("dropzone").addEventListener("click", () => $("template-input").click());
$("template-input").addEventListener("change", (event) => uploadTemplate(event.target.files[0]));
let dragDepth = 0;
$("dropzone").addEventListener("dragenter", (event) => { event.preventDefault(); dragDepth++; if (!state.uploading && !state.busy) $("dropzone").classList.add("is-dragging"); });
$("dropzone").addEventListener("dragover", (event) => event.preventDefault());
$("dropzone").addEventListener("dragleave", () => { if (--dragDepth <= 0) $("dropzone").classList.remove("is-dragging"); });
$("dropzone").addEventListener("drop", (event) => { event.preventDefault(); dragDepth = 0; $("dropzone").classList.remove("is-dragging"); if (event.dataTransfer.files.length > 1) showError("Выберите один PPTX-шаблон."); else uploadTemplate(event.dataTransfer.files[0]); });
document.addEventListener("dragover", (event) => { if (event.dataTransfer.types.includes("Files")) event.preventDefault(); });
document.addEventListener("drop", (event) => { if (event.dataTransfer.types.includes("Files")) event.preventDefault(); });
function removeTemplate() {
  if (state.busy) return;
  selectionRevision++;
  clearTimeout(previewPollTimer);
  previewRevision++;
  clearError(); clearFinishedJob(); state.template = null;
  $("selected-template").hidden = true; $("dropzone").hidden = false;
  $("max-slides").replaceChildren(new Option("Автоматически", ""));
  $("slide-preview").style.removeProperty("aspect-ratio");
  renderPreview(); updateControls(); $("dropzone").focus();
}
$("remove-template").addEventListener("click", removeTemplate);
$("library-refresh").addEventListener("click", refreshLibrary);
$("example-button").addEventListener("click", loadExample);
script.addEventListener("input", () => { clearFinishedJob(); clearError(); $("script-source").textContent = "Исходный текст"; updateControls(); });
$("max-slides").addEventListener("change", () => { clearFinishedJob(); updateControls(); });
$("import-button").addEventListener("click", () => $("script-input").click());
$("script-input").addEventListener("change", async (event) => {
  const file = event.target.files[0];
  if (!file) return;
  clearError();
  try {
    if (!file.name.toLowerCase().endsWith(".txt")) throw new Error("Выберите текстовый файл .txt в кодировке UTF-8.");
    if (file.size > 400000) throw new Error("Текст слишком большой. Используйте до 100 000 символов.");
    let text;
    try { text = new TextDecoder("utf-8", { fatal: true }).decode(await file.arrayBuffer()); }
    catch { throw new Error("Не удалось прочитать текст. Сохраните файл в кодировке UTF-8."); }
    if (!text.trim()) throw new Error("Этот текстовый файл пуст.");
    if (text.length > 100000) throw new Error("Текст слишком большой. Используйте до 100 000 символов.");
    if (state.busy) return;
    if (script.value.trim() && !confirm("Заменить текущий текст содержимым файла?")) return;
    clearFinishedJob(); script.value = text; $("script-source").textContent = file.name; updateControls(); notify("Текст загружен");
  } catch (error) { showError(error.message); }
  finally { $("script-input").value = ""; }
});
$("previous-slide").addEventListener("click", () => { if (state.slide > 0) { state.slide--; renderPreview(); } });
$("next-slide").addEventListener("click", () => { if (previewPresentation() && state.slide < previewPresentation().slides.length - 1) { state.slide++; renderPreview(); } });
$("help-button").addEventListener("click", () => $("help-dialog").showModal());
["close-help", "help-done"].forEach((id) => $(id).addEventListener("click", () => $("help-dialog").close()));
$("help-dialog").addEventListener("click", (event) => { if (event.target === $("help-dialog")) { const bounds = event.target.getBoundingClientRect(); if (event.clientX < bounds.left || event.clientX > bounds.right || event.clientY < bounds.top || event.clientY > bounds.bottom) event.target.close(); } });
$("view-materials").addEventListener("click", () => setWorkspaceView("materials"));
$("view-preview").addEventListener("click", () => setWorkspaceView("preview"));
$("activity-toggle").addEventListener("click", () => {
  activity.inspectTemplate = !activity.inspectTemplate;
  renderActivity();
});
$("motion-toggle").addEventListener("click", () => {
  activity.paused = !activity.paused;
  renderActivity();
});
new ResizeObserver(fitSlide).observe(document.querySelector(".canvas-stage"));

async function initialize() {
  updateControls();
  refreshLibrary();
  const revision = selectionRevision;
  try {
    await ensureSession();
    if (revision !== selectionRevision) return;
    let savedJobs = [];
    try { savedJobs = JSON.parse(sessionStorage.getItem("exposlides-jobs") || "[]"); } catch {}
    if (Array.isArray(savedJobs)) savedJobs.filter(id => typeof id === "string").forEach(watchBackgroundJob);
    const savedJob = sessionStorage.getItem("exposlides-job");
    if (savedJob) {
      try {
        const job = await request(`/api/jobs/${encodeURIComponent(savedJob)}`);
        if (revision !== selectionRevision) return;
        if (job.status === "running" || job.status === "queued") beginActivity({ showPreview: true });
        renderJob(job);
        if (state.busy) pollJob(savedJob);
      } catch { if (revision === selectionRevision) sessionStorage.removeItem("exposlides-job"); }
    }
  } catch (error) { showError(error.message); }
}
initialize();
