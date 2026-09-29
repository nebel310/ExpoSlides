import assert from "node:assert/strict";
import test from "node:test";
import { JSDOM } from "jsdom";
import { act } from "react";
import App from "../src/App";
import { api } from "../src/api";
import { SAVED_JOB_KEY } from "../src/jobs";
import { simpleDesignRequest } from "../src/model";
import type { DesignRequest, Job, Template } from "../src/types";

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: Error) => void;
  const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}

function makeJob(id: string, status: string, request = simpleDesignRequest(), template?: Template): Job {
  return {
    id, status, created_at: Number(id.replace(/\D/g, "")) || 1, request, template,
    story: { schema_version: "1.0", title: `Презентация ${id}`, slides: [{
      id: "s1", title: "Итоги", paragraphs: ["Результаты команды"],
      source_ids: ["source-1"], visual: null, notes: "",
    }] },
    profile: { width: 1000, height: 500, patterns: [], warnings: [] },
    variants: status === "completed" ? [{
      id: "story", name: "История", description: "", revision: 1,
      preview_urls: [`/${id}/slide.png`], exports: { pptx: `/${id}/result.pptx` },
      issues: [{ id: "fit", slide_id: "s1", slide_index: 1, rule: "text_capacity",
        severity: "warning", message: "Текст не помещается", fix: "fit_text", check_type: "deterministic" }],
    }] : [],
  };
}

