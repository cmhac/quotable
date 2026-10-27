import assert from "node:assert/strict";
import { beforeEach, test } from "node:test";

import { byClass, byTag, findAll, installDom } from "./fake_dom.mjs";

installDom();
const STATIC = "../../../quotable/review/static/";
const Q = await import(`${STATIC}queue.js`);

const ID = "7f3a29c15d0e4b8a9e210c6f3b7d12aa";

function words(node) {
  if (node.nodeType === 3) return node.data;
  return node.childNodes.map(words).join(" ");
}
const text = (node) => words(node).replace(/\s+/g, " ").trim();
const click = (node, event = {}) =>
  node.listeners.click[0]({ preventDefault() {}, ...event });
const change = (node, value) => {
  node.value = value;
  (node.listeners.change ?? node.listeners.input)[0]({ target: node });
};
const settle = () => new Promise((resolve) => setImmediate(resolve));

function memory() {
  const store = {};
  return {
    store,
    getItem: (k) => store[k] ?? null,
    setItem: (k, v) => (store[k] = v),
  };
}

// --- settings ----------------------------------------------------------------------------------
test("no query gives the defaults: all flagged statuses, review all, 95%", () => {
  assert.deepEqual(Q.parseSettings({}), {
    statuses: ["fuzzy", "misplaced", "ungrounded", "untokenized"],
    run: "",
    table: "",
    column: "",
    extra_fields: true,
    mode: "all",
    sample_size: 100,
    confidence: 95,
    margin: 8,
    seed: 1,
  });
});

test("every setting is read from the query, and bad values fall back", () => {
  const s = Q.parseSettings({
    statuses: "exact,fuzzy,nonsense",
    run: ID,
    table: "2",
    column: "Amount",
    extra_fields: "0",
    mode: "sample",
    sample_size: "120",
    confidence: "99",
    margin: "5.5",
    seed: "42",
  });
  assert.deepEqual(s.statuses, ["fuzzy", "exact"]);
  assert.equal(s.run, ID);
  assert.equal(s.table, "2");
  assert.equal(s.column, "Amount");
  assert.equal(s.extra_fields, false);
  assert.equal(s.mode, "sample");
  assert.equal(s.sample_size, 120);
  assert.equal(s.confidence, 99);
  assert.equal(s.margin, 5.5);
  assert.equal(s.seed, 42);
  const bad = Q.parseSettings({
    mode: "x",
    sample_size: "-3",
    confidence: "50",
    margin: "0",
    seed: "abc",
    table: "x",
  });
  assert.equal(bad.mode, "all");
  assert.equal(bad.sample_size, 100);
  assert.equal(bad.confidence, 95);
  assert.equal(bad.margin, 8);
  assert.equal(bad.seed, 1);
  assert.equal(bad.table, "");
});

test("the query has every setting, so the same words ask the same queue", () => {
  const s = Q.parseSettings({ run: ID, mode: "sample", seed: "7" });
  const query = Q.settingsQuery(s);
  assert.equal(query.statuses, "fuzzy,misplaced,ungrounded,untokenized");
  assert.equal(query.run, ID);
  assert.equal(query.extra_fields, "1");
  assert.equal(query.mode, "sample");
  assert.equal(query.seed, "7");
  assert.equal(query.table, undefined);
  assert.deepEqual(Q.parseSettings(query), s);
});

test("a cell in a queue carries the queue's settings and says it is in one", () => {
  const query = Q.queueRouteQuery(Q.parseSettings({ mode: "sample" }));
  assert.equal(query.queue, "1");
  assert.equal(query.mode, "sample");
  assert.equal(Q.inQueue(query), true);
  assert.equal(Q.inQueue({ status: "fuzzy" }), false);
});

