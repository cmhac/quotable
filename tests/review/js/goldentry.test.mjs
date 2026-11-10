// A smoke test of the gold entry screen over a fake browser: it mounts, saves and moves on. The
// editing itself (selection, clipboard, keys) needs a real browser and is checked by hand.
import assert from "node:assert/strict";
import { after, test } from "node:test";

import { byClass, byTag, installBrowser } from "./fake_dom.mjs";

installBrowser();
const { show } = await import("../../../quotable/review/static/goldentry.js");

// every mounted screen is disposed at the end, so a failing test cannot keep node alive
const mounted = [];
after(() => mounted.forEach((view) => view.dispose?.()));
async function mount(route, ctx) {
  const view = await show(route, ctx);
  mounted.push(view);
  return view;
}

const SHA = "a".repeat(64);
const tick = () => new Promise((r) => setTimeout(r, 5));

const FEED = {
  sample: { seed: 1, size: 2, drawn: "x", documents: [{ sha256: SHA, name: "doc.pdf", pages: 9 }] },
  pages: [
    { sha256: SHA, name: "doc.pdf", page: 1, status: "new", seconds: null },
    { sha256: SHA, name: "doc.pdf", page: 4, status: "new", seconds: null },
  ],
  done: 0,
  total: 2,
  tracked: { ok: true },
  skipped: [],
};

function setup({ records = {}, failing = false } = {}) {
  const puts = [];
  const replaced = [];
  const ctx = {
    storage: null,
    replace: (route) => replaced.push(route),
    async getJson(path) {
      if (path === "/api/gold") return JSON.parse(JSON.stringify(FEED));
      if (path.endsWith("/words")) return { width: 600, height: 800, words: [["Hello", 10, 10, 40, 20, true]] };
      const page = Number(path.split("/").at(-1));
      return { name: "doc.pdf", pages: 9, pdf: "ok", record: records[page] ?? null };
    },
  };
  globalThis.fetch = async (url, options) => {
    if (failing) throw new Error("down");
    const body = JSON.parse(options.body);
    puts.push([url, body]);
    return { ok: true, status: 200, json: async () => ({ ...body, updated: "now" }) };
  };
  return { ctx, puts, replaced };
}

const route = (page) => ({ name: "goldpage", sha: SHA, page, query: {} });
const text = (node) => node.textContent.replace(/\s+/g, " ").trim();
const doneBox = (view) => byTag(view.content, "input").find((i) => i.getAttribute("type") === "checkbox");

test("the screen mounts with the page list, the progress line and one blank table", async () => {
  const { ctx, replaced } = setup();
  const view = await mount(route(1), ctx);
  assert.equal(view.title, "doc.pdf · page 1");
  assert.equal(byClass(view.content, "gold-feed-item").length, 2);
  assert.match(text(byClass(view.content, "gold-activity")[0]), /0 of 2 pages done · time estimate after the first timed page is done/);
  assert.match(text(byClass(view.content, "gold-tabs")[0]), /Table 1 \(empty\)Add tableRemove table/);
  assert.deepEqual(replaced.at(-1), { name: "goldpage", sha: SHA, page: 1 });
  assert.equal(doneBox(view).checked ?? false, false);
  view.dispose();
});

test("nothing from an extraction is asked for: only the gold and the page are", async () => {
  const asked = [];
  const { ctx } = setup();
  const getJson = ctx.getJson;
  ctx.getJson = async (path) => (asked.push(path), getJson(path));
  const view = await mount(route(1), ctx);
  assert.ok(asked.every((p) => p.startsWith("/api/gold")));
  assert.ok(asked.every((p) => !p.includes("/api/runs")));
  view.dispose();
});

test("marking a page with nothing typed done saves it with no tables and opens the next page", async () => {
  const { ctx, puts, replaced } = setup();
  const view = await mount(route(1), ctx);
  const box = doneBox(view);
  box.checked = true;
  await box.listeners.change[0]({ target: box });
  await tick();
  assert.equal(puts.length, 1);
  const [url, body] = puts[0];
  assert.equal(url, `/api/gold/pages/${SHA}/1`);
  assert.deepEqual([body.tables, body.done], [[], true]);
  assert.equal(typeof body.seconds === "number" || body.seconds === null, true);
  assert.deepEqual(replaced.at(-1), { name: "goldpage", sha: SHA, page: 4 });
  const items = byClass(view.content, "gold-feed-item");
  assert.match(text(items[0]), /page 1 · done/);
  assert.equal(items[1].getAttribute("aria-current"), "true");
  view.dispose();
});

test("a page with an unnamed column cannot be marked done and nothing is sent", async () => {
  const records = { 1: { tables: [{ columns: ["A", ""], rows: [["1", "2"]] }], done: false, seconds: 5 } };
  const { ctx, puts } = setup({ records });
  const view = await mount(route(1), ctx);
  const box = doneBox(view);
  box.checked = true;
  await box.listeners.change[0]({ target: box });
  assert.equal(puts.length, 0);
  assert.equal(box.checked, false);
  assert.match(text(byClass(view.content, "gold-save-state")[0]), /Name every column of table 1/);
  view.dispose();
});

test("a server that cannot be reached shows the red bar and keeps the page unsaved", async () => {
  const { ctx } = setup({ failing: true });
  const view = await mount(route(1), ctx);
  const box = doneBox(view);
  box.checked = true;
  await box.listeners.change[0]({ target: box });
  await tick();
  const bar = byClass(view.content, "gold-offline")[0];
  assert.match(bar.textContent, /CANNOT REACH THE SERVER/);
  assert.match(text(byClass(view.content, "gold-save-state")[0]), /NOT SAVED/);
  view.dispose();
});

test("a stored page opens as its tables, done pages are not padded", async () => {
  const records = { 1: { tables: [{ columns: ["A"], rows: [["x"]] }], done: true, seconds: 61 } };
  const { ctx } = setup({ records });
  const view = await mount(route(1), ctx);
  assert.equal(doneBox(view).checked, true);
  assert.match(text(byClass(view.content, "gold-tabs")[0]), /^Table 1Add tableRemove table/);
  assert.match(text(byClass(view.content, "gold-timer")[0]), /1:01/);
  view.dispose();
});

test("leaving the screen removes its listeners", async () => {
  const { ctx } = setup();
  const before = (document.listeners.keydown ?? []).length;
  const view = await mount(route(1), ctx);
  assert.ok(document.listeners.keydown.length > before);
  view.dispose();
  assert.equal(document.listeners.keydown.length, before);
});

test("without a sample the screen says so and links the sample screen", async () => {
  const { ctx } = setup();
  ctx.getJson = async () => ({ ...FEED, sample: null, pages: [] });
  const view = await mount(route(1), ctx);
  assert.match(text(view.content), /No sample has been drawn yet/);
  assert.equal(view.dispose, undefined);
});

test("a page whose PDF is missing cannot be marked done and says why", async () => {
  const { ctx } = setup();
  const getJson = ctx.getJson;
  ctx.getJson = async (path) => {
    const data = await getJson(path);
    return path.startsWith("/api/gold/pages/") && !path.endsWith("/words") ? { ...data, pdf: "missing" } : data;
  };
  const view = await mount(route(1), ctx);
  const box = doneBox(view);
  assert.equal(box.disabled, true);
  assert.match(box.title, /cannot be marked done/);
  assert.match(text(view.content), /The PDF is missing/);
});
