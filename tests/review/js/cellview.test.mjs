import assert from "node:assert/strict";
import { test } from "node:test";

import { byClass, byTag, findAll, installDom } from "./fake_dom.mjs";

installDom();
const STATIC = "../../../quotable/review/static/";
const V = await import(`${STATIC}cellview.js`);

const PAYLOAD = "<img src=x onerror=alert(1)>";

function words(node) {
  if (node.nodeType === 3) return node.data;
  return node.childNodes.map(words).join(" ");
}
const text = (node) => words(node).replace(/\s+/g, " ").trim();
const ref = (page, row, name = "Amount", extra = false) => ({
  page,
  row,
  name,
  extra,
});

function cell(over = {}) {
  return {
    run: "abc",
    table: 0,
    kind: "cell",
    page: 3,
    row: 2,
    name: "Amount",
    status: "fuzzy",
    explanation: "The value is on the page with small differences.",
    value: "1,204",
    matched_text: "1,294",
    coverage: 0.5,
    density: 0.123,
    places: 3,
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
      {
        key: "fiscal_year",
        name: "fiscal_year",
        extra: true,
        value: "FY2026",
        status: "exact",
        state: "none",
        selected: false,
      },
    ],
    proposal: null,
    ocr: false,
    merge: null,
    extra: null,
    nav: {
      n: 4,
      of: 20,
      previous: ref(3, 1),
      next: ref(3, 4),
      previous_row: ref(3, 1),
      next_row: ref(3, 3),
    },
    ...over,
  };
}

const href = (target) => `#/go/${target.page}/${target.row}`;

test("the heading says where the cell is and gives the five moves with their keys", () => {
  const node = V.headingView(cell(), href);
  assert.match(text(byTag(node, "h2")[0]), /^Cell 4 of 20$/);
  assert.match(text(node), /Amount/);
  assert.match(text(node), /page 3/);
  assert.match(text(node), /row 2/);
  const moves = findAll(node, (e) =>
    (e.attributes.class ?? "").split(" ").includes("move"),
  );
  assert.deepEqual(
    moves.map((m) => text(m)),
    [
      "K Previous cell",
      "J Next cell",
      "[ Previous row",
      "] Next row",
      "N Next unreviewed",
    ],
  );
  assert.equal(moves[0].getAttribute("href"), "#/go/3/1");
  assert.equal(moves[1].getAttribute("href"), "#/go/3/4");
});

test("a move with nowhere to go is switched off, and next unreviewed waits for a queue", () => {
  const c = cell();
  c.nav = { ...c.nav, previous: null, next_row: null };
  const moves = findAll(V.headingView(c, href), (e) =>
    (e.attributes.class ?? "").split(" ").includes("move"),
  );
  assert.equal(moves[0].getAttribute("aria-disabled"), "true");
  assert.equal(moves[0].getAttribute("href"), null);
  assert.equal(moves[3].getAttribute("aria-disabled"), "true");
  assert.equal(moves[4].getAttribute("aria-disabled"), "true");
  const c2 = cell();
  c2.nav = { ...c2.nav, next_unreviewed: ref(9, 9) };
  const again = findAll(V.headingView(c2, href), (e) =>
    (e.attributes.class ?? "").split(" ").includes("move"),
  );
  assert.equal(again[4].getAttribute("href"), "#/go/9/9");
});

test("a cell outside the filter has no position", () => {
  const c = cell();
  c.nav = { ...c.nav, n: null };
  assert.equal(text(byTag(V.headingView(c, href), "h2")[0]), "Cell");
});

test("the status badge comes with its sentence", () => {
  const node = V.statusView(cell());
  assert.match(text(node), /fuzzy/);
  assert.match(text(node), /small differences/);
});

test("the value card: extracted, matched, coverage, density and places", () => {
  const node = V.valueCard(cell());
  const t = text(node);
  assert.match(t, /Extracted 1,204/);
  assert.match(t, /Matched 1,294/);
  assert.match(t, /Coverage 0\.50/);
  assert.match(t, /Density 0\.12/);
  assert.match(t, /Places found 3/);
});

test("nothing matched means no Matched line, and a missing density is a dash", () => {
  const node = V.valueCard(
    cell({ matched_text: null, density: null, coverage: 0, places: 0 }),
  );
  assert.ok(!/Matched/.test(text(node)));
  assert.match(text(node), /Density —/);
});