test("the URL wins over what is kept, and what is kept wins over the defaults", () => {
  const storage = memory();
  Q.saveSettings(
    storage,
    Q.parseSettings({ mode: "sample", seed: "9", run: ID }),
  );
  assert.equal(Q.loadSettings({}, storage).mode, "sample");
  assert.equal(Q.loadSettings({}, storage).seed, 9);
  assert.equal(Q.loadSettings({}, storage).run, "", "the run is not kept");
  assert.equal(Q.loadSettings({ mode: "all" }, storage).mode, "all");
  assert.equal(Q.loadSettings({ run: ID }, storage).run, ID);
  assert.equal(Q.loadSettings({ run: ID }, storage).mode, "sample");
  assert.equal(Q.loadSettings({}, null).mode, "all");
  assert.equal(
    Q.loadSettings(
      {},
      {
        getItem: () => {
          throw new Error("blocked");
        },
      },
    ).mode,
    "all",
  );
});

test("a new seed is a different whole number", () => {
  const seed = Q.newSeed(() => 0.5);
  assert.ok(Number.isInteger(seed) && seed > 0);
  assert.notEqual(
    Q.newSeed(() => 0.1),
    Q.newSeed(() => 0.9),
  );
});

// --- the numbers as the type board says --------------------------------------------------------
test("shares one decimal, margins as points, intervals as a range", () => {
  assert.equal(Q.percent(0.1714), "17.1%");
  assert.equal(Q.percent(0), "0.0%");
  assert.equal(Q.points(0.0871), "±8.7 pts");
  assert.equal(Q.range([0.081, 0.327]), "8.1–32.7%");
  assert.equal(Q.estimate(316.4), "≈316");
});

function stats(over = {}) {
  return {
    confidence: 95,
    population: 1846,
    sample: 120,
    reviewed: 37,
    judged: 35,
    unsure: 2,
    changed: 6,
    share: 6 / 35,
    interval: [0.081, 0.327],
    estimated: 316.4,
    estimated_interval: [150, 603],
    margin_before: 0.0894,
    correction_before: 0.9667,
    margin_so_far: 0.1271,
    correction_so_far: 0.9908,
    by_status: [
      {
        status: "fuzzy",
        population: 1000,
        sampled: 60,
        reviewed: 20,
        judged: 19,
        changed: 2,
        share: 2 / 19,
      },
      {
        status: "ungrounded",
        population: 846,
        sampled: 60,
        reviewed: 17,
        judged: 16,
        changed: 4,
        share: 0.25,
      },
    ],
    total: {
      status: "All",
      population: 1846,
      sampled: 120,
      reviewed: 37,
      judged: 35,
      changed: 6,
      share: 6 / 35,
    },
    categories: [
      ["misspelling", 4],
      ["wrong_number", 2],
    ],
    ...over,
  };
}

test("the headline: the share, 'n of m', the interval and the estimate", () => {
  const t = text(Q.headlineView(stats()));
  assert.match(t, /17\.1%/);
  assert.match(t, /6 of 35/);
  assert.match(t, /95% CI 8\.1–32\.7%/);
  assert.match(t, /≈316 \(150 – 603\) of 1,846/);
});

test("with nothing judged the headline says so and shows no numbers it cannot have", () => {
  const t = text(
    Q.headlineView(
      stats({
        judged: 0,
        changed: 0,
        share: null,
        interval: null,
        estimated: null,
        estimated_interval: null,
        reviewed: 0,
        unsure: 0,
      }),
    ),
  );
  assert.match(t, /No cells judged yet/);
  assert.ok(!/NaN|null|undefined/.test(t));
});

test("the interval chart has a text equivalent and a 0–50% axis, 0–100% past 50%", () => {
  const chart = Q.chartView(stats());
  assert.equal(chart.getAttribute("role"), "img");
  assert.match(chart.getAttribute("aria-label"), /17\.1%.*8\.1–32\.7%/);
  assert.equal(Q.axisMax([0.081, 0.327]), 0.5);
  assert.equal(Q.axisMax([0.3, 0.62]), 1);
  const wide = Q.chartView(stats({ share: 0.4, interval: [0.3, 0.7] }));
  assert.match(text(wide), /100%/);
});

test("no chart without an interval", () => {
  assert.equal(Q.chartView(stats({ share: null, interval: null })), null);
});

test("counts: population, sample, reviewed with the can't tells", () => {
  const t = text(Q.countsView(stats()));
  assert.match(t, /1,846/);
  assert.match(t, /120/);
  assert.match(t, /35 judged · 2 can’t tell/);
});

