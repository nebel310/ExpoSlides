import assert from "node:assert/strict";
import test from "node:test";
import { renderToStaticMarkup } from "react-dom/server";
import { ApiError, StudioApi } from "../src/api";
import App from "../src/App";
import { ResultViewer } from "../src/ResultViewer";
import { RecentJobs, StoryEditor, VariantWorkspace } from "../src/components";
import { jobError, jobView, recentJobLabel, restoreJob, SAVED_JOB_KEY } from "../src/jobs";
import { activeStatus, moveSlide, overlayBox, parseContentPack, parseDataset, planModeError, selectedFixes, simpleDesignRequest, slideCountLabel, validateStory } from "../src/model";
import type { DesignRequest, Issue, Job, Profile, Story, Variant } from "../src/types";

const story: Story = { schema_version: "1.0", title: "Проект", slides: [
  { id: "one", title: "Проблема", paragraphs: ["Долгая подготовка"], source_ids: ["source-1"], visual: null, notes: "" },
  { id: "two", title: "Решение", paragraphs: ["Общий план", "Три варианта"], source_ids: ["source-2"], visual: null, notes: "" },
] };
const profile: Profile = { width: 1000, height: 500, patterns: [], warnings: [] };
const issue: Issue = { id: "overflow-1", slide_id: "one", slide_index: 1, rule: "overflow", severity: "warning", message: "Текст не помещается", check_type: "deterministic", fix: "fit_text", box: { left: 100, top: 100, width: 400, height: 200 } };
const variant: Variant = { id: "balanced", name: "Сбалансированный", description: "Две колонки", revision: 1, issues: [issue], preview_urls: ["/files/1/slide.png"], exports: { pptx: "/files/1/presentation.pptx", html: "/files/1/presentation.html" }, audit: { contextual_status: "skipped", limitations: ["PDF недоступен без рендерера"] } };

test("reordering preserves slide identity, sources and the previous plan", () => {
  const changed = moveSlide(story, 1, -1);
  assert.deepEqual(changed.slides.map(s => s.id), ["two", "one"]);
  assert.equal(changed.slides[0], story.slides[1]);
  assert.deepEqual(changed.slides[0].source_ids, ["source-2"]);
  assert.deepEqual(story.slides.map(s => s.id), ["one", "two"]);
  assert.equal(moveSlide(story, 0, -1), story);
});

test("empty edits are blocked before generation", () => {
  assert.equal(validateStory(story), null);
  assert.match(validateStory({ ...story, slides: [] })!, /хотя бы один/);
  assert.match(validateStory({ ...story, slides: [{ ...story.slides[0], paragraphs: [" "] }] })!, /содержание слайда 1/);
});

test("known missing text model blocks only model planning with an explicit next step", () => {
  const message = planModeError("llm", false);
  assert.match(message!, /Модель текста не настроена на сервере/);
  assert.match(message!, /Выберите «Проверочный · без модели»/);
  assert.match(message!, /настройте модель и обновите страницу/);
  assert.equal(planModeError("extractive", false), null);
  assert.equal(planModeError("extractive", true), null);
  assert.equal(planModeError("llm", true), null);
  // Unknown readiness is not a missing configuration; the server checks again on submission.
  assert.equal(planModeError("llm", null), null);
});

test("fix selection discards stale ids and manual-only findings", () => {
  const issues = [issue, { ...issue, id: "manual", fix: "none" }, { ...issue, id: "disabled", fix_available: false }];
  assert.deepEqual(selectedFixes(issues, new Set([issue.id, "manual", "disabled", "obsolete"])), [issue.id]);
});

test("overlays map canonical slide coordinates and clip to the slide", () => {
  assert.deepEqual(overlayBox(issue, profile), { left: "10%", top: "20%", width: "40%", height: "40%" });
  assert.deepEqual(overlayBox({ ...issue, bbox: { x: -0.1, y: 0, width: 0.5, height: 2 } }), { left: "0%", top: "0%", width: "40%", height: "100%" });
  assert.equal(overlayBox({ ...issue, bbox: { x: NaN, y: 0, width: 1, height: 1 } }), null);
  assert.equal(overlayBox({ ...issue, bbox: { x: 1.1, y: 0, width: 1, height: 1 } }), null);
  assert.equal(overlayBox(issue), null);
});

