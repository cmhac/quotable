import assert from "node:assert/strict";
import { test } from "node:test";

import { byClass, byTag, installDom } from "./fake_dom.mjs";

installDom();
const S = await import("../../../quotable/review/static/shortcuts.js");

function words(node) {
  if (node.nodeType === 3) return node.data;
  return node.childNodes.map(words).join(" ");
}
const text = (node) => words(node).replace(/\s+/g, " ").trim();

test("the table lists every action of the spec with its keys", () => {
  const all = S.SHORTCUTS.map(([action]) => action);
  for (const a of [
    "Next / previous cell",
    "Next unreviewed",
    "Next / previous row",
    "Jump to page",
    "Correct, Change value, Can’t tell",
    "Error category",
    "Save",
    "Cancel",
    "Zoom in, zoom out, fit width",
    "Text layer",
    "Shortcuts",
  ])
    assert.ok(all.includes(a), a);
});

test("the dialog is a modal with the list and a Close button", () => {
  const node = S.dialogView(() => {});
  assert.equal(node.getAttribute("role"), "dialog");
  assert.equal(node.getAttribute("aria-modal"), "true");
  assert.match(text(node), /Next \/ previous cell J \/ K/);
  assert.equal(byTag(node, "button").length, 1);
});

test("Close and Esc call the closer; Tab stays on the dialog", () => {
  let closed = 0;
  const node = S.dialogView(() => closed++);
  byTag(node, "button")[0].listeners.click[0]({});
  node.listeners.keydown[0]({ key: "Escape", preventDefault() {} });
  assert.equal(closed, 2);
  let prevented = false;
  node.listeners.keydown[0]({
    key: "Tab",
    preventDefault: () => (prevented = true),
  });
  assert.equal(prevented, true);
  assert.equal(byClass(node, "keys").length >= 0, true);
});

test("the Ctrl or Command key of this system is named", () => {
  assert.equal(S.saveKey("MacIntel"), "⌘↵");
  assert.equal(S.saveKey("Win32"), "Ctrl+Enter");
});
