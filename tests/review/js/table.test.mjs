import assert from "node:assert/strict";
import { mock, test } from "node:test";

import { byClass, byTag, findAll, installDom } from "./fake_dom.mjs";

process.env.TZ = "UTC";
installDom();
const STATIC = "../../../quotable/review/static/";
const T = await import(`${STATIC}table.js`);
const { statusText } = await import(`${STATIC}status.js`);

const ID = "7f3a29c15d0e4b8a9e210c6f3b7d12aa";
const PAYLOAD = "<img src=x onerror=alert(1)>";

function words(node) {
  if (node.nodeType === 3) return node.data;
  let out = "";
  let afterElement = false;
  for (const child of node.childNodes) {
    const part = words(child);
    if (child.nodeType === 1 && afterElement && part) out += " ";
    out += part;
    if (child.nodeType === 3) afterElement = false;
    else if (part) afterElement = true;
  }
  return out;
}
const text = (node) => words(node).replace(/\s+/g, " ").trim();
const noImages = (node) =>
  assert.equal(findAll(node, (e) => e.tagName === "IMG").length, 0);
const click = (node) => node.listeners.click[0]({ preventDefault() {} });
const attr = (node, name) => node.getAttribute(name);

const STATUSES = [
  "exact",
  "fuzzy",
  "misplaced",
  "ungrounded",
  "untokenized",
  "empty",
  "not_on_page",
];

function info(over = {}) {
  return {
    index: 0,
    number: 1,
    label: "General Fund Expenditures by Department",
    columns: ["Department", "FY2025 Actual"],
    extra_names: ["fiscal_year"],
    pages: [3, 4, 5, 41],
    rows: 1214,
    merged: 1,
    ocr_pages: [17, 18],
    ...over,
  };
}

function summary(over = {}) {
  return {
    cells: 6070,
    statuses: {
      exact: 4402,
      fuzzy: 902,
      misplaced: 318,
      ungrounded: 240,
      untokenized: 52,
      empty: 101,
      not_on_page: 55,
    },
    position: { misplaced: 318, unchecked: 41 },
    recheck: { accepted: 57 },
    ...over,
  };
}

const columns = () => [
  { key: "page", name: "page", kind: "page", numeric: true, statuses: {} },
  { key: "row", name: "row", kind: "row", numeric: true, statuses: {} },
  {
    key: "Department",
    name: "Department",
    kind: "column",
    numeric: false,
    statuses: {
      exact: 603,
      fuzzy: 498,
      misplaced: 82,
      ungrounded: 21,
      not_on_page: 10,
    },
  },
  {
    key: "FY2025 Actual",
    name: "FY2025 Actual",
    kind: "column",
    numeric: true,
    statuses: { exact: 788, fuzzy: 160 },
  },
  {
    key: "fiscal_year",
    name: "fiscal_year",
    kind: "extra",
    numeric: false,
    statuses: { exact: 1126, empty: 44 },
  },
];

const cell = (key, value, status, extra = false, over = {}) => ({
  key,
  name: key,
  extra,
  value,
  status,
  coverage: 1,
  source_page: extra ? 12 : null,
  state: "none",
  ...over,
});

function review(over = {}) {
  return {
    state: "none",
    was: null,
    unreviewed: 0,
    note: false,
    ocr: false,
    merged: false,
    label: "Not reviewed",
    ...over,
  };
}

function rowData(over = {}) {
  return {
    page: 12,
    row: 4,
    status: "fuzzy",
    recheck: false,
    ocr: false,
    merged: false,
    review: review(),
    cells: [
      cell("Department", "Parks and Rec. Grants", "fuzzy"),
      cell("FY2025 Actual", "388,200", "exact"),
      cell("fiscal_year", "FY2026", "exact", true),
    ],
    ...over,
  };
}

function rowsData(over = {}) {
  return {
    offset: 0,
    limit: 100,
    matched: 486,
    total: 1214,
    columns: columns(),
    summary: summary(),
    sort: { column: "page", desc: false },
    rows: [
      rowData(),
      rowData({
        page: 13,
        row: 9,
        status: "ungrounded",
        cells: [
          cell("Department", "Library Services", "exact"),
          cell("FY2025 Actual", "2,980,114", "ungrounded"),
          cell("fiscal_year", "FY2026", "exact", true),
        ],
      }),
    ],
    ...over,
  };
}

const base = () => T.parseState({});

// --- the filters as a value ------------------------------------------------------------------
test("no query means no filters and the default sort", () => {
  assert.deepEqual(base(), {
    statuses: [],
    q: "",
    column: "",
    page: "",
    review: "any",
    flagged: false,
    recheck: false,
    ocr: false,
    merged: false,
    sort: "",
    desc: false,
    offset: 0,
    open: "",
  });
});

