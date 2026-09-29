import assert from "node:assert/strict";
import test from "node:test";
import { JSDOM } from "jsdom";
import { act } from "react";
import App from "../src/App";
import { api } from "../src/api";
import { chartData, DatasetInput } from "../src/DatasetInput";
import { parseDataset } from "../src/model";
import type { DesignRequest } from "../src/types";

test("Excel paste preserves category codes and numeric rows", () => {
  const data = chartData("Код\tВыручка\tРасходы\r\n001\t12,5\t-2\r\n002\t0\t8", "Данные", "data-1");
  assert.deepEqual(data.rows, [["001", 12.5, -2], ["002", 0, 8]]);
  assert.deepEqual(parseDataset('"Период; год",Выручка\n2025,12.5', "test.csv", "t").columns, ["Период; год", "Выручка"]);
});

test("ambiguous, missing and unsafe chart values are rejected", () => {
  for (const value of ["", "NaN", "Infinity", "12%", "1 234", "=2+2", "9007199254740992"])
    assert.throws(() => chartData(`Код;Значение\n001;${value}`, "data", "d"), /нужно число/);
  assert.throws(() => chartData("Код;Значение\n;12", "data", "d"), /первом столбце/);
  for (const text of ['a,b\nfoo"bar,12', 'a,b\n"foo"bar,12'])
    assert.throws(() => parseDataset(text, "data", "d"), /кавычк/i);
});

test("Uploaded CSV remains in the submitted job while returning clears the form", async () => {
  const dom = new JSDOM('<div id="root"></div>', { url: "http://localhost" });
  const originals = new Map<string, PropertyDescriptor | undefined>();
  for (const [key, value] of Object.entries({ window: dom.window, document: dom.window.document,
    navigator: dom.window.navigator, FileReader: dom.window.FileReader, sessionStorage: dom.window.sessionStorage,
    IS_REACT_ACT_ENVIRONMENT: true })) {
    originals.set(key, Object.getOwnPropertyDescriptor(globalThis, key));
    Object.defineProperty(globalThis, key, { configurable: true, writable: true, value });
  }
  const oldGet = api.get, oldPost = api.post, oldUpload = api.uploadTemplate;
  api.get = (async (path: string) => path === "/api/session" ? { token: "test" } : { story: true }) as typeof api.get;
  const template = { id: "template", name: "template.pptx" };
  api.uploadTemplate = (async () => template) as typeof api.uploadTemplate;
  let sent: DesignRequest | undefined;
  api.post = (async (_path: string, body: { request: DesignRequest }) => {
    sent = body.request;
    return { id: "job", status: "failed", request: sent, template };
  }) as typeof api.post;
  const { createRoot } = await import("react-dom/client");
  const root = createRoot(document.getElementById("root")!);
  const button = (text: string) => [...document.querySelectorAll("button")].find(b => (b.textContent === text || b.getAttribute("aria-label") === text))!;
  const file = async (label: string, value: unknown) => act(async () => {
    const input = document.querySelector<HTMLInputElement>(`input[aria-label="${label}"]`)!;
    Object.defineProperty(input, "files", { configurable: true, value: Array.isArray(value) ? value : [value] });
    input.dispatchEvent(new dom.window.Event("change", { bubbles: true }));
    await new Promise(resolve => setTimeout(resolve, 20));
  });
  const csv = (text: string, name = "sales.csv") => ({ name, size: text.length,
    arrayBuffer: async () => new TextEncoder().encode(text).buffer });
  try {
    await act(async () => root.render(<App />));
    await file("Файл шаблона", new dom.window.File(["pptx"], "template.pptx"));
    await file("Файл с текстом", csv("Итоги продаж", "script.txt"));
    await file("Файл с данными", csv("Период;Выручка\n001;12,5\n002;18"));
    assert.match(document.body.textContent!, /sales.csv/);
    assert.doesNotMatch(document.body.textContent!, /Ячейки из Excel|Первый столбец|Задача презентации|Аудитория/);
    assert.equal(document.querySelectorAll(".dataset-input textarea, .dataset-input table").length, 0);
    assert.equal(document.querySelector<HTMLButtonElement>('button[type="submit"]')!.disabled, false);
    assert.doesNotMatch(document.body.textContent!, /Название таблицы|Источник данных|Единицы измерения/);
    await act(async () => document.querySelector("form")!.dispatchEvent(new dom.window.Event("submit", { bubbles: true, cancelable: true })));
    assert.deepEqual(sent!.datasets, [{ id: "data-1", name: "sales", source: "sales.csv", unit: "", columns: ["Период", "Выручка"], rows: [["001", 12.5], ["002", 18]] }]);
    const firstRequest = sent!;
    await act(async () => button("Вернуться к загрузке").click());
    assert.equal(button("Удалить sales"), undefined);
    assert.equal(document.querySelector<HTMLTextAreaElement>("#script")!.value, "");
    assert.equal(document.querySelector(".file-name")!.textContent, "Выберите или перетащите файл");
    assert.equal(document.querySelector<HTMLButtonElement>('button[type="submit"]')!.disabled, true);
    assert.equal(firstRequest.datasets.length, 1);
    await file("Файл шаблона", new dom.window.File(["pptx"], "second.pptx"));
    await file("Файл с текстом", csv("Следующие итоги продаж", "script.txt"));
    await file("Файл с данными", csv("Период;Выручка\n001;12,5\n002;18"));
    await file("Файл с данными", csv("Период;Выручка\n001;"));
    assert.match(document.querySelector('[role="alert"]')!.textContent!, /нужно число/);
    assert.ok(button("Удалить sales"));
    await file("Файл с данными", [csv("Код;Число\n" + "001;1\n".repeat(1001), "large.csv"), csv("Код;Число\n002;2", "second.csv")]);
    assert.match(document.body.textContent!, /large.csv/);
    assert.ok(button("Удалить large"));
    assert.ok(button("Удалить second"));
    assert.ok(document.querySelectorAll("tbody tr").length < 100);
    await act(async () => document.querySelector("form")!.dispatchEvent(new dom.window.Event("submit", { bubbles: true, cancelable: true })));
    assert.equal(sent!.datasets.length, 3);
    assert.equal(sent!.datasets[1].rows.length, 1001);
    assert.deepEqual(sent!.datasets.map(d => d.id), ["data-1", "data-2", "data-3"]);
    assert.equal(firstRequest.datasets.length, 1, "a new request must not mutate an earlier job's data");
    await act(async () => button("Вернуться к загрузке").click());
    assert.equal(button("Удалить sales"), undefined);
    await file("Файл с данными", csv("Период;Выручка\n001;12,5\n002;18"));
    await act(async () => button("Удалить sales").click());
    assert.equal(button("Удалить sales"), undefined);
  } finally {
    await act(async () => root.unmount());
    api.get = oldGet; api.post = oldPost; api.uploadTemplate = oldUpload;
    dom.window.close();
    for (const [key, descriptor] of originals) {
      if (descriptor) Object.defineProperty(globalThis, key, descriptor);
      else Reflect.deleteProperty(globalThis, key);
    }
  }
});


