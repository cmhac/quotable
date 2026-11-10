import assert from "node:assert/strict";
import { test } from "node:test";

import {
  START_ROWS,
  addTable,
  blankTable,
  fromRecord,
  isBlank,
  problem,
  removeTable,
  status,
  toPayload,
  trimBottom,
} from "../../../quotable/review/static/goldmodel.js";

const typed = (columns, rows) => ({
  columns,
  rows: rows.map((cells) => ({ cells, ghost: false })),
});

test("a page with nothing stored opens with one blank table of 20 rows", () => {
  const tables = fromRecord(null);
  assert.equal(tables.length, 1);
  assert.deepEqual(tables[0].columns, [""]);
  assert.equal(tables[0].rows.length, START_ROWS);
  assert.equal(isBlank(tables[0]), true);
});

test("a blank table is not sent: a page with nothing typed is a page with no table", () => {
  assert.deepEqual(toPayload([blankTable()]), []);
  assert.deepEqual(toPayload([blankTable(), blankTable()]), []);
});

test("a stored page opens as its tables, padded with empty rows", () => {
  const record = { tables: [{ columns: ["A", "B"], rows: [["1", "2"]] }], done: false };
  const [t] = fromRecord(record);
  assert.equal(t.rows.length, START_ROWS);
  assert.deepEqual(t.rows[0].cells, ["1", "2"]);
  assert.equal(fromRecord(record, { pad: false })[0].rows.length, 1);
});

test("the payload keeps typed tables and cuts empty rows at the bottom only", () => {
  const t = typed(["A", "B"], [["1", ""], ["", ""], ["2", "x"], ["", ""], ["", ""]]);
  assert.deepEqual(toPayload([blankTable(), t]), [
    { columns: ["A", "B"], rows: [["1", ""], ["", ""], ["2", "x"]] },
  ]);
});

test("a table with named columns and no rows is still a table", () => {
  assert.deepEqual(toPayload([typed(["A"], [])]), [{ columns: ["A"], rows: [] }]);
});

test("a done page needs every column of every used table named, once", () => {
  assert.equal(problem([blankTable()]), null);
  assert.equal(problem([typed(["A", "B"], [["1", "2"]])]), null);
  assert.match(problem([typed(["A", ""], [["1", "2"]])]), /table 1/);
  assert.match(problem([typed(["A"], [["1"]]), typed(["B", "B "], [["1", "2"]])]), /table 2/);
  assert.match(problem([blankTable(), typed(["A", "A"], [])]), /table 1/); // numbers skip blank tables
});

test("status is new, started or done", () => {
  assert.equal(status([blankTable()], false), "new");
  assert.equal(status([typed(["A"], [])], false), "started");
  assert.equal(status([blankTable()], true), "done");
});

test("tables are added at the end and the last one removed leaves a blank one", () => {
  const tables = [typed(["A"], [["1"]])];
  assert.equal(addTable(tables), 1);
  assert.equal(tables.length, 2);
  assert.equal(removeTable(tables, 1), 0);
  assert.equal(tables.length, 1);
  assert.equal(removeTable(tables, 0), 0);
  assert.equal(isBlank(tables[0]), true);
});

test("trimBottom drops empty rows at the bottom of an editor table", () => {
  const t = typed(["A"], [["1"], [""], [""]]);
  trimBottom(t);
  assert.equal(t.rows.length, 1);
});