test("the two margin tiles write the correction out", () => {
  const tiles = byClass(Q.marginsView(stats()), "tile");
  assert.equal(tiles.length, 2);
  assert.match(text(tiles[0]), /Before reviewing/);
  assert.match(text(tiles[0]), /±8\.9 pts/);
  assert.match(text(tiles[0]), /p = 0\.5/);
  assert.match(text(tiles[0]), /n = 120/);
  assert.match(text(tiles[0]), /0\.967/);
  assert.match(text(tiles[1]), /So far/);
  assert.match(text(tiles[1]), /±12\.7 pts/);
  assert.match(text(tiles[1]), /p = 0\.171/);
  assert.match(text(tiles[1]), /n = 35/);
});

test("the margin so far waits for a judged cell", () => {
  const tiles = byClass(
    Q.marginsView(stats({ margin_so_far: null, share: null })),
    "tile",
  );
  assert.match(text(tiles[1]), /—/);
});

test("by status: a line each, the All line, and the note on can't tell", () => {
  const node = Q.byStatusView(stats());
  const rows = byTag(node, "tbody")[0].children;
  assert.equal(rows.length, 3);
  assert.match(text(rows[0]), /fuzzy 1,000 60 20 2 10\.5%/);
  assert.match(text(rows[2]), /All 1,846 120 37 6 17\.1%/);
  assert.match(text(node), /2 can’t tell verdicts are left out/);
});

test("a status with nothing judged has a dash for its share", () => {
  const node = Q.byStatusView(
    stats({
      by_status: [
        {
          status: "fuzzy",
          population: 5,
          sampled: 5,
          reviewed: 0,
          judged: 0,
          changed: 0,
          share: null,
        },
      ],
    }),
  );
  assert.match(text(byTag(node, "tbody")[0].children[0]), /—/);
});

test("categories: one bar each, most first, and the note on verdicts.jsonl", () => {
  const node = Q.categoriesView(stats());
  const bars = byClass(node, "cat-row");
  assert.equal(bars.length, 2);
  assert.match(text(bars[0]), /misspelling 4/);
  assert.match(text(node), /\.quotable\/review\/verdicts\.jsonl/);
  assert.equal(Q.categoriesView(stats({ categories: [] })), null);
});

// --- cell links --------------------------------------------------------------------------------
test("a queue item opens its cell; an extra field opens row 1 of its printing page", () => {
  const settings = Q.parseSettings({ mode: "sample" });
  const cellItem = {
    run: ID,
    table: 1,
    page: 3,
    row: 2,
    column: "Amount",
    extra: false,
  };
  const route = Q.entryRoute(cellItem, settings);
  assert.deepEqual(route.cell, {
    page: 3,
    row: 2,
    name: "Amount",
    extra: false,
  });
  assert.equal(route.run, ID);
  assert.equal(route.table, 1);
  assert.equal(route.query.queue, "1");
  assert.equal(route.query.mode, "sample");
  const extra = Q.entryRoute(
    { ...cellItem, row: null, column: "fiscal_year", extra: true },
    settings,
  );
  assert.deepEqual(extra.cell, {
    page: 3,
    row: 1,
    name: "fiscal_year",
    extra: true,
  });
});

// --- the screen --------------------------------------------------------------------------------
function queueData(over = {}) {
  return {
    settings: {},
    counts: {
      fuzzy: 1000,
      misplaced: 500,
      ungrounded: 346,
      untokenized: 0,
      exact: 20000,
    },
    matching: 1846,
    suggested: 120,
    queue: [
      {
        run: ID,
        table: 0,
        page: 1,
        row: 1,
        column: "Amount",
        extra: false,
        status: "fuzzy",
        review: { state: "none" },
      },
      {
        run: ID,
        table: 0,
        page: 1,
        row: 2,
        column: "Amount",
        extra: false,
        status: "fuzzy",
        review: { state: "correct" },
      },
    ],
    first_unreviewed: 0,
    stats: stats({ reviewed: 0 }),
    ...over,
  };
}

function runData() {
  return {
    id: ID,
    short_id: ID.slice(0, 8),
    document: { name: "county_budget.pdf" },
    tables: [
      {
        index: 0,
        number: 1,
        label: "General Fund",
        columns: ["Name", "Amount"],
        extra_names: ["fiscal_year"],
        pages: [1, 2],
      },
    ],
  };
}

