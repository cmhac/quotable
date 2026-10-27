import assert from "node:assert/strict";
import { test } from "node:test";

import { byClass, byTag, installDom } from "./fake_dom.mjs";

installDom();
const STATIC = "../../../quotable/review/static/";
const B = await import(`${STATIC}queuebar.js`);
const { parseSettings } = await import(`${STATIC}queue.js`);

function words(node) {
  if (node.nodeType === 3) return node.data;
  return node.childNodes.map(words).join(" ");
}
const text = (node) => words(node).replace(/\s+/g, " ").trim();
const ID = "7f3a29c15d0e4b8a9e210c6f3b7d12aa";

const entry = (row, state, over = {}) => ({
  run: ID,
  short_run: ID.slice(0, 8),
  table: 0,
  table_number: 1,
  page: 2,
  row,
  column: "Amount",
  extra: false,
  status: "fuzzy",
  review: { state },
  ...over,
});

function data(over = {}) {
  return {
    queue: [
      entry(1, "correct"),
      entry(2, "changed"),
      entry(3, "unsure"),
      entry(4, "none"),
      entry(5, "stale"),
    ],
    stats: {
      confidence: 95,
      reviewed: 3,
      judged: 2,
      changed: 1,
      share: 0.5,
      interval: [0.095, 0.905],
    },
    ...over,
  };
}
const hrefFor = (item) => `#/go/${item.row}`;

test("the description says what the queue is", () => {
  assert.equal(
    B.describe(
      parseSettings({ mode: "sample", sample_size: "120" }),
      data({ queue: new Array(120).fill(0) }).queue,
    ),
    "Flagged cells · sample of 120",
  );
  assert.equal(
    B.describe(parseSettings({}), new Array(1846).fill(0)),
    "Flagged cells · all 1,846",
  );
  assert.equal(
    B.describe(
      parseSettings({ statuses: "fuzzy,exact" }),
      new Array(3).fill(0),
    ),
    "Cells · all 3",
  );
});

test("a mark is one of five looks; a stale verdict counts as not reviewed", () => {
  assert.equal(B.markState(entry(1, "correct"), false), "correct");
  assert.equal(B.markState(entry(1, "changed"), false), "changed");
  assert.equal(B.markState(entry(1, "unsure"), false), "unsure");
  assert.equal(B.markState(entry(1, "none"), false), "none");
  assert.equal(B.markState(entry(1, "stale"), false), "none");
  assert.equal(B.markState(entry(1, "correct"), true), "current");
});

test("hover text names run, table, page, row, column and status", () => {
  assert.equal(
    B.hoverText(entry(3, "none")),
    `run ${ID.slice(0, 8)}, table 1, page 2, row 3, column Amount, fuzzy`,
  );
  assert.match(
    B.hoverText(entry(null, "none", { extra: true, column: "fiscal_year" })),
    /extra field fiscal_year/,
  );
});

test("the bar: description, edit link, reviewed count and the changed share", () => {
  const node = B.barView({
    data: data(),
    index: 3,
    settings: parseSettings({}),
    hrefFor,
  });
  const t = text(node);
  assert.match(t, /Queue/);
  assert.match(t, /Flagged cells · all 5/);
  assert.match(t, /3 \/ 5 reviewed/);
  assert.match(t, /Changed 50\.0% \(95% CI 9\.5–90\.5%, 1 of 2 judged\)/);
  const edit = byTag(node, "a").find((a) => text(a) === "Edit queue");
  assert.match(edit.getAttribute("href"), /^#\/queue\?/);
});

test("with nothing judged the bar says so", () => {
  const d = data();
  d.stats = {
    ...d.stats,
    judged: 0,
    changed: 0,
    share: null,
    interval: null,
    reviewed: 0,
  };
  assert.match(
    text(
      B.barView({ data: d, index: 0, settings: parseSettings({}), hrefFor }),
    ),
    /No cells judged yet/,
  );
});

test("the strip has a mark per cell, the current one marked, each a link with hover text", () => {
  const node = B.barView({
    data: data(),
    index: 3,
    settings: parseSettings({}),
    hrefFor,
  });
  const marks = byClass(byClass(node, "strip")[0], "mark");
  assert.equal(marks.length, 5);
  assert.deepEqual(
    marks.map((m) =>
      m.attributes.class.split(" ").find((c) => c.startsWith("m-")),
    ),
    ["m-correct", "m-changed", "m-unsure", "m-current", "m-none"],
  );
  assert.equal(marks[3].getAttribute("aria-current"), "true");
  assert.equal(marks[1].getAttribute("href"), "#/go/2");
  assert.match(marks[1].getAttribute("title"), /row 2/);
});

test("the legend names the marks and says how to use them", () => {
  const t = text(
    byClass(
      B.barView({
        data: data(),
        index: 0,
        settings: parseSettings({}),
        hrefFor,
      }),
      "legend",
    )[0],
  );
  for (const part of [
    "correct",
    "changed",
    "can’t tell",
    "not reviewed",
    "current",
    "Hover a mark for run, table, page, row, column, status · click to jump",
  ])
    assert.ok(t.includes(part), part);
});

test("the queue's neighbours and the next unreviewed come from the queue itself", () => {
  const q = data().queue;
  assert.equal(B.neighbour(q, 3, -1), q[2]);
  assert.equal(B.neighbour(q, 3, 1), q[4]);
  assert.equal(B.neighbour(q, 0, -1), null);
  assert.equal(B.neighbour(q, 4, 1), null);
  assert.equal(B.nextUnreviewed(q, 0), q[3]);
  assert.equal(
    B.nextUnreviewed(q, 3),
    q[4],
    "a stale verdict is still to review",
  );
  assert.equal(B.nextUnreviewed(q, 4), q[3], "wraps to the start");
  assert.equal(B.nextUnreviewed([entry(1, "correct")], 0), null);
});

test("a cell is found in the queue by where it is", () => {
  const q = data().queue;
  assert.equal(
    B.indexOf(q, {
      run: ID,
      table: 0,
      page: 2,
      row: 4,
      name: "Amount",
      extra: false,
    }),
    3,
  );
  assert.equal(
    B.indexOf(q, {
      run: ID,
      table: 0,
      page: 2,
      row: 99,
      name: "Amount",
      extra: false,
    }),
    -1,
  );
  const extra = [entry(null, "none", { extra: true, column: "fy", page: 3 })];
  assert.equal(
    B.indexOf(extra, {
      run: ID,
      table: 0,
      page: 3,
      row: 1,
      name: "fy",
      extra: true,
    }),
    0,
  );
});
