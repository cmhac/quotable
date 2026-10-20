import assert from "node:assert/strict";
import { test } from "node:test";

import { hashFor, parseHash } from "../../../quotable/review/static/route.js";

const ID = "0123456789abcdef0123456789abcdef";

test("the empty hash and #/ are the runs list", () => {
  assert.deepEqual(parseHash(""), { name: "runs", query: {} });
  assert.deepEqual(parseHash("#"), { name: "runs", query: {} });
  assert.deepEqual(parseHash("#/"), { name: "runs", query: {} });
});

test("the runs list keeps its filters", () => {
  assert.deepEqual(parseHash("#/?document=a%20b&model=demo%3Afirst"), {
    name: "runs",
    query: { document: "a b", model: "demo:first" },
  });
});

test("a run", () => {
  assert.deepEqual(parseHash(`#/run/${ID}`), {
    name: "run",
    run: ID,
    query: {},
  });
});

test("a table, with its filters", () => {
  assert.deepEqual(
    parseHash(`#/run/${ID}/table/2?status=fuzzy,misplaced&page=3`),
    {
      name: "table",
      run: ID,
      table: 2,
      query: { status: "fuzzy,misplaced", page: "3" },
    },
  );
});

test("a cell of a column and a cell of an extra field", () => {
  assert.deepEqual(
    parseHash(`#/run/${ID}/table/0/cell/14/7/Requestor(s)?flagged=1`),
    {
      name: "cell",
      run: ID,
      table: 0,
      cell: { page: 14, row: 7, name: "Requestor(s)", extra: false },
      query: { flagged: "1" },
    },
  );
  assert.deepEqual(
    parseHash(`#/run/${ID}/table/0/cell/3/1/extra/fiscal%20year`).cell,
    {
      page: 3,
      row: 1,
      name: "fiscal year",
      extra: true,
    },
  );
});

test("the queue screen", () => {
  assert.deepEqual(parseHash(`#/queue?run=${ID}&seed=7`), {
    name: "queue",
    query: { run: ID, seed: "7" },
  });
});

test("anything else is not found", () => {
  for (const hash of [
    "#/nothing",
    `#/run/`,
    `#/run/${ID}/table/x`,
    `#/run/${ID}/table/-1`,
    `#/run/${ID}/table/0/cell/1`,
    `#/run/${ID}/table/0/cell/a/1/Name`,
    `#/run/${ID}/other`,
  ]) {
    assert.equal(parseHash(hash).name, "notfound", hash);
  }
});

test("a malformed escape is not found, not an exception", () => {
  assert.equal(parseHash(`#/run/%E0%A4%A`).name, "notfound");
});

test("hashFor is the inverse of parseHash", () => {
  const routes = [
    { name: "runs", query: {} },
    { name: "runs", query: { document: "a b&c", model: "demo:first" } },
    { name: "run", run: ID, query: {} },
    { name: "table", run: ID, table: 4, query: { status: "fuzzy", q: "x/y" } },
    {
      name: "cell",
      run: ID,
      table: 1,
      cell: { page: 2, row: 9, name: "A/B ?#", extra: false },
      query: {},
    },
    {
      name: "cell",
      run: ID,
      table: 1,
      cell: { page: 2, row: 9, name: "fiscal year", extra: true },
      query: { n: "1" },
    },
    { name: "queue", query: { run: ID } },
  ];
  for (const route of routes)
    assert.deepEqual(parseHash(hashFor(route)), route);
});

test("hashFor leaves out empty query values", () => {
  assert.equal(
    hashFor({ name: "runs", query: { document: "", model: "x" } }),
    "#/?model=x",
  );
  assert.equal(hashFor({ name: "runs" }), "#/");
});
