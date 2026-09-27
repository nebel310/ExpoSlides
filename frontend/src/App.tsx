import { useEffect, useRef, useState } from "react";
import { api, ApiError } from "./api";
import { ProfileCard, RecentJobs, StoryEditor, VariantWorkspace } from "./components";
import { jobError, jobView, restoreJob, SAVED_JOB_KEY } from "./jobs";
import { activeStatus, parseContentPack, parseDataset, validateStory } from "./model";
import type { Dataset, DesignRequest, Job, Story, Template, Variant } from "./types";

const stageCopy: Record<string, string> = {
  queued: "Материалы приняты", planning: "Выделяем главное и составляем историю",
  running: "Готовим презентацию", building: "Собираем три композиции",
  rendering: "Готовим изображения слайдов", auditing: "Проверяем содержание и оформление",
  fixing: "Применяем выбранные исправления", completed: "Презентации готовы",
  awaiting_review: "План готов к проверке", cancelled: "Работа остановлена", failed: "Не удалось завершить работу",
  cancelling: "Останавливаем работу", template: "Изучаем правила вашего шаблона", story: "Выделяем факты и составляем историю",
  illustration: "Создаём иллюстрацию в стиле шаблона",
};

const initialRequest: DesignRequest = {
  script: "", purpose: "Объяснить главное и предложить следующий шаг", audience: "Коллеги",
  slide_count: 12, count_mode: "exact", language: "ru", mode: "llm", required_messages: [], datasets: [],
  contextual_audit: false,
  generated_image: { enabled: false, prompt: "", seed: 0, width: 1024, height: 576, source_ids: [], palette: [] },
};

function readFile(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(new Error("Не удалось прочитать файл."));
    reader.onload = () => resolve(String(reader.result).split(",")[1]);
    reader.readAsDataURL(file);
  });
}