function fakeCtx(over = {}) {
  const calls = [];
  const replaced = [];
  return {
    calls,
    replaced,
    storage: memory(),
    getJson: async (path, query) => {
      calls.push([path, query]);
      return path === "/api/queue" ? queueData() : runData();
    },
    replace: (route) => replaced.push(route),
    ...over,
  };
}

const route = (query = {}) => ({ name: "queue", query });

test("the screen asks for the queue with the settings of the URL and the run for the scope", async () => {
  const ctx = fakeCtx();
  const view = await Q.show(route({ run: ID, mode: "sample", seed: "5" }), ctx);
  const queueCall = ctx.calls.find(([p]) => p === "/api/queue");
  assert.equal(queueCall[1].run, ID);
  assert.equal(queueCall[1].mode, "sample");
  assert.equal(queueCall[1].seed, "5");
  assert.ok(ctx.calls.some(([p]) => p === `/api/runs/${ID}`));
  assert.equal(view.title, "Review");
  assert.deepEqual(
    view.crumbs.map((c) => c.text),
    ["Runs", "county_budget.pdf", "Review"],
  );
});

test("without a run there is no run to ask for and the crumbs are Runs / Review", async () => {
  const ctx = fakeCtx();
  const view = await Q.show(route(), ctx);
  assert.ok(!ctx.calls.some(([p]) => p.startsWith("/api/runs/")));
  assert.deepEqual(
    view.crumbs.map((c) => c.text),
    ["Runs", "Review"],
  );
});

test("the statuses: a box each with its badge and count, exact apart and off", async () => {
  const { content } = await Q.show(route({ run: ID }), fakeCtx());
  const boxes = byTag(byClass(content, "statuses")[0], "input");
  assert.equal(boxes.length, 5);
  assert.deepEqual(
    boxes.map((b) => b.getAttribute("checked")),
    ["", "", "", "", null],
  );
  assert.match(text(byClass(content, "statuses")[0]), /fuzzy 1,000/);
  assert.match(text(byClass(content, "statuses")[0]), /exact 20,000/);
  assert.match(
    text(content),
    /add to estimate the error rate of cells that passed/,
  );
});

test("the count of matching cells is large and says 'flagged' unless exact is on", async () => {
  const ctx = fakeCtx();
  const first = await Q.show(route({ run: ID }), ctx);
  assert.match(
    text(byClass(first.content, "matching")[0]),
    /1,846 flagged cells match/,
  );
  const withExact = await Q.show(
    route({ run: ID, statuses: "fuzzy,exact" }),
    ctx,
  );
  assert.match(
    text(byClass(withExact.content, "matching")[0]),
    /1,846 cells match/,
  );
});

test("one matching cell is singular", async () => {
  const ctx = fakeCtx({
    getJson: async (path) =>
      path === "/api/queue" ? queueData({ matching: 1 }) : runData(),
  });
  const { content } = await Q.show(route({ run: ID }), ctx);
  assert.match(text(byClass(content, "matching")[0]), /1 flagged cell matches/);
});

test("toggling a status asks again, updates the URL and keeps the settings", async () => {
  const ctx = fakeCtx();
  const { content } = await Q.show(route({ run: ID }), ctx);
  const box = byTag(byClass(content, "statuses")[0], "input")[0];
  box.listeners.change[0]({ target: { checked: false } });
  await settle();
  const last = ctx.replaced.at(-1);
  assert.equal(last.name, "queue");
  assert.ok(!last.query.statuses.split(",").includes("fuzzy"));
  assert.equal(ctx.calls.filter(([p]) => p === "/api/queue").length, 2);
  assert.equal(
    JSON.parse(ctx.storage.store["quotable.review.queue"]).statuses.includes(
      "fuzzy",
    ),
    false,
  );
});