test("every filter is read from the query", () => {
  const state = T.parseState({
    status: "fuzzy,misplaced",
    q: "parks",
    column: "Department",
    page: "14",
    review: "changed",
    flagged: "1",
    recheck: "1",
    ocr: "1",
    merged: "1",
    sort: "FY2025 Actual",
    desc: "1",
    offset: "200",
    open: "14.7",
  });
  assert.deepEqual(state, {
    statuses: ["fuzzy", "misplaced"],
    q: "parks",
    column: "Department",
    page: "14",
    review: "changed",
    flagged: true,
    recheck: true,
    ocr: true,
    merged: true,
    sort: "FY2025 Actual",
    desc: true,
    offset: 200,
    open: "14.7",
  });
});

test("what is not a status, a review state or a number is dropped", () => {
  const state = T.parseState({
    status: "fuzzy,bogus,,exact",
    review: "nope",
    offset: "-3",
    page: "x",
  });
  assert.deepEqual(state.statuses, ["exact", "fuzzy"]);
  assert.equal(state.review, "any");
  assert.equal(state.offset, 0);
  assert.equal(state.page, "");
});

test("the URL holds only what differs from the defaults, and reads back the same", () => {
  assert.deepEqual(T.stateQuery(base()), {});
  const state = T.parseState({
    status: "misplaced,fuzzy",
    q: "parks",
    flagged: "1",
    sort: "Department",
    desc: "1",
    offset: "100",
    open: "3.4",
  });
  const query = T.stateQuery(state);
  assert.deepEqual(query, {
    status: "fuzzy,misplaced",
    q: "parks",
    flagged: "1",
    sort: "Department",
    desc: "1",
    offset: "100",
    open: "3.4",
  });
  assert.deepEqual(T.parseState(query), state);
});

test("the server's query has no open row, and a cell's link has no paging either", () => {
  const state = T.parseState({
    status: "fuzzy",
    offset: "100",
    open: "3.4",
    sort: "page",
    desc: "1",
  });
  assert.deepEqual(T.apiQuery(state), {
    status: "fuzzy",
    sort: "page",
    desc: "1",
    offset: "100",
  });
  assert.deepEqual(T.cellQuery(state), {
    status: "fuzzy",
    sort: "page",
    desc: "1",
  });
});

test("toggling a status keeps the canonical order and goes back to the first page", () => {
  let state = { ...base(), offset: 300 };
  state = T.toggleStatus(state, "misplaced");
  state = T.toggleStatus(state, "exact");
  assert.deepEqual(state.statuses, ["exact", "misplaced"]);
  assert.equal(state.offset, 0);
  assert.deepEqual(T.toggleStatus(state, "exact").statuses, ["misplaced"]);
});

test("a filter is on when a filter differs; sort and paging do not count", () => {
  assert.equal(T.hasFilters(base()), false);
  assert.equal(
    T.hasFilters({
      ...base(),
      sort: "Department",
      desc: true,
      offset: 100,
      open: "1.1",
    }),
    false,
  );
  for (const change of [
    { statuses: ["fuzzy"] },
    { q: "x" },
    { column: "Department" },
    { page: "3" },
    { review: "note" },
    { flagged: true },
    { recheck: true },
    { ocr: true },
    { merged: true },
  ]) {
    assert.equal(
      T.hasFilters({ ...base(), ...change }),
      true,
      JSON.stringify(change),
    );
  }
});

test("clearing filters keeps the sort and the open row", () => {
  const state = {
    ...base(),
    statuses: ["fuzzy"],
    q: "x",
    flagged: true,
    sort: "Department",
    desc: true,
    offset: 100,
    open: "1.2",
  };
  const cleared = T.clearFilters(state);
  assert.equal(T.hasFilters(cleared), false);
  assert.deepEqual(
    [cleared.sort, cleared.desc, cleared.open, cleared.offset],
    ["Department", true, "1.2", 0],
  );
});

test("clicking a heading sorts ascending, then reverses, then reverses again", () => {
  let state = T.nextSort(base(), "Department", "page");
  assert.deepEqual([state.sort, state.desc], ["Department", false]);
  state = T.nextSort(state, "Department", "page");
  assert.deepEqual([state.sort, state.desc], ["Department", true]);
  state = T.nextSort(state, "Department", "page");
  assert.deepEqual([state.sort, state.desc], ["Department", false]);
});

test("the default order is page ascending, and a click on page reverses it", () => {
  let state = T.nextSort(base(), "page", "page");
  assert.deepEqual([state.sort, state.desc], ["page", true]);
  state = T.nextSort(state, "page", "page");
  assert.deepEqual([state.sort, state.desc], ["", false]);
  state = T.nextSort({ ...base(), sort: "Fund", offset: 200 }, "page", "page");
  assert.deepEqual([state.sort, state.desc, state.offset], ["", false, 0]);
});

test("the sort line says what the order is", () => {
  const cols = columns();
  assert.equal(
    T.sortText({ column: "page", desc: false }, cols),
    "Sorted by page, row · click a column heading to sort",
  );
  assert.equal(
    T.sortText({ column: "page", desc: true }, cols),
    "Sorted by page, row (descending) · click a column heading to sort",
  );
  assert.equal(
    T.sortText({ column: "Department", desc: false }, cols),
    "Sorted by Department (ascending) · click a column heading to sort",
  );
  assert.equal(
    T.sortText({ column: "FY2025 Actual", desc: true }, cols),
    "Sorted by FY2025 Actual (descending) · click a column heading to sort",
  );
});