test("CSV keeps quoted labels and parses Russian decimal notation", () => {
  const data = parseDataset('\uFEFFПериод;Выручка\r\n"Первое; полугодие";12,5\r\n"Второе\nполугодие";18', "Выручка.csv", "sales");
  assert.deepEqual(data.columns, ["Период", "Выручка"]);
  assert.deepEqual(data.rows, [["Первое; полугодие", 12.5], ["Второе\nполугодие", 18]]);
  assert.equal(data.source, "Выручка.csv");
  assert.equal(data.name, "Выручка");
  assert.deepEqual(parseDataset('Name,Value\n"A ""quoted"" value",2', "data.csv", "data").rows, [['A "quoted" value', 2]]);
});

test("CSV rejects malformed data before upload", () => {
  assert.throws(() => parseDataset("a,a\n1,2", "a.csv", "a"), /различаться/);
  assert.throws(() => parseDataset("a,b\n1,2,3", "a.csv", "a"), /одинаковым/);
  assert.throws(() => parseDataset('a,b\n"open,2', "a.csv", "a"), /не закрыта/);
  assert.throws(() => parseDataset("a,b\n" + "1,2\n".repeat(201), "a.csv", "a"), /200/);
});

test("cancellation keeps polling until acknowledged", () => {
  assert.equal(activeStatus("cancelling"), true);
  for (const state of ["awaiting_review", "completed", "cancelled", "failed"]) assert.equal(activeStatus(state), false);
});

test("content pack imports text, theses, datasets and optional brief without enabling a model", () => {
  const data = parseContentPack(JSON.stringify({ script: "Выручка выросла", purpose: "Отчёт", audience: "Коллеги", required_messages: ["Показать результат"], datasets: [{ id: "sales", name: "Выручка", columns: ["Год", "Значение"], rows: [["2025", 5], ["2026", 8]], source: "Отчёт" }] }));
  assert.equal(data.script, "Выручка выросла");
  assert.deepEqual(data.required_messages, ["Показать результат"]);
  assert.equal(data.datasets[0].unit, "");
  assert.deepEqual(data.datasets[0].rows[1], ["2026", 8]);
  assert.equal(data.purpose, "Отчёт");
  assert.deepEqual(parseContentPack('{"script":"Текст"}'), { script: "Текст", required_messages: [], datasets: [] });
  assert.throws(() => parseContentPack('{"script":"Текст","generated_image":{"enabled":true}}'), /Неизвестные поля/);
});

test("content pack rejects ambiguous dataset identity, malformed rows and invalid JSON", () => {
  const data = { id: "sales", name: "Выручка", columns: ["Год", "Значение"], rows: [["2026", 8]], source: "Отчёт" };
  assert.throws(() => parseContentPack(JSON.stringify({ script: "Текст", datasets: [data, data] })), /id должен быть уникальным/);
  assert.throws(() => parseContentPack(JSON.stringify({ script: "Текст", datasets: [{ ...data, rows: [[true, 8]] }] })), /строковых или числовых/);
  assert.throws(() => parseContentPack(JSON.stringify({ script: "Текст", datasets: [{ ...data, rows: [[1]] }] })), /числу столбцов/);
  assert.throws(() => parseContentPack('{"script":'), /корректный JSON/);
  assert.throws(() => parseContentPack('{"script":" "}'), /script/);
  assert.throws(() => parseContentPack('{"script":"Текст","required_messages":[4]}'), /required_messages/);
});

test("mutations get a fresh session token and use the canonical payload", async () => {
  const calls: { path: string; init?: RequestInit }[] = [];
  const transport: typeof fetch = async (path, init) => {
    calls.push({ path: String(path), init });
    return Response.json(String(path) === "/api/session" ? { token: "fresh-token" } : { id: "job-1", status: "queued" });
  };
  const api = new StudioApi(transport);
  const result = await api.post<{ id: string }>("/api/design/jobs/job-1/build", { story });
  assert.equal(result.id, "job-1");
  assert.deepEqual(calls.map(c => c.path), ["/api/session", "/api/design/jobs/job-1/build"]);
  assert.equal(calls[1].init?.method, "POST");
  assert.equal(calls[1].init?.credentials, "same-origin");
  assert.equal(new Headers(calls[1].init?.headers).get("X-Session-Token"), "fresh-token");
  assert.deepEqual(JSON.parse(String(calls[1].init?.body)), { story });
});