test("sampling: review all, or a sample with a size, a confidence, a margin and a seed", async () => {
  const ctx = fakeCtx();
  const { content } = await Q.show(
    route({ run: ID, mode: "sample", sample_size: "60" }),
    ctx,
  );
  const t = text(byClass(content, "sampling")[0]);
  assert.match(t, /Review all 1,846/);
  assert.match(t, /Random sample/);
  assert.match(t, /80%/);
  assert.match(t, /99%/);
  assert.match(t, /suggests 120 cells/);
  const radios = byTag(byClass(content, "confidence")[0], "input");
  assert.equal(radios.length, 4);
  assert.equal(radios[2].getAttribute("checked"), "");
  const [slider, numberBox] = ["range", "number"].map(
    (type) =>
      findAll(
        content,
        (e) =>
          e.tagName === "INPUT" &&
          e.getAttribute("type") === type &&
          e.getAttribute("name") === "sample_size",
      )[0],
  );
  assert.equal(slider.value, "60");
  assert.equal(numberBox.value, "60");
});

test("the slider and the number box stay in step", async () => {
  const ctx = fakeCtx();
  const { content } = await Q.show(route({ run: ID, mode: "sample" }), ctx);
  const size = (type) =>
    findAll(
      content,
      (e) =>
        e.tagName === "INPUT" &&
        e.getAttribute("type") === type &&
        e.getAttribute("name") === "sample_size",
    )[0];
  change(size("range"), "300");
  await settle();
  assert.equal(size("number").value, "300");
  assert.equal(size("range").value, "300");
  assert.equal(ctx.replaced.at(-1).query.sample_size, "300");
});

test("New seed asks for another sample", async () => {
  const ctx = fakeCtx();
  const { content } = await Q.show(
    route({ run: ID, mode: "sample", seed: "1" }),
    ctx,
  );
  const button = byTag(content, "button").find((b) => text(b) === "New seed");
  click(button);
  await settle();
  assert.notEqual(ctx.replaced.at(-1).query.seed, "1");
});

test("Start review opens the first unreviewed cell of the queue", async () => {
  const { content } = await Q.show(route({ run: ID }), fakeCtx());
  const start = byClass(content, "start")[0];
  assert.equal(text(start), "Start review");
  assert.match(
    start.getAttribute("href"),
    new RegExp(`^#/run/${ID}/table/0/cell/1/1/Amount\\?`),
  );
  assert.match(start.getAttribute("href"), /queue=1/);
});

test("once a verdict is saved it says Resume, and with nothing left it is off", async () => {
  const resumed = await Q.show(
    route({ run: ID }),
    fakeCtx({
      getJson: async (path) =>
        path === "/api/queue"
          ? queueData({ first_unreviewed: 1, stats: stats() })
          : runData(),
    }),
  );
  assert.equal(text(byClass(resumed.content, "start")[0]), "Resume review");
  const done = await Q.show(
    route({ run: ID }),
    fakeCtx({
      getJson: async (path) =>
        path === "/api/queue"
          ? queueData({ first_unreviewed: null })
          : runData(),
    }),
  );
  assert.equal(
    byClass(done.content, "start")[0].getAttribute("aria-disabled"),
    "true",
  );
  const none = await Q.show(
    route({ run: ID }),
    fakeCtx({
      getJson: async (path) =>
        path === "/api/queue"
          ? queueData({ queue: [], matching: 0, first_unreviewed: null })
          : runData(),
    }),
  );
  assert.equal(
    byClass(none.content, "start")[0].getAttribute("aria-disabled"),
    "true",
  );
});

test("the statistics sit beside the settings", async () => {
  const { content } = await Q.show(route({ run: ID }), fakeCtx());
  const t = text(content);
  assert.match(t, /How good is this extraction\?/);
  assert.match(t, /Updates after each verdict/);
  assert.match(t, /6 of 35/);
  assert.match(t, /Error categories/);
});

test("a failed update is an alert and the settings stay", async () => {
  let fail = false;
  const ctx = fakeCtx({
    getJson: async (path) => {
      if (fail) throw new Error("boom");
      return path === "/api/queue" ? queueData() : runData();
    },
  });
  const { content } = await Q.show(route({ run: ID }), ctx);
  fail = true;
  const box = byTag(byClass(content, "statuses")[0], "input")[0];
  box.listeners.change[0]({ target: { checked: false } });
  await settle();
  assert.match(
    text(byClass(content, "queue-results")[0]),
    /could not be loaded/i,
  );
});
