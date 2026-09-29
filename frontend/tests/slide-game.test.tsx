import assert from "node:assert/strict";
import test from "node:test";
import { JSDOM } from "jsdom";
import { act } from "react";
import App from "../src/App";
import { api } from "../src/api";
import { SAVED_JOB_KEY } from "../src/jobs";
import type { Job } from "../src/types";

for (const status of ["completed", "failed", "cancelled", "cancelling"]) {
  test(`game can be interrupted by ${status} without finishing a palette`, async () => {
    const dom = new JSDOM('<div id="root"></div>', { url: "http://localhost" });
    const original = new Map<string, PropertyDescriptor | undefined>();
    for (const [key, value] of Object.entries({ window: dom.window, document: dom.window.document,
      navigator: dom.window.navigator, sessionStorage: dom.window.sessionStorage,
      IS_REACT_ACT_ENVIRONMENT: true })) {
      original.set(key, Object.getOwnPropertyDescriptor(globalThis, key));
      Object.defineProperty(globalThis, key, { configurable: true, writable: true, value });
    }
    const oldGet = api.get;
    let job: Job = { id: "playing", status: "running" };
    dom.window.sessionStorage.setItem(SAVED_JOB_KEY, job.id);
    api.get = (async (path: string) => path === "/api/session" ? { token: "test" }
      : path === "/api/capabilities" ? { story: true } : job) as typeof api.get;
    const { createRoot } = await import("react-dom/client");
    const root = createRoot(dom.window.document.getElementById("root")!);
    const document = dom.window.document;
    const click = async (selector: string) => {
      const button = document.querySelector<HTMLButtonElement>(selector);
      assert.ok(button, selector);
      await act(async () => { button.click(); });
    };
    try {
      await act(async () => { root.render(<App />); });
      assert.ok(document.querySelector(".slide-game"));
      const shades = () => [...document.querySelectorAll<HTMLButtonElement>(".palette-shade")];
      const brightness = () => shades().map(button => Number(button.getAttribute("aria-label")!.match(/светлота (\d+)%/)![1]));
      const target = [88, 76, 64, 52, 40, 28];
      const initial = brightness();
      assert.deepEqual([...initial].sort((a, b) => b - a), target);
      assert.notDeepEqual(initial, target);
      await click(".palette-shade:nth-child(1)");
      assert.equal(shades()[0].getAttribute("aria-pressed"), "true");
      await click(".palette-shade:nth-child(1)");
      assert.equal(shades()[0].getAttribute("aria-pressed"), "false");
      assert.deepEqual(brightness(), initial);
      await click(".palette-shade:nth-child(1)");
      await click(".palette-shade:nth-child(2)");
      assert.deepEqual(brightness(), [initial[1], initial[0], ...initial.slice(2)]);
      await click(".slide-game-heading button");
      assert.equal(document.querySelector(".palette-board"), null);
      await click(".slide-game-heading button");
      assert.deepEqual(brightness(), [initial[1], initial[0], ...initial.slice(2)]);
      for (let position = 0; position < target.length; position++) {
        const other = brightness().indexOf(target[position]);
        if (other === position) continue;
        await click(`.palette-shade:nth-child(${position + 1})`);
        await click(`.palette-shade:nth-child(${other + 1})`);
      }
      assert.deepEqual(brightness(), target);
      assert.match(document.querySelector(".slide-game-footer")!.textContent!, /красивый переход/);
      await click(".palette-shade:nth-child(1)");
      assert.equal(document.querySelector('[aria-pressed="true"]'), null);
      assert.equal(document.querySelector(".slide-game-footer button"), null);
      assert.ok(document.querySelector(".palette-board.is-complete"));
      await act(async () => { await new Promise(resolve => setTimeout(resolve, 750)); });
      assert.equal(document.querySelector(".palette-board.is-complete"), null);
      assert.notDeepEqual(brightness(), target);
      assert.match(document.querySelector(".palette-caption")!.textContent!, /Шалфей/);
      assert.equal(document.querySelector('[aria-pressed="true"]'), null);
      await click(".palette-shade:nth-child(1)");
      job = { ...job, status, ...(status === "completed" ? { variants: [{ id: "result", name: "Готово",
        description: "", revision: 1, issues: [], preview_urls: [], exports: { pptx: "/result.pptx" } }] } : {}) };
      await act(async () => { await new Promise(resolve => setTimeout(resolve, 1600)); });
      assert.equal(document.querySelector(".slide-game"), null);
      if (status === "completed") assert.ok(document.querySelector('a[href="/result.pptx"]'));
    } finally {
      await act(async () => root.unmount());
      api.get = oldGet;
      dom.window.close();
      for (const [key, descriptor] of original) {
        if (descriptor) Object.defineProperty(globalThis, key, descriptor);
        else Reflect.deleteProperty(globalThis, key);
      }
    }
  });
}
