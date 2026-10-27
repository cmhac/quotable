// The cell screen (spec 013 C4, C5): the page with its highlights beside the cell view.
// What the person sees of the page (zoom, view mode, text layer, which highlights) outlives the
// screen, so moving to the next cell keeps it; it is a display preference, not review state.

import { ApiError } from "./api.js";
import { cellView } from "./cellview.js";
import { el } from "./dom.js";
import { number } from "./format.js";
import {
  boxesFor,
  cellAt,
  defaultToggles,
  fitZoom,
  loadToggles,
  saveToggles,
  scrollTarget,
  shownToggles,
  surface,
  visible,
  place,
  zoomIn,
  zoomOut,
  zoomText,
} from "./pageview.js";
import { createVerdictPanel } from "./verdict.js";
import {
  entryRoute,
  inQueue,
  loadSettings,
  queueRouteQuery,
  settingsQuery,
} from "./queue.js";
import { barView, indexOf, neighbour, nextUnreviewed } from "./queuebar.js";
import { hashFor } from "./route.js";
import { pdfAlert } from "./run.js";
import { cellQuery, parseState } from "./table.js";

const KEYS = {
  j: "next",
  k: "previous",
  "]": "next_row",
  "[": "previous_row",
  n: "next_unreviewed",
  g: "jump",
  "+": "zoom_in",
  "=": "zoom_in",
  "-": "zoom_out",
  f: "fit",
  t: "text",
  c: "correct",
  x: "change",
  u: "unsure",
};
const TEXT_BOXES = ["INPUT", "TEXTAREA", "SELECT"];
const MOVES = [
  "previous",
  "next",
  "previous_row",
  "next_row",
  "next_unreviewed",
];

// --- what the person last chose, kept while the app is open ------------------------------------
const prefs = { zoom: 1, mode: "highlights", text: false, toggles: null };

export function resetPrefs() {
  Object.assign(prefs, {
    zoom: 1,
    mode: "highlights",
    text: false,
    toggles: null,
  });
}

function storage() {
  try {
    return globalThis.localStorage ?? null;
  } catch {
    return null;
  }
}

function toggles() {
  prefs.toggles ??= storage() ? loadToggles(storage()) : defaultToggles();
  return prefs.toggles;
}

// --- keys --------------------------------------------------------------------------------------
export function keyAction(event) {
  if (event.altKey) return null;
  if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) return "save";
  if (event.metaKey || event.ctrlKey) return null;
  if (event.key === "Escape") return "cancel";
  const target = event.target;
  if (TEXT_BOXES.includes(target?.tagName) || target?.isContentEditable)
    return null;
  if (/^[1-9]$/.test(event.key)) return `category:${event.key}`;
  return KEYS[String(event.key).toLowerCase()] ?? null;
}

let active = null;

if (typeof document.addEventListener === "function") {
  document.addEventListener("keydown", (event) => {
    if (!active) return;
    if (!String(globalThis.location?.hash).includes("/cell/")) {
      active = null;
      return;
    }
    const action = keyAction(event);
    if (action && active.act(action)) event.preventDefault();
  });
}

// --- the page view -----------------------------------------------------------------------------
const sr = (words) => el("span", { class: "sr" }, words);

function iconButton(glyph, words, onclick, extra = {}) {
  return el(
    "button",
    { class: "btn icon", type: "button", onclick, ...extra },
    glyph,
    sr(words),
  );
}

