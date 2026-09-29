import { useEffect, useRef, useState } from "react";
import { api, ApiError } from "./api";
import { jobError, restoreJob, SAVED_JOB_KEY } from "./jobs";
import { activeStatus, simpleDesignRequest, slideCountLabel, validateStory } from "./model";
import { ResultViewer } from "./ResultViewer";
import { DatasetInput } from "./DatasetInput";
import { StoryEditor } from "./components";
import { SlideGame } from "./SlideGame";
import type { DesignRequest, Job, Template, Variant } from "./types";

const initialRequest = simpleDesignRequest();
type Page = "upload" | "result" | "history";

function historyStatus(job: Job): string {
  if (job.status === "completed") return "Готово";
  if (job.status === "failed") return job.variants?.length ? "Готово частично" : "Не удалось создать";
  if (job.status === "cancelled") return "Остановлено";
  if (job.status === "awaiting_review") return "Можно продолжить";
  return "Создаётся";
}
function progressText(job: Job): string {
  const stage = job.stage?.split(":")[0];
  if (job.status === "cancelling") return "Останавливаем создание…";
  if (stage === "template") return "Читаем ваш шаблон";
  if (stage === "story") return "Готовим содержание";
  if (stage === "rendering" || stage === "auditing") return "Проверяем готовые слайды";
  return "Собираем слайды в вашем шаблоне";
}
function readFile(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(new Error("Не удалось прочитать файл. Сохраните PPTX на устройство и выберите его ещё раз."));
    reader.onabort = () => reject(new Error("Чтение файла отменено. Выберите PPTX ещё раз."));
    reader.onload = () => resolve(String(reader.result).split(",")[1]);
    reader.readAsDataURL(file);
  });
}