for (const outcome of ["success", "failure"] as const) {
  test(`leaving a pending table import unlocks actions and ignores its late ${outcome}`, async () => {
    const dom = new JSDOM('<div id="root"></div>', { url: "http://localhost" });
    const originals = new Map<string, PropertyDescriptor | undefined>();
    for (const [key, value] of Object.entries({ window: dom.window, document: dom.window.document,
      navigator: dom.window.navigator, IS_REACT_ACT_ENVIRONMENT: true })) {
      originals.set(key, Object.getOwnPropertyDescriptor(globalThis, key));
      Object.defineProperty(globalThis, key, { configurable: true, writable: true, value });
    }
    const { createRoot } = await import("react-dom/client");
    const root = createRoot(document.getElementById("root")!);
    let resolveRead!: (data: ArrayBuffer) => void;
    let rejectRead!: (error: Error) => void;
    const reading = new Promise<ArrayBuffer>((resolve, reject) => {
      resolveRead = resolve; rejectRead = reject;
    });
    let pending = false;
    let changed = false;
    const onPending = (value: boolean) => { pending = value; };
    try {
      await act(async () => root.render(<DatasetInput datasets={[]} disabled={false}
        onPending={onPending} onChange={() => { changed = true; }} />));
      await act(async () => {
        const input = document.querySelector<HTMLInputElement>('input[type="file"]')!;
        Object.defineProperty(input, "files", { configurable: true, value: [
          { name: "old.csv", size: 30, arrayBuffer: () => reading },
        ] });
        input.dispatchEvent(new dom.window.Event("change", { bubbles: true }));
      });
      assert.equal(pending, true);
      // Navigation unmounts DatasetInput while result actions still use the parent's pending flag.
      await act(async () => root.render(<p>Результат другой презентации</p>));
      assert.equal(pending, false);
      await act(async () => {
        if (outcome === "success") resolveRead(new TextEncoder().encode("Период;Выручка\n001;12").buffer);
        else rejectRead(new Error("Отложенная ошибка"));
      });
      assert.equal(changed, false, "a stale import must not replace another page's materials");
      assert.equal(pending, false);
      assert.doesNotMatch(document.body.textContent!, /Отложенная ошибка/);
    } finally {
      await act(async () => root.unmount());
      dom.window.close();
      for (const [key, descriptor] of originals) {
        if (descriptor) Object.defineProperty(globalThis, key, descriptor);
        else Reflect.deleteProperty(globalThis, key);
      }
    }
  });
}