async function workspace(status = "running") {
  const dom = new JSDOM('<div id="root"></div>', { url: "http://localhost" });
  const originals = new Map<string, PropertyDescriptor | undefined>();
  for (const [key, value] of Object.entries({ window: dom.window, document: dom.window.document,
    navigator: dom.window.navigator, FileReader: dom.window.FileReader, sessionStorage: dom.window.sessionStorage,
    IS_REACT_ACT_ENVIRONMENT: true })) {
    originals.set(key, Object.getOwnPropertyDescriptor(globalThis, key));
    Object.defineProperty(globalThis, key, { configurable: true, writable: true, value });
  }
  dom.window.HTMLElement.prototype.scrollBy = () => {};
  const originalGet = api.get, originalPost = api.post, originalUpload = api.uploadTemplate;
  const jobs = new Map<string, Job>();
  const templates = new Map<string, Template>();
  const calls: { path: string; body?: unknown; signal?: AbortSignal }[] = [];
  const intercept: {
    get?: (path: string, signal?: AbortSignal) => Promise<unknown> | undefined;
    post?: (path: string, body?: unknown) => Promise<unknown> | undefined;
  } = {};
  api.get = (async (path: string, signal?: AbortSignal) => {
    calls.push({ path, signal });
    const response = intercept.get?.(path, signal);
    if (response) return response;
    if (path === "/api/session") return { token: "test" };
    if (path === "/api/capabilities") return { story: true };
    if (path === "/api/design/jobs") return { jobs: [...jobs.values()] };
    const job = jobs.get(decodeURIComponent(path.split("/").at(-1)!));
    assert.ok(job, `Unexpected request: ${path}`);
    return job;
  }) as typeof api.get;
  api.uploadTemplate = (async (body: { name: string }) => {
    const template = { id: `template-${templates.size + 1}`, name: body.name, slide_count: 3 };
    templates.set(template.id, template);
    return template;
  }) as typeof api.uploadTemplate;
  api.post = (async (path: string, body?: unknown) => {
    calls.push({ path, body });
    const response = intercept.post?.(path, body);
    if (response) return response;
    assert.equal(path, "/api/design/generate");
    const sent = body as { request: DesignRequest; template_id: string };
    const job = makeJob(`job-${jobs.size + 1}`, status, structuredClone(sent.request), templates.get(sent.template_id));
    jobs.set(job.id, job);
    return job;
  }) as typeof api.post;
  const { createRoot } = await import("react-dom/client");
  let root = createRoot(document.getElementById("root")!);
  const button = (label: string) => {
    const found = [...document.querySelectorAll<HTMLButtonElement>("button")]
      .find(item => item.textContent === label || item.getAttribute("aria-label") === label);
    assert.ok(found, `Button not found: ${label}`);
    return found;
  };
  const click = async (label: string) => act(async () => button(label).click());
  const file = async (label: string, value: unknown) => act(async () => {
    const input = document.querySelector<HTMLInputElement>(`input[aria-label="${label}"]`)!;
    assert.ok(input, `File input not found: ${label}`);
    Object.defineProperty(input, "files", { configurable: true, value: [value] });
    input.dispatchEvent(new dom.window.Event("change", { bubbles: true }));
    await new Promise(resolve => setTimeout(resolve, 20));
  });
  const textFile = (name: string, content: string) => ({ name, size: content.length,
    arrayBuffer: async () => new TextEncoder().encode(content).buffer });
  const fill = async (label: string, withData = false) => {
    await file("Файл шаблона", new dom.window.File(["pptx"], `${label}.pptx`));
    await file("Файл с текстом", textFile("script.txt", `Содержание ${label}`));
    if (withData) {
      await file("Файл с данными", textFile("sales.csv", "Период;Выручка\n001;12\n002;18"));
      await act(async () => {
        const input = document.querySelector<HTMLInputElement>('input[type="number"]')!;
        Object.getOwnPropertyDescriptor(dom.window.HTMLInputElement.prototype, "value")!.set!.call(input, "7");
        input.dispatchEvent(new dom.window.Event("input", { bubbles: true }));
      });
    }
    assert.equal(document.querySelector<HTMLButtonElement>('button[type="submit"]')!.disabled, false);
  };
  const submit = async () => act(async () => {
    document.querySelector("form")!.dispatchEvent(new dom.window.Event("submit", { bubbles: true, cancelable: true }));
  });
  const fresh = () => {
    assert.equal(document.querySelector("h1")!.textContent, "Новая презентация");
    assert.equal(document.querySelector<HTMLTextAreaElement>("#script")!.value, "");
    assert.equal(document.querySelector<HTMLInputElement>('input[type="number"]')!.value, String(simpleDesignRequest().slide_count));
    assert.equal(document.querySelector(".file-name")!.textContent, "Выберите или перетащите файл");
    assert.equal(document.querySelector<HTMLButtonElement>(".upload-zone")!.disabled, false);
    assert.equal(document.querySelector<HTMLButtonElement>('button[type="submit"]')!.disabled, true);
    assert.equal(document.querySelectorAll(".dataset-file").length, 0);
    assert.doesNotMatch(document.body.textContent!, /sales\.csv|Создаём презентацию|Подготовка…/);
    assert.equal(button("Результат").disabled, true);
    assert.equal(sessionStorage.getItem(SAVED_JOB_KEY), null);
  };
  await act(async () => root.render(<App />));
  return { dom, jobs, calls, intercept, button, click, fill, submit, fresh,
    async reload() {
      await act(async () => root.unmount());
      root = createRoot(document.getElementById("root")!);
      await act(async () => root.render(<App />));
    },
    async dispose() {
      await act(async () => root.unmount());
      api.get = originalGet; api.post = originalPost; api.uploadTemplate = originalUpload;
      dom.window.close();
      for (const [key, descriptor] of originals) {
        if (descriptor) Object.defineProperty(globalThis, key, descriptor);
        else Reflect.deleteProperty(globalThis, key);
      }
    },
  };
}

