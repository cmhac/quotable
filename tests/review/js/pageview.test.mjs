import assert from "node:assert/strict";
import { test } from "node:test";

import { byClass, byTag, installDom } from "./fake_dom.mjs";

installDom();
const STATIC = "../../../quotable/review/static/";
const P = await import(`${STATIC}pageview.js`);

const SIZE = [612, 792];

function cell(over = {}) {
  return {
    page: 3,
    row: 2,
    name: "Amount",
    kind: "cell",
    status: "fuzzy",
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
      header: { line: 100, bottom: 112, x: { Amount: 140, Name: 40 } },
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
        header: { line: 100, bottom: 112, x: { Amount: 140, Name: 40 } },
        rows: { 1: [170, 190], 2: [195, 215] },
        columns: { Name: [20, 80], Amount: [90, 190] },
      },
    ],
    ...over,
  };
}

const kinds = (boxes) => boxes.map((b) => b.kind);

test("six toggles, the header off by default, the band only on a shared page", () => {
  assert.deepEqual(
    P.HIGHLIGHTS.map((h) => h.key),
    ["matched", "also", "area", "row", "column", "header", "band"],
  );
  assert.deepEqual(P.defaultToggles(), {
    matched: true,
    also: true,
    area: true,
    row: true,
    column: true,
    header: false,
    band: true,
  });
  assert.deepEqual(
    P.shownToggles(false).map((h) => h.key),
    ["matched", "also", "area", "row", "column", "header"],
  );
  assert.equal(P.shownToggles(true).length, 7);
});

test("toggles are kept in storage, and bad storage gives the defaults", () => {
  const store = {};
  const storage = {
    getItem: (k) => store[k] ?? null,
    setItem: (k, v) => (store[k] = v),
  };
  assert.deepEqual(P.loadToggles(storage), P.defaultToggles());
  P.saveToggles(storage, {
    ...P.defaultToggles(),
    header: true,
    matched: false,
  });
  const back = P.loadToggles(storage);
  assert.equal(back.header, true);
  assert.equal(back.matched, false);
  store[Object.keys(store)[0]] = "{not json";
  assert.deepEqual(P.loadToggles(storage), P.defaultToggles());
  assert.deepEqual(
    P.loadToggles({
      getItem: () => {
        throw new Error("blocked");
      },
    }),
    P.defaultToggles(),
  );
});

test("on the cell's page every highlight of the cell is drawn with its label", () => {
  const boxes = P.boxesFor({
    cell: cell(),
    page: 3,
    data: pageData(),
    table: 0,
  });
  assert.deepEqual([...new Set(kinds(boxes))].sort(), [
    "also",
    "area",
    "centre",
    "column",
    "header",
    "matched",
    "row",
  ]);
  const by = Object.fromEntries(boxes.map((b) => [b.kind, b]));
  assert.deepEqual(by.matched.box, [100, 200, 180, 212]);
  assert.equal(by.matched.label, "matched words");
  assert.equal(by.also.label, "also found");
  assert.deepEqual(by.also.box, [300, 400, 380, 412]);
  assert.deepEqual(by.area.box, [90, 195, 190, 215]);
  assert.equal(by.area.label, null);
  assert.deepEqual(by.row.box, [0, 195, 612, 215]);
  assert.equal(by.row.label, "row 2 window");
  assert.deepEqual(by.column.box, [90, 0, 190, 792]);
  assert.equal(by.column.label, "column range");
  assert.equal(by.header?.label, "header · column centres");
});

test("the header box and a mark at each column centre", () => {
  const boxes = P.boxesFor({
    cell: cell(),
    page: 3,
    data: pageData(),
    table: 0,
  });
  const header = boxes.find((b) => b.kind === "header");
  assert.deepEqual(header.box, [0, 100, 612, 112]);
  const marks = boxes.filter((b) => b.kind === "centre");
  assert.equal(marks.length, 2);
  assert.deepEqual(
    marks.map((m) => m.box[0]).sort((a, b) => a - b),
    [40, 140],
  );
  assert.ok(marks.every((m) => m.toggle === "header"));
});

test("a misplaced cell shows its area and the matched words elsewhere together", () => {
  const c = cell({ status: "misplaced" });
  c.highlights.matched = [400, 600, 450, 612];
  const boxes = P.boxesFor({ cell: c, page: 3, data: pageData(), table: 0 });
  assert.ok(kinds(boxes).includes("area"));
  assert.ok(kinds(boxes).includes("matched"));
});

test("an ungrounded cell has no matched box", () => {
  const c = cell({ status: "ungrounded" });
  c.highlights.matched = null;
  c.highlights.candidates = [];
  const boxes = P.boxesFor({ cell: c, page: 3, data: pageData(), table: 0 });
  assert.ok(!kinds(boxes).includes("matched"));
  assert.ok(!kinds(boxes).includes("also"));
  assert.ok(kinds(boxes).includes("area"));
});

test("another page shows only its header and table band", () => {
  const data = pageData({
    page: 4,
    tables: [
      { ...pageData().tables[0], band: [300, 500] },
      { ...pageData().tables[0], index: 1, number: 2, band: [510, 700] },
    ],
  });
  const boxes = P.boxesFor({ cell: cell(), page: 4, data, table: 0 });
  assert.deepEqual([...new Set(kinds(boxes))].sort(), [
    "band",
    "centre",
    "header",
  ]);
  assert.deepEqual(
    boxes.find((b) => b.kind === "band").box,
    [0, 300, 612, 500],
  );
});

