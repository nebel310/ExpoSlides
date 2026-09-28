import { useEffect, useRef, useState } from "react";
import { api, ApiError } from "./api";
import { jobError, restoreJob, SAVED_JOB_KEY } from "./jobs";
import { activeStatus, simpleDesignRequest, slideCountLabel } from "./model";
import { ResultViewer } from "./ResultViewer";
import type { DesignRequest, Job, Template } from "./types";

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
    reader.onerror = () => reject(new Error("Не удалось прочитать файл."));
    reader.onload = () => resolve(String(reader.result).split(",")[1]);
    reader.readAsDataURL(file);
  });
}

export default function App() {
  const [page, setPage] = useState<Page>("upload");
  const [request, setRequest] = useState<DesignRequest>(initialRequest);
  const [template, setTemplate] = useState<Template | null>(null);
  const [job, setJob] = useState<Job | null>(null);
  const [activeJobId, setActiveJobId] = useState<string | null>(null);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [error, setError] = useState("");
  const [ready, setReady] = useState(false);
  const [restoring, setRestoring] = useState(true);
  const [busyAction, setBusyAction] = useState(false);
  const [connectionLostId, setConnectionLostId] = useState<string | null>(null);
  const [storyAvailable, setStoryAvailable] = useState<boolean | null>(null);
  const [connectAttempt, setConnectAttempt] = useState(0);
  const [historyRefresh, setHistoryRefresh] = useState(0);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [historyError, setHistoryError] = useState("");
  const [dragging, setDragging] = useState(false);
  const uploadRef = useRef<HTMLInputElement>(null);
  const textRef = useRef<HTMLInputElement>(null);
  const running = !!job && activeStatus(job.status);
  const busy = busyAction || !ready || restoring;
  const generationBusy = busy || !!activeJobId || running;

  function failure(value: unknown) {
    setError(value instanceof Error ? value.message : "Не удалось выполнить действие.");
  }
  function trackJob(next: Job) {
    setJob(next);
    if (activeStatus(next.status)) setActiveJobId(current => current ?? next.id);
    else setActiveJobId(current => current === next.id ? null : current);
  }
  function navigate(next: Page) { setPage(next); setError(""); }

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
    restoreJob(api, storage, controller.signal).then(value => {
      if (!controller.signal.aborted && value) { trackJob(value); setPage("result"); }
    }).catch(() => {
      if (!controller.signal.aborted) setError("Не удалось открыть последнюю презентацию. Она сохранена в истории.");
    }).finally(() => { if (!controller.signal.aborted) setRestoring(false); });
    return () => controller.abort();
  }, [ready]);

  useEffect(() => {
    if (page !== "history" || !ready) return;
    const controller = new AbortController();
    setHistoryLoading(true); setHistoryError("");
    api.get<{ jobs: Job[] }>("/api/design/jobs", controller.signal).then(value => {
      if (!controller.signal.aborted) setJobs([...value.jobs].sort((a, b) => (b.created_at ?? 0) - (a.created_at ?? 0)));
    }).catch(value => {
      if (!controller.signal.aborted) setHistoryError(value instanceof Error ? value.message : "Не удалось загрузить историю.");
    }).finally(() => { if (!controller.signal.aborted) setHistoryLoading(false); });
    return () => controller.abort();
  }, [page, ready, historyRefresh, job?.status]);

  function watchJob(id: string) {
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    function finish() {
      setActiveJobId(current => current === id ? null : current);
      setHistoryRefresh(value => value + 1);
      setConnectionLostId(current => current === id ? null : current);
    }
    async function poll() {
      try {
        const next = await api.get<Job>(`/api/design/jobs/${encodeURIComponent(id)}`, controller.signal);
        if (controller.signal.aborted) return;
        setConnectionLostId(current => current === id ? null : current);
        setJob(current => current?.id === id ? next : current);
        setJobs(current => current.map(item => item.id === id ? next : item));
        if (activeStatus(next.status)) timer = setTimeout(poll, 1500);
        else finish();
      } catch (value) {
        if (controller.signal.aborted) return;
        if (value instanceof ApiError && value.status === 404) {
          const markMissing = (current: Job): Job => current.id === id
            ? { ...current, status: "failed", error: value.message } : current;
          setJob(current => current ? markMissing(current) : current);
          setJobs(current => current.map(markMissing));
          finish();
        } else { setConnectionLostId(id); timer = setTimeout(poll, 4000); }
      }
    }
    timer = setTimeout(poll, 400);
    return () => { controller.abort(); clearTimeout(timer); };
  }

  // Основной процесс опрашивается независимо от открытого результата и страницы истории.
  useEffect(() => {
    if (activeJobId) return watchJob(activeJobId);
  }, [activeJobId]);

  const viewedActiveId = running && job.id !== activeJobId ? job.id : null;
  useEffect(() => {
    if (viewedActiveId) return watchJob(viewedActiveId);
  }, [viewedActiveId]);

  useEffect(() => {
    if (!activeJobId && running) {
      setActiveJobId(job.id);
    }
  }, [activeJobId, job?.id, running]);

  useEffect(() => {
    // Просмотр готового результата не должен забывать выполняющуюся работу при обновлении страницы.
    const savedId = activeJobId ?? job?.id;
    if (savedId) {
      try { sessionStorage.setItem(SAVED_JOB_KEY, savedId); } catch { /* Работа остаётся в истории. */ }
    }
  }, [activeJobId, job?.id]);

  async function upload(file?: File) {
    if (!file || busy) return;
    if (!/\.pptx$/i.test(file.name) || !file.size || file.size > 25 * 1024 * 1024) {
      setError("Выберите PPTX размером до 25 МБ."); return;
    }
    setBusyAction(true); setError("");
    try {
      setTemplate(await api.post<Template>("/api/templates", { name: file.name, data: await readFile(file) }));
    } catch (value) { failure(value); }
    finally { setBusyAction(false); if (uploadRef.current) uploadRef.current.value = ""; }
  }
  async function importText(file?: File) {
    if (!file || busy) return;
    setBusyAction(true); setError("");
    try {
      if (!/\.txt$/i.test(file.name) || file.size > 400000) throw new Error("Выберите текстовый файл TXT в UTF-8.");
      const script = new TextDecoder("utf-8", { fatal: true }).decode(await file.arrayBuffer());
      if (!script.trim() || script.length > 100000) throw new Error("В файле должен быть текст до 100 000 символов.");
      setRequest(current => ({ ...current, script }));
    } catch (value) { failure(value); }
    finally { setBusyAction(false); if (textRef.current) textRef.current.value = ""; }
  }
  async function generate() {
    if (generationBusy || !template || !request.script.trim()) return;
    setBusyAction(true); setError("");
    try {
      trackJob(await api.post<Job>("/api/design/generate", { template_id: template.id, request: simpleDesignRequest(request) }));
      setConnectionLostId(null); setPage("result");
    } catch (value) { failure(value); }
    finally { setBusyAction(false); }
  }
  async function openJob(id: string) {
    if (busy) return;
    setBusyAction(true); setError("");
    try {
      trackJob(await api.get<Job>(`/api/design/jobs/${encodeURIComponent(id)}`));
      setConnectionLostId(null); setPage("result");
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
  async function continueSavedJob() {
    if (!job?.story || generationBusy) return;
    setBusyAction(true); setError("");
    try { trackJob(await api.post<Job>(`/api/design/jobs/${encodeURIComponent(job.id)}/build`, { story: job.story })); }
    catch (value) { failure(value); }
    finally { setBusyAction(false); }
  }
  function editMaterials() {
    setRequest(simpleDesignRequest(job?.request));
    setTemplate(job?.template ?? null);
    navigate("upload");
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
            <h2 className="field-label" id="template-label"><span className="field-number" aria-hidden="true">01</span>Шаблон презентации</h2>
            <input ref={uploadRef} type="file" accept=".pptx" hidden aria-label="Файл шаблона" onChange={event => upload(event.target.files?.[0])} />
            <button type="button" className={`upload-zone ${dragging ? "dragging" : ""} ${template ? "loaded" : ""}`} disabled={busy}
              onClick={() => uploadRef.current?.click()} onDragOver={event => { event.preventDefault(); if (!busy) setDragging(true); }}
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
              <strong className="file-name">{template?.name || "Выберите или перетащите файл"}</strong>
              <span className="file-meta">{template ? "Нажмите, чтобы заменить" : "PPTX · до 25 МБ"}</span>
            </button>
          </section><section aria-labelledby="script-label">
            <div className="input-heading"><label className="field-label" id="script-label" htmlFor="script"><span className="field-number" aria-hidden="true">02</span>Содержание</label><button type="button" className="text-button" disabled={busy} onClick={() => textRef.current?.click()}>Загрузить текст</button></div>
            <input ref={textRef} type="file" accept=".txt" hidden aria-label="Файл с текстом" onChange={event => importText(event.target.files?.[0])} />
            <textarea className="script-input" id="script" value={request.script} rows={12} maxLength={100000} disabled={busy} placeholder="О чём будет презентация? Вставьте сюда текст, факты и основные мысли." onChange={event => setRequest({ ...request, script: event.target.value })} />
          </section></div>
          <div className="upload-actions"><label className="slide-count">Слайдов<input type="number" min={1} max={50} required value={request.slide_count} disabled={busy} onChange={event => setRequest({ ...request, slide_count: Math.min(50, Math.max(1, Number(event.target.value))) })} /></label>
            <button className="primary" type="submit" disabled={generationBusy || !template || !request.script.trim() || (request.mode === "llm" && storyAvailable === false)}>{busyAction ? "Подготовка…" : "Создать презентацию"}<span className="action-arrow" aria-hidden="true">↗</span></button></div>
          {request.mode === "llm" && storyAvailable === false && <p className="error-message" role="status">Сервис генерации временно недоступен. Попробуйте позже.</p>}
        </form>
      </>}
      {page === "result" && job && <>
        <div className="page-heading result-heading"><h1>{job.variants?.length ? job.story?.title || "Ваша презентация" : running ? "Создаём презентацию" : "Презентация"}</h1></div>
        {connectionLostId === job.id && <p className="error-message" role="status">Связь прервалась. Презентация продолжает создаваться — переподключаемся.</p>}
        {running && <section className="status-panel" role="status" aria-live="polite"><span className="spinner" aria-hidden="true" /><h2>{progressText(job)}</h2><p>Это займёт несколько минут. Результат сохранится в истории.</p><button className="text-button" disabled={busyAction || job.status === "cancelling"} onClick={cancel}>Остановить</button></section>}
        {jobError(job) && <p className="error-message" role="alert">{jobError(job)}</p>}
        {!!job.variants?.length && <ResultViewer job={job} />}
        {!running && !job.variants?.length && <section className="status-panel">
          {job.status === "awaiting_review" ? <><p>Эту презентацию можно досоздать.</p><button className="primary" disabled={generationBusy} onClick={continueSavedJob}>Продолжить создание</button></> : <><p>{job.status === "cancelled" ? "Создание остановлено." : "Презентация пока не готова."}</p><button className="secondary" onClick={editMaterials}>Вернуться к загрузке</button></>}
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
