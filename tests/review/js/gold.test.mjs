import assert from "node:assert/strict";
import { test } from "node:test";

import { byClass, byTag, findAll, installDom } from "./fake_dom.mjs";

installDom();
const STATIC = "../../../quotable/review/static/";
const gold = await import(`${STATIC}gold.js`);
const { hashFor, parseHash } = await import(`${STATIC}route.js`);

const SHA = "a".repeat(64);
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

const counts = (over = {}) => ({
  cells: 10,
  hits: { exact: 8, normal: 9, fuzzy: 10 },
  missed: 1,
  extra: 0,
  cells_correct: 9,
  gold_rows: 4,
  pred_rows: 3,
  matched_rows: 3,
  rows: 4,
  rows_correct: 3,
  ...over,
});

const report = (over = {}) => ({
  runs: { [SHA]: { id: "r".repeat(32), started: "2026-11-10T00:00:00Z", model: "m", name: "doc.pdf" } },
  not_scored: [],
  notes: [],
  benchmark: "normal",
  total: counts(),
  units: [
    { name: "cell", correct: 9, gold: 10, extracted: 9, either: 10, recall: 0.9, precision: 1, accuracy: 0.9 },
    { name: "row", correct: 3, gold: 4, extracted: 3, either: 4, recall: 0.75, precision: 1, accuracy: 0.75 },
    { name: "page", correct: 0, gold: 0, extracted: 0, either: 0, recall: null, precision: null, accuracy: null },
  ],
  documents: [{ sha256: SHA, name: "doc.pdf", pages: 2, counted: 2, correct: 1, counts: counts() }],
  tables: [{ sha256: SHA, name: "doc.pdf", index: 0, label: "Table 1", counts: counts() }],
  interval: { share: 0.5, low: 0.2, high: 0.8, confidence: 95, n: 2, sampled: 2, pages: 40 },
  pages: [
    {
      sha256: SHA,
      page: 3,
      pairs: [
        {
          gold: 1,
          extracted: 0,
          label: "Table 1",
          columns: [
            { gold: "Name", extracted: "Name", how: "name" },
            { gold: "Money", extracted: "Funding", how: "values" },
            { gold: "Note", extracted: null, how: "none" },
            { gold: null, extracted: "State", how: "none" },
          ],
        },
      ],
      unmatched_gold: [2],
      unmatched_extracted: [],
    },
  ],
  cells: [
    { document: "doc.pdf", sha256: SHA, page: 3, table: "Table 1", column: "Name", gold_row: 1, gold: "ANN", extracted: "Ann", best: "normal" },
    { document: "doc.pdf", sha256: SHA, page: 3, table: "Table 1", column: "Money", gold_row: 2, gold: "9", extracted: "8", best: "none" },
    { document: "doc.pdf", sha256: SHA, page: 3, table: "Table 1", column: "Name", gold_row: null, gold: "", extracted: PAYLOAD, best: "none" },
  ],
  ...over,
});

test("a document with a usable PDF has a checkbox, one without says why", () => {
  const ok = gold.documentRow({ sha256: SHA, name: "a.pdf", pages: 12, pdf: "ok" }, true, () => {});
  const bad = gold.documentRow({ sha256: SHA, name: "b.pdf", pages: 1, pdf: "missing" }, true, () => {});
  assert.equal(text(ok), "a.pdf 12 pages");
  assert.equal(byTag(ok, "input")[0].getAttribute("disabled") ?? null, null);
  assert.match(text(bad), /PDF missing/);
  assert.equal(byTag(bad, "input")[0].getAttribute("disabled"), "");
});

test("the page list links each page and shows its status and time", () => {
  const list = gold.pageList([
    { sha256: SHA, name: "a.pdf", page: 7, status: "done", seconds: 131 },
    { sha256: SHA, name: "a.pdf", page: 9, status: "new", seconds: null },
  ]);
  const links = byTag(list, "a");
  assert.equal(links[0].getAttribute("href"), `#/gold/page/${SHA}/7`);
  assert.match(text(list), /7 done 2:11/);
  assert.match(text(list), /9 new/);
});

test("the headline table has the three units, their rates and n/a where there is nothing", () => {
  const t = gold.headlineTable(report().units);
  assert.match(text(t), /cell 9 10 9 90.0% 100.0% 90.0%/);
  assert.match(text(t), /page 0 0 0 n\/a n\/a n\/a/);
});

test("the interval line says who it is an estimate for and why cells have none", () => {
  const line = gold.intervalText(report().interval);
  assert.match(line, /50.0% of 2 counted pages, 95% interval 20.0% to 80.0%/);
  assert.match(line, /estimate for this document only/);
  assert.match(line, /not independent/);
  assert.equal(gold.intervalText(null), null);
});

test("an incomplete score says what is left and links the pages", () => {
  const view = gold.incompleteView({
    done: 3,
    total: 5,
    left: [{ sha256: SHA, name: "a.pdf", page: 4 }, { sha256: SHA, name: "a.pdf", page: 9 }],
  });
  assert.match(text(view), /3 of 5 sampled pages are done/);
  assert.equal(byTag(view, "a").filter((a) => a.getAttribute("href").startsWith("#/gold/page/")).length, 2);
  assert.doesNotMatch(text(view), /recall/);
});

