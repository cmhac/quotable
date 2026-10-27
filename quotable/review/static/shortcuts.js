// The "Shortcuts ?" dialog (spec 013 D7): the key table, focus kept inside while it is open.

import { el } from "./dom.js";

export const saveKey = (platform = "") =>
  /mac|iphone|ipad/i.test(platform) ? "⌘↵" : "Ctrl+Enter";

export const SHORTCUTS = [
  ["Next / previous cell", "J / K"],
  ["Next unreviewed", "N"],
  ["Next / previous row", "] / ["],
  ["Jump to page", "G"],
  ["Correct, Change value, Can’t tell", "C, X, U"],
  ["Error category", "1–9"],
  ["Save", saveKey(globalThis.navigator?.platform)],
  ["Cancel", "Esc"],
  ["Zoom in, zoom out, fit width", "+, −, F"],
  ["Text layer", "T"],
  ["Shortcuts", "?"],
];

export function dialogView(close) {
  const button = el(
    "button",
    { class: "btn", type: "button", onclick: () => close() },
    "Close",
  );
  return el(
    "div",
    {
      class: "dialog",
      role: "dialog",
      "aria-modal": "true",
      "aria-label": "Keyboard shortcuts",
      onkeydown: (event) => {
        if (event.key === "Escape") {
          event.preventDefault();
          close();
        } else if (event.key === "Tab") {
          event.preventDefault();
          button.focus?.();
        }
      },
    },
    el(
      "div",
      { class: "dialog-card card" },
      el("h2", null, "Keyboard shortcuts"),
      el(
        "p",
        { class: "note" },
        "Single keys do nothing while you type in a box; Save and Cancel still work there.",
      ),
      el(
        "table",
        null,
        el(
          "tbody",
          null,
          SHORTCUTS.map(([action, keys]) =>
            el(
              "tr",
              null,
              el("td", null, action),
              el("td", { class: "mono" }, keys),
            ),
          ),
        ),
      ),
      button,
    ),
  );
}

let open = null;

export const shortcutsOpen = () => open !== null;

export function openShortcuts() {
  if (open) return;
  const before = globalThis.document.activeElement;
  const close = () => {
    open?.remove?.();
    open = null;
    before?.focus?.();
  };
  open = dialogView(close);
  globalThis.document.body?.appendChild(open);
  open.querySelector?.("button")?.focus?.();
}
