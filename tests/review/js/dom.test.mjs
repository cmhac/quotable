import assert from "node:assert/strict";
import { test } from "node:test";

import { byTag, installDom } from "./fake_dom.mjs";

installDom();
const { el } = await import("../../../quotable/review/static/dom.js");

const PAYLOAD = "<img src=x onerror=alert(1)>";

test("strings and numbers become text nodes, null and false are skipped", () => {
  const node = el("p", { class: "x" }, "a", 1, null, false, undefined, ["b", ["c"]]);
  assert.equal(node.tagName, "P");
  assert.equal(node.getAttribute("class"), "x");
  assert.equal(node.textContent, "a1bc");
  assert.ok(node.childNodes.every((c) => c.nodeType === 3));
});

test("markup in a string is text, never an element", () => {
  const node = el("td", null, PAYLOAD);
  assert.equal(node.textContent, PAYLOAD);
  assert.equal(node.children.length, 0);
  assert.equal(byTag(node, "img").length, 0);
});

test("markup in an attribute value stays one attribute value", () => {
  const node = el("span", { title: PAYLOAD, "aria-label": `"><b>` });
  assert.equal(node.getAttribute("title"), PAYLOAD);
  assert.equal(node.children.length, 0);
});

test("elements nest and keep their order", () => {
  const inner = el("b", null, "x");
  const node = el("p", null, "a", inner, "c");
  assert.deepEqual(
    node.childNodes.map((c) => c.textContent),
    ["a", "x", "c"],
  );
  assert.equal(node.children[0], inner);
});

test("a function on* attribute is an event listener", () => {
  const click = () => {};
  const node = el("button", { onclick: click });
  assert.deepEqual(node.listeners.click, [click]);
  assert.equal(node.getAttribute("onclick"), null);
});

test("style takes an object and goes through the style object", () => {
  const node = el("span", { style: { width: "40%" } });
  assert.equal(node.styles.width, "40%");
  assert.equal(node.getAttribute("style"), null);
});

test("true is an empty attribute, false and null leave it out", () => {
  const node = el("input", { disabled: true, checked: false, title: null });
  assert.equal(node.getAttribute("disabled"), "");
  assert.equal(node.getAttribute("checked"), null);
  assert.equal(node.getAttribute("title"), null);
});

test("a value is set after the children, so a select can pick its option", () => {
  const node = el("select", { value: "b" }, el("option", { value: "a" }, "A"));
  assert.equal(node.value, "b");
});

test("a link goes only to the app's own pages", () => {
  assert.equal(el("a", { href: "#/run/abc" }).getAttribute("href"), "#/run/abc");
  assert.equal(el("a", { href: "/api/runs/abc/pdf" }).getAttribute("href"), "/api/runs/abc/pdf");
  for (const bad of ["javascript:alert(1)", "//evil.example/x", "data:text/html,x", "https:x"]) {
    assert.throws(() => el("a", { href: bad }), /unsafe href/);
  }
});