test("missing session token never sends a mutation", async () => {
  let calls = 0;
  const api = new StudioApi(async () => { calls++; return Response.json({}); });
  await assert.rejects(api.post("/api/design/plan", {}), (error: unknown) => error instanceof ApiError && error.status === 403);
  assert.equal(calls, 1);
});

test("uncertain POST failure is not retried", async () => {
  let writes = 0;
  const api = new StudioApi(async path => {
    if (String(path) === "/api/session") return Response.json({ token: "token" });
    writes++; throw new TypeError("connection closed after accepting request");
  });
  await assert.rejects(api.post("/api/design/plan", {}), /Нет связи/);
  assert.equal(writes, 1);
});

test("structured validation errors and ownership failures remain visible", async () => {
  const api = new StudioApi(async () => Response.json({ detail: [{ loc: ["body", "request", "slide_count"], msg: "Must be at most 50" }] }, { status: 422 }));
  await assert.rejects(api.get("/api/design/jobs/one"), /request · slide_count: Must be at most 50/);
  const privateApi = new StudioApi(async () => Response.json({ detail: "Презентация не найдена" }, { status: 404 }));
  await assert.rejects(privateApi.get("/api/design/jobs/foreign"), (error: unknown) => error instanceof ApiError && error.status === 404);
});

test("cancelled API requests are distinguishable from network errors", async () => {
  const abort = new AbortController(); abort.abort();
  const api = new StudioApi(async (_path, init) => {
    assert.equal(init?.signal?.aborted, true); throw new DOMException("aborted", "AbortError");
  });
  await assert.rejects(api.get("/api/design/jobs/one", abort.signal), (error: unknown) => error instanceof DOMException && error.name === "AbortError");
});

test("results expose three variants, precise overlays and only available exports", () => {
  const variants = [variant, { ...variant, id: "editorial", name: "Редакционный" }, { ...variant, id: "visual", name: "Визуальный" }];
  const html = renderToStaticMarkup(<VariantWorkspace variants={variants} profile={profile} busy={false} onFix={async () => {}} />);
  assert.match(html, /Сбалансированный/); assert.match(html, /Редакционный/); assert.match(html, /Визуальный/);
  assert.match(html, /left:10%;top:20%;width:40%;height:40%/);
  assert.match(html, /href="\/files\/1\/presentation.pptx"/);
  assert.match(html, /PDF недоступен/);
  assert.doesNotMatch(html, /href="[^"]+\.pdf"/);
  assert.match(html, /disabled="">Исправить выбранное/);
  assert.match(html, /Проверка изображений моделью отключена/);
});

test("manual findings cannot be selected for an automatic fix", () => {
  const html = renderToStaticMarkup(<VariantWorkspace variants={[{ ...variant, issues: [{ ...issue, fix: "none" }] }]} busy={false} onFix={async () => {}} />);
  assert.match(html, /Требует проверки содержания или ручной правки/);
  assert.doesNotMatch(html, /Исправить это замечание/);
});

test("outline contains accessible editable fields and linked sources", () => {
  const html = renderToStaticMarkup(<StoryEditor story={story} datasets={[]} busy={false} onChange={() => {}} onBuild={() => {}} />);
  assert.match(html, /aria-label="Заголовок слайда 1"/);
  assert.match(html, /aria-label="Содержание слайда 2"/);
  assert.match(html, /title="source-1"/);
  assert.match(html, /aria-label="Поднять слайд 1" disabled/);
  assert.match(html, /Собрать три варианта/);
});

test("native SmartArt is offered only for a compatible template and diagram labels are editable", () => {
  const props = { story, datasets: [], busy: false, onChange: () => {}, onBuild: () => {} };
  assert.doesNotMatch(renderToStaticMarkup(<StoryEditor {...props} profile={profile} />), /value="smartart"/);
  const nativeProfile: Profile = { ...profile, patterns: [{ name: "SmartArt", source_slide_index: 1, font: "Arial", palette: [], warnings: [], visual_shape_ids: { smartart: [5] } }] };
  assert.match(renderToStaticMarkup(<StoryEditor {...props} profile={nativeProfile} />), /value="smartart"/);
  const diagram: Story = { ...story, slides: [{ ...story.slides[0], visual: { kind: "process", labels: ["Подготовка", "Результат"] } }] };
  assert.match(renderToStaticMarkup(<StoryEditor {...props} story={diagram} />), /aria-label="Подписи схемы слайда 1"/);
  assert.match(validateStory({ ...diagram, slides: [{ ...diagram.slides[0], visual: { kind: "process", labels: [" "] } }] })!, /двух непустых подписей/);
});

