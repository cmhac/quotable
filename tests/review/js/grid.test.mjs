// The model functions of the gold table editor (spec 016), ported from the VRA app's tests.
import assert from "node:assert/strict";
import { test } from "node:test";

import { clearRange, fillRange, mountGrid, parseTsv, pasteAt, setCell, toTsv, trim } from "../../../quotable/review/static/grid.js";
import { installBrowser } from "./fake_dom.mjs";

const empty = () => ({ columns: ["A", "B"], rows: [], done: false });

test("typing in the ghost row adds a row; clearing it at the bottom drops it", () => {
  const t = empty();
  setCell(t, 0, 1, "x");
  assert.deepEqual(t.rows, [{ cells: ["", "x"], ghost: true }]);
  setCell(t, 0, 1, "");
  trim(t);
  assert.deepEqual(t.rows, []);
});

test("blank rows higher up and New-row rows are kept", () => {
  const t = empty();
  setCell(t, 0, 0, "a");
  setCell(t, 1, 0, "b");
  clearRange(t, [0, 0, 0, 1]);
  assert.equal(t.rows.length, 2);
  t.rows.push({ cells: ["", ""], ghost: false });
  trim(t);
  assert.equal(t.rows.length, 3);
});

test("deleting a block that reaches the bottom drops the emptied ghost rows", () => {
  const t = empty();
  pasteAt(t, 0, 0, [["a", "b"], ["c", "d"], ["e", "f"]]);
  clearRange(t, [1, 0, 2, 1]);
  assert.deepEqual(t.rows.map((r) => r.cells), [["a", "b"]]);
});

test("a pasted block fills names, adds rows and columns", () => {
  const t = empty();
  const range = pasteAt(t, -1, 1, [["B2", "C"], ["1", "2"]]);
  assert.deepEqual(t.columns, ["A", "B2", "C"]);
  assert.deepEqual(t.rows.map((r) => r.cells), [["", "1", "2"]]);
  assert.deepEqual(range, [-1, 1, 0, 2]);
});

test("TSV round-trips quoted cells with tabs, line breaks and quotes", () => {
  const block = [["plain", 'say "hi"'], ["two\nlines", "a\tb"]];
  assert.deepEqual(parseTsv(`${toTsv(block)}\r\n`), block);
  assert.deepEqual(parseTsv("a\tb\r\nc\td\r\n"), [["a", "b"], ["c", "d"]]);
});

test("filling repeats the source block down into new rows and up", () => {
  const t = empty();
  pasteAt(t, 0, 0, [["a", "1"], ["b", "2"], ["", ""], ["", ""]]);
  fillRange(t, [0, 0, 1, 1], [0, 0, 4, 1]);
  assert.deepEqual(t.rows.map((r) => r.cells), [["a", "1"], ["b", "2"], ["a", "1"], ["b", "2"], ["a", "1"]]);
  fillRange(t, [3, 0, 3, 0], [0, 0, 3, 0]);
  assert.deepEqual(t.rows.map((r) => r.cells[0]), ["b", "b", "b", "b", "a"]);
});

// -- lock modes: page copies go into the selected cell and the selection moves on ------------

function mounted(table) {
  installBrowser();
  let changes = 0;
  const grid = mountGrid(document.createElement("table"), document.createElement("textarea"), () => table, () => changes++);
  grid.reset();
  return { grid, changes: () => changes };
}
const filled = (columns, rows) => ({ columns, rows: rows.map((cells) => ({ cells, ghost: false })), done: false });

test("lock column pastes down the column and never starts in the name row", () => {
  const t = filled(["A", "B"], [["", ""], ["", ""], ["", ""]]);
  const { grid } = mounted(t);
  grid.setLock("column"); // the selection starts on the name row
  assert.equal(grid.pasteNext("a"), "row 1, A");
  assert.equal(grid.pasteNext("b"), "row 2, A");
  assert.deepEqual(t.columns, ["A", "B"]);
  assert.deepEqual(t.rows.map((r) => r.cells[0]), ["a", "b", ""]);
});

test("lock column goes to the top of the next column where the tallest other column ends", () => {
  const t = filled(["A", "B"], [["", "x"], ["", "y"], ["", "z"]]);
  const { grid } = mounted(t);
  grid.setLock("column");
  const where = [1, 2, 3, 4].map((n) => grid.pasteNext(`v${n}`));
  assert.deepEqual(where, ["row 1, A", "row 2, A", "row 3, A", "row 1, B"]);
  assert.deepEqual(t.rows.map((r) => r.cells[1]), ["v4", "y", "z"]);
});

test("lock row fills the column names, adds a column after the last name, then rows", () => {
  const t = filled(["A"], [["", ""]]);
  t.columns = ["A", ""];
  t.rows = [{ cells: ["", ""], ghost: false }];
  const { grid } = mounted(t);
  grid.setLock("row");
  assert.equal(grid.pasteNext("Name"), "column name 1");
  assert.equal(grid.pasteNext("Amount"), "column name 2");
  assert.deepEqual(t.columns, ["Name", "Amount", ""]); // a column was added to carry on
  assert.equal(t.rows[0].cells.length, 3);
});

const press = (grid, key) =>
  grid.key({ key, shiftKey: false, metaKey: false, ctrlKey: false, preventDefault() {} });

test("lock row moves right through a row and wraps to the next", () => {
  const t = filled(["A", "B"], [["", ""], ["", ""]]);
  const { grid } = mounted(t);
  press(grid, "ArrowDown"); // off the name row, to row 1
  grid.setLock("row");
  assert.equal(grid.pasteNext("a"), "row 1, A");
  assert.equal(grid.pasteNext("b"), "row 1, B");
  assert.equal(grid.pasteNext("c"), "row 2, A");
  assert.deepEqual(t.rows.map((r) => r.cells), [["a", "b"], ["c", ""]]);
});

test("holding Shift adds to the cell after a dot and stays on it", () => {
  const t = filled(["A", "B"], [["", ""], ["", ""]]);
  const { grid } = mounted(t);
  grid.setLock("column");
  assert.equal(grid.pasteNext("Parent"), "row 1, A");
  press(grid, "ArrowUp"); // back to the cell just filled
  assert.equal(grid.pasteNext("Child", true), "row 1, A");
  assert.equal(t.rows[0].cells[0], "Parent.Child");
  assert.equal(grid.pasteNext("Next"), "row 1, A"); // the selection stayed, so this replaces it
  assert.equal(t.rows[0].cells[0], "Next");
});

test("one paste is one undo step and undo returns to the cell it went into", () => {
  const t = filled(["A", "B"], [["", ""], ["", ""]]);
  const { grid } = mounted(t);
  grid.setLock("column");
  grid.pasteNext("a");
  grid.pasteNext("b");
  grid.undo();
  assert.deepEqual(t.rows.map((r) => r.cells[0]), ["a", ""]);
  grid.undo();
  assert.deepEqual(t.rows.map((r) => r.cells[0]), ["", ""]);
});

test("turning a lock mode off puts the table back to plain typing", () => {
  const t = filled(["A"], [[""]]);
  const { grid } = mounted(t);
  grid.setLock("row");
  grid.setLock(null);
  assert.equal(typeof grid.pasteNext, "function");
});