// --- status text -----------------------------------------------------------------------------
test("a status with a count reads as glyph, word and count", () => {
  assert.equal(statusText("fuzzy", 902), "≈ fuzzy 902");
  assert.equal(statusText("not_on_page", 1), "— not on page 1");
  assert.equal(statusText("exact"), "✓ exact");
});

// --- the heading -----------------------------------------------------------------------------
test("the heading line gives the table's facts and the label is the title", () => {
  const node = T.headView(ID, info(), 486, base());
  assert.equal(
    text(byClass(node, "where")[0]),
    "Table 1 · pages 3–5, 41 · 1,214 rows · 1 merged part · OCR on pp. 17–18",
  );
  assert.equal(
    text(byTag(node, "h1")[0]),
    "General Fund Expenditures by Department",
  );
});

test("only the facts that apply are in the heading line, and a table without a label is 'Table N'", () => {
  const node = T.headView(
    ID,
    info({
      number: 2,
      index: 1,
      label: "",
      merged: 3,
      ocr_pages: [],
      pages: [43],
      rows: 1,
    }),
    1,
    base(),
  );
  assert.equal(
    text(byClass(node, "where")[0]),
    "Table 2 · page 43 · 1 row · 3 merged parts",
  );
  assert.equal(text(byTag(node, "h1")[0]), "Table 2");
});

test("the buttons open the queue for this table and download the matching rows", () => {
  const state = T.parseState({
    status: "fuzzy",
    q: "parks",
    sort: "Department",
    desc: "1",
    offset: "200",
    open: "3.4",
  });
  const node = T.headView(ID, info(), 486, state);
  const [review, csv] = byClass(node, "btn");
  assert.equal(text(review), "Review flagged cells");
  assert.equal(attr(review, "href"), `#/queue?run=${ID}&table=0`);
  assert.equal(text(csv), "Download 486 rows as CSV");
  const href = attr(csv, "href");
  assert.ok(href.startsWith(`/api/runs/${ID}/tables/0/rows.csv?`), href);
  const query = new URLSearchParams(href.split("?")[1]);
  assert.deepEqual(Object.fromEntries(query), {
    status: "fuzzy",
    q: "parks",
    sort: "Department",
    desc: "1",
  });
  assert.equal(attr(csv, "download"), "");
});

test("one row is 'Download 1 row as CSV' and no filters means a bare link", () => {
  const node = T.headView(ID, info(), 1, base());
  const csv = byClass(node, "btn")[1];
  assert.equal(text(csv), "Download 1 row as CSV");
  assert.equal(attr(csv, "href"), `/api/runs/${ID}/tables/0/rows.csv`);
});

// --- the summary -----------------------------------------------------------------------------
test("the bar's segments are each status's share of all the cells", () => {
  const parts = T.barParts({
    cells: 100,
    statuses: { exact: 50, fuzzy: 25, misplaced: 0, ungrounded: 25 },
  });
  assert.deepEqual(
    parts.map((p) => p.status),
    ["exact", "fuzzy", "ungrounded"],
  );
  assert.deepEqual(
    parts.map((p) => p.width),
    ["50%", "25%", "25%"],
  );
  assert.deepEqual(T.barParts({ cells: 0, statuses: {} }), []);
});

test("the summary card: the bar, the counts under it, the position check and the recheck", () => {
  const node = T.summaryView(summary());
  assert.equal(text(byClass(node, "label")[0]), "Cells by status · 6,070");
  const bar = byClass(node, "bar-stack")[0];
  assert.equal(attr(bar, "aria-hidden"), "true");
  assert.equal(bar.children.length, 7);
  assert.ok(
    byClass(bar, "seg-exact").length && byClass(bar, "seg-untokenized").length,
  );
  assert.equal(
    text(byClass(node, "counts")[0]),
    "✓ exact 4,402 ≈ fuzzy 902 ⇄ misplaced 318 × ungrounded 240 # untokenized 52 ∅ empty 101 — not on page 55",
  );
  assert.match(text(node), /Position check 318 misplaced · 41 unchecked/);
  assert.match(text(node), /Recheck 57 changes accepted/);
});

test("one recheck change is singular, and none says so", () => {
  assert.match(
    text(T.summaryView(summary({ recheck: { accepted: 1 } }))),
    /Recheck 1 change accepted/,
  );
  assert.match(
    text(T.summaryView(summary({ recheck: { accepted: 0 } }))),
    /Recheck 0 changes accepted/,
  );
});

// --- the filters card ------------------------------------------------------------------------
function filters(state = base(), over = {}) {
  const changes = [];
  const card = T.createFilters({
    columns: columns(),
    summary: summary(),
    pages: [3, 4, 5, 41],
    state,
    onChange: (next) => changes.push(next),
    ...over,
  });
  card.sync(486, 1214, { column: "page", desc: false });
  return { card, changes };
}