function createPageView({ runId, table, cell, run, ctx, query }) {
  const pdfOk = run.pdf.status === "ok";
  const pages = run.document.pages;
  const pdfUrl = `/api/runs/${encodeURIComponent(runId)}/pdf`;
  const cache = new Map();
  let page = cell.highlights.page;
  let latest = 0;

  const toolbar = el("div", { class: "toolbar" });
  const row = el("div", { class: "hl-toggles" });
  const stage = el("div", { class: "viewport" });
  const note = el("div", { class: "page-note" });
  let pageBox = null;

  const data = () => cache.get(page) ?? null;
  const repaint = () => {
    paintToolbar();
    paintRow();
    paintStage();
  };

  async function goTo(n) {
    const wanted = Math.min(pages, Math.max(1, n));
    page = wanted;
    const mine = ++latest;
    if (!cache.has(wanted)) {
      let found = null;
      try {
        found = await ctx.getJson(
          `/api/runs/${encodeURIComponent(runId)}/pages/${wanted}`,
        );
      } catch (error) {
        if (!(error instanceof ApiError && error.status === 404)) throw error;
      }
      cache.set(wanted, found);
      if (mine !== latest) return;
    }
    repaint();
  }

  function paintToolbar() {
    const mode = (value, label) =>
      el(
        "button",
        {
          class: "btn",
          type: "button",
          "aria-pressed": String(prefs.mode === value),
          disabled: value === "pdf" && !pdfOk,
          onclick: () => {
            prefs.mode = value;
            repaint();
          },
        },
        label,
      );
    pageBox = el("input", {
      class: "input page-box",
      type: "text",
      inputmode: "numeric",
      value: String(page),
      "aria-label": "Page number",
      onchange: (event) => {
        const typed = event.target.value.trim();
        if (/^[0-9]+$/.test(typed)) goTo(Number(typed));
        else event.target.value = String(page);
      },
    });
    toolbar.replaceChildren(
      el(
        "div",
        { class: "group" },
        mode("highlights", "Highlights"),
        mode("pdf", "Browser PDF viewer"),
      ),
      el(
        "div",
        { class: "group" },
        iconButton("‹", "Previous page", () => goTo(page - 1), {
          disabled: page <= 1,
        }),
        el(
          "span",
          { class: "pages" },
          "Page ",
          pageBox,
          ` of ${number(pages)}`,
        ),
        iconButton("›", "Next page", () => goTo(page + 1), {
          disabled: page >= pages,
        }),
      ),
      el(
        "div",
        { class: "group" },
        iconButton("−", "Zoom out", () => act("zoom_out")),
        el("span", { class: "zoom mono" }, zoomText(prefs.zoom)),
        iconButton("+", "Zoom in", () => act("zoom_in")),
        el(
          "button",
          { class: "btn", type: "button", onclick: () => act("fit") },
          "Fit width",
        ),
      ),
      el(
        "button",
        {
          class: "btn",
          type: "button",
          "aria-pressed": String(prefs.text),
          onclick: () => act("text"),
        },
        "Text layer ",
        el("span", { class: "key" }, "T"),
      ),
      pdfOk
        ? el(
            "a",
            {
              class: "btn",
              href: `${pdfUrl}#page=${page}`,
              target: "_blank",
              rel: "noopener",
            },
            `Open full PDF at p. ${page}`,
          )
        : el(
            "span",
            { class: "btn", "aria-disabled": "true" },
            `Open full PDF at p. ${page}`,
          ),
    );
  }

  function paintRow() {
    const on = toggles();
    const shared = (data()?.tables.length ?? 0) > 1;
    row.replaceChildren(
      el("span", { class: "label" }, "Show"),
      ...shownToggles(shared).map((h) =>
        el(
          "button",
          {
            class: ["tog", on[h.key] ? null : "off"].filter(Boolean).join(" "),
            type: "button",
            "aria-pressed": String(on[h.key]),
            onclick: () => {
              prefs.toggles = { ...on, [h.key]: !on[h.key] };
              if (storage()) saveToggles(storage(), prefs.toggles);
              repaint();
            },
          },
          el("span", { class: `swatch sw-${h.key}`, "aria-hidden": "true" }),
          h.label,
        ),
      ),
    );
  }

  const pick = (event, _box, at) => {
    const found = at && data() ? cellAt(data(), table, at[0], at[1]) : null;
    if (!found) return;
    ctx.go({
      name: "cell",
      run: runId,
      table,
      cell: {
        page: data().page,
        row: found.row,
        name: found.name,
        extra: false,
      },
      query,
    });
  };

  function paintStage() {
    const here = data();
    const image = `/api/runs/${encodeURIComponent(runId)}/pages/${page}.png`;
    const alt = `Page ${page} of ${run.document.name}`;
    if (prefs.mode === "pdf" && pdfOk) {
      note.replaceChildren(
        "The browser’s own viewer shows the PDF. It has no highlights.",
      );
      stage.replaceChildren(
        el("iframe", {
          class: "pdf-frame",
          src: `${pdfUrl}#page=${page}`,
          title: alt,
        }),
      );
      return;
    }
    if (!here) {
      note.replaceChildren(
        "No text was kept for this page, so there is nothing to highlight; the image is as printed.",
      );
      stage.replaceChildren(
        pdfOk ? el("img", { class: "plain", src: image, alt }) : "",
      );
      return;
    }
    note.replaceChildren(here.ocr ? "This page’s text came from OCR." : "");
    const boxes = boxesFor({ cell, page, data: here, table });
    stage.replaceChildren(
      surface({
        size: here.size,
        zoom: prefs.zoom,
        imageSrc: pdfOk ? image : null,
        alt,
        words: here.words,
        boxes,
        toggles: toggles(),
        textLayer: prefs.text,
        onPick: pick,
      }),
    );
    const target =
      page === cell.highlights.page
        ? scrollTarget(visible(boxes, toggles()))
        : null;
    if (target && typeof stage.scrollTo === "function") {
      const at = place(target.box, prefs.zoom);
      globalThis.requestAnimationFrame?.(() =>
        stage.scrollTo({
          left: Math.max(0, at.left - stage.clientWidth / 3),
          top: Math.max(0, at.top - stage.clientHeight / 3),
        }),
      );
    }
  }

  function act(action) {
    if (action === "zoom_in") prefs.zoom = zoomIn(prefs.zoom);
    else if (action === "zoom_out") prefs.zoom = zoomOut(prefs.zoom);
    else if (action === "fit")
      prefs.zoom = fitZoom((stage.clientWidth ?? 0) - 32, data()?.size[0] ?? 0);
    else if (action === "text") prefs.text = !prefs.text;
    else return false;
    repaint();
    return true;
  }

  cache.set(page, cell.page_data);
  repaint();
  return {
    node: el(
      "section",
      { class: "page-view", "aria-label": "PDF page" },
      toolbar,
      row,
      note,
      stage,
    ),
    act,
    focusPage: () => pageBox?.focus?.(),
  };
}