function storedJob(id = "saved-job") {
  const entries = new Map([[SAVED_JOB_KEY, id]]);
  return { getItem: (key: string) => entries.get(key) ?? null, removeItem: (key: string) => { entries.delete(key); }, setItem: (key: string, value: string) => { entries.set(key, value); } };
}

test("restore retains saved job through connection and server failures", async () => {
  for (const status of [0, 403, 500, 503]) {
    const storage = storedJob();
    const api = new StudioApi(async () => {
      if (!status) throw new TypeError("network unavailable");
      return Response.json({ detail: "temporarily unavailable" }, { status });
    });
    await assert.rejects(restoreJob(api, storage, new AbortController().signal));
    assert.equal(storage.getItem(SAVED_JOB_KEY), "saved-job");
  }
});

test("React effect cancellation does not erase restoration state", async () => {
  const storage = storedJob();
  const abort = new AbortController();
  const api = new StudioApi(async () => {
    abort.abort(); throw new DOMException("StrictMode cleanup", "AbortError");
  });
  await assert.rejects(restoreJob(api, storage, abort.signal), (error: unknown) => error instanceof DOMException && error.name === "AbortError");
  assert.equal(storage.getItem(SAVED_JOB_KEY), "saved-job");
});

test("only confirmed missing saved job is removed, without erasing a newer run", async () => {
  const storage = storedJob();
  const missing = new StudioApi(async () => Response.json({ detail: "missing" }, { status: 404 }));
  assert.equal(await restoreJob(missing, storage, new AbortController().signal), null);
  assert.equal(storage.getItem(SAVED_JOB_KEY), null);
  storage.setItem(SAVED_JOB_KEY, "old-job");
  const race = new StudioApi(async () => {
    storage.setItem(SAVED_JOB_KEY, "new-job");
    return Response.json({ detail: "missing" }, { status: 404 });
  });
  assert.equal(await restoreJob(race, storage, new AbortController().signal), null);
  assert.equal(storage.getItem(SAVED_JOB_KEY), "new-job");
});

test("partial failure restores available variants and their error instead of discarding results", async () => {
  const partial: Job = { id: "saved-job", status: "failed", error: "Rendering second variant failed", story, variants: [variant] };
  const api = new StudioApi(async () => Response.json(partial));
  const restored = await restoreJob(api, storedJob(), new AbortController().signal);
  assert.equal(jobView(restored!), "results");
  assert.equal(jobError(restored!), "Rendering second variant failed");
  const html = renderToStaticMarkup(<VariantWorkspace variants={restored!.variants!} busy={false} onFix={async () => {}} fixUnavailableReason="Исправления доступны после успешной сборки." />);
  assert.match(html, /Доступно вариантов: 1 из 3/);
  assert.match(html, /Презентация/);
  assert.match(html, /href="\/files\/1\/presentation.pptx"/);
  assert.doesNotMatch(html, /Доступно вариантов: 3 из 3/);
  assert.match(html, /Исправления доступны после успешной сборки/);
  assert.match(html, /type="checkbox" disabled=""/);
  assert.equal(jobView({ id: "pending", status: "awaiting_review", story }), "outline");
});

test("first render provides only upload, result and history with material actions session-guarded", () => {
  const html = renderToStaticMarkup(<App />);
  const navigation = html.match(/<nav[^>]*aria-label="Основная навигация"[^>]*>(.*?)<\/nav>/)?.[1];
  assert.ok(navigation);
  assert.equal((navigation.match(/<button/g) ?? []).length, 3);
  assert.match(navigation, /aria-current="page"[^>]*>Загрузка<\/button>/);
  assert.match(navigation, /disabled=""[^>]*>Результат<\/button>/);
  assert.match(navigation, /disabled=""[^>]*>История<\/button>/);
  assert.match(html, /<h1>Новая презентация<\/h1>/);
  assert.match(html, /type="file" accept="\.pptx"/);
  assert.match(html, /type="file" accept="\.txt"/);
  assert.match(html, /<textarea[^>]*id="script"[^>]*disabled=""/);
  assert.match(html, /type="submit" disabled=""[^>]*>Создать презентацию<span class="action-arrow" aria-hidden="true">↗<\/span><\/button>/);
  assert.doesNotMatch(html, /JSON|CSV|HTML|Аудит|Профиль шаблона|Создать план|С моделью|Дополнительные настройки|Открыть пример|Проверочный/);
});

