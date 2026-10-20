import assert from "node:assert/strict";
import { test } from "node:test";

import { byClass, byTag, findAll, installDom } from "./fake_dom.mjs";

process.env.TZ = "UTC";
installDom();
const STATIC = "../../../quotable/review/static/";
const { header, failureView } = await import(`${STATIC}chrome.js`);
const { introView, groupsView, emptyView } = await import(`${STATIC}runs.js`);
const { runView, pdfAlert } = await import(`${STATIC}run.js`);
const { badge } = await import(`${STATIC}status.js`);

const NOW = new Date("2026-10-20T15:00:00Z");
const PAYLOAD = "<img src=x onerror=alert(1)>";
const ID = "7f3a29c15d0e4b8a9e210c6f3b7d12aa";
const SHA = "9c1e07b3d2aa11bb22cc33dd44ee55ff66778899aabbccddeeff00112233f5a14a7b";

const noImages = (node) => assert.equal(findAll(node, (e) => e.tagName === "IMG").length, 0);

// The words a reader gets: neighbouring elements are separated by a space, text runs on.
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

function runLine(over = {}) {
  return {
    id: ID,
    short_id: ID.slice(0, 8),
    started: "2026-10-20T10:14:00Z",
    ended: "2026-10-20T10:31:00Z",
    model: "claude-sonnet-4-5",
    quotable: "0.1.0",
    tables: 3,
    rows: 1488,
    cells: 7440,
    flagged: { fuzzy: 1102, misplaced: 388, ungrounded: 291, untokenized: 65 },
    flagged_total: 1846,
    ocr_pages: [17, 18],
    cost: { kind: "usd", usd: 4.82 },
    review: { reviewed: 37, flagged: 1846, done: false },
    ...over,
  };
}

function runsData(over = {}) {
  const second = runLine({
    id: "51b08e7d".padEnd(32, "0"),
    short_id: "51b08e7d",
    started: "2026-10-19T16:40:00Z",
    cost: { kind: "free" },
    review: { reviewed: 1846, flagged: 1846, done: true },
  });
  const third = runLine({
    id: "c88e1f02".padEnd(32, "0"),
    short_id: "c88e1f02",
    started: "2026-10-16T14:27:00Z",
    cost: { kind: "unknown" },
    flagged: {},
    flagged_total: 0,
    ocr_pages: [],
    review: { reviewed: 0, flagged: 0, done: false },
  });
  return {
    project: "/p/.quotable",
    total_runs: 4,
    total_documents: 2,
    runs: 4,
    models: ["claude-sonnet-4-5"],
    unreadable: 0,
    documents: [
      {
        name: "county_budget_fy2026.pdf",
        sha256: SHA,
        sha_short: "9c1e…4a7b",
        pages: 62,
        size: 3_800_000,
        runs: [runLine(), second],
      },
      { name: "permits.pdf", sha256: "ab".repeat(32), sha_short: "abab…abab", pages: 214, size: 41_200_000, runs: [third] },
    ],
    ...over,
  };
}

function runData(over = {}) {
  return {
    id: ID,
    short_id: ID.slice(0, 8),
    started: "2026-10-20T14:14:07Z",
    ended: "2026-10-20T14:31:52Z",
    model: "claude-sonnet-4-5",
    quotable: "0.1.0",
    format: 1,
    settings: {
      discovery_pages: 3,
      recheck: true,
      ocr: "auto",
      merge_reworded: true,
      max_requests: 400,
      extra_fields: {
        fields: [{ name: "fiscal_year", description: "Fiscal year printed in the page header", group: null }],
        prompt: "",
        carry_forward: true,
      },
    },
    document: {
      name: "county_budget_fy2026.pdf",
      path: "/Users/you/county/county_budget_fy2026.pdf",
      size: 3_800_000,
      sha256: SHA,
      sha_short: "9c1e…4a7b",
      pages: 62,
    },
    pdf: { status: "ok", path: "/Users/you/county/county_budget_fy2026.pdf" },
    summary: { tables: 3, rows: 1488, cells: 7440, flagged: {}, flagged_total: 1846, ocr_pages: [17, 18] },
    cost: { kind: "usd", usd: 4.82 },
    review: { reviewed: 37, flagged: 1846, done: false },
    tables: [
      {
        index: 0,
        number: 1,
        label: "General Fund Expenditures by Department",
        columns: ["Department", "Fund", "FY2025 Actual"],
        extra_names: ["fiscal_year"],
        pages: [3, 4, 5, 41],
        rows: 1214,
        flagged: { fuzzy: 1 },
        flagged_total: 1512,
        merged: 1,
        ocr_pages: [17, 18],
        note: [
          { kind: "merged", text: "Merged part: pp. 22–24, columns Dept · Fund" },
          { kind: "changes", text: "57 recheck changes accepted" },
        ],
      },
      {
        index: 1,
        number: 2,
        label: "",
        columns: ["Project", "District"],
        extra_names: [],
        pages: [43],
        rows: 236,
        flagged: {},
        flagged_total: 301,
        merged: 0,
        ocr_pages: [],
        note: [],
      },
    ],
    ...over,
  };
}

