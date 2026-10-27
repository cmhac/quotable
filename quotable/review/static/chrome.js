// The parts every screen shares: the header bar, the alert and the failure page.

import { el } from "./dom.js";
import { openShortcuts } from "./shortcuts.js";

const WARNING = "\u26A0\uFE0E";

function crumb(item, last) {
  if (item.href && !last) {
    return el(
      "a",
      { href: item.href },
      item.text,
      item.sub ? el("span", { class: "sub" }, `· ${item.sub}`) : null,
    );
  }
  return el(
    "span",
    { class: "current", "aria-current": last ? "page" : null },
    el("span", { class: "name" }, item.text),
    item.sub ? el("span", { class: "sub" }, `· ${item.sub}`) : null,
  );
}

export function header({ crumbs, project, address }) {
  return el(
    "header",
    { class: "bar" },
    el(
      "div",
      { class: "brand" },
      el("span", null, "quotable"),
      el("span", { class: "accent" }, "review"),
    ),
    el(
      "nav",
      { class: "crumbs", "aria-label": "Breadcrumb" },
      crumbs.map((item, i) => [
        i > 0 ? el("span", { class: "sep", "aria-hidden": "true" }, "/") : null,
        crumb(item, i === crumbs.length - 1),
      ]),
    ),
    el(
      "button",
      { class: "shortcuts-btn", type: "button", onclick: openShortcuts },
      "Shortcuts ",
      el("span", { class: "key" }, "?"),
    ),
    el(
      "span",
      { class: "addr" },
      project ? `${project} · ${address}` : address,
    ),
  );
}

export function alertBox({ headline, text, detail }) {
  return el(
    "div",
    { class: "alert", role: "alert" },
    el("span", { class: "icon", "aria-hidden": "true" }, WARNING),
    el(
      "div",
      { class: "body" },
      el("div", null, el("b", null, headline), text ? ` ${text}` : null),
      detail ? el("div", { class: "detail" }, detail) : null,
    ),
  );
}

export function failureView(error) {
  return el(
    "div",
    { class: "page" },
    alertBox({
      headline: "This screen could not be loaded.",
      text: error.message,
    }),
    el("p", null, el("a", { href: "#/" }, "Back to the runs list")),
  );
}
