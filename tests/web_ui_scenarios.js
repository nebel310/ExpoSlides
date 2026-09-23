"use strict";

// This intentionally small DOM runs the production event handlers and async API
// work. Every fetch is routed in memory; no browser, server or npm package is used.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const root = path.resolve(__dirname, "..");
const appSource = fs.readFileSync(path.join(root, "exposlides/web_static/app.js"), "utf8");
const htmlSource = fs.readFileSync(path.join(root, "exposlides/web_static/index.html"), "utf8");

function deferred() {
  let resolve;
  const promise = new Promise((done) => { resolve = done; });
  return { promise, resolve };
}

function response(data, status = 200) {
  return { ok: status >= 200 && status < 300, status, json: async () => data };
}

function presentation(id, count, { status = "ready", prefix = id } = {}) {
  return {
    id, name: `${id}.pptx`, slide_count: count, width: 1600, height: 900,
    slides: Array.from({ length: count }, (_, index) => ({
      index: index + 1, title: `${prefix} title ${index + 1}`,
      texts: [`${prefix} title ${index + 1}`, `${prefix} body ${index + 1}`],
      placeholder_count: 2,
    })),
    preview: {
      status,
      slides: status === "ready"
        ? Array.from({ length: count }, (_, index) => `/images/${prefix}-${index + 1}.png`)
        : [],
    },
  };
}

function completedJob(id = "done", count = 2) {
  return { id, status: "completed", stage: "builder", slide_count: count };
}