test("the report shows runs, headline, definitions, interval and the table lines", () => {
  const view = gold.reportView(report(), {});
  const all = text(view);
  assert.match(all, /doc.pdf: rrrrrrrr · m · 2026-11-10T00:00:00Z/);
  assert.match(all, /recall precision accuracy/);
  assert.match(all, /recall = correct \/ gold/);
  assert.match(all, /Pages correct: 50.0%/);
  assert.match(all, /doc.pdf · Table 1/);
  assert.match(all, /Cell accuracy: exact 80.0%, normal 90.0%, fuzzy 100.0%/);
});

test("every column pairing is listed, with how it was paired", () => {
  const list = gold.pairingList(report().pages, { [SHA]: "doc.pdf" });
  const all = text(list);
  assert.match(all, /Name = Name \[name\]/);
  assert.match(all, /Money = Funding \[values\]/);
  assert.match(all, /Note \(no partner\)/);
  assert.match(all, /\(extra column State\)/);
  assert.match(all, /gold table 2: no extracted table matched it/);
});

test("the differences list filters by match level and links the page", () => {
  const all = gold.differenceRows(report().cells, "all");
  assert.equal(all.length, 3);
  assert.equal(gold.differenceRows(report().cells, "normal").length, 1);
  assert.equal(gold.differenceRows(report().cells, "none").length, 2);
  const table = gold.differencesTable(report().cells, "normal");
  assert.equal(byTag(table, "a")[0].getAttribute("href"), `#/gold/page/${SHA}/3`);
  assert.match(text(table), /ANN Ann normal/);
});

test("a value that looks like markup is shown as text and no element comes from it", () => {
  const table = gold.differencesTable(report().cells, "all");
  assert.match(text(table), /<img src=x onerror=alert\(1\)>/);
  noImages(table);
  const view = gold.reportView(report({ not_scored: [PAYLOAD] }), {});
  noImages(view);
});

test("a missing second document is listed as not scored", () => {
  const view = gold.reportView(report({ not_scored: ["second.pdf"], notes: ["a note"] }), {});
  assert.match(text(view), /Not scored \(no usable run\): second.pdf/);
  assert.match(text(view), /a note/);
});

test("the csv links carry the chosen runs", () => {
  const view = gold.reportView(report(), { run: ["abc", "d e"] });
  const hrefs = byTag(view, "a").map((a) => a.getAttribute("href"));
  assert.ok(hrefs.includes("/api/gold/score.csv?kind=cells&run=abc&run=d%20e"));
  assert.ok(hrefs.includes("/api/gold/score.csv?kind=pages&run=abc&run=d%20e"));
});

test("the gold screens have hash routes that round-trip", () => {
  assert.deepEqual(parseHash("#/gold"), { name: "gold", query: {} });
  assert.deepEqual(parseHash("#/gold/score?run=abc"), { name: "goldscore", query: { run: "abc" } });
  const page = parseHash(`#/gold/page/${SHA}/12`);
  assert.deepEqual(page, { name: "goldpage", sha: SHA, page: 12, query: {} });
  assert.equal(hashFor(page), `#/gold/page/${SHA}/12`);
  assert.equal(hashFor({ name: "gold" }), "#/gold");
  assert.equal(hashFor({ name: "goldscore" }), "#/gold/score");
  assert.equal(parseHash("#/gold/page/nothex/12").name, "notfound");
  assert.equal(parseHash(`#/gold/page/${SHA}/x`).name, "notfound");
  assert.equal(parseHash("#/gold/other").name, "notfound");
});

test("byClass finds the definitions list", () => {
  const view = gold.reportView(report(), {});
  assert.equal(byClass(view, "gold-definitions").length, 1);
  assert.equal(gold.DEFINITIONS.length, 4);
});

test("each document has a run selector, newest first, set to the run scored", () => {
  const older = "o".repeat(32);
  const r = report({
    choices: {
      [SHA]: [
        { id: "r".repeat(32), started: "2026-11-10T00:00:00Z", model: "m" },
        { id: older, started: "2026-11-09T00:00:00Z", model: "old-model" },
      ],
    },
  });
  const view = gold.runChoices(r, () => {});
  const [select] = byTag(view, "select");
  assert.equal(byTag(select, "option").length, 2);
  assert.equal(select.value, "r".repeat(32));
  assert.match(text(view), /oooooooo · old-model/);
});

test("choosing another run reloads the score with every document's run", () => {
  const older = "o".repeat(32);
  const r = report({ choices: { [SHA]: [{ id: "r".repeat(32), started: "x", model: "m" }, { id: older, started: "y", model: "n" }] } });
  const seen = [];
  const view = gold.runChoices(r, (route) => seen.push(route));
  const [select] = byTag(view, "select");
  select.value = older;
  select.listeners.change[0]();
  assert.deepEqual(seen, [{ name: "goldscore", query: { run: older } }]);
});