test("seven status toggles, each with its count and its state", () => {
  const { card } = filters(T.parseState({ status: "fuzzy" }));
  const toggles = byClass(card.node, "fchip");
  assert.deepEqual(toggles.map(text), [
    "✓ exact 4,402",
    "≈ fuzzy 902",
    "⇄ misplaced 318",
    "× ungrounded 240",
    "# untokenized 52",
    "∅ empty 101",
    "— not on page 55",
  ]);
  assert.deepEqual(
    toggles.map((t) => attr(t, "aria-pressed")),
    ["false", "true", "false", "false", "false", "false", "false"],
  );
  assert.ok(toggles.every((t) => attr(t, "type") === "button"));
});

test("clicking a status toggle asks for the new state and syncing shows it", () => {
  const { card, changes } = filters();
  click(byClass(card.node, "fchip")[2]);
  assert.deepEqual(changes[0].statuses, ["misplaced"]);
  card.sync(10, 1214, { column: "page", desc: false });
  assert.equal(attr(byClass(card.node, "fchip")[2], "aria-pressed"), "true");
  assert.ok(byClass(card.node, "f-misplaced").length);
});

test("search, column, page, review state: the controls and what they ask for", () => {
  const { card, changes } = filters();
  const [search] = byTag(card.node, "input").filter(
    (i) => attr(i, "type") === "search",
  );
  assert.equal(attr(search, "placeholder"), "Search all values of a row");
  const selects = byTag(card.node, "select");
  assert.deepEqual(
    selects.map((s) => attr(s, "aria-label")),
    ["Column", "Page", "Review state"],
  );
  assert.deepEqual(byTag(selects[0], "option").map(text), [
    "Any column",
    "Department",
    "FY2025 Actual",
    "fiscal_year",
  ]);
  assert.deepEqual(byTag(selects[1], "option").map(text), [
    "Any page",
    "3",
    "4",
    "5",
    "41",
  ]);
  assert.deepEqual(byTag(selects[2], "option").map(text), [
    "Any review state",
    "Not reviewed",
    "Correct",
    "Changed",
    "Can’t tell",
    "Has a note",
  ]);
  assert.deepEqual(
    byTag(selects[2], "option").map((o) => o.value),
    ["any", "unreviewed", "correct", "changed", "unsure", "note"],
  );
  selects[0].listeners.change[0]({ target: { value: "Department" } });
  selects[1].listeners.change[0]({ target: { value: "41" } });
  selects[2].listeners.change[0]({ target: { value: "changed" } });
  assert.deepEqual(
    changes.map((c) => [c.column, c.page, c.review]),
    [
      ["Department", "", "any"],
      ["Department", "41", "any"],
      ["Department", "41", "changed"],
    ],
  );
});

test("each change starts from the state the card last showed", () => {
  const { card, changes } = filters();
  const select = byTag(card.node, "select")[0];
  select.listeners.change[0]({ target: { value: "Department" } });
  card.sync(10, 1214, { column: "page", desc: false });
  byTag(card.node, "select")[1].listeners.change[0]({
    target: { value: "41" },
  });
  assert.deepEqual([changes[1].column, changes[1].page], ["Department", "41"]);
});

test("the four check boxes", () => {
  const { card, changes } = filters();
  const boxes = byTag(card.node, "input").filter(
    (i) => attr(i, "type") === "checkbox",
  );
  assert.deepEqual(byClass(card.node, "chk").map(text), [
    "Flagged rows only",
    "Changed by recheck",
    "On OCR’d pages",
    "From a merged part",
  ]);
  boxes.forEach((box) =>
    box.listeners.change[0]({ target: { checked: true } }),
  );
  assert.deepEqual(
    changes.map(
      (c) => [c.flagged, c.recheck, c.ocr, c.merged].filter(Boolean).length,
    ),
    [1, 2, 3, 4],
  );
  assert.deepEqual(
    [changes[0].flagged, changes[1].recheck, changes[2].ocr, changes[3].merged],
    [true, true, true, true],
  );
});

test("a filter change goes back to the first page", () => {
  const { card, changes } = filters({ ...base(), offset: 300 });
  byTag(card.node, "select")[0].listeners.change[0]({
    target: { value: "Department" },
  });
  assert.equal(changes[0].offset, 0);
});

test("typing in search waits for a pause, and only the last text is asked for", () => {
  mock.timers.enable({ apis: ["setTimeout"] });
  try {
    const { card, changes } = filters();
    const search = byTag(card.node, "input").find(
      (i) => attr(i, "type") === "search",
    );
    search.listeners.input[0]({ target: { value: "p" } });
    mock.timers.tick(100);
    search.listeners.input[0]({ target: { value: "par" } });
    mock.timers.tick(100);
    assert.equal(changes.length, 0);
    mock.timers.tick(300);
    assert.deepEqual(
      changes.map((c) => c.q),
      ["par"],
    );
  } finally {
    mock.timers.reset();
  }
});

