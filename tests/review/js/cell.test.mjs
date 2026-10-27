import assert from "node:assert/strict";
import { beforeEach, test } from "node:test";

import { byClass, byTag, findAll, installDom } from "./fake_dom.mjs";

installDom();
const STATIC = "../../../quotable/review/static/";
const C = await import(`${STATIC}cell.js`);

const ID = "7f3a29c15d0e4b8a9e210c6f3b7d12aa";
const SIZE = [612, 792];
beforeEach(() => C.resetPrefs());

function words(node) {
  if (node.nodeType === 3) return node.data;
  return node.childNodes.map(words).join(" ");
}
const text = (node) => words(node).replace(/\s+/g, " ").trim();
const click = (node, event = {}) =>
  node.listeners.click[0]({ preventDefault() {}, ...event });
const settle = () => new Promise((resolve) => setImmediate(resolve));
const withClass = (node, name) => byClass(node, name);

function cellData(over = {}) {
  return {
    run: ID,
    table: 0,
    kind: "cell",
    page: 3,
    row: 2,
    name: "Amount",
    key: "Amount",
    status: "fuzzy",
    explanation: "The value is on the page with small differences.",
    value: "1,204",
    matched_text: "1,294",
    coverage: 0.5,
    density: 0.12,
    places: 2,
    row_cells: [
      {
        key: "Name",
        name: "Name",
        extra: false,
        value: "Parks",
        status: "exact",
        state: "none",
        selected: false,
      },
      {
        key: "Amount",
        name: "Amount",
        extra: false,
        value: "1,204",
        status: "fuzzy",
        state: "none",
        selected: true,
      },
    ],
    proposal: null,
    ocr: false,
    merge: null,
    extra: null,
    review: {
      state: "none",
      verdict: null,
      draft: null,
      reviewable: true,
      key: {},
    },
    highlights: {
      page: 3,
      size: SIZE,
      matched: [100, 200, 180, 212],
      candidates: [[300, 400, 380, 412]],
      row_window: [195, 215],
      row_label: "row 2",
      column_range: [90, 190],
      cell_area: [90, 195, 190, 215],
      band: null,
      header: { line: 100, bottom: 112, x: { Amount: 140 } },
    },
    nav: {
      n: 4,
      of: 20,
      previous: { page: 3, row: 1, extra: false, name: "Amount" },
      next: { page: 3, row: 3, extra: false, name: "Amount" },
      previous_row: { page: 3, row: 1, extra: false, name: "Amount" },
      next_row: { page: 3, row: 3, extra: false, name: "Amount" },
    },
    ...over,
  };
}

function pageData(over = {}) {
  return {
    page: 3,
    size: SIZE,
    words: [["Total", 10, 20, 40, 30]],
    ocr: false,
    tables: [
      {
        index: 0,
        number: 1,
        band: null,
        header: { line: 100, bottom: 112, x: { Amount: 140 } },
        rows: { 1: [170, 190], 2: [195, 215] },
        columns: { Name: [20, 80], Amount: [90, 190] },
      },
    ],
    ...over,
  };
}

function runData(over = {}) {
  return {
    id: ID,
    short_id: ID.slice(0, 8),
    document: { name: "county_budget.pdf", pages: 41 },
    pdf: { status: "ok", path: "/docs/county_budget.pdf" },
    tables: [{ index: 0, number: 1, label: "General Fund", pages: [3, 4] }],
    ...over,
  };
}

function fakeCtx(over = {}) {
  const calls = [];
  const went = [];
  return {
    calls,
    went,
    getJson: async (path, query) => {
      calls.push([path, query]);
      if (path.includes("/cells/")) return cellData();
      if (path.includes("/pages/")) return pageData();
      return runData();
    },
    replace: () => {},
    go: (route) => went.push(route),
    ...over,
  };
}

const route = (over = {}) => ({
  name: "cell",
  run: ID,
  table: 0,
  cell: { page: 3, row: 2, name: "Amount", extra: false },
  query: {},
  ...over,
});