test("no band is drawn when the page holds one table", () => {
  const boxes = P.boxesFor({
    cell: cell(),
    page: 3,
    data: pageData(),
    table: 0,
  });
  assert.ok(!kinds(boxes).includes("band"));
});

test("an extra field has no row or column areas of its own", () => {
  const c = cell({ kind: "extra", name: "fiscal_year" });
  c.highlights.row_window = null;
  c.highlights.column_range = null;
  c.highlights.cell_area = null;
  const boxes = P.boxesFor({ cell: c, page: 3, data: pageData(), table: 0 });
  assert.deepEqual(
    kinds(boxes).filter((k) => ["row", "column", "area"].includes(k)),
    [],
  );
  assert.ok(kinds(boxes).includes("matched"));
});

test("toggles hide boxes, and the centre marks follow the header toggle", () => {
  const boxes = P.boxesFor({
    cell: cell(),
    page: 3,
    data: pageData(),
    table: 0,
  });
  const on = { ...P.defaultToggles(), header: true, matched: false };
  const shown = P.visible(boxes, on);
  assert.ok(!kinds(shown).includes("matched"));
  assert.ok(kinds(shown).includes("centre"));
  assert.ok(kinds(shown).includes("header"));
  const off = P.visible(boxes, P.defaultToggles());
  assert.ok(!kinds(off).includes("header"));
  assert.ok(!kinds(off).includes("centre"));
});

test("a box is placed in pixels by the zoom", () => {
  assert.deepEqual(P.place([100, 200, 180, 212], 1.5), {
    left: 150,
    top: 300,
    width: 120,
    height: 18,
  });
  assert.deepEqual(P.place([10, 10, 10, 10], 2), {
    left: 20,
    top: 20,
    width: 2,
    height: 2,
  });
});

test("zoom steps are clamped and read as a percentage", () => {
  assert.equal(P.zoomIn(1), 1.25);
  assert.equal(P.zoomOut(1), 0.75);
  assert.equal(P.zoomOut(0.25), 0.25);
  assert.equal(P.zoomIn(4), 4);
  assert.equal(P.zoomText(1.25), "125%");
  assert.equal(P.zoomText(0.333), "33%");
});

test("fit width takes the room there is, within the limits", () => {
  assert.equal(P.fitZoom(612, 612), 1);
  assert.equal(P.fitZoom(918, 612), 1.5);
  assert.equal(P.fitZoom(10, 612), 0.25);
  assert.equal(P.fitZoom(99999, 612), 4);
  assert.equal(P.fitZoom(0, 612), 1);
});

test("the view scrolls to matched words, else the cell area, else the row window", () => {
  const boxes = P.boxesFor({
    cell: cell(),
    page: 3,
    data: pageData(),
    table: 0,
  });
  assert.deepEqual(P.scrollTarget(boxes).kind, "matched");
  const noMatch = boxes.filter((b) => b.kind !== "matched");
  assert.equal(P.scrollTarget(noMatch).kind, "area");
  const rowOnly = boxes.filter((b) => b.kind === "row");
  assert.equal(P.scrollTarget(rowOnly).kind, "row");
  assert.equal(P.scrollTarget([]), null);
});

test("a point on the page is the cell whose row window and column range hold it", () => {
  const data = pageData();
  assert.deepEqual(P.cellAt(data, 0, 120, 205), { row: 2, name: "Amount" });
  assert.deepEqual(P.cellAt(data, 0, 30, 180), { row: 1, name: "Name" });
  assert.equal(P.cellAt(data, 0, 120, 300), null);
  assert.equal(P.cellAt(data, 0, 5, 205), null);
  assert.equal(P.cellAt(data, 7, 120, 205), null);
});

test("the text layer is one span per word, placed and sized by the zoom", () => {
  const nodes = P.textLayer(
    [
      ["Total", 10, 20, 40, 30],
      ["<b>x</b>", 50, 20, 70, 30],
    ],
    2,
  );
  assert.equal(nodes.length, 2);
  assert.equal(nodes[0].textContent, "Total");
  assert.equal(nodes[1].textContent, "<b>x</b>");
  assert.equal(nodes[0].styles.left, "20px");
  assert.equal(nodes[0].styles.top, "40px");
  assert.equal(nodes[0].styles.width, "60px");
  assert.equal(nodes[0].styles.height, "20px");
});

test("the page surface holds the image, then the layers, and a blank page without an image", () => {
  const withImage = P.surface({
    size: SIZE,
    zoom: 1,
    imageSrc: "/api/runs/abc/pages/3.png",
    alt: "Page 3 of the PDF",
    words: [["Total", 10, 20, 40, 30]],
    boxes: P.boxesFor({ cell: cell(), page: 3, data: pageData(), table: 0 }),
    toggles: P.defaultToggles(),
    textLayer: false,
    onPick: () => {},
  });
  assert.equal(byTag(withImage, "img").length, 1);
  assert.match(byTag(withImage, "img")[0].getAttribute("alt"), /page 3|Page 3/);
  assert.equal(withImage.styles.width, "612px");
  assert.equal(byClass(withImage, "hl").length > 0, true);
  assert.equal(byClass(withImage, "textlayer").length, 0);

  const blank = P.surface({
    size: SIZE,
    zoom: 1,
    imageSrc: null,
    words: [["Total", 10, 20, 40, 30]],
    boxes: [],
    toggles: P.defaultToggles(),
    textLayer: true,
    onPick: () => {},
  });
  assert.equal(byTag(blank, "img").length, 0);
  assert.ok(
    byClass(blank, "blank").length >= 1 ||
      blank.attributes.class.includes("blank"),
  );
  assert.equal(byClass(blank, "textlayer").length, 1);
});