// --- the screen --------------------------------------------------------------------------------
const cellPath = (runId, index, { page, row, name, extra }) =>
  `/api/runs/${encodeURIComponent(runId)}/tables/${index}/cells/${page}/${row}/${
    extra ? "extra/" : ""
  }${encodeURIComponent(name)}`;

export async function show(route, ctx) {
  const runId = route.run;
  const queued = inQueue(route.query);
  const settings = queued ? loadSettings(route.query, null) : null;
  const query = queued
    ? queueRouteQuery(settings)
    : cellQuery(parseState(route.query));
  const [run, cell, queueData] = await Promise.all([
    ctx.getJson(`/api/runs/${encodeURIComponent(runId)}`),
    ctx.getJson(cellPath(runId, route.table, route.cell), queued ? {} : query),
    queued ? ctx.getJson("/api/queue", settingsOf(settings)) : null,
  ]);
  let index = -1;
  if (queueData) {
    index = indexOf(queueData.queue, {
      run: runId,
      ...route.cell,
      table: route.table,
    });
    if (index >= 0) {
      const q = queueData.queue;
      const ref = (e) =>
        e && { page: e.page, row: e.row ?? 1, name: e.column, extra: e.extra };
      cell.nav = {
        ...cell.nav,
        n: index + 1,
        of: q.length,
        previous: ref(neighbour(q, index, -1)),
        next: ref(neighbour(q, index, 1)),
        next_unreviewed: ref(nextUnreviewed(q, index)),
      };
    }
  }
  const info = run.tables.find((t) => t.index === route.table);
  if (!info) throw new Error("no such table");
  const shown = cell.highlights.page;
  let pageData = null;
  try {
    pageData = await ctx.getJson(
      `/api/runs/${encodeURIComponent(runId)}/pages/${shown}`,
    );
  } catch (error) {
    if (!(error instanceof ApiError && error.status === 404)) throw error;
  }
  cell.page_data = pageData;

  const hrefFor = (target) =>
    hashFor({
      name: "cell",
      run: runId,
      table: route.table,
      cell: target,
      query,
    });
  const view = createPageView({
    runId,
    table: route.table,
    cell,
    run,
    ctx,
    query,
  });
  const tableName = info.label
    ? `Table ${info.number} · ${info.label}`
    : `Table ${info.number}`;
  const verdict = createVerdictPanel({
    cell,
    ctx,
    settings,
    onSaved: (answer) => {
      if (answer.next) ctx.go(entryRoute(answer.next.item, settings));
      else ctx.refresh?.();
    },
  });
  const goMove = (name) => {
    const target = cell.nav?.[name];
    if (!target) return false;
    ctx.go({
      name: "cell",
      run: runId,
      table: route.table,
      cell: target,
      query,
    });
    return true;
  };
  active = {
    act: (action) => {
      if (action === "jump") {
        view.focusPage();
        return true;
      }
      if (MOVES.includes(action)) return goMove(action);
      return view.act(action) || verdict.act(action);
    },
  };
  const alert = pdfAlert(run.pdf);
  return {
    title: `${cell.nav?.n ? `Cell ${number(cell.nav.n)} of ${number(cell.nav.of)}` : "Cell"} · ${cell.name}`,
    crumbs: [
      { text: "Runs", href: "#/" },
      {
        text: run.document.name,
        sub: run.short_id,
        href: hashFor({ name: "run", run: runId }),
      },
      {
        text: tableName,
        href: hashFor({ name: "table", run: runId, table: route.table }),
      },
      { text: "Cell" },
    ],
    content: el(
      "div",
      { class: "cell-screen" },
      alert,
      queueData && index >= 0
        ? barView({ data: queueData, index, settings, hrefFor })
        : null,
      el(
        "div",
        { class: "cell-layout" },
        view.node,
        el(
          "div",
          { class: "cell-side" },
          cellView(cell, hrefFor),
          verdict.node,
        ),
      ),
    ),
  };
}

const settingsOf = (settings) => settingsQuery(settings);