test("keys: moves, zoom, fit and the text layer; modifiers and text boxes are left alone", () => {
  const key = (k, over = {}) =>
    C.keyAction({ key: k, target: { tagName: "BODY" }, ...over });
  assert.equal(key("j"), "next");
  assert.equal(key("k"), "previous");
  assert.equal(key("]"), "next_row");
  assert.equal(key("["), "previous_row");
  assert.equal(key("n"), "next_unreviewed");
  assert.equal(key("g"), "jump");
  assert.equal(key("+"), "zoom_in");
  assert.equal(key("="), "zoom_in");
  assert.equal(key("-"), "zoom_out");
  assert.equal(key("f"), "fit");
  assert.equal(key("t"), "text");
  assert.equal(key("J"), "next");
  assert.equal(key("q"), null);
  assert.equal(key("j", { metaKey: true }), null);
  assert.equal(key("j", { ctrlKey: true }), null);
  assert.equal(key("j", { target: { tagName: "INPUT" } }), null);
  assert.equal(key("j", { target: { tagName: "TEXTAREA" } }), null);
  assert.equal(key("j", { target: { tagName: "SELECT" } }), null);
  assert.equal(
    key("j", { target: { tagName: "DIV", isContentEditable: true } }),
    null,
  );
});

test("the screen asks for the run, the cell with the filters, and the cell's page", async () => {
  const ctx = fakeCtx();
  await C.show(route({ query: { status: "fuzzy", sort: "page" } }), ctx);
  const paths = ctx.calls.map(([p]) => p);
  assert.ok(paths.includes(`/api/runs/${ID}`));
  const cellCall = ctx.calls.find(([p]) => p.includes("/cells/"));
  assert.equal(cellCall[0], `/api/runs/${ID}/tables/0/cells/3/2/Amount`);
  assert.deepEqual(cellCall[1], { status: "fuzzy", sort: "page" });
  assert.ok(paths.includes(`/api/runs/${ID}/pages/3`));
});

test("an extra field is asked for under extra/ and its page is the printing page", async () => {
  const ctx = fakeCtx({
    getJson: async (path) => {
      ctx.calls.push([path]);
      if (path.includes("/cells/"))
        return cellData({
          kind: "extra",
          name: "fiscal_year",
          extra: {
            name: "fiscal_year",
            source_page: 2,
            carried: true,
            change: null,
          },
          highlights: {
            ...cellData().highlights,
            page: 2,
            row_window: null,
            column_range: null,
            cell_area: null,
          },
        });
      if (path.includes("/pages/")) return pageData({ page: 2 });
      return runData();
    },
  });
  const view = await C.show(
    route({ cell: { page: 3, row: 2, name: "fiscal_year", extra: true } }),
    ctx,
  );
  assert.ok(
    ctx.calls.some(
      ([p]) => p === `/api/runs/${ID}/tables/0/cells/3/2/extra/fiscal_year`,
    ),
  );
  assert.ok(ctx.calls.some(([p]) => p === `/api/runs/${ID}/pages/2`));
  assert.ok(text(view.content).includes("carried forward"));
});

test("the title and crumbs lead back to the table", async () => {
  const view = await C.show(route(), fakeCtx());
  assert.equal(view.title, "Cell 4 of 20 · Amount");
  assert.deepEqual(
    view.crumbs.map((c) => c.text),
    ["Runs", "county_budget.pdf", "Table 1 · General Fund", "Cell"],
  );
  assert.equal(view.crumbs[2].href, `#/run/${ID}/table/0`);
});

test("the page view and the cell view sit side by side", async () => {
  const { content } = await C.show(route(), fakeCtx());
  assert.equal(withClass(content, "page-view").length, 1);
  assert.equal(withClass(content, "cell-view").length, 1);
  assert.ok(content.attributes.class.includes("cell-screen"));
});

test("the toolbar: mode, page, zoom, fit, text layer and the full-PDF link", async () => {
  const { content } = await C.show(route(), fakeCtx());
  const t = text(withClass(content, "toolbar")[0]);
  for (const part of [
    "Highlights",
    "Browser PDF viewer",
    "Page",
    "of 41",
    "100%",
    "Fit width",
    "Text layer",
    "Open full PDF at p. 3",
  ])
    assert.ok(t.includes(part), part);
  const link = findAll(
    content,
    (e) => e.tagName === "A" && text(e).startsWith("Open full PDF"),
  )[0];
  assert.equal(link.getAttribute("href"), `/api/runs/${ID}/pdf#page=3`);
  assert.equal(link.getAttribute("target"), "_blank");
  assert.match(link.getAttribute("rel"), /noopener/);
});

test("the highlights row has six toggles, the header off, and an off toggle is marked", async () => {
  const { content } = await C.show(route(), fakeCtx());
  const toggles = byTag(withClass(content, "hl-toggles")[0], "button");
  assert.deepEqual(toggles.map(text), [
    "Matched words",
    "Other places found",
    "Cell area",
    "Row window",
    "Column range",
    "Header & column centres",
  ]);
  assert.deepEqual(
    toggles.map((t) => t.getAttribute("aria-pressed")),
    ["true", "true", "true", "true", "true", "false"],
  );
  assert.ok(toggles[5].attributes.class.split(" ").includes("off"));
});