test("values are text, never markup", () => {
  const node = V.valueCard(cell({ value: PAYLOAD, matched_text: PAYLOAD }));
  assert.equal(findAll(node, (e) => e.tagName === "IMG").length, 0);
  assert.ok(text(node).includes(PAYLOAD));
});

test("the row table marks the selected cell and the extra fields, and badges what is not exact", () => {
  const node = V.rowTable(cell());
  const heads = byTag(node, "th").map(text);
  assert.deepEqual(heads, ["Name", "Amount", "fiscal_year extra"]);
  const cells = byTag(node, "td");
  assert.equal(cells.length, 3);
  assert.ok(cells[1].attributes.class.split(" ").includes("selected"));
  assert.ok(!cells[0].attributes.class?.split(" ").includes("selected"));
  assert.equal(byClass(cells[0], "badge").length, 0);
  assert.equal(byClass(cells[1], "badge").length, 1);
});

test("a long value is cut with an ellipsis but keeps its full text as the title", () => {
  const long = "x".repeat(200);
  const c = cell();
  c.row_cells[0].value = long;
  const first = byTag(V.rowTable(c), "td")[0];
  const shown = text(byClass(first, "value")[0]);
  assert.ok(shown.endsWith("…"));
  assert.ok(shown.length < 60);
  assert.equal(byClass(first, "value")[0].getAttribute("title"), long);
});

test("there are no sections when none applies", () => {
  assert.deepEqual(V.sections(cell()), []);
});

test("the recheck history shows the outcome in its summary", () => {
  const c = cell({
    proposal: {
      page: 3,
      row: 2,
      column: "Amount",
      original: "1,204",
      proposed: "1,294",
      status_before: "fuzzy",
      status_after: "exact",
      outcome: "accepted",
    },
  });
  const [section] = V.sections(c);
  assert.equal(section.tagName, "DETAILS");
  assert.match(text(byTag(section, "summary")[0]), /Recheck history/);
  assert.match(text(byTag(section, "summary")[0]), /accepted/);
  const t = text(section);
  assert.match(t, /1,204/);
  assert.match(t, /1,294/);
  assert.match(t, /fuzzy/);
  assert.match(t, /exact/);
});

test("the OCR section says the page's text came from OCR", () => {
  const [section] = V.sections(cell({ ocr: true }));
  assert.match(text(byTag(section, "summary")[0]), /OCR/);
  assert.match(text(section), /OCR errors/);
});

test("the merge section gives the part's pages, columns and evidence", () => {
  const [section] = V.sections(
    cell({
      merge: {
        pages: [22, 23, 24],
        columns: ["Dept", "Amt"],
        original_column: "Amt",
        evidence: {
          token_sets: [[["dept"], ["department"]]],
          equal_positions: 1,
          max_x_difference: 3.5,
          shapes: ["text", "number"],
          cells: [
            [8, 9],
            [7, 7],
          ],
        },
      },
    }),
  );
  assert.match(text(byTag(section, "summary")[0]), /Merge/);
  const t = text(section);
  assert.match(t, /pp\. 22–24/);
  assert.match(t, /Dept/);
  assert.match(t, /Amt/);
  assert.match(t, /3\.5 pt/);
  assert.match(t, /number/);
});

test("the extra-field section names the printing page and says when it was carried forward", () => {
  const c = cell({
    kind: "extra",
    name: "fiscal_year",
    extra: {
      name: "fiscal_year",
      source_page: 2,
      carried: true,
      change: { original: "FY2025", new: "FY2026" },
    },
  });
  const [section] = V.sections(c);
  assert.match(text(byTag(section, "summary")[0]), /Extra field/);
  const t = text(section);
  assert.match(t, /p\. 2/);
  assert.match(t, /carried forward/i);
  assert.match(t, /FY2025/);
  assert.match(t, /FY2026/);
});

test("the whole cell view in order: heading, status, value, row, then the sections", () => {
  const node = V.cellView(cell({ ocr: true }), href);
  const order = ["Cell 4 of 20", "fuzzy", "Extracted", "Row 2", "OCR"];
  let at = 0;
  const t = text(node);
  for (const part of order) {
    const found = t.indexOf(part, at);
    assert.ok(found >= at, `${part} after ${at}`);
    at = found;
  }
});