function harness({ routes = {}, savedJob = null, readFile = async () => "data:application/octet-stream;base64,UEs=" } = {}) {
  const elements = new Map();
  const timers = new Map();
  const storage = new Map(savedJob ? [["exposlides-job", savedJob]] : []);
  const calls = [];
  const fileReads = [];
  let timerId = 0;
  let document;

  class Element {
    constructor(tag = "div", id = "") {
      this.tagName = tag.toUpperCase();
      this.id = id;
      this.hidden = false;
      this.disabled = false;
      this.readOnly = false;
      this.value = "";
      this.children = [];
      this.parentElement = null;
      this.dataset = {};
      this.attributes = new Map();
      this.events = new Map();
      this._text = "";
      const classes = new Set();
      this.classList = {
        add: (...names) => names.forEach((name) => classes.add(name)),
        remove: (...names) => names.forEach((name) => classes.delete(name)),
        contains: (name) => classes.has(name),
        toggle: (name, force) => {
          const present = force === undefined ? !classes.has(name) : force;
          if (present) classes.add(name); else classes.delete(name);
          return present;
        },
      };
      this.style = { removeProperty(name) { delete this[name]; } };
      this.clientWidth = 1000;
      this.clientHeight = 720;
    }
    set textContent(value) { this._text = String(value); this.children = []; }
    get textContent() { return this._text + this.children.map((child) => child.textContent).join(""); }
    set src(value) { this.setAttribute("src", value); }
    get src() { return this.getAttribute("src") || ""; }
    set href(value) { this.setAttribute("href", value); }
    get href() { return this.getAttribute("href") || ""; }
    setAttribute(name, value) { this.attributes.set(name, String(value)); }
    getAttribute(name) { return this.attributes.get(name) ?? null; }
    removeAttribute(name) { this.attributes.delete(name); }
    append(...children) {
      for (const child of children) { child.parentElement = this; this.children.push(child); }
    }
    replaceChildren(...children) {
      this.children.forEach((child) => { child.parentElement = null; });
      this.children = [];
      this._text = "";
      this.append(...children);
    }
    add(child) { this.append(child); }
    contains(child) { return child === this || this.children.some((item) => item.contains(child)); }
    addEventListener(type, callback) {
      if (!this.events.has(type)) this.events.set(type, []);
      this.events.get(type).push(callback);
    }
    async dispatch(type, properties = {}) {
      const event = { target: this, preventDefault() {}, ...properties };
      await Promise.all((this.events.get(type) || []).map((callback) => callback(event)));
    }
    click() { return this.dispatch("click"); }
    focus() { document.activeElement = this; }
    scrollIntoView() {}
    showModal() { this.open = true; }
    close() { this.open = false; }
    getBoundingClientRect() { return { left: 0, right: 1000, top: 0, bottom: 720 }; }
  }

  for (const [, id] of htmlSource.matchAll(/\bid="([^"]+)"/g)) {
    elements.set(id, new Element("div", id));
  }
  const stage = new Element();
  const jobStages = [new Element("li"), new Element("li"), new Element("li")];
  document = {
    activeElement: null,
    getElementById(id) { assert.ok(elements.has(id), `Unknown DOM element ${id}`); return elements.get(id); },
    createElement(tag) { return new Element(tag); },
    querySelector(selector) {
      assert.equal(selector, ".canvas-stage");
      return stage;
    },
    querySelectorAll(selector) {
      assert.equal(selector, ".job-stages li");
      return jobStages;
    },
    addEventListener() {},
  };
  const context = vm.createContext({
    document,
    window: { matchMedia: () => ({ matches: false }) },
    getComputedStyle: () => ({ paddingLeft: "0", paddingRight: "0", paddingTop: "0", paddingBottom: "0" }),
    requestAnimationFrame: (callback) => callback(),
    ResizeObserver: class { observe() {} },
    Option: class extends Element {
      constructor(text, value) { super("option"); this.textContent = text; this.value = value; }
    },
    sessionStorage: {
      getItem: (key) => storage.get(key) ?? null,
      setItem: (key, value) => storage.set(key, String(value)),
      removeItem: (key) => storage.delete(key),
    },
    AbortController,
    TextDecoder,
    FileReader: class {
      readAsDataURL(file) {
        fileReads.push(file);
        Promise.resolve().then(() => readFile(file)).then((result) => {
          this.result = result;
          this.onload();
        }, (error) => {
          this.error = error;
          this.onerror();
        });
      }
    },
    console,
    confirm: () => true,
    setTimeout(callback, delay) { const id = ++timerId; timers.set(id, { callback, delay }); return id; },
    clearTimeout(id) { timers.delete(id); },
    async fetch(url, options) {
      calls.push({ url, options });
      if (url === "/api/session" && !Object.hasOwn(routes, url)) return response({ token: "offline-token" });
      if (url === "/api/library" && !Object.hasOwn(routes, url)) return response({ persistent: false, templates: [], jobs: [] });
      assert.ok(Object.hasOwn(routes, url), `Unexpected API request ${url}`);
      const route = routes[url];
      return typeof route === "function" ? route(options) : response(route);
    },
  });
  vm.runInContext(appSource, context, { filename: "app.js" });
  return {
    calls,
    fileReads,
    element: (id) => document.getElementById(id),
    evaluate: (code) => vm.runInContext(code, context),
    async call(name, ...args) {
      context.testArguments = args;
      return vm.runInContext(`${name}(...testArguments)`, context);
    },
    async flush() { for (let i = 0; i < 3; i++) await new Promise(setImmediate); },
    async tick(delay) {
      const due = Array.from(timers).filter(([, timer]) => timer.delay === delay);
      assert.ok(due.length > 0, `Expected a ${delay} ms polling timer`);
      for (const [id, timer] of due) { timers.delete(id); timer.callback(); }
      await this.flush();
    },
  };
}

async function withTemplate(routes = {}) {
  const app = harness({ routes });
  await app.flush();
  await app.call("setWorkspaceView", "materials");
  await app.call("applyTemplate", presentation("template", 4));
  return app;
}