test("syncing fills the controls from the state, and the line under them says how many rows match", () => {
  const state = T.parseState({
    q: "parks",
    column: "Department",
    page: "5",
    review: "note",
    flagged: "1",
  });
  const { card } = filters(state);
  const search = byTag(card.node, "input").find(
    (i) => attr(i, "type") === "search",
  );
  assert.equal(search.value, "parks");
  const selects = byTag(card.node, "select");
  assert.deepEqual(
    selects.map((s) => s.value),
    ["Department", "5", "note"],
  );
  const box = byTag(card.node, "input").find(
    (i) => attr(i, "type") === "checkbox",
  );
  assert.equal(box.checked, true);
  assert.equal(
    text(byClass(card.node, "matches")[0]),
    "486 of 1,214 rows match",
  );
  assert.equal(
    text(byClass(card.node, "sorted")[0]),
    "Sorted by page, row · click a column heading to sort",
  );
});

test("clear filters is off with no filter and clears them otherwise", () => {
  const none = filters();
  const [off] = byClass(none.card.node, "clear");
  assert.equal(text(off), "Clear filters");
  assert.equal(attr(off, "disabled"), "");

  const on = filters(
    T.parseState({ status: "fuzzy", q: "x", sort: "Department" }),
  );
  const [button] = byClass(on.card.node, "clear");
  assert.equal(attr(button, "disabled"), null);
  click(button);
  assert.equal(T.hasFilters(on.changes[0]), false);
  assert.equal(on.changes[0].sort, "Department");
});

test("one matching row is singular", () => {
  const { card } = filters();
  card.sync(1, 1, { column: "page", desc: false });
  assert.equal(text(byClass(card.node, "matches")[0]), "1 of 1 row match");
});

// --- the grid --------------------------------------------------------------------------------
const grid = (data = rowsData(), state = base(), calls = []) =>
  T.gridView(data, {
    run: ID,
    table: 0,
    state,
    onSort: (key) => calls.push(key),
  });

test("headings: sortable buttons with ▲ ▼ ↕, numbers right-aligned, extra fields after a divider", () => {
  const node = grid();
  const heads = byTag(node, "th");
  assert.deepEqual(heads.map(text), [
    "page ▲",
    "row ↕",
    "Department ↕",
    "FY2025 Actual ↕",
    "fiscal_year extra ↕",
    "Review",
  ]);
  assert.deepEqual(
    heads.map((h) => attr(h, "aria-sort")),
    ["ascending", "none", "none", "none", "none", null],
  );
  assert.ok(attr(heads[3], "class").split(" ").includes("num"));
  assert.ok(!attr(heads[2], "class")?.split(" ").includes("num"));
  assert.ok(attr(heads[4], "class").split(" ").includes("divider"));
  assert.equal(byClass(heads[4], "tag")[0].textContent, "extra");
});

test("a descending sort shows ▼ and aria-sort", () => {
  const data = rowsData({ sort: { column: "Department", desc: true } });
  const heads = byTag(grid(data), "th");
  assert.equal(text(heads[2]), "Department ▼");
  assert.equal(attr(heads[2], "aria-sort"), "descending");
  assert.equal(text(heads[0]), "page ↕");
});

test("clicking a heading asks to sort by that column's key", () => {
  const calls = [];
  const node = grid(rowsData(), base(), calls);
  const buttons = byTag(byTag(node, "thead")[0], "button");
  assert.equal(buttons.length, 5);
  click(buttons[2]);
  click(buttons[4]);
  assert.deepEqual(calls, ["Department", "fiscal_year"]);
});

test("the 'By status' row gives each column's non-zero counts", () => {
  const node = grid();
  const [, second] = byTag(byTag(node, "thead")[0], "tr");
  const cells = byTag(second, "td").map(text);
  assert.equal(cells[0], "By status");
  assert.equal(
    cells[1],
    "✓ exact 603 ≈ fuzzy 498 ⇄ misplaced 82 × ungrounded 21 — not on page 10",
  );
  assert.equal(cells[2], "✓ exact 788 ≈ fuzzy 160");
  assert.equal(cells[3], "✓ exact 1,126 ∅ empty 44");
  assert.equal(cells.length, 5);
  assert.equal(attr(byTag(second, "td")[0], "colspan"), "2");
});

test("each row has its page, row, values with their status, and a Review label", () => {
  const node = grid();
  const [first] = byTag(byTag(node, "tbody")[0], "tr");
  const cells = byTag(first, "td");
  assert.equal(cells.length, 6);
  assert.deepEqual(cells.slice(0, 2).map(text), ["12", "4"]);
  assert.equal(text(cells[2]), "Parks and Rec. Grants ≈ fuzzy");
  assert.equal(text(cells[3]), "388,200 ✓ exact");
  assert.equal(text(cells[4]), "FY2026 ✓ exact");
  assert.equal(text(cells[5]), "Not reviewed");
});