test("a shared page adds the Table band toggle", async () => {
  const ctx = fakeCtx({
    getJson: async (path) => {
      if (path.includes("/cells/")) return cellData();
      if (path.includes("/pages/")) {
        const t = pageData().tables[0];
        return pageData({
          tables: [
            { ...t, band: [100, 400] },
            { ...t, index: 1, number: 2, band: [410, 700] },
          ],
        });
      }
      return runData();
    },
  });
  const { content } = await C.show(route(), ctx);
  assert.equal(byTag(withClass(content, "hl-toggles")[0], "button").length, 7);
});

test("the page is the PNG at the cell's page with the highlights over it", async () => {
  const { content } = await C.show(route(), fakeCtx());
  const img = byTag(content, "img")[0];
  assert.equal(img.getAttribute("src"), `/api/runs/${ID}/pages/3.png`);
  assert.match(img.getAttribute("alt"), /page 3/i);
  assert.ok(withClass(content, "hl-matched").length === 1);
  assert.ok(
    text(withClass(content, "hl-matched")[0]).includes("matched words"),
  );
});

test("a toggle takes its highlight off the page", async () => {
  const { content } = await C.show(route(), fakeCtx());
  const first = () => byTag(withClass(content, "hl-toggles")[0], "button")[0];
  click(first());
  assert.equal(withClass(content, "hl-matched").length, 0);
  assert.equal(first().getAttribute("aria-pressed"), "false");
  click(first());
  assert.equal(withClass(content, "hl-matched").length, 1);
});

test("the text layer toggle lays the words over the page", async () => {
  const { content } = await C.show(route(), fakeCtx());
  const button = () =>
    byTag(withClass(content, "toolbar")[0], "button").find((b) =>
      text(b).startsWith("Text layer"),
    );
  assert.equal(withClass(content, "textlayer").length, 0);
  click(button());
  assert.equal(withClass(content, "textlayer").length, 1);
  assert.equal(button().getAttribute("aria-pressed"), "true");
  click(button());
  assert.equal(withClass(content, "textlayer").length, 0);
});

test("zoom in and out change the zoom text and the page's width", async () => {
  const { content } = await C.show(route(), fakeCtx());
  const bar = withClass(content, "toolbar")[0];
  const button = (label) =>
    byTag(bar, "button").find((b) => text(b).includes(label));
  click(button("Zoom in"));
  assert.ok(text(bar).includes("125%"));
  assert.equal(
    withClass(content, "surface")[0].styles.width,
    `${612 * 1.25}px`,
  );
  click(button("Zoom out"));
  click(button("Zoom out"));
  assert.ok(text(bar).includes("75%"));
});

test("next page loads that page's words and image", async () => {
  const ctx = fakeCtx();
  const { content } = await C.show(route(), ctx);
  const next = byTag(withClass(content, "toolbar")[0], "button").find((b) =>
    text(b).includes("Next page"),
  );
  click(next);
  await settle();
  assert.ok(ctx.calls.some(([p]) => p === `/api/runs/${ID}/pages/4`));
  assert.equal(
    byTag(content, "img")[0].getAttribute("src"),
    `/api/runs/${ID}/pages/4.png`,
  );
  assert.equal(withClass(content, "hl-matched").length, 0);
});

test("a page without stored text says so and still shows the image", async () => {
  const ctx = fakeCtx({
    getJson: async (path) => {
      if (path.includes("/cells/")) return cellData();
      if (path.endsWith("/pages/4")) {
        const { ApiError } = await import(`${STATIC}api.js`);
        throw new ApiError("no table of this run is on that page", 404);
      }
      if (path.includes("/pages/")) return pageData();
      return runData();
    },
  });
  const { content } = await C.show(route(), ctx);
  const next = byTag(withClass(content, "toolbar")[0], "button").find((b) =>
    text(b).includes("Next page"),
  );
  click(next);
  await settle();
  assert.ok(
    text(withClass(content, "page-note")[0]).includes("No text was kept"),
  );
  assert.equal(byTag(content, "img").length, 1);
});

