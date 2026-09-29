import assert from "node:assert/strict";
import test from "node:test";
import { JSDOM } from "jsdom";
import { act } from "react";
import App from "../src/App";
import { api } from "../src/api";

for (const outcome of ["success", "failure"] as const) {
  test(`text stays editable during upload and survives ${outcome}`, async () => {
    const dom = new JSDOM('<div id="root"></div>', { url: "http://localhost" });
    const oldGet = api.get, oldUpload = api.uploadTemplate;
    const original = new Map<string, PropertyDescriptor | undefined>();
    for (const [key, value] of Object.entries({ window: dom.window, document: dom.window.document,
      navigator: dom.window.navigator, FileReader: dom.window.FileReader, sessionStorage: dom.window.sessionStorage,
      IS_REACT_ACT_ENVIRONMENT: true })) {
      original.set(key, Object.getOwnPropertyDescriptor(globalThis, key));
      Object.defineProperty(globalThis, key, { configurable: true, writable: true, value });
    }
    api.get = (async (path: string) => path === "/api/session" ? { token: "test" } : { story: true }) as typeof api.get;
    let resolveUpload!: (value: unknown) => void;
    let rejectUpload!: (reason: Error) => void;
    let uploads = 0;
    api.uploadTemplate = (() => { uploads++; return new Promise<unknown>((resolve, reject) => {
      resolveUpload = resolve; rejectUpload = reject;
    }); }) as typeof api.uploadTemplate;
    const { createRoot } = await import("react-dom/client");
    const root = createRoot(dom.window.document.getElementById("root")!);
    const changeFile = (label: string, file: unknown) => {
      const input = dom.window.document.querySelector<HTMLInputElement>(`input[aria-label="${label}"]`)!;
      Object.defineProperty(input, "files", { configurable: true, value: [file] });
      input.dispatchEvent(new dom.window.Event("change", { bubbles: true }));
    };
    try {
      await act(async () => { root.render(<App />); });
      await act(async () => {
        changeFile("Файл шаблона", new dom.window.File(["pptx"], "template.pptx"));
        for (let i = 0; i < 20 && !uploads; i++) await new Promise(resolve => setTimeout(resolve, 5));
      });
      assert.equal(uploads, 1);
      const script = dom.window.document.querySelector<HTMLTextAreaElement>("#script")!;
      assert.equal(script.disabled, false); assert.equal(script.readOnly, false);
      const importButton = [...dom.window.document.querySelectorAll("button")].find(b => b.textContent === "Загрузить текст")!;
      assert.equal(importButton.disabled, false);
      assert.equal(dom.window.document.querySelector<HTMLButtonElement>(".upload-zone")!.disabled, true);
      assert.equal(dom.window.document.querySelector<HTMLButtonElement>('button[type="submit"]')!.disabled, true);
      await act(async () => {
        changeFile("Файл с текстом", { name: "text.txt", size: 30,
          arrayBuffer: async () => new TextEncoder().encode("Текст во время загрузки").buffer });
      });
      assert.equal(script.value, "Текст во время загрузки");
      await act(async () => {
        Object.getOwnPropertyDescriptor(dom.window.HTMLTextAreaElement.prototype, "value")!.set!.call(script, "Дополненный текст");
        script.dispatchEvent(new dom.window.Event("input", { bubbles: true }));
      });
      await act(async () => {
        changeFile("Файл шаблона", new dom.window.File(["other"], "second.pptx"));
      });
      assert.equal(uploads, 1);
      await act(async () => {
        if (outcome === "success") resolveUpload({ id: "uploaded", name: "template.pptx", slide_count: 1 });
        else rejectUpload(new Error("Проверочная ошибка загрузки"));
      });
      assert.equal(script.value, "Дополненный текст");
      assert.equal(script.disabled, false);
      assert.equal(dom.window.document.querySelector<HTMLButtonElement>(".upload-zone")!.disabled, false);
      assert.equal(dom.window.document.querySelector<HTMLButtonElement>('button[type="submit"]')!.disabled, outcome === "failure");
      if (outcome === "failure") assert.match(dom.window.document.body.textContent!, /Проверочная ошибка/);
    } finally {
      await act(async () => root.unmount());
      api.get = oldGet; api.uploadTemplate = oldUpload;
      dom.window.close();
      for (const [key, descriptor] of original) {
        if (descriptor) Object.defineProperty(globalThis, key, descriptor);
        else Reflect.deleteProperty(globalThis, key);
      }
    }
  });
}