test("recent jobs show precise status and accessible choices without claiming missing variants", () => {
  const jobs: Job[] = [{ id: "review", status: "awaiting_review", story }, { id: "partial", status: "failed", story: { ...story, title: "Частичный результат" }, variants: [variant] }];
  const html = renderToStaticMarkup(<RecentJobs jobs={jobs} currentId="review" loading={false} error="" busy={false} onOpen={() => {}} onRefresh={() => {}} />);
  assert.match(html, /aria-labelledby="recent-heading"/);
  assert.match(html, /aria-current="true"/);
  assert.match(html, /План ожидает проверки/);
  assert.match(html, /Ошибка · готово 1 из 3/);
  assert.doesNotMatch(html, /Три варианта готовы/);
  assert.equal(recentJobLabel({ id: "done", status: "completed", variants: [variant] }), "Доступно вариантов: 1");
  const failed = renderToStaticMarkup(<RecentJobs jobs={[]} loading={false} error="Соединение прервано" busy={false} onOpen={() => {}} onRefresh={() => {}} />);
  assert.match(failed, /role="alert">Соединение прервано/);
  assert.doesNotMatch(failed, /Работ пока нет/);
});

test("simple results provide slide navigation and only PowerPoint and PDF downloads", () => {
  const ready: Variant = {
    ...variant, preview_urls: ["/files/1/slide-1.png", "/files/1/slide-2.png"],
    exports: { ...variant.exports, pdf: "/files/1/presentation.pdf" },
  };
  const job: Job = {
    id: "ready-job", status: "completed", story, profile,
    variants: [ready, { ...ready, id: "evidence", name: "С данными" }, { ...ready, id: "cards", name: "Карточки" }],
  };
  const html = renderToStaticMarkup(<ResultViewer job={job} />);
  assert.match(html, /Вариант/);
  for (const name of ["Сбалансированный", "С данными", "Карточки"]) assert.ok(html.includes(name));
  assert.match(html, /alt="Слайд 1: Проблема"/);
  assert.match(html, /src="\/files\/1\/slide-1.png"/);
  assert.match(html, /aria-label="Открыть слайд 1"[^>]*aria-current="true"/);
  assert.match(html, /aria-label="Открыть слайд 2"/);
  assert.match(html, /aria-label="Предыдущий слайд"[^>]*disabled=""/);
  assert.match(html, /aria-label="Следующий слайд"/);
  assert.match(html, /href="\/files\/1\/presentation.pptx"[^>]*>Скачать PPTX<\/a>/);
  assert.match(html, /href="\/files\/1\/presentation.pdf"[^>]*>PDF<\/a>/);
  assert.doesNotMatch(html, /presentation\.html|>HTML<|Исправить|type="checkbox"/);
});

test("simple results do not expose audit, template internals, prompts or generation settings", () => {
  const hidden = ["private-audit-evidence", "private-audit-warning", "private-template-font", "private-template-pattern", "private-prompt-text", "private-job-warning", "private-slide-notes"];
  const job: Job = {
    id: "private-job", status: "completed",
    story: { ...story, slides: [{ ...story.slides[0], notes: hidden[6] }] },
    profile: { ...profile, warnings: [hidden[1]], patterns: [{ name: hidden[3], source_slide_index: 42, font: hidden[2], palette: ["00AACC"], warnings: [] }] },
    warnings: [hidden[5]],
    request: { script: hidden[4], purpose: "private-purpose", audience: "private-audience", slide_count: 12, count_mode: "exact", language: "ru", mode: "llm", required_messages: [], datasets: [], contextual_audit: true },
    variants: [{ ...variant, issues: [{ ...issue, evidence: hidden[0] }], audit: { contextual_status: "failed", limitations: [hidden[1]], checks: ["native_geometry"] } }],
  };
  const html = renderToStaticMarkup(<ResultViewer job={job} />);
  for (const text of hidden) assert.ok(!html.includes(text), `Result leaked ${text}`);
  assert.doesNotMatch(html, /<textarea|<pre|<details|JSON|HTML|Профиль шаблона|Аудит|Проверка изображений|native_geometry|source_shape_id|slide_count|contextual_audit|type="checkbox"/);
  assert.match(html, /Скачать PPTX/);
});