test("the browser PDF viewer is an iframe at the page, with a line that it has no highlights", async () => {
  const { content } = await C.show(route(), fakeCtx());
  const mode = byTag(withClass(content, "toolbar")[0], "button").find(
    (b) => text(b) === "Browser PDF viewer",
  );
  click(mode);
  const frame = byTag(content, "iframe")[0];
  assert.equal(frame.getAttribute("src"), `/api/runs/${ID}/pdf#page=3`);
  assert.match(text(content), /no highlights/i);
  assert.equal(withClass(content, "hl-matched").length, 0);
  const back = byTag(withClass(content, "toolbar")[0], "button").find(
    (b) => text(b) === "Highlights",
  );
  click(back);
  assert.equal(byTag(content, "iframe").length, 0);
});

test("a missing PDF: the notice, a blank page of the stored size with highlights and the text", async () => {
  const ctx = fakeCtx({
    getJson: async (path) => {
      if (path.includes("/cells/")) return cellData();
      if (path.includes("/pages/")) return pageData();
      return runData({ pdf: { status: "missing", path: "/gone.pdf" } });
    },
  });
  const { content } = await C.show(route(), ctx);
  assert.ok(text(content).includes("The PDF is missing."));
  assert.equal(byTag(content, "img").length, 0);
  const surface = withClass(content, "surface")[0];
  assert.ok(surface.attributes.class.includes("blank"));
  assert.equal(surface.styles.width, "612px");
  assert.ok(withClass(content, "hl-matched").length === 1);
  const bar = withClass(content, "toolbar")[0];
  const mode = byTag(bar, "button").find(
    (b) => text(b) === "Browser PDF viewer",
  );
  assert.equal(mode.getAttribute("disabled"), "");
  const link = findAll(bar, (e) => text(e).startsWith("Open full PDF"))[0];
  assert.equal(link.getAttribute("href"), null);
  assert.equal(link.getAttribute("aria-disabled"), "true");
});

test("a missing PDF still shows the words, on a blank page", async () => {
  const ctx = fakeCtx({
    getJson: async (path) => {
      if (path.includes("/cells/")) return cellData();
      if (path.includes("/pages/")) return pageData();
      return runData({
        pdf: {
          status: "changed",
          path: "/x.pdf",
          expected: "aaaa…bbbb",
          found: "cccc…dddd",
        },
      });
    },
  });
  const { content } = await C.show(route(), ctx);
  assert.ok(text(content).includes("no longer matches"));
  const bar = withClass(content, "toolbar")[0];
  const textButton = byTag(bar, "button").find((b) =>
    text(b).startsWith("Text layer"),
  );
  click(textButton);
  assert.equal(withClass(content, "textlayer").length, 1);
  assert.equal(text(withClass(content, "textlayer")[0]), "Total");
});

test("selecting a cell area on the page opens that cell", async () => {
  const ctx = fakeCtx();
  const { content } = await C.show(route(), ctx);
  const surface = withClass(content, "surface")[0];
  surface.listeners.click[0]({
    clientX: 120,
    clientY: 180,
    currentTarget: { getBoundingClientRect: () => ({ left: 0, top: 0 }) },
  });
  assert.deepEqual(ctx.went[0].cell, {
    page: 3,
    row: 1,
    name: "Amount",
    extra: false,
  });
  assert.equal(ctx.went[0].name, "cell");
  assert.equal(ctx.went[0].table, 0);
});

test("a click outside every cell area changes nothing", async () => {
  const ctx = fakeCtx();
  const { content } = await C.show(route(), ctx);
  withClass(content, "surface")[0].listeners.click[0]({
    clientX: 5,
    clientY: 5,
    currentTarget: { getBoundingClientRect: () => ({ left: 0, top: 0 }) },
  });
  assert.deepEqual(ctx.went, []);
});

test("the cell view's moves link to the cells with the filters carried", async () => {
  const { content } = await C.show(
    route({ query: { status: "fuzzy" } }),
    fakeCtx(),
  );
  const next = findAll(
    content,
    (e) => e.tagName === "A" && text(e).includes("Next cell"),
  )[0];
  assert.equal(
    next.getAttribute("href"),
    `#/run/${ID}/table/0/cell/3/3/Amount?status=fuzzy`,
  );
});

test("the page's own text stays text", async () => {
  const PAYLOAD = "<img src=x onerror=alert(1)>";
  const ctx = fakeCtx({
    getJson: async (path) => {
      if (path.includes("/cells/")) return cellData({ value: PAYLOAD });
      if (path.includes("/pages/"))
        return pageData({ words: [[PAYLOAD, 10, 20, 40, 30]] });
      return runData();
    },
  });
  const { content } = await C.show(route(), ctx);
  const button = byTag(withClass(content, "toolbar")[0], "button").find((b) =>
    text(b).startsWith("Text layer"),
  );
  click(button);
  assert.equal(
    findAll(content, (e) => e.tagName === "IMG" && e.getAttribute("onerror"))
      .length,
    0,
  );
  assert.equal(byTag(content, "img").length, 1);
});