// --- the header and the failure page ---------------------------------------------------------
test("the header shows the name, the crumbs, the project and the address", () => {
  const node = header({
    crumbs: [{ text: "Runs", href: "#/" }, { text: "a.pdf", sub: "7f3a29c1" }],
    project: "/p/.quotable",
    address: "127.0.0.1:8765",
  });
  assert.equal(text(node), "quotable review Runs / a.pdf · 7f3a29c1 /p/.quotable · 127.0.0.1:8765");
  const [link] = byTag(node, "a");
  assert.equal(link.getAttribute("href"), "#/");
  const current = byClass(node, "current");
  assert.equal(current.length, 1);
  assert.equal(current[0].getAttribute("aria-current"), "page");
});

test("the header shows only the address when there is no project", () => {
  const node = header({ crumbs: [{ text: "Runs" }], address: "127.0.0.1:8765" });
  assert.equal(text(node), "quotable review Runs 127.0.0.1:8765");
});

test("a failure is an alert with the message and a way back", () => {
  const node = failureView(new Error("no such run"));
  assert.equal(byClass(node, "alert")[0].getAttribute("role"), "alert");
  assert.match(text(node), /no such run/);
  assert.equal(byTag(node, "a")[0].getAttribute("href"), "#/");
});

// --- badges ----------------------------------------------------------------------------------
test("a badge is glyph, word and count, never colour alone", () => {
  assert.equal(text(badge("fuzzy", 1102)), "≈ fuzzy 1,102");
  assert.equal(text(badge("exact")), "✓ exact");
  assert.equal(text(badge("not_on_page")), "— not on page");
  assert.equal(text(badge("misplaced")), "⇄ misplaced");
  assert.equal(text(badge("ungrounded")), "× ungrounded");
  assert.equal(text(badge("untokenized")), "# untokenized");
  assert.equal(text(badge("empty")), "∅ empty");
  assert.ok(badge("fuzzy").getAttribute("class").split(" ").includes("s-fuzzy"));
});

// --- the runs list ---------------------------------------------------------------------------
test("the intro counts what is shown", () => {
  assert.equal(
    text(introView(runsData())),
    "4 runs of 2 documents in .quotable/runs/, newest first. Re-runs of the same PDF are grouped.",
  );
  assert.match(text(introView(runsData({ runs: 1, documents: [runsData().documents[1]] }))), /^1 run of 1 document /);
});

test("one group a document, with its facts and run count", () => {
  const node = groupsView(runsData(), NOW);
  const groups = byClass(node, "group");
  assert.equal(groups.length, 2);
  assert.match(text(byClass(groups[0], "group-head")[0]), /county_budget_fy2026\.pdf sha256 9c1e…4a7b · 62 pages · 3\.8 MB 2 runs/);
  assert.match(text(byClass(groups[1], "group-head")[0]), /permits\.pdf .* 214 pages · 41\.2 MB 1 run$/);
});

test("a run line has every figure of the board", () => {
  const node = groupsView(runsData(), NOW);
  const [row] = byTag(node, "tr").filter((r) => byTag(r, "td").length);
  const cells = byTag(row, "td").map(text);
  assert.equal(cells[0], "7f3a29c1");
  assert.equal(cells[1], "Today 10:14");
  assert.equal(cells[2], "claude-sonnet-4-5");
  assert.deepEqual(cells.slice(3, 6), ["3", "1,488", "7,440"]);
  assert.equal(cells[6], "≈ fuzzy 1,102 ⇄ misplaced 388 × ungrounded 291 # untokenized 65 = 1,846");
  assert.deepEqual(cells.slice(7), ["2", "$4.82", "37 / 1,846"]);
  const [link] = byTag(row, "a");
  assert.equal(link.getAttribute("href"), `#/run/${ID}`);
});