test("saved plan can be edited and built, audit fixes submit only selected issues", async () => {
  const dom = new JSDOM('<div id="root"></div>', { url: "http://localhost" });
  const oldGet = api.get, oldPost = api.post;
  const original = new Map<string, PropertyDescriptor | undefined>();
  for (const [key, value] of Object.entries({ window: dom.window, document: dom.window.document,
    navigator: dom.window.navigator, sessionStorage: dom.window.sessionStorage, IS_REACT_ACT_ENVIRONMENT: true })) {
    original.set(key, Object.getOwnPropertyDescriptor(globalThis, key));
    Object.defineProperty(globalThis, key, { configurable: true, writable: true, value });
  }
  dom.window.HTMLElement.prototype.scrollBy = () => {};
  const story = { schema_version: "1.0", title: "Библиотека", slides: [{ id: "s1", title: "Каталог", paragraphs: ["Читатели выбирают книги"], source_ids: ["source-1"], visual: null, notes: "" }] };
  const issue = { id: "fit", slide_id: "s1", slide_index: 1, rule: "text_capacity", severity: "warning", message: "Текст не помещается", fix: "fit_text", check_type: "deterministic", box: { left: 10, top: 10, width: 100, height: 50 } };
  let saved: any = { id: "test-job", status: "awaiting_review", story, request: { datasets: [] } };
  dom.window.sessionStorage.setItem("exposlides-studio-job", saved.id);
  api.get = (async (path: string) => path === "/api/session" ? { token: "test" }
    : path === "/api/capabilities" ? { story: true, contextual_audit: true } : saved) as typeof api.get;
  const calls: { path: string; body: any }[] = [];
  api.post = (async (path: string, body: any) => {
    calls.push({ path, body });
    saved = { ...saved, status: "completed", story: body.story ?? saved.story,
      profile: { width: 1000, height: 500, patterns: [], warnings: [] },
      variants: [{ id: "story", name: "История", revision: path.endsWith("/fix") ? 2 : 1,
        issues: path.endsWith("/fix") ? [] : [issue, { ...issue, id: "manual", fix: "none", message: "Проверьте смысл" }],
        preview_urls: ["/slide.png"], exports: { pptx: "/presentation.pptx" }, contextual_status: "not_run",
        limitations: ["Техническое ограничение: endpoint с поддержкой изображений"] }] };
    return saved;
  }) as typeof api.post;
  const { createRoot } = await import("react-dom/client");
  const root = createRoot(dom.window.document.getElementById("root")!);
  const button = (text: string) => [...dom.window.document.querySelectorAll<HTMLButtonElement>("button")].find(b => b.textContent?.includes(text))!;
  try {
    await act(async () => root.render(<App />));
    const title = dom.window.document.querySelector<HTMLInputElement>('input[aria-label="Заголовок слайда 1"]')!;
    assert.ok(title);
    await act(async () => {
      Object.getOwnPropertyDescriptor(dom.window.HTMLInputElement.prototype, "value")!.set!.call(title, "Выбор книг");
      title.dispatchEvent(new dom.window.Event("input", { bubbles: true }));
    });
    await act(async () => button("Собрать три варианта").click());
    assert.equal(calls[0].path, "/api/design/jobs/test-job/build");
    assert.equal(calls[0].body.story.slides[0].title, "Выбор книг");
    assert.doesNotMatch(dom.window.document.body.textContent!, /моделью|endpoint|Техническое ограничение/);
    assert.match(dom.window.document.body.textContent!, /Текст не помещается/);
    assert.match(dom.window.document.body.textContent!, /Проверьте смысл/);
    const check = dom.window.document.querySelector<HTMLInputElement>('.workflow-issue input[type="checkbox"]')!;
    assert.equal(dom.window.document.querySelectorAll('.workflow-issue input').length, 1);
    await act(async () => check.click());
    assert.equal(button("Исправить выбранное").disabled, false);
    await act(async () => button("Исправить выбранное").click());
    assert.deepEqual(calls[1], { path: "/api/design/jobs/test-job/variants/story/fix", body: { revision: 1, issue_ids: ["fit"] } });
    assert.match(dom.window.document.body.textContent!, /версия 2/);
    assert.equal(button("Исправить выбранное"), undefined);
    assert.match(dom.window.document.body.textContent!, /Замечаний нет/);
  } finally {
    await act(async () => root.unmount()); api.get = oldGet; api.post = oldPost; dom.window.close();
    for (const [key, descriptor] of original) {
      if (descriptor) Object.defineProperty(globalThis, key, descriptor); else Reflect.deleteProperty(globalThis, key);
    }
  }
});