function assertResult(app, result, slide = 0) {
  assert.equal(app.element("workspace").dataset.view, "preview");
  assert.equal(app.element("preview-counter").textContent, `${result.slide_count} слайда`);
  assert.equal(app.element("slide-title").textContent, result.slides[slide].title);
  assert.equal(app.element("rendered-slide").src, result.preview.slides[slide]);
  assert.equal(app.element("rendered-slide").hidden, false);
  assert.equal(app.element("thumbnails").children.length, result.slide_count);
  assert.equal(app.element("generation-view").hidden, true);
  assert.equal(app.element("download-button").hidden, false);
  assert.equal(app.element("result-download").hidden, false);
  assert.equal(app.element("result-download").href, `/api/jobs/${result.id}/download`);
  assert.equal(app.element("slide-preview").style.aspectRatio, `${result.width} / ${result.height}`);
  assert.match(app.element("preview-heading").textContent, /готов|результат/i);
}

const scenarios = {
  async parallel_generations() {
    const late = deferred();
    const first = { id: "first", status: "running", stage: "content" };
    const second = { id: "second", status: "running", stage: "parser" };
    const app = await withTemplate({
      "/api/jobs/first": () => late.promise,
      "/api/jobs/second": second,
      "/api/jobs": second,
    });
    app.element("script").value = "Первый текст";
    await app.call("renderJob", first);
    const polling = app.call("pollJob", "first");
    await app.element("new-presentation").click();
    assert.equal(app.element("generate-button").disabled, false);
    app.element("script").value = "Второй текст";
    await app.element("presentation-form").dispatch("submit");
    await app.flush();
    assert.equal(app.evaluate("state.job.id"), "second");
    late.resolve(response(completedJob("first")));
    await polling;
    await app.flush();
    assert.equal(app.evaluate("state.job.id"), "second");
    assert.equal(app.evaluate("state.busy"), true);
    assert.equal(app.element("parallel-jobs").children.length, 2);
    assert.match(app.element("parallel-jobs").textContent, /Готово/);
    const submitted = app.calls.find(call => call.url === "/api/jobs");
    assert.equal(JSON.parse(submitted.options.body).script, "Второй текст");
    assert.equal(JSON.parse(app.evaluate('sessionStorage.getItem("exposlides-jobs")')).length, 2);
  },
  async temporary_library_hidden() {
    const app = harness();
    await app.flush();
    assert.equal(app.element("library-panel").hidden, true);
    assert.match(app.element("help-storage").textContent, /до остановки/);
  },

  async saved_template_selection() {
    const template = presentation("saved template", 3);
    template.name = "<img src=x onerror=alert(1)>.pptx";
    const app = harness({ routes: {
      "/api/library": { persistent: true, templates: [template], jobs: [] },
      "/api/templates/saved%20template/preview": template.preview,
    } });
    await app.flush();
    app.element("script").value = "Мой исходный текст";
    const button = app.element("library-templates").children[0].children[0];
    assert.equal(app.element("library-panel").hidden, false);
    assert.match(app.element("help-storage").textContent, /после перезапуска/);
    assert.equal(button.children[0].textContent, template.name);
    assert.equal(button.children[0].children.length, 0);
    await button.click();
    assert.equal(app.evaluate("state.template.id"), template.id);
    assert.equal(app.element("template-name").textContent, template.name);
    assert.equal(app.element("script").value, "Мой исходный текст");
    assert.equal(app.element("generate-button").disabled, false);
    assert.equal(app.element("max-slides").children.length, 4);
    assert.equal(button.getAttribute("aria-pressed"), "true");
    assert.equal(app.element("library-results-empty").hidden, false);
  },

  async saved_result_selection_race() {
    const old = deferred();
    const result = presentation("latest", 2);
    const jobs = [completedJob("older"), completedJob("latest")];
    const app = harness({ routes: {
      "/api/library": { persistent: true, templates: [], jobs },
      "/api/jobs/older/presentation": () => old.promise,
      "/api/jobs/latest/presentation": result,
    } });
    await app.flush();
    const row = app.element("library-results").children[0];
    assert.equal(row.children[1].href, "/api/jobs/older/download");
    assert.equal(row.children[1].getAttribute("download"), "presentation.pptx");
    await row.children[0].click();
    assert.equal(app.element("preview-loading").hidden, false);
    await app.element("library-results").children[1].children[0].click();
    await app.flush();
    old.resolve(response(presentation("older", 2)));
    await app.flush();
    assertResult(app, result);
    assert.equal(app.evaluate('sessionStorage.getItem("exposlides-job")'), "latest");
    assert.equal(app.element("library-results").children[1].children[0].getAttribute("aria-pressed"), "true");
  },

  async saved_selection_locked_during_generation() {
    const app = await withTemplate({
      "/api/library": { persistent: true, templates: [presentation("saved", 2)], jobs: [completedJob("done")] },
    });
    await app.call("renderJob", { id: "running", status: "running", stage: "content" });
    for (const id of ["library-templates", "library-results"]) {
      const button = app.element(id).children[0].children[0];
      assert.equal(button.disabled, true);
      await button.click();
    }
    assert.equal(app.evaluate("state.job.id"), "running");
    assert.equal(app.evaluate("state.template.id"), "template");
    assert.equal(app.element("library-results").children[0].children[1].href, "/api/jobs/done/download");
  },

  async library_refreshes_after_saved_files() {
    const templates = [];
    const jobs = [];
    const uploaded = presentation("uploaded", 2);
    const example = { ...presentation("example", 2), script: "Пример текста" };
    const result = presentation("done", 2);
    const app = harness({ routes: {
      "/api/library": () => response({ persistent: true, templates: [...templates], jobs: [...jobs] }),
      "/api/templates": () => { templates.push(uploaded); return response(uploaded); },
      "/api/example": () => { templates.push(example); return response(example); },
      "/api/jobs/done/presentation": result,
    } });
    await app.flush();
    assert.equal(app.element("library-templates-empty").hidden, false);
    await app.call("uploadTemplate", { name: "uploaded.pptx", size: 2 });
    await app.flush();
    assert.equal(app.element("library-templates").children.length, 1);
    await app.call("loadExample");
    await app.flush();
    assert.equal(app.element("library-templates").children.length, 2);
    jobs.push(completedJob());
    await app.call("renderJob", completedJob());
    await app.flush();
    assert.equal(app.element("library-results").children.length, 1);
    assert.equal(app.calls.filter(({ url }) => url === "/api/library").length, 4);
    assertResult(app, result);
  },

  async library_failure_preserves_materials() {
    let available = true;
    const app = await withTemplate({
      "/api/library": () => available
        ? response({ persistent: true, templates: [presentation("saved", 2)], jobs: [] })
        : response({ error: "Хранилище недоступно" }, 503),
    });
    available = false;
    await app.call("showError", "Другая ошибка");
    await app.call("renderJob", { id: "running", status: "running", stage: "content" });
    await app.element("library-refresh").click();
    assert.equal(app.element("library-panel").hidden, false);
    assert.equal(app.element("library-status").hidden, false);
    assert.match(app.element("library-status").textContent, /Попробуйте ещё раз/);
    assert.equal(app.element("library-templates").children.length, 1);
    assert.equal(app.element("library-refresh").disabled, false);
    assert.equal(app.evaluate("state.template.id"), "template");
    assert.equal(app.evaluate("state.job.id"), "running");
    assert.equal(app.evaluate("state.busy"), true);
    assert.equal(app.element("error-message").textContent, "Другая ошибка");
  },

  async stale_library_response() {
    const old = deferred();
    let calls = 0;
    const app = harness({ routes: {
      "/api/library": () => ++calls === 1 ? old.promise
        : response({ persistent: true, templates: [presentation("latest", 2)], jobs: [] }),
    } });
    await app.flush();
    assert.equal(app.element("library-refresh").disabled, true);
    await app.call("refreshLibrary");
    old.resolve(response({ persistent: false, templates: [], jobs: [] }));
    await app.flush();
    assert.equal(app.element("library-panel").hidden, false);
    assert.equal(app.element("library-refresh").disabled, false);
    assert.equal(app.element("library-templates").children.length, 1);
    assert.match(app.element("library-templates").textContent, /latest/);
  },

  async saved_selection_wins_over_restored_job() {
    const old = deferred();
    const app = harness({ savedJob: "old", routes: {
      "/api/library": { persistent: true, templates: [presentation("saved", 2)], jobs: [] },
      "/api/templates/saved/preview": presentation("saved", 2).preview,
      "/api/jobs/old": () => old.promise,
    } });
    await app.flush();
    await app.element("library-templates").children[0].children[0].click();
    old.resolve(response(completedJob("old")));
    await app.flush();
    assert.equal(app.evaluate("state.template.id"), "saved");
    assert.equal(app.evaluate("state.job"), null);
    assert.equal(app.element("slide-title").textContent, "saved title 1");
    assert.ok(app.calls.every(({ url }) => !url.endsWith("/presentation")));
  },

  async saved_template_restores_preview_without_stale_selection() {
    const old = deferred();
    const templates = [presentation("first", 2, { status: "unavailable" }), presentation("second", 2, { status: "unavailable" })];
    const app = harness({ routes: {
      "/api/library": { persistent: true, templates, jobs: [] },
      "/api/templates/first/preview": () => old.promise,
      "/api/templates/second/preview": { status: "ready", slides: ["/restored/1.png", "/restored/2.png"] },
    } });
    await app.flush();
    await app.element("library-templates").children[0].children[0].click();
    await app.element("library-templates").children[1].children[0].click();
    await app.flush();
    assert.equal(app.element("rendered-slide").src, "/restored/1.png");
    old.resolve(response({ status: "ready", slides: ["/stale/1.png", "/stale/2.png"] }));
    await app.flush();
    assert.equal(app.evaluate("state.template.id"), "second");
    assert.equal(app.element("rendered-slide").src, "/restored/1.png");
    assert.equal(app.calls.filter(({ url }) => url.endsWith("/preview")).length, 2);
  },

  async completed_result() {
    const result = presentation("done", 2, { prefix: "generated" });
    result.width = 1200;
    const app = await withTemplate({ "/api/jobs/done/presentation": result });
    for (let index = 0; index < 3; index++) await app.element("next-slide").click();
    assert.equal(app.evaluate("state.slide"), 3);
    await app.call("renderJob", completedJob());
    await app.flush();
    assertResult(app, result);
    assert.equal(app.element("download-button").href, "/api/jobs/done/download");
    assert.equal(app.element("template-name").textContent, "template.pptx");
    assert.equal(app.element("slide-texts").textContent, "generated body 1");
    assert.equal(app.element("slide-preview").style.width, "960px");
    assert.ok(app.calls.every(({ url }) => !url.includes("/templates/")));
  },

  async pending_result() {
    const metadata = deferred();
    const images = deferred();
    const result = presentation("done", 2, { prefix: "generated", status: "pending" });
    const app = await withTemplate({
      "/api/jobs/done/presentation": () => metadata.promise,
      "/api/jobs/done/preview": () => images.promise,
    });
    await app.call("renderJob", completedJob());
    await app.flush();
    assert.equal(app.element("workspace").dataset.view, "preview");
    assert.equal(app.element("rendered-slide").hidden, true);
    assert.equal(app.element("rendered-slide").src, "");
    assert.equal(app.element("slide-content").hidden, true);
    assert.equal(app.element("download-button").hidden, false);
    assert.ok(app.element("thumbnails").hidden || app.element("thumbnails").children.length === 0);
    metadata.resolve(response(result));
    await app.flush();
    assert.equal(app.element("preview-loading").hidden, false);
    assert.equal(app.element("slide-content").hidden, true);
    images.resolve(response({ status: "ready", slides: ["/final/1.png", "/final/2.png"] }));
    await app.flush();
    assertResult(app, { ...result, preview: { status: "ready", slides: ["/final/1.png", "/final/2.png"] } });
  },

  async result_preview_polling() {
    const result = presentation("done", 2, { prefix: "generated", status: "pending" });
    let polls = 0;
    const ready = { status: "ready", slides: ["/polled/1.png", "/polled/2.png"] };
    const app = await withTemplate({
      "/api/jobs/done/presentation": result,
      "/api/jobs/done/preview": () => response(++polls === 1 ? { status: "pending" } : ready),
    });
    await app.call("renderJob", completedJob());
    await app.flush();
    assert.equal(app.element("preview-loading").hidden, false);
    assert.equal(app.element("download-button").hidden, false);
    await app.tick(1200);
    assert.equal(polls, 2);
    assertResult(app, { ...result, preview: ready });
  },

  async result_navigation() {
    const result = presentation("done", 2, { prefix: "generated" });
    const app = await withTemplate({ "/api/jobs/done/presentation": result });
    await app.call("renderJob", completedJob());
    await app.flush();
    await app.element("next-slide").click();
    assertResult(app, result, 1);
    assert.equal(app.element("slide-position").textContent, "2 из 2");
    assert.equal(app.element("next-slide").disabled, true);
    await app.element("next-slide").click();
    assert.equal(app.evaluate("state.slide"), 1);
    await app.element("thumbnails").children[0].click();
    assertResult(app, result, 0);
    assert.equal(app.element("previous-slide").disabled, true);
  },

  async template_upload_stays_on_materials() {
    const app = await withTemplate();
    assert.equal(app.element("workspace").dataset.view, "materials");
    assert.equal(app.element("rendered-slide").src, "/images/template-1.png");
    await app.call("applyTemplate", presentation("replacement", 3));
    assert.equal(app.element("workspace").dataset.view, "materials");
    assert.equal(app.element("rendered-slide").src, "/images/replacement-1.png");
  },

  async template_upload_refreshes_session_after_reading_file() {
    let token = "before-restart";
    const fileRead = deferred();
    const file = { name: "Шаблон.pptx", size: 2 };
    const app = harness({
      routes: {
        "/api/session": () => response({ token }),
        "/api/templates": presentation("uploaded", 2),
      },
      readFile: () => fileRead.promise,
    });
    await app.flush();
    assert.equal(app.evaluate("state.token"), "before-restart");

    const upload = app.call("uploadTemplate", file);
    await app.flush();
    assert.equal(app.evaluate("state.uploading"), true);
    assert.equal(app.element("template-input").disabled, true);
    assert.deepEqual(app.calls.filter(({ url }) => url !== "/api/library").map(({ url }) => url), ["/api/session"]);
    assert.deepEqual(app.fileReads, [file]);

    token = "after-restart";
    fileRead.resolve("data:application/octet-stream;base64,UEs=");
    await upload;
    assert.deepEqual(app.calls.filter(({ url }) => url !== "/api/library").map(({ url }) => url), ["/api/session", "/api/session", "/api/templates"]);
    const posted = app.calls.find(({ url }) => url === "/api/templates").options;
    assert.equal(posted.headers["X-ExpoSlides-Token"], "after-restart");
    assert.deepEqual(JSON.parse(posted.body), { name: file.name, data: "UEs=" });
    assert.equal(app.evaluate("state.template.id"), "uploaded");
    assert.equal(app.evaluate("state.uploading"), false);
    assert.equal(app.element("template-input").disabled, false);
    assert.equal(app.element("error-message").hidden, true);
  },

  async template_upload_forbidden_clears_session() {
    const app = harness({ routes: {
      "/api/templates": () => response({ error: "Сессия устарела. Обновите страницу." }, 403),
    } });
    await app.flush();
    await app.call("uploadTemplate", { name: "Шаблон.pptx", size: 2 });

    assert.equal(app.evaluate("state.token"), null);
    assert.equal(app.evaluate("state.template"), null);
    assert.equal(app.calls.filter(({ url }) => url === "/api/templates").length, 1);
    assert.equal(app.element("error-message").textContent, "Сессия устарела. Обновите страницу.");
    assert.equal(app.element("error-message").hidden, false);
    assert.equal(app.evaluate("state.uploading"), false);
    assert.equal(app.element("template-input").disabled, false);
  },

  async template_upload_stops_when_session_refresh_fails() {
    let available = true;
    const app = harness({ routes: {
      "/api/session": () => available
        ? response({ token: "before-restart" })
        : response({ error: "Сервер временно недоступен." }, 503),
    } });
    await app.flush();
    available = false;
    await app.call("uploadTemplate", { name: "Шаблон.pptx", size: 2 });

    assert.equal(app.fileReads.length, 1);
    assert.deepEqual(app.calls.filter(({ url }) => url !== "/api/library").map(({ url }) => url), ["/api/session", "/api/session"]);
    assert.equal(app.evaluate("state.template"), null);
    assert.equal(app.evaluate("state.uploading"), false);
    assert.equal(app.element("template-input").disabled, false);
    assert.equal(app.element("generation-view").hidden, true);
    assert.equal(app.element("upload-title").textContent, "Выберите файл");
    assert.equal(app.element("error-message").textContent, "Сервер временно недоступен.");
  },

  async template_upload_network_failure_is_not_retried() {
    const app = harness({ routes: {
      "/api/templates": () => { throw app.evaluate('new TypeError("Failed to fetch")'); },
    } });
    await app.flush();
    await app.call("uploadTemplate", { name: "Шаблон.pptx", size: 2 });

    assert.equal(app.calls.filter(({ url }) => url === "/api/templates").length, 1);
    assert.equal(app.evaluate("state.uploading"), false);
    assert.equal(app.element("template-input").disabled, false);
    assert.equal(app.element("error-message").textContent,
      "Не удалось связаться с сервером. Проверьте подключение к интернету и попробуйте ещё раз.");
  },

  async stale_result_metadata() {
    const old = deferred();
    const app = await withTemplate({ "/api/jobs/old/presentation": () => old.promise });
    await app.call("renderJob", completedJob("old"));
    await app.call("setWorkspaceView", "materials");
    await app.call("applyTemplate", presentation("replacement", 3));
    old.resolve(response(presentation("old", 2)));
    await app.flush();
    assert.equal(app.evaluate("state.job"), null);
    assert.equal(app.element("workspace").dataset.view, "materials");
    assert.equal(app.element("rendered-slide").src, "/images/replacement-1.png");
    assert.equal(app.element("slide-title").textContent, "replacement title 1");
    assert.equal(app.element("download-button").hidden, true);
  },

  async stale_result_preview() {
    const old = deferred();
    const result = presentation("current", 3);
    const app = await withTemplate({
      "/api/jobs/old/presentation": presentation("old", 2, { status: "pending" }),
      "/api/jobs/old/preview": () => old.promise,
      "/api/jobs/current/presentation": result,
    });
    await app.call("renderJob", completedJob("old"));
    await app.flush();
    await app.call("renderJob", { id: "current", status: "running", stage: "content" });
    await app.call("renderJob", completedJob("current", 3));
    await app.flush();
    old.resolve(response({ status: "ready", slides: ["/stale/1.png", "/stale/2.png"] }));
    await app.flush();
    assertResult(app, result);
    assert.equal(app.element("download-button").href, "/api/jobs/current/download");
  },

  async stale_template_preview() {
    const old = deferred();
    const result = presentation("done", 2, { prefix: "generated" });
    const app = await withTemplate({
      "/api/templates/pending-template/preview": () => old.promise,
      "/api/jobs/done/presentation": result,
    });
    await app.call("applyTemplate", presentation("pending-template", 4, { status: "pending" }));
    await app.call("renderJob", completedJob());
    await app.flush();
    old.resolve(response({ status: "ready", slides: ["/stale/template.png"] }));
    await app.flush();
    assertResult(app, result);
  },

  async restore_completed_job() {
    const result = presentation("restored", 2);
    const app = harness({ savedJob: "restored", routes: {
      "/api/jobs/restored": completedJob("restored"),
      "/api/jobs/restored/presentation": result,
    } });
    await app.flush();
    assert.equal(app.evaluate("state.template"), null);
    assertResult(app, result);
    assert.equal(app.element("download-button").href, "/api/jobs/restored/download");
    assert.equal(app.calls.filter(({ url }) => url.endsWith("/presentation")).length, 1);
  },

  async result_metadata_failure() {
    const app = await withTemplate({
      "/api/jobs/done/presentation": () => response({ error: "Предпросмотр временно недоступен" }, 500),
    });
    await app.call("renderJob", completedJob());
    await app.flush();
    assert.equal(app.element("workspace").dataset.view, "preview");
    assert.equal(app.element("download-button").hidden, false);
    assert.equal(app.element("download-button").href, "/api/jobs/done/download");
    assert.equal(app.element("rendered-slide").src, "");
    assert.equal(app.element("rendered-slide").hidden, true);
    assert.equal(app.element("slide-content").hidden, true);
    assert.ok(app.element("thumbnails").hidden || app.element("thumbnails").children.length === 0);
    assert.match(app.element("preview-heading").textContent, /готов|результат/i);
    await app.tick(2000);
    await app.tick(2000);
    await app.tick(2000);
    assert.equal(app.calls.filter(({ url }) => url.endsWith("/presentation")).length, 4);
    assert.equal(app.element("preview-loading").hidden, true);
    assert.equal(app.element("empty-preview").hidden, false);
    assert.match(app.element("empty-preview-description").textContent, /скачать/i);
    assert.equal(app.element("download-button").hidden, false);
    assert.equal(app.element("result-download").hidden, false);
    assert.equal(app.element("rendered-slide").src, "");
  },

  async result_preview_failure() {
    const result = presentation("done", 2, { prefix: "generated", status: "pending" });
    const app = await withTemplate({
      "/api/jobs/done/presentation": result,
      "/api/jobs/done/preview": { status: "failed", message: "Не удалось подготовить изображения" },
    });
    await app.call("renderJob", completedJob());
    await app.flush();
    assert.equal(app.element("rendered-slide").hidden, true);
    assert.equal(app.element("slide-content").hidden, false);
    assert.equal(app.element("slide-title").textContent, "generated title 1");
    assert.equal(app.element("slide-texts").textContent, "generated body 1");
    assert.equal(app.element("download-button").hidden, false);
    assert.equal(app.element("preview-counter").textContent, "2 слайда");
    assert.equal(app.element("preview-loading").hidden, true);
    assert.match(app.element("preview-caption").textContent, /Не удалось подготовить изображения/);
  },

  async result_image_failure() {
    const result = presentation("done", 2, { prefix: "generated" });
    const app = await withTemplate({ "/api/jobs/done/presentation": result });
    await app.call("renderJob", completedJob());
    await app.flush();
    await app.element("rendered-slide").dispatch("error");
    assert.equal(app.element("rendered-slide").hidden, true);
    assert.equal(app.element("rendered-slide").src, "");
    assert.equal(app.element("slide-content").hidden, false);
    assert.equal(app.element("slide-title").textContent, "generated title 1");
    assert.equal(app.element("slide-texts").textContent, "generated body 1");
    assert.equal(app.element("download-button").hidden, false);
    assert.equal(app.element("preview-counter").textContent, "2 слайда");
  },
};

const scenario = process.argv[2];
assert.ok(Object.hasOwn(scenarios, scenario), `Unknown scenario ${scenario}`);
scenarios[scenario]().then(() => {
  process.stdout.write(`${scenario}: passed\n`);
}).catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