for (const status of ["completed", "running"] as const) {
  for (const destination of ["Загрузка", "История", "ExpoSlides"] as const) {
    test(`leaving ${status} result through ${destination} clears materials and permits another job`, async () => {
      const app = await workspace(status);
      try {
        await app.fill("Первая", true);
        await app.submit();
        const first = app.jobs.get("job-1")!;
        assert.equal(first.request!.slide_count, 7);
        assert.equal(first.request!.datasets.length, 1);
        assert.equal(sessionStorage.getItem(SAVED_JOB_KEY), "job-1");
        await app.click(destination);
        assert.equal(app.button("Результат").disabled, true);
        assert.equal(sessionStorage.getItem(SAVED_JOB_KEY), null);
        if (destination === "История") {
          assert.equal(document.querySelectorAll(".history-row").length, 1);
          await app.click("Загрузка");
        }
        app.fresh();
        await app.reload();
        app.fresh();
        await app.fill("Вторая");
        await app.submit();
        assert.equal(app.jobs.size, 2);
        assert.equal(app.jobs.get("job-1")!.status, status);
        assert.equal(app.jobs.get("job-2")!.request!.script, "Содержание Вторая");
        assert.deepEqual(app.jobs.get("job-2")!.request!.datasets, []);
        assert.equal(app.jobs.get("job-2")!.request!.slide_count, 12);
        assert.equal(sessionStorage.getItem(SAVED_JOB_KEY), "job-2");
        await app.click("История");
        const rows = [...document.querySelectorAll<HTMLButtonElement>(".history-row")];
        assert.equal(rows.length, 2);
        assert.match(rows[0].textContent!, /Презентация job-2/);
        const firstRow = rows.find(row => row.textContent?.includes("Презентация job-1"))!;
        assert.match(firstRow.textContent!, status === "running" ? /Создаётся/ : /Готово/);
        await act(async () => firstRow.click());
        assert.equal(sessionStorage.getItem(SAVED_JOB_KEY), "job-1");
        assert.equal(document.querySelector("h1")!.textContent,
          status === "running" ? "Создаём презентацию" : "Презентация job-1");
        assert.equal(app.calls.filter(call => call.path.endsWith("/cancel")).length, 0);
        assert.equal(first.request!.script, "Содержание Первая");
        assert.equal(first.request!.datasets.length, 1);
        await app.click("Загрузка");
        app.fresh();
      } finally { await app.dispose(); }
    });
  }
}

test("leaving a result aborts polling and ignores its late response", async () => {
  const app = await workspace();
  const pending = deferred<Job>();
  try {
    await app.fill("Первая");
    await app.submit();
    app.intercept.get = path => path.endsWith("/job-1") ? pending.promise : undefined;
    await act(async () => { await new Promise(resolve => setTimeout(resolve, 450)); });
    const poll = app.calls.find(call => call.path.endsWith("/job-1"));
    assert.ok(poll);
    await app.click("Загрузка");
    app.fresh();
    assert.equal(poll.signal?.aborted, true);
    await app.fill("Вторая");
    await app.submit();
    await act(async () => pending.resolve(makeJob("job-1", "completed")));
    assert.equal(sessionStorage.getItem(SAVED_JOB_KEY), "job-2");
    assert.equal(document.querySelector("h1")!.textContent, "Создаём презентацию");
    assert.doesNotMatch(document.body.textContent!, /Презентация job-1/);
  } finally { await app.dispose(); }
});

for (const action of ["cancel", "fix", "build"] as const) {
  for (const outcome of ["success", "failure"] as const) {
    test(`late ${action} ${outcome} cannot restore an old result or unlock a new submission`, async () => {
      const app = await workspace(action === "fix" ? "completed" : action === "build" ? "awaiting_review" : "running");
      const pending = deferred<Job>();
      const next = deferred<Job>();
      try {
        await app.fill("Первая");
        await app.submit();
        app.intercept.post = path => path.endsWith(`/${action}`) ? pending.promise : undefined;
        if (action === "fix") {
          await act(async () => document.querySelector<HTMLInputElement>('.workflow-issue input[type="checkbox"]')!.click());
          await app.click("Исправить выбранное (1)");
        } else await app.click(action === "cancel" ? "Остановить" : "Собрать три варианта");
        assert.ok(app.calls.some(call => call.path.endsWith(`/${action}`)));
        await app.click("Загрузка");
        app.fresh();
        await app.fill("Вторая");
        app.intercept.post = path => path === "/api/design/generate" ? next.promise : undefined;
        await app.submit();
        assert.equal(document.querySelector<HTMLButtonElement>('button[type="submit"]')!.disabled, true);
        await act(async () => {
          if (outcome === "success") pending.resolve(makeJob("job-1", action === "cancel" ? "cancelled" : "completed"));
          else pending.reject(new Error("Ошибка предыдущей презентации"));
        });
        assert.equal(document.querySelector("h1")!.textContent, "Новая презентация");
        assert.equal(document.querySelector<HTMLTextAreaElement>("#script")!.value, "Содержание Вторая");
        assert.equal(document.querySelector<HTMLButtonElement>('button[type="submit"]')!.disabled, true,
          "old action must not release the new submission's busy state");
        assert.equal(app.button("Результат").disabled, true);
        assert.doesNotMatch(document.body.textContent!, /Ошибка предыдущей презентации/);
        await act(async () => next.resolve(makeJob("job-2", "completed")));
        assert.equal(document.querySelector("h1")!.textContent, "Презентация job-2");
        assert.equal(sessionStorage.getItem(SAVED_JOB_KEY), "job-2");
      } finally { await app.dispose(); }
    });
  }
}