test("exact is a quiet label and the others are badges; ungrounded values are underlined", () => {
  const node = grid();
  const rows = byTag(byTag(node, "tbody")[0], "tr");
  const exact = byClass(byTag(rows[0], "td")[3], "badge")[0];
  assert.ok(attr(exact, "class").split(" ").includes("quiet"));
  const fuzzy = byClass(byTag(rows[0], "td")[2], "badge")[0];
  assert.ok(!attr(fuzzy, "class").split(" ").includes("quiet"));
  assert.ok(attr(fuzzy, "class").split(" ").includes("s-fuzzy"));
  const bad = byTag(rows[1], "td")[3];
  assert.ok(byClass(bad, "ungrounded").length);
  assert.equal(byClass(byTag(rows[0], "td")[3], "ungrounded").length, 0);
});

test("numbers are right-aligned and extra fields sit after the divider", () => {
  const node = grid();
  const [first] = byTag(byTag(node, "tbody")[0], "tr");
  const cells = byTag(first, "td");
  const has = (cellNode, name) =>
    (attr(cellNode, "class") ?? "").split(" ").includes(name);
  assert.ok(
    has(cells[0], "num") && has(cells[1], "num") && has(cells[3], "num"),
  );
  assert.ok(!has(cells[2], "num"));
  assert.ok(has(cells[4], "divider"));
});

test("a cell is a link to its cell screen carrying the filters, but not the paging", () => {
  const state = T.parseState({
    status: "fuzzy",
    sort: "Department",
    offset: "100",
  });
  const node = grid(rowsData(), state);
  const [first] = byTag(byTag(node, "tbody")[0], "tr");
  const links = byTag(first, "a");
  assert.equal(links.length, 3);
  assert.equal(
    attr(links[0], "href"),
    `#/run/${ID}/table/0/cell/12/4/Department?status=fuzzy&sort=Department`,
  );
  assert.equal(
    attr(links[2], "href"),
    `#/run/${ID}/table/0/cell/12/4/extra/fiscal_year?status=fuzzy&sort=Department`,
  );
});

test("the open row is highlighted and says so in the Review column", () => {
  const node = grid(rowsData(), T.parseState({ open: "13.9" }));
  const rows = byTag(byTag(node, "tbody")[0], "tr");
  assert.ok(
    !byClass(rows[0], "open").length &&
      !(attr(rows[0], "class") ?? "").includes("open"),
  );
  assert.ok(attr(rows[1], "class").split(" ").includes("open"));
  assert.equal(text(byTag(rows[1], "td")[5]), "◉ Open in review");
});

test("a row with nothing to show for a value leaves it empty, and a grid with no rows says so", () => {
  const data = rowsData({
    rows: [
      rowData({
        cells: [
          cell("Department", "", "empty"),
          cell("FY2025 Actual", "", "not_on_page"),
          cell("fiscal_year", "", "empty", true),
        ],
      }),
    ],
  });
  const [first] = byTag(byTag(grid(data), "tbody")[0], "tr");
  assert.equal(text(byTag(first, "td")[2]), "∅ empty");
  assert.match(
    text(grid(rowsData({ rows: [], matched: 0 }))),
    /No rows match the filters\./,
  );
});

test("values are text, never markup", () => {
  const data = rowsData();
  data.rows[0].cells[0].value = PAYLOAD;
  data.columns[2].name = PAYLOAD;
  data.rows[0].review.state = "stale";
  data.rows[0].review.was = PAYLOAD;
  const node = grid(data);
  noImages(node);
  assert.ok(text(node).includes(PAYLOAD));
});

// --- the Review column -----------------------------------------------------------------------
const parts = (over, open = false) =>
  T.reviewParts(rowData({ review: review(over) }), open);

test("the main label is the most important verdict, as the board styles it", () => {
  assert.deepEqual(parts({}).main, { text: "Not reviewed", tone: "none" });
  assert.deepEqual(parts({ state: "correct" }).main, {
    text: "✓ Correct",
    tone: "correct",
  });
  assert.deepEqual(parts({ state: "changed" }).main, {
    text: "✎ Changed",
    tone: "changed",
  });
  assert.deepEqual(parts({ state: "unsure" }).main, {
    text: "? Can’t tell",
    tone: "unsure",
  });
  assert.deepEqual(parts({ state: "stale", was: "1,250,000" }).main, {
    text: "Stale · was 1,250,000",
    tone: "stale",
  });
  assert.deepEqual(parts({ state: "none" }, true).main, {
    text: "◉ Open in review",
    tone: "open",
  });
});

test("then each thing that applies, and 'not reviewed' only once the row has a verdict", () => {
  assert.deepEqual(
    parts({
      state: "correct",
      unreviewed: 2,
      note: true,
      ocr: true,
      merged: true,
    }).rest,
    ["· 2 not reviewed", "· note", "· OCR page", "· merged part"],
  );
  assert.deepEqual(parts({ state: "none", unreviewed: 2 }).rest, []);
  assert.deepEqual(parts({ state: "changed" }).rest, []);
  assert.deepEqual(parts({ state: "none", ocr: true }).rest, ["· OCR page"]);
});