test("a result without rendered images keeps its available download and explains the missing preview", () => {
  const html = renderToStaticMarkup(<ResultViewer job={{ id: "partial-job", status: "failed", variants: [{ ...variant, preview_urls: [], exports: { pptx: "/partial.pptx", html: "/partial.html" } }] }} />);
  assert.match(html, /Предпросмотр недоступен/);
  assert.match(html, /Презентацию можно скачать и открыть на компьютере/);
  assert.match(html, /href="\/partial.pptx"/);
  assert.doesNotMatch(html, /<img|href="\/partial.html"|>PDF<|Слайд 0|undefined|NaN/);
});

test("an unfinished result does not invent exports or slide previews", () => {
  const html = renderToStaticMarkup(<ResultViewer job={{ id: "pending-job", status: "building" }} />);
  assert.match(html, /Презентация ещё не готова/);
  assert.doesNotMatch(html, /<img|Скачать PPTX|>PDF<|undefined|NaN/);
});


test("retrying a legacy job sends only visible materials and clears hidden generation settings", async () => {
  const legacy: DesignRequest = {
    script: "Старый текст", slide_count: 7, purpose: "Старый бриф", audience: "Инвесторы",
    language: "en", mode: "extractive", count_mode: "maximum", contextual_audit: true,
    required_messages: ["Устаревший обязательный тезис"],
    datasets: [{ id: "old-data", name: "Старые данные", columns: ["Год", "Прибыль"], rows: [[2025, 100]], source: "old.csv", unit: "руб." }],
    generated_image: { enabled: true, prompt: "Старая иллюстрация", seed: 42, width: 1024, height: 576, source_ids: ["old-source"], palette: ["FF0000"] },
  };
  const restored = simpleDesignRequest(legacy);
  assert.equal(restored.script, "Старый текст");
  assert.equal(restored.slide_count, 7);
  assert.equal(restored.required_messages.length, 0);
  assert.equal(restored.datasets.length, 0);
  assert.equal(restored.generated_image, undefined);
  assert.equal(restored.contextual_audit, false);
  assert.equal(restored.mode, "llm");
  assert.equal(restored.count_mode, "exact");
  assert.equal(restored.language, "ru");
  assert.notEqual(restored.purpose, legacy.purpose);
  assert.notEqual(restored.audience, legacy.audience);
  const api = new StudioApi(async (path, init) => {
    if (String(path) === "/api/session") return Response.json({ token: "token" });
    assert.equal(String(path), "/api/design/generate");
    const payload = JSON.parse(String(init?.body));
    assert.equal(payload.request.script, "Новые факты");
    assert.equal(payload.request.slide_count, 7);
    assert.doesNotMatch(JSON.stringify(payload), /old-data|old-source|old.csv|Устаревший|Старая иллюстрация|generated_image/);
    assert.equal(payload.request.contextual_audit, false);
    return Response.json({ id: "new-job", status: "queued" });
  });
  await api.post("/api/design/generate", { template_id: "template-1", request: simpleDesignRequest({ ...restored, script: "Новые факты" }) });
  assert.equal(legacy.generated_image?.enabled, true);
  assert.equal(legacy.datasets.length, 1);
  restored.datasets.push(legacy.datasets[0]);
  restored.required_messages.push("Локальная правка");
  assert.deepEqual(simpleDesignRequest().datasets, []);
  assert.deepEqual(simpleDesignRequest().required_messages, []);
});

test("history slide counts use Russian plural forms including the eleven-to-fourteen exception", () => {
  for (const [count, label] of [[0, "0 слайдов"], [1, "1 слайд"], [2, "2 слайда"], [3, "3 слайда"], [4, "4 слайда"], [5, "5 слайдов"], [11, "11 слайдов"], [12, "12 слайдов"], [14, "14 слайдов"], [20, "20 слайдов"], [21, "21 слайд"], [22, "22 слайда"], [25, "25 слайдов"], [101, "101 слайд"], [111, "111 слайдов"], [114, "114 слайдов"]] as const) {
    assert.equal(slideCountLabel(count), label);
  }
});