test("cost styles, done and runs without flagged cells", () => {
  const node = groupsView(runsData(), NOW);
  const rows = byTag(node, "tr").filter((r) => byTag(r, "td").length);
  const cost = (row) => byTag(row, "td").map(text)[8];
  assert.equal(cost(rows[1]), "free");
  assert.equal(cost(rows[2]), "unknown");
  assert.ok(byClass(rows[1], "cost-free").length);
  assert.ok(byClass(rows[2], "cost-unknown").length);
  assert.equal(text(byTag(rows[1], "td")[9]), "1,846 / 1,846 · done");
  assert.ok(byClass(rows[1], "done").length);
  assert.equal(byTag(rows[2], "td").map(text)[6], "—");
  assert.equal(byClass(rows[0], "done").length, 0);
});

test("the progress bar has its width and a text equivalent", () => {
  const node = groupsView(runsData(), NOW);
  const [bar] = byClass(node, "progress");
  assert.equal(bar.getAttribute("role"), "img");
  assert.equal(bar.getAttribute("aria-label"), "37 of 1,846 flagged cells reviewed");
  assert.equal(byClass(bar, "fill")[0].styles.width, "2%");
});

test("the note under the list explains cost", () => {
  const node = groupsView(runsData(), NOW);
  assert.match(text(byClass(node, "note")[0]), /^Cost is the sum of the run’s records in \.quotable\/cost\/\. “free” = every answer came from the cache; “unknown” = a record has no price\.$/);
});

test("untrusted text in the runs list is text", () => {
  const data = runsData();
  data.documents[0].name = PAYLOAD;
  data.documents[0].runs[0].model = PAYLOAD;
  const node = groupsView(data, NOW);
  noImages(node);
  assert.ok(text(node).includes(PAYLOAD));
});