test("the Review column of a row reads as one label", () => {
  const data = rowsData();
  data.rows[0].review = review({
    state: "correct",
    unreviewed: 3,
    note: true,
    ocr: true,
  });
  const [first] = byTag(byTag(grid(data), "tbody")[0], "tr");
  assert.equal(
    text(byTag(first, "td")[5]),
    "✓ Correct · 3 not reviewed · note · OCR page",
  );
  assert.ok(byClass(byTag(first, "td")[5], "rv-correct").length);
});

// --- the pager -------------------------------------------------------------------------------
test("the pager shows the rows, the page and its neighbours", () => {
  const node = T.pagerView(
    { offset: 100, limit: 100, matched: 486, shown: 100 },
    () => {},
  );
  assert.equal(text(byClass(node, "range")[0]), "Rows 101–200 of 486");
  const [previous, next] = byTag(node, "button");
  assert.equal(text(previous), "‹ Previous");
  assert.equal(text(next), "Next ›");
  assert.equal(attr(previous, "disabled"), null);
  assert.equal(attr(next, "disabled"), null);
  const box = byTag(node, "input")[0];
  assert.equal(box.value, "2");
  assert.equal(attr(box, "aria-label"), "Page of rows");
  assert.match(text(byClass(node, "pages")[0]), /^Page of 5$/);
});

test("the first and the last page switch off one button; the last range ends at the total", () => {
  const first = T.pagerView(
    { offset: 0, limit: 100, matched: 486, shown: 100 },
    () => {},
  );
  assert.equal(attr(byTag(first, "button")[0], "disabled"), "");
  assert.equal(text(byClass(first, "range")[0]), "Rows 1–100 of 486");
  const last = T.pagerView(
    { offset: 400, limit: 100, matched: 486, shown: 86 },
    () => {},
  );
  assert.equal(attr(byTag(last, "button")[1], "disabled"), "");
  assert.equal(text(byClass(last, "range")[0]), "Rows 401–486 of 486");
});

test("no rows, one page: nothing to page", () => {
  const node = T.pagerView(
    { offset: 0, limit: 100, matched: 0, shown: 0 },
    () => {},
  );
  assert.equal(text(byClass(node, "range")[0]), "Rows 0 of 0");
  assert.ok(byTag(node, "button").every((b) => attr(b, "disabled") === ""));
  assert.equal(byTag(node, "input")[0].value, "1");
});

test("previous, next and the page box ask for an offset", () => {
  const asked = [];
  const node = T.pagerView(
    { offset: 100, limit: 100, matched: 486, shown: 100 },
    (offset) => asked.push(offset),
  );
  const [previous, next] = byTag(node, "button");
  click(previous);
  click(next);
  const box = byTag(node, "input")[0];
  box.listeners.change[0]({ target: box });
  box.value = "5";
  box.listeners.change[0]({ target: box });
  box.value = "99";
  box.listeners.change[0]({ target: box });
  box.value = "0";
  box.listeners.change[0]({ target: box });
  assert.deepEqual(asked, [0, 200, 100, 400, 400, 0]);
});

test("a page box with no number goes back to the page it is on", () => {
  const asked = [];
  const node = T.pagerView(
    { offset: 100, limit: 100, matched: 486, shown: 100 },
    (offset) => asked.push(offset),
  );
  const box = byTag(node, "input")[0];
  box.value = "abc";
  box.listeners.change[0]({ target: box });
  assert.deepEqual(asked, []);
  assert.equal(box.value, "2");
});

// --- the screen ------------------------------------------------------------------------------
const runData = () => ({
  id: ID,
  short_id: ID.slice(0, 8),
  document: { name: "county_budget_fy2026.pdf" },
  tables: [info(), info({ index: 1, number: 2, label: "", pages: [43] })],
});

function fakeCtx(over = {}) {
  const calls = [];
  const replaced = [];
  const ctx = {
    calls,
    replaced,
    getJson: async (path, query) => {
      calls.push([path, query]);
      return path.endsWith("/rows") ? rowsData() : runData();
    },
    replace: (route) => replaced.push(route),
    ...over,
  };
  return ctx;
}

const route = (query = {}, table = 0) => ({
  name: "table",
  run: ID,
  table,
  query,
});
const settle = () => new Promise((resolve) => setImmediate(resolve));

