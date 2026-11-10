import assert from "node:assert/strict";
import { test } from "node:test";

import {
  cleanText,
  nextRotation,
  sameRange,
  shortNote,
  turn,
  watchSelection,
} from "../../../quotable/review/static/textlayer.js";

test("whitespace, tabs and repeated spaces become single spaces", () => {
  assert.equal(cleanText("  a \t b\n\n c  "), "a b c");
});

test("a hyphen that ends a line is dropped and the halves join", () => {
  assert.equal(cleanText("Plan-\nning Grant"), "Planning Grant");
  assert.equal(cleanText("Plan- \r\n  ning"), "Planning");
});

test("a hyphen inside a line stays", () => {
  assert.equal(cleanText("Cherfilus-McCormick"), "Cherfilus-McCormick");
  assert.equal(cleanText("Place-Based Plan"), "Place-Based Plan");
});

test("trailing periods and dot leaders go, inner periods stay", () => {
  assert.equal(cleanText("Corp."), "Corp");
  assert.equal(cleanText("Pine County . . . . . ."), "Pine County");
  assert.equal(cleanText("Pine County........"), "Pine County");
  assert.equal(cleanText("St. Louis"), "St. Louis");
  assert.equal(cleanText("1.5"), "1.5");
});

test("nothing selected cleans to nothing", () => {
  assert.equal(cleanText(""), "");
  assert.equal(cleanText(" \n "), "");
});

test("a long note is cut at 60 characters", () => {
  assert.equal(shortNote("abc"), "abc");
  assert.equal(shortNote("x".repeat(61)), `${"x".repeat(60)}…`);
});

const range = (start, end) => ({
  start,
  end,
  compareBoundaryPoints(how, other) {
    return how === 0 ? this.start - other.start : this.end - other.end;
  },
  cloneRange() {
    return range(this.start, this.end);
  },
});

test("two ranges over the same text are the same, others are not", () => {
  assert.equal(sameRange(range(1, 5), range(1, 5)), true);
  assert.equal(sameRange(range(1, 5), range(1, 6)), false);
  assert.equal(sameRange(range(1, 5), range(2, 5)), false);
  assert.equal(sameRange(null, range(1, 5)), false);
});

test("the text layer turns with the page like the VRA app's", () => {
  assert.deepEqual(turn(0, 600, 800), { viewBox: "0 0 600 800", transform: "rotate(0)" });
  assert.deepEqual(turn(90, 600, 800), {
    viewBox: "0 0 800 600",
    transform: "translate(800 0) rotate(90)",
  });
  assert.deepEqual(turn(180, 600, 800), {
    viewBox: "0 0 600 800",
    transform: "translate(600 800) rotate(180)",
  });
  assert.deepEqual(turn(270, 600, 800), {
    viewBox: "0 0 800 600",
    transform: "translate(0 600) rotate(270)",
  });
});

function harness(texts) {
  const listeners = {};
  const area = {
    addEventListener: (name, fn) => (listeners[name] = fn),
    removeEventListener: (name) => delete listeners[name],
    contains: () => true,
  };
  let current = { text: texts[0], range: range(0, 1) };
  const selection = () => ({
    anchorNode: {},
    getRangeAt: () => current.range,
    removeAllRanges: () => (current = { text: "", range: null }),
    toString: () => current.text,
  });
  const copied = [];
  const seen = [];
  let failing = false;
  const stop = watchSelection(area, {
    onText: (text, shift) => seen.push([text, shift]),
    onFail: () => seen.push("fail"),
    shiftClears: () => true,
    env: {
      selection,
      copy: async (text) => {
        if (failing) throw new Error("no");
        copied.push(text);
      },
    },
  });
  return {
    listeners,
    copied,
    seen,
    stop,
    select: (text, start, end) => (current = { text, range: range(start, end) }),
    fail: () => (failing = true),
  };
}
const tick = () => new Promise((r) => setTimeout(r, 5));

test("releasing the mouse over a new selection copies its clean text once", async () => {
  const h = harness(["Plan-\nning."]);
  h.listeners.mouseup({ shiftKey: false });
  await tick();
  assert.deepEqual(h.copied, ["Planning"]);
  assert.deepEqual(h.seen, [["Planning", false]]);
  h.listeners.mouseup({ shiftKey: false }); // a click inside the same highlight
  await tick();
  assert.equal(h.copied.length, 1);
  h.select("Next Word", 3, 4);
  h.listeners.mouseup({ shiftKey: true });
  await tick();
  assert.deepEqual(h.seen.at(-1), ["Next Word", true]);
  h.stop();
  assert.equal(h.listeners.mouseup, undefined);
});

test("a clipboard that refuses is reported, not pasted", async () => {
  const h = harness(["abc"]);
  h.fail();
  h.listeners.mouseup({ shiftKey: false });
  await tick();
  assert.deepEqual(h.seen, ["fail"]);
});

test("an empty selection copies nothing", async () => {
  const h = harness(["  "]);
  h.listeners.mouseup({ shiftKey: false });
  await tick();
  assert.deepEqual(h.copied, []);
  assert.deepEqual(h.seen, []);
});

test("the copy event gives the clean text", () => {
  const h = harness(["Corp."]);
  const data = {};
  let prevented = false;
  h.listeners.copy({
    clipboardData: { setData: (kind, text) => (data[kind] = text) },
    preventDefault: () => (prevented = true),
  });
  assert.deepEqual(data, { "text/plain": "Corp" });
  assert.equal(prevented, true);
});

test("shift-drag in a lock mode starts a fresh selection", () => {
  const h = harness(["abc"]);
  h.listeners.mousedown({ shiftKey: true });
  assert.equal(h.seen.length, 0);
  h.listeners.mouseup({ shiftKey: false });
});

test("turning right or left keeps the turn in 0, 90, 180 and 270", () => {
  assert.equal(nextRotation(0, 90), 90);
  assert.equal(nextRotation(270, 90), 0);
  assert.equal(nextRotation(0, -90), 270);
  assert.equal(nextRotation(90, -90), 0);
  assert.equal(nextRotation(180, 90), 270);
});
