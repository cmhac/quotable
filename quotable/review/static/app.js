// The app: reads the hash, asks a screen to show it, draws the header and the screen.

import { ApiError, getJson, sendJson } from "./api.js";
import * as cell from "./cell.js";
import { alertBox, failureView, header } from "./chrome.js";
import { el } from "./dom.js";
import { hashFor, parseHash } from "./route.js";
import { openShortcuts, shortcutsOpen } from "./shortcuts.js";
import * as queue from "./queue.js";
import * as run from "./run.js";
import * as runs from "./runs.js";
import * as table from "./table.js";

const SCREENS = {
  runs: runs.show,
  run: run.show,
  table: table.show,
  cell: cell.show,
  queue: queue.show,
};
function storage() {
  try {
    return globalThis.localStorage ?? null;
  } catch {
    return null;
  }
}

const ctx = {
  getJson,
  sendJson,
  get storage() {
    return storage();
  },
  refresh: () => show(),
  replace: (route) => history.replaceState(null, "", hashFor(route)),
  go: (route) => {
    location.hash = hashFor(route);
  },
};

function unavailable(route) {
  const missing = route.name === "notfound";
  const content = el(
    "div",
    { class: "page" },
    alertBox({
      headline: missing
        ? "There is no such page."
        : "This screen is not available yet.",
      text: missing ? route.hash : null,
    }),
    el("p", null, el("a", { href: "#/" }, "Back to the runs list")),
  );
  return {
    title: "Not available",
    crumbs: [{ text: "Runs", href: "#/" }],
    content,
  };
}

let latest = 0;
let firstScreen = true;

async function show() {
  const mine = ++latest;
  const route = parseHash(location.hash);
  let view;
  try {
    view = await (SCREENS[route.name] ?? unavailable)(route, ctx);
  } catch (error) {
    if (!(error instanceof ApiError)) console.error(error);
    view = {
      title: "Error",
      crumbs: [{ text: "Runs", href: "#/" }],
      content: failureView(error),
    };
  }
  if (mine !== latest) return;
  const main = document.getElementById("main");
  document.getElementById("chrome").replaceChildren(
    header({
      crumbs: view.crumbs,
      project: view.project,
      address: location.host,
    }),
  );
  main.replaceChildren(view.content);
  document.title = `${view.title} · quotable review`;
  window.scrollTo(0, 0);
  if (!firstScreen) main.focus({ preventScroll: true });
  firstScreen = false;
}

window.addEventListener("hashchange", show);
show();

window.addEventListener("keydown", (event) => {
  const tag = event.target?.tagName;
  if (event.key !== "?" || event.metaKey || event.ctrlKey || event.altKey)
    return;
  if (["INPUT", "TEXTAREA", "SELECT"].includes(tag) || shortcutsOpen()) return;
  event.preventDefault();
  openShortcuts();
});