test("the screen asks for the run and the first page of rows with the URL's filters", async () => {
  const ctx = fakeCtx();
  const view = await T.show(route({ status: "fuzzy", open: "13.9" }), ctx);
  const rowsCall = ctx.calls.find(([path]) => path.endsWith("/rows"));
  assert.equal(rowsCall[0], `/api/runs/${ID}/tables/0/rows`);
  assert.deepEqual(rowsCall[1], { status: "fuzzy" });
  assert.ok(ctx.calls.some(([path]) => path === `/api/runs/${ID}`));
  assert.equal(view.title, "Table 1 · General Fund Expenditures by Department");
  assert.deepEqual(view.crumbs, [
    { text: "Runs", href: "#/" },
    {
      text: "county_budget_fy2026.pdf",
      sub: ID.slice(0, 8),
      href: `#/run/${ID}`,
    },
    { text: "Table 1 · General Fund Expenditures by Department" },
  ]);
  assert.equal(
    text(byTag(view.content, "h1")[0]),
    "General Fund Expenditures by Department",
  );
  assert.equal(byClass(view.content, "fchip").length, 7);
  assert.equal(byTag(view.content, "tbody")[0].children.length, 2);
  assert.ok(
    attr(byTag(byTag(view.content, "tbody")[0], "tr")[1], "class")
      .split(" ")
      .includes("open"),
  );
});

test("a table without a label is 'Table N' in the crumbs too", async () => {
  const ctx = fakeCtx();
  const view = await T.show(route({}, 1), ctx);
  assert.equal(view.crumbs[2].text, "Table 2");
});

test("a table that does not exist is a failure the app can show", async () => {
  const ctx = fakeCtx({
    getJson: async (path) => {
      if (path.endsWith("/rows")) throw new Error("no such table");
      return runData();
    },
  });
  await assert.rejects(() => T.show(route({}, 7), ctx), /no such table/);
});

test("a filter change updates the URL and asks again; the screen shows the new rows", async () => {
  const ctx = fakeCtx();
  const view = await T.show(route(), ctx);
  ctx.getJson = async (path, query) => {
    ctx.calls.push([path, query]);
    return rowsData({ matched: 5, rows: [rowData()] });
  };
  click(byClass(view.content, "fchip")[1]);
  await settle();
  assert.deepEqual(ctx.replaced.at(-1), {
    name: "table",
    run: ID,
    table: 0,
    query: { status: "fuzzy" },
  });
  assert.deepEqual(ctx.calls.at(-1), [
    `/api/runs/${ID}/tables/0/rows`,
    { status: "fuzzy" },
  ]);
  assert.equal(
    text(byClass(view.content, "matches")[0]),
    "5 of 1,214 rows match",
  );
  assert.equal(byTag(byTag(view.content, "tbody")[0], "tr").length, 1);
  assert.equal(attr(byClass(view.content, "fchip")[1], "aria-pressed"), "true");
  assert.equal(text(byClass(view.content, "btn")[1]), "Download 5 rows as CSV");
});

test("clicking a heading sorts, and paging asks for the next rows; the open row stays in the URL", async () => {
  const ctx = fakeCtx();
  const view = await T.show(route({ open: "13.9" }), ctx);
  click(byTag(byTag(view.content, "thead")[0], "button")[2]);
  await settle();
  assert.deepEqual(ctx.replaced.at(-1).query, {
    sort: "Department",
    open: "13.9",
  });
  click(byTag(byClass(view.content, "pager")[0], "button")[1]);
  await settle();
  assert.deepEqual(ctx.replaced.at(-1).query, {
    sort: "Department",
    offset: "100",
    open: "13.9",
  });
  assert.deepEqual(ctx.calls.at(-1)[1], { sort: "Department", offset: "100" });
});

test("only the newest answer is drawn", async () => {
  const ctx = fakeCtx();
  const view = await T.show(route(), ctx);
  const waiting = [];
  ctx.getJson = (path, query) =>
    new Promise((resolve) =>
      waiting.push(() =>
        resolve(
          rowsData({ matched: query.status === "fuzzy" ? 11 : 22, rows: [] }),
        ),
      ),
    );
  click(byClass(view.content, "fchip")[1]);
  click(byClass(view.content, "fchip")[2]);
  waiting[1]();
  await settle();
  waiting[0]();
  await settle();
  assert.equal(
    text(byClass(view.content, "matches")[0]),
    "22 of 1,214 rows match",
  );
});

test("a failed update is an alert in place of the rows; the filters stay", async () => {
  const ctx = fakeCtx();
  const view = await T.show(route(), ctx);
  ctx.getJson = async () => {
    throw new Error("Could not reach the review server.");
  };
  click(byClass(view.content, "fchip")[1]);
  await settle();
  const alert = byClass(view.content, "alert")[0];
  assert.equal(attr(alert, "role"), "alert");
  assert.match(text(alert), /Could not reach the review server\./);
  assert.equal(byClass(view.content, "fchip").length, 7);
});

test("one screen's worth of untrusted text stays text", async () => {
  const data = rowsData();
  data.rows[0].cells[0].value = PAYLOAD;
  const ctx = fakeCtx({
    getJson: async (path) =>
      path.endsWith("/rows")
        ? data
        : { ...runData(), tables: [info({ label: PAYLOAD })] },
  });
  const view = await T.show(route(), ctx);
  noImages(view.content);
  assert.ok(text(view.content).includes(PAYLOAD));
  assert.ok(view.crumbs[2].text.includes(PAYLOAD));
});