export default function App() {
  const [request, setRequest] = useState<DesignRequest>(initialRequest);
  const [template, setTemplate] = useState<Template | null>(null);
  const [job, setJob] = useState<Job | null>(null);
  const [story, setStory] = useState<Story | null>(null);
  const [view, setView] = useState<"materials" | "outline" | "results">("materials");
  const [error, setError] = useState("");
  const [busyAction, setBusyAction] = useState(false);
  const [connectionLost, setConnectionLost] = useState(false);
  const [dragging, setDragging] = useState(false);
  const [help, setHelp] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const [imageAvailable, setImageAvailable] = useState(false);
  const [contextAvailable, setContextAvailable] = useState(false);
  const [storyAvailable, setStoryAvailable] = useState<boolean | null>(null);
  const [restoreFailed, setRestoreFailed] = useState(false);
  const [restoring, setRestoring] = useState(true);
  const [showRecent, setShowRecent] = useState(false);
  const [recentJobs, setRecentJobs] = useState<Job[]>([]);
  const [recentLoading, setRecentLoading] = useState(false);
  const [recentError, setRecentError] = useState("");
  const [recentRefresh, setRecentRefresh] = useState(0);
  const [ready, setReady] = useState(false);
  const [connectError, setConnectError] = useState("");
  const [connectAttempt, setConnectAttempt] = useState(0);
  const uploadRef = useRef<HTMLInputElement>(null);
  const txtRef = useRef<HTMLInputElement>(null);
  const csvRef = useRef<HTMLInputElement>(null);
  const packRef = useRef<HTMLInputElement>(null);
  const dirtyStory = useRef(false);
  const operation = useRef(0);
  const running = !!job && activeStatus(job.status);
  const busy = busyAction || running || !ready || restoring;
  const profile = template?.profile ?? (job?.template_id === template?.id ? job?.profile : undefined);
  const image = request.generated_image ?? initialRequest.generated_image!;

  function failure(value: unknown) { setError(value instanceof Error ? value.message : "Не удалось выполнить действие."); }
  function trackJob(next: Job) {
    setJob(current => current?.id === next.id ? { ...current, ...next } : next);
    try { sessionStorage.setItem(SAVED_JOB_KEY, next.id); } catch { /* Хранилище браузера может быть отключено. */ }
  }
  function hydrateJob(value: Job) {
    trackJob(value);
    setRequest(value.request ? { ...initialRequest, ...value.request } : initialRequest);
    setTemplate(value.template ?? null);
    setStory(value.story ? structuredClone(value.story) : null);
    setView(jobView(value)); setError(jobError(value)); setRestoreFailed(false);
    setConnectionLost(false); dirtyStory.current = false;
  }
  async function openJob(id: string) {
    if (busy) return;
    if (dirtyStory.current && !confirm("Открыть другую работу и отменить несохранённые изменения плана?")) return;
    operation.current++;
    setBusyAction(true); setError("");
    try {
      hydrateJob(await api.get<Job>(`/api/design/jobs/${encodeURIComponent(id)}`));
      setShowRecent(false);
    } catch (value) { failure(value); }
    finally { setBusyAction(false); }
  }

  useEffect(() => {
    const controller = new AbortController();
    setConnectError("");
    // Получаем cookie владельца до параллельных чтений и любых пользовательских действий.
    api.get<{ token: string }>("/api/session", controller.signal).then(value => {
      if (controller.signal.aborted) return;
      if (!value.token) throw new Error("Не удалось открыть сессию.");
      setReady(true);
    }).catch(value => {
      if (!controller.signal.aborted) setConnectError(value instanceof Error ? value.message : "Не удалось подключиться к серверу.");
    });
    return () => controller.abort();
  }, [connectAttempt]);

  useEffect(() => {
    if (!ready) return;
    const controller = new AbortController();
    api.get<{ generated_image: boolean; contextual_audit: boolean; story: boolean }>("/api/capabilities", controller.signal)
      .then(value => { setImageAvailable(value.generated_image === true); setContextAvailable(value.contextual_audit === true); setStoryAvailable(value.story === true); }).catch(() => {});
    return () => controller.abort();
  }, [ready]);

  useEffect(() => {
    if (!ready) return;
    let cancelled = false;
    const controller = new AbortController();
    let storage: Storage;
    try { storage = sessionStorage; storage.getItem(SAVED_JOB_KEY); } catch { setRestoring(false); return () => controller.abort(); }
    restoreJob(api, storage, controller.signal).then(value => {
      if (cancelled || operation.current !== 0 || !value) return;
      hydrateJob(value);
    }).catch(() => {
      if (!cancelled && !controller.signal.aborted && operation.current === 0) setRestoreFailed(true);
    }).finally(() => { if (!cancelled) setRestoring(false); });
    return () => { cancelled = true; controller.abort(); };
  }, [ready]);

  useEffect(() => {
    if (!showRecent || !ready) return;
    const controller = new AbortController();
    setRecentLoading(true); setRecentError("");
    // Сервер ограничивает список владельцем HttpOnly cookie; клиент не получает чужие задания.
    api.get<{ jobs: Job[] }>("/api/design/jobs", controller.signal).then(value => {
      if (controller.signal.aborted) return;
      setRecentJobs([...value.jobs].reverse().sort((a, b) => (b.created_at ?? 0) - (a.created_at ?? 0)));
    }).catch(value => {
      if (!controller.signal.aborted) setRecentError(value instanceof Error ? value.message : "Не удалось получить список работ.");
    }).finally(() => { if (!controller.signal.aborted) setRecentLoading(false); });
    return () => controller.abort();
  }, [showRecent, recentRefresh, job?.id, job?.status, ready]);

  useEffect(() => {
    if (!job?.id || !activeStatus(job.status)) return;
    const id = job.id;
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    let stopped = false;
    async function poll() {
      try {
        const next = await api.get<Job>(`/api/design/jobs/${encodeURIComponent(id)}`, controller.signal);
        if (stopped) return;
        setConnectionLost(false);
        setJob(current => current?.id === id ? next : current);
        if (next.story && !dirtyStory.current) setStory(structuredClone(next.story));
        if (next.status === "awaiting_review") setView("outline");
        else if (!activeStatus(next.status) && next.variants?.length) setView("results");
        if (jobError(next)) setError(jobError(next));
        if (activeStatus(next.status)) timer = setTimeout(poll, 1500);
      } catch (value) {
        if (stopped) return;
        if (value instanceof ApiError && value.status >= 400 && value.status < 500) {
          failure(value); setJob(current => current?.id === id ? { ...current, status: "failed" } : current);
        } else { setConnectionLost(true); timer = setTimeout(poll, 4000); }
      }
    }
    timer = setTimeout(poll, 400);
    return () => { stopped = true; clearTimeout(timer); controller.abort(); };
  }, [job?.id, job?.status]);

  useEffect(() => {
    if (!running) return;
    setElapsed(0);
    const started = Date.now();
    const interval = setInterval(() => setElapsed(Math.floor((Date.now() - started) / 1000)), 1000);
    return () => clearInterval(interval);
  }, [running]);

  async function upload(file?: File) {
    if (!file || busy) return;
    if (!/\.pptx$/i.test(file.name) || !file.size || file.size > 25 * 1024 * 1024) {
      setError("Выберите непустой PPTX размером до 25 МБ."); return;
    }
    operation.current++;
    setBusyAction(true); setError("");
    try {
      const data = await readFile(file);
      setTemplate(await api.post<Template>("/api/templates", { name: file.name, data }));
      setView("materials");
    } catch (value) { failure(value); }
    finally { setBusyAction(false); if (uploadRef.current) uploadRef.current.value = ""; }
  }

  async function example() {
    if (busy) return;
    if ((template || request.script.trim()) && !confirm("Заменить выбранный шаблон и материалы встроенным примером?")) return;
    operation.current++;
    setBusyAction(true); setError("");
    try {
      const data = await api.get<{ template_id: string; script: string; template?: Template; profile?: Template["profile"]; name?: string; datasets?: Dataset[] }>("/api/example");
      const chosen = data.template ?? (data.profile ? { id: data.template_id, name: data.name || "Пример.pptx", profile: data.profile } : null);
      if (!chosen) throw new Error("Пример не содержит профиль шаблона. Перезапустите сервер.");
      setTemplate(chosen); setRequest(current => ({ ...current, script: data.script, datasets: data.datasets ?? [], required_messages: [] }));
      setView("materials");
    } catch (value) { failure(value); }
    finally { setBusyAction(false); }
  }

  async function importText(file?: File) {
    if (!file || busy) return;
    try {
      if (!/\.txt$/i.test(file.name) || file.size > 400000) throw new Error("Нужен TXT в UTF-8, до 100 000 символов.");
      const script = new TextDecoder("utf-8", { fatal: true }).decode(await file.arrayBuffer());
      if (!script.trim() || script.length > 100000) throw new Error("Текст должен содержать от 1 до 100 000 символов.");
      if (request.script.trim() && !confirm("Заменить текст материалами из файла?")) return;
      setRequest(current => ({ ...current, script })); setError("");
    } catch (value) { failure(value); }
    finally { if (txtRef.current) txtRef.current.value = ""; }
  }

  async function importCsv(file?: File) {
    if (!file || busy) return;
    try {
      if (!/\.csv$/i.test(file.name) || file.size > 500000) throw new Error("Нужен CSV до 500 КБ, максимум 200 строк.");
      if (request.datasets.length >= 20) throw new Error("Допускается не более 20 таблиц данных.");
      const text = new TextDecoder("utf-8", { fatal: true }).decode(await file.arrayBuffer());
      const data = parseDataset(text, file.name, `data_${Date.now()}`);
      setRequest(current => ({ ...current, datasets: [...current.datasets, data] })); setError("");
    } catch (value) { failure(value); }
    finally { if (csvRef.current) csvRef.current.value = ""; }
  }

  async function importPack(file?: File) {
    if (!file || busy) return;
    try {
      if (!/\.json$/i.test(file.name) || file.size > 2000000) throw new Error("Нужен JSON в UTF-8 до 2 МБ.");
      const text = new TextDecoder("utf-8", { fatal: true }).decode(await file.arrayBuffer());
      const content = parseContentPack(text);
      if ((request.script.trim() || request.datasets.length) && !confirm("Заменить текст, обязательные тезисы и данные материалами из JSON?")) return;
      setRequest(current => ({ ...current, ...content })); setError("");
    } catch (value) { failure(value); }
    finally { if (packRef.current) packRef.current.value = ""; }
  }

  async function plan() {
    if (busy || !template) return;
    if (!request.script.trim()) { setError("Добавьте исходный текст."); return; }
    if (image.enabled && (!imageAvailable || !image.prompt.trim())) { setError("Для иллюстрации нужны описание и настроенный генератор на сервере."); return; }
    operation.current++;
    setBusyAction(true); setError(""); dirtyStory.current = false;
    try {
      const next = await api.post<Job>("/api/design/plan", {
        template_id: template.id,
        request: { ...request, required_messages: request.required_messages.map(s => s.trim()).filter(Boolean) },
      });
      setStory(null); trackJob(next); setView("materials");
    } catch (value) { failure(value); }
    finally { setBusyAction(false); }
  }

  async function build() {
    if (!story || !job || busy) return;
    const message = validateStory(story);
    if (message) { setError(message); return; }
    setBusyAction(true); setError("");
    try {
      const cleaned = { ...story, slides: story.slides.map(s => ({ ...s, paragraphs: s.paragraphs.map(p => p.trim()).filter(Boolean) })) };
      const next = await api.post<Job>(`/api/design/jobs/${encodeURIComponent(job.id)}/build`, { story: cleaned });
      dirtyStory.current = false; trackJob(next);
    } catch (value) { failure(value); }
    finally { setBusyAction(false); }
  }

  async function fix(variant: Variant, issueIds: string[]) {
    if (!job || !issueIds.length || busy) return;
    setBusyAction(true); setError("");
    try {
      trackJob(await api.post<Job>(`/api/design/jobs/${encodeURIComponent(job.id)}/variants/${encodeURIComponent(variant.id)}/fix`, {
        issue_ids: issueIds, revision: variant.revision,
      }));
    } catch (value) { failure(value); }
    finally { setBusyAction(false); }
  }

  async function cancel() {
    if (!job || busyAction) return;
    setBusyAction(true);
    try { trackJob(await api.post<Job>(`/api/design/jobs/${encodeURIComponent(job.id)}/cancel`)); }
    catch (value) { failure(value); }
    finally { setBusyAction(false); }
  }

  return <>
    <a className="skip-link" href="#main">К материалам презентации</a>
    <header className="topbar"><a href="/" className="brand" aria-label="ExpoSlides — главная"><span className="brand-symbol">E</span><strong>ExpoSlides</strong><span className="brand-label">Дизайнер презентаций</span></a>
      <div className="header-actions"><button className="help-button" disabled={!ready} onClick={() => setShowRecent(!showRecent)} aria-expanded={showRecent} aria-controls="recent-jobs">Предыдущие работы</button><button className="help-button" onClick={() => setHelp(!help)} aria-expanded={help}>Как это работает <span>?</span></button></div></header>
    {showRecent && <RecentJobs jobs={recentJobs} loading={recentLoading} error={recentError} currentId={job?.id} busy={busy} onOpen={openJob} onRefresh={() => setRecentRefresh(value => value + 1)} />}
    {help && <section className="help-panel"><h2>Ваш шаблон. Ваша история.</h2><p>Загрузите PPTX и материалы. Сначала проверьте план, затем сравните три варианта. Выберите исправления, которые стоит применить, и скачайте результат.</p>
      <p>При работе с моделью исходный текст, структура шаблона и данные отправляются настроенному провайдеру. Проверочный режим использует только локальную обработку. Хранение и ограничения зависят от конфигурации сервера.</p><button onClick={() => setHelp(false)}>Понятно</button></section>}
    <nav className="steps" aria-label="Этапы работы"><button className={view === "materials" ? "active" : ""} onClick={() => setView("materials")} aria-current={view === "materials" ? "step" : undefined}><span>01</span> Материалы</button><i />
      <button className={view === "outline" ? "active" : ""} onClick={() => setView("outline")} disabled={!story} aria-current={view === "outline" ? "step" : undefined}><span>02</span> План истории</button><i />
      <button className={view === "results" ? "active" : ""} onClick={() => setView("results")} disabled={!job?.variants?.length} aria-current={view === "results" ? "step" : undefined}><span>03</span> Варианты и аудит</button></nav>
    <main id="main">
      {!ready && <div className="message" role="status"><span>{connectError || "Подключаемся к серверу…"}</span>{connectError && <button className="text-button" onClick={() => setConnectAttempt(value => value + 1)}>Повторить</button>}</div>}
      {ready && restoring && <div className="message" role="status">Восстанавливаем последнюю работу…</div>}
      {restoreFailed && <div className="message warning" role="status"><span>Не удалось восстановить последнюю работу. Ссылка сохранена — откройте список, когда связь появится.</span><button className="text-button" onClick={() => setShowRecent(true)}>Предыдущие работы</button></div>}
      {error && <div className="message error" role="alert"><span>{error}</span><button aria-label="Скрыть сообщение" onClick={() => setError("")}>×</button></div>}
      {job?.status === "failed" && !!job.variants?.length && <div className="message warning" role="status">Сборка остановилась с ошибкой. Готово {job.variants.length} из 3 вариантов — опубликованные файлы доступны ниже.</div>}
      {connectionLost && <div className="message warning" role="status">Соединение прервано. Проверяем состояние уже запущенной работы — повторная генерация не нужна.</div>}
      {running && <section className="progress-banner" role="status" aria-live="polite"><span className="spinner" /><div><strong>{job.status === "cancelling" ? stageCopy.cancelling : stageCopy[job.stage?.split(":")[0] ?? job.status] || stageCopy[job.status] || "Готовим результат"}</strong><p>{elapsed > 0 ? `${Math.floor(elapsed / 60)}:${String(elapsed % 60).padStart(2, "0")} с начала этапа` : "Это может занять несколько минут"}</p></div><button className="text-button" disabled={busyAction || job.status === "cancelling"} onClick={cancel}>Остановить</button></section>}
      {job?.status === "cancelled" && <div className="message" role="status">Работа остановлена. Вы можете изменить материалы и начать снова.</div>}
      {view === "materials" && <div className="materials-layout"><section className="materials-main">
        <div className="section-top"><div><span className="eyebrow">01 / Начнём с главного</span><h1>Из материалов —<br />в убедительную презентацию</h1><p>Сохраним стиль вашего шаблона.<br />Поможем выбрать композицию и проверить результат.</p></div><button className="text-button example" disabled={busy} onClick={example}>Открыть пример ↗</button></div>
        <div className="material-card"><div className="card-heading"><span className="step-dot">1</span><div><h2>Шаблон оформления</h2><p>Любой PPTX — макеты, шрифты, палитра и фирменные элементы</p></div></div>
          <input ref={uploadRef} type="file" accept=".pptx" hidden onChange={e => upload(e.target.files?.[0])} />
          <button type="button" className={`dropzone ${dragging ? "dragging" : ""} ${template ? "loaded" : ""}`} disabled={busy} onClick={() => uploadRef.current?.click()}
            onDragOver={e => { e.preventDefault(); if (!busy) setDragging(true); }} onDragLeave={() => setDragging(false)}
            onDrop={e => { e.preventDefault(); setDragging(false); if (e.dataTransfer.files.length > 1) setError("Выберите один PPTX-шаблон."); else upload(e.dataTransfer.files[0]); }}>
            <span className="file-glyph">{template ? "P" : "↑"}</span><span><strong>{template?.name || "Выберите или перетащите PPTX"}</strong><small>{template ? "Нажмите, чтобы заменить шаблон" : "До 25 МБ · исходное оформление остаётся с вами"}</small></span><span className="file-check">{template ? "✓" : "+"}</span></button>
          {profile && <ProfileCard profile={profile} />}
        </div>
        <div className="material-card"><div className="card-heading"><span className="step-dot">2</span><div><h2>Исходные материалы</h2><p>Факты, заметки, выводы — всё, на что должна опираться история</p></div><div className="import-buttons"><button className="text-button" disabled={busy} onClick={() => txtRef.current?.click()}>Импорт TXT</button><button className="text-button" disabled={busy} onClick={() => packRef.current?.click()}>Импорт JSON</button></div></div>
          <input ref={txtRef} type="file" accept=".txt" hidden onChange={e => importText(e.target.files?.[0])} />
          <input ref={packRef} type="file" accept=".json,application/json" hidden onChange={e => importPack(e.target.files?.[0])} />
          <label className="sr-only" htmlFor="script">Исходный текст</label><textarea id="script" className="source-input" value={request.script} maxLength={100000} rows={10} disabled={busy}
            placeholder="О чём вы хотите рассказать?\n\nВставьте материалы: основные мысли, факты, результаты и следующий шаг." onChange={e => setRequest({ ...request, script: e.target.value })} />
          <div className="source-footer"><span>Сохраняем связь с источниками</span><span>{request.script.length.toLocaleString("ru-RU")} / 100 000</span></div>
          <details className="data-details"><summary>Формат пакета JSON</summary><p>Обязательное поле <code>script</code> содержит текст. В <code>required_messages</code> передайте список тезисов, в <code>datasets</code> — таблицы с полями id, name, columns, rows, source и необязательным unit. Поля purpose и audience уточняют цель и аудиторию. JSON заменит исходные материалы после подтверждения.</p></details>
          <details className="data-details"><summary>Данные для таблиц и графиков <span>{request.datasets.length || "+"}</span></summary>
            <p>Добавьте CSV с заголовками столбцов. Значения будут использованы для нативных таблиц и диаграмм.</p>
            <input ref={csvRef} type="file" accept=".csv" hidden onChange={e => importCsv(e.target.files?.[0])} />
            {request.datasets.map(data => <div className="dataset" key={data.id}><div><strong>{data.name}</strong><span>{data.rows.length} строк · {data.columns.join(", ")}</span></div>
              <label>Единицы<input value={data.unit} placeholder="руб., %…" disabled={busy} onChange={e => setRequest({ ...request, datasets: request.datasets.map(d => d.id === data.id ? { ...d, unit: e.target.value } : d) })} /></label>
              <button aria-label={`Удалить данные ${data.name}`} disabled={busy} onClick={() => setRequest({ ...request, datasets: request.datasets.filter(d => d.id !== data.id) })}>×</button></div>)}
            <button className="secondary" disabled={busy} onClick={() => csvRef.current?.click()}>Добавить CSV +</button>
          </details>
        </div>
      </section><aside className="brief-panel"><span className="eyebrow">Настроим историю</span><h2>Для кого и зачем?</h2>
        <label className="field">Цель презентации<textarea rows={3} maxLength={1000} disabled={busy} value={request.purpose} onChange={e => setRequest({ ...request, purpose: e.target.value })} /></label>
        <label className="field">Аудитория<input value={request.audience} maxLength={500} disabled={busy} onChange={e => setRequest({ ...request, audience: e.target.value })} /></label>
        <div className="count-fields"><label className="field">Слайдов<input type="number" min={1} max={50} value={request.slide_count} disabled={busy} onChange={e => setRequest({ ...request, slide_count: Math.min(50, Math.max(1, Number(e.target.value))) })} /></label>
          <label className="field">Количество<select value={request.count_mode} disabled={busy} onChange={e => setRequest({ ...request, count_mode: e.target.value as DesignRequest["count_mode"] })}><option value="exact">Ровно</option><option value="maximum">Не больше</option></select></label></div>
        <label className="field">Что обязательно сохранить<textarea rows={3} placeholder="Каждый обязательный тезис — с новой строки" disabled={busy} value={request.required_messages.join("\n")} onChange={e => setRequest({ ...request, required_messages: e.target.value.split("\n").slice(0, 50) })} /></label>
        <label className="field">Режим<select value={request.mode} disabled={busy} onChange={e => setRequest({ ...request, mode: e.target.value as DesignRequest["mode"], contextual_audit: e.target.value === "llm" && request.contextual_audit, generated_image: { ...image, enabled: e.target.value === "llm" && image.enabled } })}><option value="llm">С моделью</option><option value="extractive">Проверочный · без модели</option></select></label>
        <p className="mode-hint">{request.mode === "llm" ? "Модель подготовит формулировки; факты проверяются по вашим материалам." : "Текст распределяется по слайдам без обращения к модели. Подходит для проверки шаблона и экспорта."}</p>
        {request.mode === "llm" && storyAvailable === false && <p className="audit-coverage">Модель текста на сервере не настроена. Для локальной проверки выберите проверочный режим.</p>}
        <label className="check-label contextual-toggle"><input type="checkbox" disabled={busy || request.mode !== "llm" || !contextAvailable} checked={request.contextual_audit} onChange={e => setRequest({ ...request, contextual_audit: e.target.checked })} /> Проверить смысл по изображениям слайдов</label>
        <p className="mode-hint">{contextAvailable ? "Дополнительная отправка изображений слайдов настроенной модели." : "Проверка смысла по изображениям на сервере не настроена. Проверки по правилам доступны."}</p>
        <label className="check-label contextual-toggle"><input type="checkbox" disabled={busy || request.mode !== "llm" || !imageAvailable} checked={image.enabled} onChange={e => setRequest({ ...request, generated_image: { ...image, enabled: e.target.checked } })} /> Создать иллюстрацию для обложки</label>
        {image.enabled && <label className="field">Что изобразить<textarea rows={3} maxLength={4000} disabled={busy} value={image.prompt} placeholder="Опишите сюжет без текста и неподтверждённых фактов" onChange={e => setRequest({ ...request, generated_image: { ...image, prompt: e.target.value } })} /></label>}
        <p className="mode-hint">{imageAvailable ? "Описание отправится генератору изображений. Палитру возьмём из вашего шаблона; иллюстрация будет общей для трёх вариантов." : "Генератор изображений на сервере не настроен. Иллюстрации из шаблона сохраняются."}</p>
        <button className="primary plan-button" disabled={busy || !template || !request.script.trim()} onClick={plan}>{busyAction ? "Подготавливаем…" : "Создать план истории"}<span>→</span></button>
        <p className="under-button">Сначала вы сможете проверить и изменить план</p>
      </aside></div>}
      {view === "outline" && story && <>{job?.profile && <details className="profile-summary"><summary>Правила оформления шаблона</summary><ProfileCard profile={job.profile} /></details>}<StoryEditor story={story} datasets={request.datasets} profile={job?.profile} busy={busy}
        onChange={value => { dirtyStory.current = true; setStory(value); }} onBuild={build} /></>}
      {view === "results" && !!job?.variants?.length && <VariantWorkspace variants={job.variants} profile={job.profile ?? template?.profile} busy={busy} onFix={fix}
        fixUnavailableReason={job.status === "failed" || job.status === "cancelled" ? "Исправления доступны после успешной сборки. Готовые файлы можно проверить и скачать." : undefined} />}
    </main><footer className="footer"><span>ExpoSlides</span><span>Ваши материалы → ваш стиль → ваш результат</span></footer>
  </>;
}