test("no runs yet says how to make one", () => {
  const node = emptyView({ total_runs: 0, runs: 0, documents: [], unreadable: 0 });
  assert.match(text(node), /No runs yet/);
  assert.match(text(node), /extract_tables/);
  assert.match(text(node), /\.quotable\/runs\//);
});

test("filters that match nothing are not 'no runs yet'", () => {
  const node = emptyView({ total_runs: 5, runs: 0, documents: [], unreadable: 0 });
  assert.match(text(node), /No runs match/);
  assert.doesNotMatch(text(node), /No runs yet/);
});

test("run folders that cannot be read are mentioned", () => {
  assert.match(text(groupsView(runsData({ unreadable: 2 }), NOW)), /2 run folders could not be read/);
  assert.match(text(groupsView(runsData({ unreadable: 1 }), NOW)), /1 run folder could not be read/);
  assert.doesNotMatch(text(groupsView(runsData(), NOW)), /could not be read/);
});

// --- the run screen --------------------------------------------------------------------------
test("the heading has the label, the file and one line of facts", () => {
  const node = runView(runData(), NOW);
  assert.equal(text(byClass(node, "label")[0]), "Run 7f3a29c1");
  assert.equal(text(byTag(node, "h1")[0]), "county_budget_fy2026.pdf");
  assert.equal(
    text(byClass(node, "facts")[0]),
    "Today 14:14–14:31 · claude-sonnet-4-5 · 3 tables · 1,488 rows · 1,846 flagged cells · $4.82",
  );
});

test("the main button opens the queue for this run", () => {
  const [button] = byClass(runView(runData(), NOW), "btn");
  assert.equal(text(button), "Review this run · 37 / 1,846");
  assert.equal(button.getAttribute("href"), `#/queue?run=${ID}`);
});

test("the run card lists its facts and the settings that change results", () => {
  const node = runView(runData(), NOW);
  const cards = byClass(node, "card").filter((c) => byClass(c, "kv").length);
  const run = text(cards[0]);
  assert.match(run, /Run id 7f3a29c15d0e4b8a9e210c6f3b7d12aa/);
  assert.match(run, /Started · ended 2026-10-20 14:14:07Z · 14:31:52Z/);
  assert.match(run, /Model claude-sonnet-4-5/);
  assert.match(run, /quotable 0\.1\.0/);
  assert.match(run, /Format run format 1/);
  const chips = byClass(cards[0], "chip").map(text);
  assert.deepEqual(chips.slice(0, 5), [
    "discovery_pages=3",
    "recheck=True",
    'ocr="auto"',
    "merge_reworded=True",
    "max_requests=400",
  ]);
  assert.match(run, /extra_fields fiscal_year — “Fiscal year printed in the page header”/);
});

test("without extra fields there is no extra-fields line, and unset limits are None", () => {
  const data = runData();
  data.settings.extra_fields = null;
  data.settings.max_requests = null;
  const node = runView(data, NOW);
  assert.doesNotMatch(text(node), /extra_fields/);
  assert.match(text(node), /max_requests=None/);
});

test("the document card", () => {
  const node = runView(runData(), NOW);
  const card = byClass(node, "card").filter((c) => byClass(c, "kv").length)[1];
  const body = text(card);
  assert.match(body, /File county_budget_fy2026\.pdf/);
  assert.match(body, /Path \/Users\/you\/county\/county_budget_fy2026\.pdf/);
  assert.match(body, /Size · pages 3\.8 MB · 62 pages/);
  assert.match(body, /SHA-256 9c1e07b3d2…f5a14a7b/);
});

test("one card a table, each linking to its table screen, in order", () => {
  const cards = byClass(runView(runData(), NOW), "table-card");
  assert.equal(cards.length, 2);
  assert.equal(cards[0].getAttribute("href"), `#/run/${ID}/table/0`);
  assert.equal(cards[1].getAttribute("href"), `#/run/${ID}/table/1`);
  assert.match(text(byClass(cards[0], "where")[0]), /^Table 1 · pages 3–5, 41$/);
  assert.equal(text(byClass(cards[0], "title")[0]), "General Fund Expenditures by Department");
  assert.equal(text(byClass(cards[0], "columns")[0]), "Department · Fund · FY2025 Actual + fiscal_year (extra)");
  const numbers = byClass(cards[0], "stat").map(text);
  assert.deepEqual(numbers, ["Rows 1,214", "Flagged 1,512", "Merged parts 1", "OCR pages 2 (pp. 17–18)"]);
});

test("a table without a label is only 'Table N'", () => {
  const [, second] = byClass(runView(runData(), NOW), "table-card");
  assert.equal(text(byClass(second, "title")[0]), "Table 2");
  assert.equal(byClass(second, "table-note").length, 0);
  assert.deepEqual(byClass(second, "stat").map(text).slice(2), ["Merged parts 0", "OCR pages 0"]);
});

test("the note under a table's numbers lists each fact", () => {
  const [first] = byClass(runView(runData(), NOW), "table-card");
  const lines = byClass(first, "table-note")[0].childNodes.map(text);
  assert.deepEqual(lines, ["Merged part: pp. 22–24, columns Dept · Fund", "57 recheck changes accepted"]);
});

test("a PDF that is fine has no alert", () => {
  assert.equal(pdfAlert({ status: "ok", path: "/x.pdf" }), null);
  assert.equal(byClass(runView(runData(), NOW), "alert").length, 0);
});

test("a missing PDF is an alert with the path", () => {
  const node = pdfAlert({ status: "missing", path: "/Users/you/permits.pdf" });
  assert.equal(node.getAttribute("role"), "alert");
  assert.equal(
    text(node).replace(/^\S+ /, ""),
    "The PDF is missing. Page images can’t be shown. Values, statuses and text still can. not found: /Users/you/permits.pdf",
  );
});

test("a changed PDF is an alert with both SHA-256s", () => {
  const node = pdfAlert({ status: "changed", path: "/x.pdf", expected: "3b70…e019", found: "22f8…01d6" });
  assert.match(text(node), /The PDF’s SHA-256 no longer matches\. Page images can’t be shown\. Values, statuses and text still can\./);
  assert.match(text(node), /expected 3b70…e019 · found 22f8…01d6$/);
});

test("the alert comes above the cards and the rest of the screen is unchanged", () => {
  const data = runData({ pdf: { status: "missing", path: "/gone.pdf" } });
  const node = runView(data, NOW);
  const order = node.childNodes.map((c) => c.getAttribute?.("class") ?? "");
  const alertAt = order.findIndex((c) => c.includes("alert"));
  const cardsAt = order.findIndex((c) => c.includes("cards"));
  assert.ok(alertAt >= 0 && alertAt < cardsAt, order.join("|"));
  assert.equal(byClass(node, "table-card").length, 2);
});

test("untrusted text on the run screen is text", () => {
  const data = runData({ pdf: { status: "missing", path: PAYLOAD } });
  data.document.name = PAYLOAD;
  data.document.path = PAYLOAD;
  data.model = PAYLOAD;
  data.settings.extra_fields.fields[0].name = PAYLOAD;
  data.settings.extra_fields.fields[0].description = PAYLOAD;
  data.tables[0].label = PAYLOAD;
  data.tables[0].columns = [PAYLOAD, "B"];
  data.tables[0].extra_names = [PAYLOAD];
  data.tables[0].note = [{ text: PAYLOAD }];
  const node = runView(data, NOW);
  noImages(node);
  assert.ok(text(node).includes(PAYLOAD));
});