export default function App() {
  const [page, setPage] = useState<Page>("upload");
  const [request, setRequest] = useState<DesignRequest>(initialRequest);
  const [template, setTemplate] = useState<Template | null>(null);
  const [job, setJob] = useState<Job | null>(null);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [error, setError] = useState("");
  const [ready, setReady] = useState(false);
  const [restoring, setRestoring] = useState(true);
  const [busyAction, setBusyAction] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [uploadProgress, setUploadProgress] = useState<number | null>(null);
  const [uploadName, setUploadName] = useState("");
  const [connectionLostId, setConnectionLostId] = useState<string | null>(null);
  const [storyAvailable, setStoryAvailable] = useState<boolean | null>(null);
  const [connectAttempt, setConnectAttempt] = useState(0);
  const [historyRefresh, setHistoryRefresh] = useState(0);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [historyError, setHistoryError] = useState("");
  const [dataPending, setDataPending] = useState(false);
  const [dragging, setDragging] = useState(false);
  const workspaceVersion = useRef(0);
  const uploadRef = useRef<HTMLInputElement>(null);
  const textRef = useRef<HTMLInputElement>(null);
  const running = !!job && activeStatus(job.status);
  const busy = busyAction || !ready || restoring;
  const uploadBusy = busy || uploading;
  const generationBusy = dataPending || uploadBusy || running;

  function failure(value: unknown) {
    setError(value instanceof Error ? value.message : "Не удалось выполнить действие.");
  }
  function navigate(next: Page) {
    setError("");
    if (next === page) return;
    // Поздние ответы старой страницы не должны менять новую форму или результат.
    workspaceVersion.current++;
    setBusyAction(false); setUploading(false); setUploadProgress(null); setUploadName("");
    setDataPending(false); setDragging(false); setConnectionLostId(null);
    if (page === "result") {
      setRequest(simpleDesignRequest()); setTemplate(null); setJob(null);
      try { sessionStorage.removeItem(SAVED_JOB_KEY); } catch { /* Работа остаётся в истории. */ }
    }
    setPage(next);
  }

  useEffect(() => {
    const controller = new AbortController();
    setError("");
    api.get<{ token: string }>("/api/session", controller.signal).then(value => {
      if (!value.token) throw new Error("Не удалось подключиться к серверу.");
      if (!controller.signal.aborted) setReady(true);
    }).catch(value => { if (!controller.signal.aborted) { failure(value); setRestoring(false); } });
    return () => controller.abort();
  }, [connectAttempt]);

  useEffect(() => {
    if (!ready) return;
    const controller = new AbortController();
    api.get<{ story: boolean }>("/api/capabilities", controller.signal)
      .then(value => { if (!controller.signal.aborted) setStoryAvailable(value.story === true); })
      .catch(() => {});
    let storage: Storage;
    try { storage = sessionStorage; storage.getItem(SAVED_JOB_KEY); }
    catch { setRestoring(false); return () => controller.abort(); }
    const version = workspaceVersion.current;
    restoreJob(api, storage, controller.signal).then(value => {
      if (!controller.signal.aborted && version === workspaceVersion.current && value) { setJob(value); setPage("result"); }
    }).catch(() => {
      if (!controller.signal.aborted && version === workspaceVersion.current) setError("Не удалось открыть последнюю презентацию. Она сохранена в истории.");
    }).finally(() => { if (!controller.signal.aborted) setRestoring(false); });
    return () => controller.abort();
  }, [ready]);

  useEffect(() => {
    if (page !== "history" || !ready) return;
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    setHistoryLoading(true); setHistoryError("");
    async function refresh() {
      try {
        const value = await api.get<{ jobs: Job[] }>("/api/design/jobs", controller.signal);
        if (controller.signal.aborted) return;
        setJobs([...value.jobs].sort((a, b) => (b.created_at ?? 0) - (a.created_at ?? 0)));
        setHistoryError("");
        if (value.jobs.some(item => activeStatus(item.status))) timer = setTimeout(refresh, 1500);
      } catch (value) {
        if (controller.signal.aborted) return;
        setHistoryError(value instanceof Error ? value.message : "Не удалось загрузить историю.");
        timer = setTimeout(refresh, 4000);
      } finally {
        if (!controller.signal.aborted) setHistoryLoading(false);
      }
    }
    void refresh();
    return () => { controller.abort(); clearTimeout(timer); };
  }, [page, ready, historyRefresh]);

  // Сервер продолжает все работы; здесь следим только за открытым результатом.
  useEffect(() => {
    if (page !== "result" || !job || !running) return;
    const id = job.id;
    const version = workspaceVersion.current;
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      try {
        const next = await api.get<Job>(`/api/design/jobs/${encodeURIComponent(id)}`, controller.signal);
        if (controller.signal.aborted || version !== workspaceVersion.current) return;
        setConnectionLostId(null);
        setJob(current => current?.id === id ? next : current);
        if (activeStatus(next.status)) timer = setTimeout(poll, 1500);
      } catch (value) {
        if (controller.signal.aborted || version !== workspaceVersion.current) return;
        if (value instanceof ApiError && value.status === 404) {
          setJob(current => current?.id === id ? { ...current, status: "failed", error: value.message } : current);
          setConnectionLostId(null);
        } else { setConnectionLostId(id); timer = setTimeout(poll, 4000); }
      }
    }
    timer = setTimeout(poll, 400);
    return () => { controller.abort(); clearTimeout(timer); };
  }, [page, job?.id, running]);

  useEffect(() => {
    if (job) {
      try { sessionStorage.setItem(SAVED_JOB_KEY, job.id); } catch { /* Работа остаётся в истории. */ }
    }
  }, [job?.id]);

  async function runJobAction(action: () => Promise<Job>, showResult = false) {
    const version = workspaceVersion.current;
    setBusyAction(true); setError("");
    try {
      const next = await action();
      setHistoryRefresh(value => value + 1);
      if (version !== workspaceVersion.current) return;
      setJob(next); setConnectionLostId(null);
      if (showResult) setPage("result");
    } catch (value) {
      if (version === workspaceVersion.current) failure(value);
    } finally {
      if (version === workspaceVersion.current) setBusyAction(false);
    }
  }

  async function upload(file?: File) {
    if (!file || uploadBusy) return;
    if (!/\.pptx$/i.test(file.name) || !file.size || file.size > 25 * 1024 * 1024) {
      setError("Выберите PPTX размером до 25 МБ."); return;
    }
    const version = workspaceVersion.current;
    setUploading(true); setUploadProgress(null); setUploadName(file.name); setError("");
    try {
      const data = await readFile(file);
      if (version !== workspaceVersion.current) return;
      setUploadProgress(0);
      const next = await api.uploadTemplate<Template>({ name: file.name, data }, percent => {
        if (version === workspaceVersion.current) setUploadProgress(percent);
      });
      if (version === workspaceVersion.current) setTemplate(next);
    } catch (value) { if (version === workspaceVersion.current) failure(value); }
    finally {
      if (version === workspaceVersion.current) {
        setUploading(false); if (uploadRef.current) uploadRef.current.value = "";
      }
    }
  }
  async function importText(file?: File) {
    if (!file || busy) return;
    const version = workspaceVersion.current;
    setBusyAction(true); setError("");
    try {
      if (!/\.txt$/i.test(file.name) || file.size > 400000) throw new Error("Выберите текстовый файл TXT в UTF-8.");
      const script = new TextDecoder("utf-8", { fatal: true }).decode(await file.arrayBuffer());
      if (!script.trim() || script.length > 100000) throw new Error("В файле должен быть текст до 100 000 символов.");
      if (version === workspaceVersion.current) setRequest(current => ({ ...current, script }));
    } catch (value) { if (version === workspaceVersion.current) failure(value); }
    finally {
      if (version === workspaceVersion.current) {
        setBusyAction(false); if (textRef.current) textRef.current.value = "";
      }
    }
  }
  async function generate() {
    if (generationBusy || !template || !request.script.trim()) return;
    await runJobAction(() => api.post<Job>("/api/design/generate", {
      template_id: template.id, request: simpleDesignRequest(request),
    }), true);
  }
  async function openJob(id: string) {
    if (busy) return;
    await runJobAction(() => api.get<Job>(`/api/design/jobs/${encodeURIComponent(id)}`), true);
  }
  async function cancel() {
    if (!job || busyAction) return;
    await runJobAction(() => api.post<Job>(`/api/design/jobs/${encodeURIComponent(job.id)}/cancel`));
  }
  async function continueSavedJob() {
    if (!job?.story || generationBusy) return;
    const invalid = validateStory(job.story);
    if (invalid) { setError(invalid); return; }
    await runJobAction(() => api.post<Job>(`/api/design/jobs/${encodeURIComponent(job.id)}/build`, { story: job.story }));
  }
  async function fixVariant(variant: Variant, ids: string[]) {
    if (!job || generationBusy || job.status !== "completed") return;
    await runJobAction(() => api.post<Job>(`/api/design/jobs/${encodeURIComponent(job.id)}/variants/${encodeURIComponent(variant.id)}/fix`, { revision: variant.revision, issue_ids: ids }));
  }

  return <div className="app-shell">
    <a className="skip-link" href="#main">К содержимому</a>
    <header className="site-header"><button className="brand" onClick={() => navigate("upload")}>ExpoSlides</button>
      <nav className="navigation" aria-label="Основная навигация">
        <button className={page === "upload" ? "active" : ""} aria-current={page === "upload" ? "page" : undefined} onClick={() => navigate("upload")}>Загрузка</button>
        <button className={page === "result" ? "active" : ""} aria-current={page === "result" ? "page" : undefined} disabled={!job} onClick={() => navigate("result")}>Результат</button>
        <button className={page === "history" ? "active" : ""} aria-current={page === "history" ? "page" : undefined} disabled={!ready || restoring} onClick={() => navigate("history")}>История</button>
      </nav>
    </header>
    <main className={`page ${page}-page`} id="main">
      {error && <div className="error-message" role="alert">{error}{!ready && <button className="text-button" onClick={() => setConnectAttempt(value => value + 1)}>Повторить</button>}</div>}
      {page === "upload" && <>
        <div className="page-heading"><h1>Новая презентация</h1><p>Добавьте шаблон и текст. Остальное мы сделаем сами.</p></div>
        <form onSubmit={event => { event.preventDefault(); void generate(); }}>
          <div className="upload-grid"><section aria-labelledby="template-label">
            <h2 className="field-label" id="template-label">Шаблон презентации</h2>
            <input ref={uploadRef} type="file" accept=".pptx" hidden disabled={uploadBusy} aria-label="Файл шаблона" onChange={event => upload(event.target.files?.[0])} />
            <button type="button" className={`upload-zone ${dragging ? "dragging" : ""} ${template ? "loaded" : ""}`} disabled={uploadBusy} aria-busy={uploading}
              onClick={() => uploadRef.current?.click()} onDragOver={event => { event.preventDefault(); if (!uploadBusy) setDragging(true); }}
              onDragLeave={() => setDragging(false)} onDrop={event => { event.preventDefault(); setDragging(false); if (event.dataTransfer.files.length !== 1) setError("Выберите один шаблон."); else void upload(event.dataTransfer.files[0]); }}>
              <span className="upload-icon" aria-hidden="true"><svg viewBox="0 0 220 144" fill="none">
                <rect x="36" y="18" width="144" height="96" rx="5" fill="#252820" transform="rotate(-12 108 66)" />
                <rect x="36" y="23" width="144" height="96" rx="5" fill="#DA5738" transform="rotate(7 108 71)" />
                <rect x="34" y="25" width="144" height="96" rx="5" fill="#FFFEF9" stroke="#D9D5C9" />
                <path d="M51 45H90M51 56H111" stroke="#252820" strokeWidth="5" />
                <path d="M51 91H94M51 99H80" stroke="#C6C4BA" strokeWidth="2" />
                <circle cx="147" cy="94" r="14" fill="#DA5738" />
                <path d="M147 100V88M142 93L147 88L152 93" stroke="#FFFEF9" strokeWidth="1.8" />
              </svg></span>
              <strong className="file-name">{uploading ? uploadName : template?.name || "Выберите или перетащите файл"}</strong>
              <span className="file-meta">{template ? "Нажмите, чтобы заменить" : "PPTX · до 25 МБ"}</span>
            </button>
            {uploading && <div role="status" aria-live="polite">
              <p>{uploadProgress === null ? "Читаем файл…" : uploadProgress < 100 ? `Загружаем шаблон: ${uploadProgress}%` : "Проверяем презентацию…"} Можно добавлять текст.</p>
              <progress aria-label="Загрузка шаблона" max={100} value={uploadProgress ?? undefined} />
            </div>}
          </section><section aria-labelledby="script-label">
            <div className="input-heading"><label className="field-label" id="script-label" htmlFor="script">Содержание</label><button type="button" className="text-button" disabled={busy} onClick={() => textRef.current?.click()}>Загрузить текст</button></div>
            <input ref={textRef} type="file" accept=".txt" hidden aria-label="Файл с текстом" onChange={event => importText(event.target.files?.[0])} />
            <textarea className="script-input" id="script" value={request.script} rows={12} maxLength={100000} disabled={busy} placeholder="О чём будет презентация? Вставьте сюда текст, факты и основные мысли." onChange={event => setRequest({ ...request, script: event.target.value })} />
          </section></div>
          <DatasetInput datasets={request.datasets} disabled={busy || running}
            onChange={datasets => setRequest(current => ({ ...current, datasets }))} onPending={setDataPending} />
          <div className="upload-actions"><label className="slide-count">Слайдов<input type="number" min={1} max={50} required value={request.slide_count} disabled={busy} onChange={event => setRequest({ ...request, slide_count: Math.min(50, Math.max(1, Number(event.target.value))) })} /></label>
            <button className="primary" type="submit" disabled={generationBusy || !template || !request.script.trim() || (request.mode === "llm" && storyAvailable === false)}>{busyAction ? "Подготовка…" : "Создать презентацию"}<span className="action-arrow" aria-hidden="true">↗</span></button></div>
          {request.mode === "llm" && storyAvailable === false && <p className="error-message" role="status">Сервис генерации временно недоступен. Попробуйте позже.</p>}
        </form>
      </>}
      {page === "result" && job && <>
        <div className="page-heading result-heading"><h1>{job.variants?.length ? job.story?.title || "Ваша презентация" : running ? "Создаём презентацию" : "Презентация"}</h1></div>
        {connectionLostId === job.id && <p className="error-message" role="status">Связь прервалась. Презентация продолжает создаваться — переподключаемся.</p>}
        {running && <section className="status-panel" role="status" aria-live="polite"><span className="spinner" aria-hidden="true" /><h2>{progressText(job)}</h2><p>Можно начать ещё одну презентацию. Эта продолжит создаваться и сохранится в истории.</p><button className="text-button" disabled={busyAction || job.status === "cancelling"} onClick={cancel}>Остановить</button></section>}
        {running && job.status !== "cancelling" && !job.variants?.length && <SlideGame key={job.id} />}
        {jobError(job) && <p className="error-message" role="alert">{jobError(job)}</p>}
        {!!job.variants?.length && <ResultViewer job={job} busy={generationBusy} onFix={fixVariant} />}
        {!running && job.status === "awaiting_review" && job.story && <StoryEditor story={job.story}
          datasets={job.request?.datasets ?? []} profile={job.profile} busy={generationBusy}
          onChange={story => setJob(current => current ? { ...current, story } : current)} onBuild={continueSavedJob} />}
        {!running && job.status !== "awaiting_review" && !job.variants?.length && <section className="status-panel">
          <p>{job.status === "cancelled" ? "Создание остановлено." : "Презентация пока не готова."}</p><button className="secondary" onClick={() => navigate("upload")}>Вернуться к загрузке</button>
        </section>}
      </>}
      {page === "history" && <>
        <div className="page-heading"><h1>История</h1><p>Ваши презентации — всё в одном месте.</p></div>
        {historyLoading && <p role="status">Загружаем…</p>}
        {historyError && <div className="error-message" role="alert">{historyError}<button className="text-button" onClick={() => setHistoryRefresh(value => value + 1)}>Повторить</button></div>}
        {!historyLoading && !historyError && !jobs.length && <div className="status-panel"><p>Здесь появится ваша первая презентация.</p><button className="primary" onClick={() => navigate("upload")}>Создать презентацию</button></div>}
        <div className="history-list">{jobs.map(item => <button className="history-row" key={item.id} disabled={busy} onClick={() => openJob(item.id)}>
          <span><strong>{item.story?.title || item.template?.name || "Презентация"}</strong><small>{item.created_at ? new Date(item.created_at * 1000).toLocaleDateString("ru-RU") : ""}{item.request?.slide_count ? ` · ${slideCountLabel(item.request.slide_count)}` : ""}</small></span>
          <span className={`history-status ${item.status === "failed" ? "failed" : ""}`}>{historyStatus(item)}<span aria-hidden="true"> ↗</span></span>
        </button>)}</div>
      </>}
    </main>
  </div>;
}