for (const action of ["open", "generate"] as const) {
  test(`leaving a pending ${action} does not reopen its result when the response arrives`, async () => {
    const app = await workspace("completed");
    const pending = deferred<Job>();
    try {
      await app.fill("Первая");
      if (action === "open") {
        await app.submit();
        await app.click("История");
        app.intercept.get = path => path.endsWith("/job-1") ? pending.promise : undefined;
        await act(async () => document.querySelector<HTMLButtonElement>(".history-row")!.click());
        await app.click("Загрузка");
        app.fresh();
      } else {
        app.intercept.post = path => path === "/api/design/generate" ? pending.promise : undefined;
        await app.submit();
        await app.click("История");
      }
      await act(async () => pending.resolve(makeJob("job-1", "completed")));
      assert.equal(document.querySelector("h1")!.textContent, action === "open" ? "Новая презентация" : "История");
      assert.equal(app.button("Результат").disabled, true);
      assert.equal(sessionStorage.getItem(SAVED_JOB_KEY), null);
      assert.equal(document.querySelectorAll('[role="alert"]').length, 0);
    } finally { await app.dispose(); }
  });
}

for (const status of ["failed", "cancelled"] as const) {
  test(`return button clears all materials from a ${status} result`, async () => {
    const app = await workspace(status);
    try {
      await app.fill("Первая", true);
      await app.submit();
      await app.click("Вернуться к загрузке");
      app.fresh();
      assert.equal(app.jobs.get("job-1")!.request!.datasets.length, 1);
      await app.click("История");
      assert.equal(document.querySelectorAll(".history-row").length, 1);
    } finally { await app.dispose(); }
  });
}

test("history refreshes running jobs and can reopen a newly completed presentation", async () => {
  const app = await workspace();
  try {
    await app.fill("Первая");
    await app.submit();
    await app.click("История");
    assert.match(document.querySelector(".history-row")!.textContent!, /Создаётся/);
    const initialRefreshes = app.calls.filter(call => call.path === "/api/design/jobs").length;
    const first = app.jobs.get("job-1")!;
    app.jobs.set(first.id, makeJob(first.id, "completed", first.request, first.template));
    await act(async () => { await new Promise(resolve => setTimeout(resolve, 1550)); });
    assert.ok(app.calls.filter(call => call.path === "/api/design/jobs").length > initialRefreshes);
    assert.match(document.querySelector(".history-row")!.textContent!, /Готово/);
    assert.doesNotMatch(document.querySelector(".history-row")!.textContent!, /Создаётся/);
    await act(async () => document.querySelector<HTMLButtonElement>(".history-row")!.click());
    assert.equal(document.querySelector("h1")!.textContent, "Презентация job-1");
    assert.equal(document.querySelector<HTMLAnchorElement>('.viewer-downloads a')!.getAttribute("href"), "/job-1/result.pptx");
    await app.click("ExpoSlides");
    app.fresh();
  } finally { await app.dispose(); }
});