// --- queue bar, verdict panel and keys (task 013) ----------------------------------------------
const qentry = (row, state = "none") => ({
  run: ID,
  short_run: ID.slice(0, 8),
  table: 0,
  table_number: 1,
  page: 3,
  row,
  column: "Amount",
  extra: false,
  status: "fuzzy",
  review: { state },
});

function queueCtx(over = {}) {
  const sent = [];
  const base = fakeCtx({
    sent,
    sendJson: async (method, path, body) => {
      sent.push([method, path, body]);
      if (path === "/api/drafts") return { saved_at: "2026-10-20T14:05:00Z" };
      return { verdict: {}, next: { index: 2, item: qentry(3) } };
    },
    getJson: async (path, query) => {
      base.calls.push([path, query]);
      if (path === "/api/queue")
        return {
          queue: [qentry(1, "correct"), qentry(2), qentry(3)],
          stats: {
            confidence: 95,
            reviewed: 1,
            judged: 1,
            changed: 0,
            share: 0,
            interval: [0, 0.5],
          },
        };
      if (path.includes("/cells/")) return cellData();
      if (path.includes("/pages/")) return pageData();
      return runData();
    },
    refreshed: 0,
    refresh() {
      this.refreshed++;
    },
    ...over,
  });
  return base;
}
const qroute = () => route({ query: { queue: "1", mode: "all" } });

test("in a queue the screen shows the queue bar and a verdict panel; the heading follows the queue", async () => {
  const ctx = queueCtx();
  const { content } = await C.show(qroute(), ctx);
  assert.equal(withClass(content, "queue-bar").length, 1);
  assert.equal(withClass(content, "verdict").length, 1);
  assert.match(text(content), /Cell 2 of 3/);
  assert.ok(ctx.calls.some(([p]) => p === "/api/queue"));
});

test("without a queue there is a verdict panel but no queue bar", async () => {
  const { content } = await C.show(route(), queueCtx());
  assert.equal(withClass(content, "queue-bar").length, 0);
  assert.equal(withClass(content, "verdict").length, 1);
});

test("in a queue the moves link through the queue with its settings", async () => {
  const { content } = await C.show(qroute(), queueCtx());
  const next = findAll(
    content,
    (e) => e.tagName === "A" && text(e).includes("Next cell"),
  )[0];
  assert.match(next.getAttribute("href"), /cell\/3\/3\/Amount\?.*queue=1/);
});

test("a saved verdict in a queue goes to the next unreviewed cell", async () => {
  const ctx = queueCtx();
  const { content } = await C.show(qroute(), ctx);
  const choice = byTag(withClass(content, "choices")[0], "button")[0];
  click(choice);
  click(withClass(content, "save")[0]);
  await settle();
  assert.equal(ctx.went.at(-1).cell.row, 3);
  assert.equal(ctx.went.at(-1).query.queue, "1");
});

test("a saved verdict outside a queue refreshes the screen", async () => {
  const ctx = queueCtx({
    sendJson: async () => ({ verdict: {}, next: null }),
  });
  const { content } = await C.show(route(), ctx);
  click(byTag(withClass(content, "choices")[0], "button")[0]);
  click(withClass(content, "save")[0]);
  await settle();
  assert.equal(ctx.refreshed, 1);
});

test("keys: verdict choices and categories; save and cancel work inside a text box", () => {
  const key = (k, over = {}) =>
    C.keyAction({ key: k, target: { tagName: "BODY" }, ...over });
  assert.equal(key("c"), "correct");
  assert.equal(key("x"), "change");
  assert.equal(key("u"), "unsure");
  assert.equal(key("3"), "category:3");
  assert.equal(key("0"), null);
  assert.equal(key("Enter", { metaKey: true }), "save");
  assert.equal(key("Enter", { ctrlKey: true }), "save");
  assert.equal(key("Escape"), "cancel");
  const box = { tagName: "TEXTAREA" };
  assert.equal(key("Enter", { ctrlKey: true, target: box }), "save");
  assert.equal(key("Escape", { target: box }), "cancel");
  assert.equal(key("c", { target: box }), null);
});
