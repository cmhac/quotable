import assert from "node:assert/strict";
import { test } from "node:test";

process.env.TZ = "UTC";
const f = await import("../../../quotable/review/static/format.js");

test("numbers have thousands separators", () => {
  assert.equal(f.number(1488), "1,488");
  assert.equal(f.number(0), "0");
  assert.equal(f.number(18144), "18,144");
});

test("plural counts the thing", () => {
  assert.equal(f.plural(1, "table"), "1 table");
  assert.equal(f.plural(3, "table"), "3 tables");
  assert.equal(f.plural(1488, "row"), "1,488 rows");
  assert.equal(f.plural(0, "run"), "0 runs");
});

test("times are Today, then month and day", () => {
  const now = new Date("2026-10-20T15:00:00Z");
  assert.equal(f.formatTime("2026-10-20T10:14:00Z", now), "Today 10:14");
  assert.equal(f.formatTime("2026-10-19T16:40:00Z", now), "Oct 19, 16:40");
  assert.equal(f.formatTime("2025-10-19T16:40:00Z", now), "Oct 19, 2025, 16:40");
  assert.equal(f.formatTime("2026-01-02T09:05:00Z", now), "Jan 2, 09:05");
});

test("a span has the end as a clock time when it is the same day", () => {
  const now = new Date("2026-10-20T15:00:00Z");
  assert.equal(f.formatSpan("2026-10-20T10:14:00Z", "2026-10-20T10:31:00Z", now), "Today 10:14–10:31");
  assert.equal(
    f.formatSpan("2026-10-19T23:50:00Z", "2026-10-20T00:10:00Z", now),
    "Oct 19, 23:50–Today 00:10",
  );
  assert.equal(f.formatSpan("2026-10-19T16:40:00Z", "2026-10-19T16:41:00Z", now), "Oct 19, 16:40–16:41");
});

test("UTC stamps for the run card", () => {
  assert.equal(
    f.utcSpan("2026-10-20T14:14:07Z", "2026-10-20T14:31:52Z"),
    "2026-10-20 14:14:07Z · 14:31:52Z",
  );
  assert.equal(
    f.utcSpan("2026-10-20T23:59:00Z", "2026-10-21T00:03:10Z"),
    "2026-10-20 23:59:00Z · 2026-10-21 00:03:10Z",
  );
});

test("cost: dollars, free or unknown", () => {
  assert.equal(f.costText({ kind: "usd", usd: 4.82 }), "$4.82");
  assert.equal(f.costText({ kind: "usd", usd: 2.8056 }), "$2.81");
  assert.equal(f.costText({ kind: "usd", usd: 0.0123 }), "$0.0123");
  assert.equal(f.costText({ kind: "usd", usd: 0.37 }), "$0.37");
  assert.equal(f.costText({ kind: "usd", usd: 0 }), "$0.00");
  assert.equal(f.costText({ kind: "free" }), "free");
  assert.equal(f.costText({ kind: "unknown" }), "unknown");
});

test("sizes", () => {
  assert.equal(f.sizeText(3_800_000), "3.8 MB");
  assert.equal(f.sizeText(164_292), "0.2 MB");
  assert.equal(f.sizeText(41_589), "41.6 KB");
  assert.equal(f.sizeText(900), "0.9 KB");
});

test("a SHA-256 is shortened to its ends", () => {
  const sha = "9c1e07b3d2aa11bb22cc33dd44ee55ff66778899aabbccddeeff00112233f5a14a7b";
  assert.equal(f.shortSha(sha, 10, 8), "9c1e07b3d2…f5a14a7b");
  assert.equal(f.shortSha(sha, 4, 4), "9c1e…4a7b");
});

test("page lists collapse into ranges", () => {
  assert.equal(f.pagesText([3, 4, 5, 41]), "pages 3–5, 41");
  assert.equal(f.pagesText(Array.from({ length: 39 }, (_, i) => i + 3)), "pages 3–41");
  assert.equal(f.pagesText([5]), "page 5");
  assert.equal(f.pagesText([1, 2, 3, 5]), "pages 1–3, 5");
  assert.equal(f.pagesText([2, 1]), "pages 1–2");
  assert.equal(f.pagesAbbr([17, 18]), "pp. 17–18");
  assert.equal(f.pagesAbbr([5]), "p. 5");
  assert.equal(f.pagesText([]), "");
});

test("settings are shown the way Python writes them", () => {
  assert.equal(f.settingValue(true), "True");
  assert.equal(f.settingValue(false), "False");
  assert.equal(f.settingValue(null), "None");
  assert.equal(f.settingValue(3), "3");
  assert.equal(f.settingValue("auto"), '"auto"');
  assert.equal(f.settingValue({ a: 1 }), '{"a":1}');
});

test("flagged counts come in the order of the statuses, zeros left out", () => {
  assert.deepEqual(f.flaggedParts({ ungrounded: 4, fuzzy: 29, misplaced: 6, untokenized: 0 }), [
    ["fuzzy", 29],
    ["misplaced", 6],
    ["ungrounded", 4],
  ]);
  assert.deepEqual(f.flaggedParts({}), []);
  assert.deepEqual(f.flaggedParts({ odd: 2, fuzzy: 1 }), [
    ["fuzzy", 1],
    ["odd", 2],
  ]);
});

test("the progress bar's width", () => {
  assert.equal(f.progressWidth({ reviewed: 37, flagged: 1846 }), "2%");
  assert.equal(f.progressWidth({ reviewed: 1, flagged: 100000 }), "1px");
  assert.equal(f.progressWidth({ reviewed: 0, flagged: 10 }), "0%");
  assert.equal(f.progressWidth({ reviewed: 0, flagged: 0 }), "0%");
  assert.equal(f.progressWidth({ reviewed: 41, flagged: 41 }), "100%");
});
