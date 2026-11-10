// The gold entry screen (spec 015): a sampled page next to a spreadsheet-style editor, for typing
// the tables the page really prints. Ported from the VRA gold annotation app. The extraction is
// never shown here: the editor is blind (FR-014).

import { alertBox } from "./chrome.js";
import { clock, makeTimer, progressLine } from "./clock.js";
import { el } from "./dom.js";
import { mountGrid } from "./grid.js";
import {
  addTable,
  fromRecord,
  isBlank,
  problem,
  removeTable,
  status as pageStatus,
  toPayload,
  trimBottom,
} from "./goldmodel.js";
import { SVG_NS, nextRotation, renderTextLayer, shortNote, watchSelection } from "./textlayer.js";

const RETRY_MS = 3000;
const SAVE_DELAY_MS = 400;
const KEYS_SWALLOWED = new Set(["Tab", "Enter", "F2", "Delete", "Backspace", "Escape"]);
const KEYS_SCROLL = new Set(["home", "end", "pageup", "pagedown"]);
const ZOOM_KEY = "quotable.gold.zoom";
const FEED_KEY = "quotable.gold.feedHidden";

const keyOf = (p) => `${p.sha256}:${p.page}`;
const pagePath = (sha, n) => `/api/gold/pages/${sha}/${n}`;

function noSample() {
  return {
    title: "Gold check",
    crumbs: [{ text: "Gold check", href: "#/gold" }],
    content: el(
      "div",
      { class: "page" },
      alertBox({ headline: "No sample has been drawn yet." }),
      el("p", null, el("a", { href: "#/gold" }, "Draw a sample on the Gold check screen")),
    ),
  };
}

export async function show(route, ctx) {
  const feed = await ctx.getJson("/api/gold");
  if (!feed.sample) return noSample();
  const entry = createEntry(ctx, feed);
  await entry.open(route.sha, route.page, { first: true });
  return {
    title: `${entry.name()} · page ${route.page}`,
    crumbs: [{ text: "Gold check", href: "#/gold" }, { text: entry.name(), sub: `page ${route.page}` }],
    content: entry.root,
    dispose: entry.dispose,
  };
}

function createEntry(ctx, feed) {
  const storage = ctx.storage;
  const state = {
    pages: feed.pages.map((p) => ({ ...p })),
    sha: null,
    page: null,
    name: "",
    docPages: 0,
    pdf: "ok",
    tables: [],
    active: 0,
    done: false,
    zoom: Number(storage?.getItem(ZOOM_KEY)) || 1.75,
    view: "page",
    lock: null,
    unsaved: false, // a save could not reach the server
  };
  const timer = makeTimer();
  let saveTimer = null;
  let retryTimer = null;
  let toastTimer = null;
  let observer = null;
  let loadedKey = "";
  const cleanups = [];
  const listen = (target, name, fn, options) => {
    target.addEventListener(name, fn, options);
    cleanups.push(() => target.removeEventListener(name, fn, options));
  };

  // -- the pieces of the screen -------------------------------------------------------------
  const offline = el("div", { class: "gold-offline", role: "alert", hidden: true });
  const progress = el("progress", { max: 1, value: 0 });
  const progressText = el("span");
  const activity = el(
    "div",
    { class: "gold-activity", role: "status", "aria-label": "Progress" },
    progress,
    progressText,
  );
  const feedList = el("ol", { class: "gold-feed-list" });
  const feedCount = el("p", { class: "gold-feed-count" });
  const feedNav = el(
    "nav",
    { class: "gold-feed", "aria-label": "Sampled pages" },
    el("h2", null, "Sampled pages"),
    feedCount,
    feedList,
  );
  const pageTitle = el("strong");
  const toast = el("span", { class: "gold-toast", role: "status", hidden: true });
  const pageImage = el("img", { class: "gold-page-image", alt: "The page" });
  const textSvg = document.createElementNS(SVG_NS, "svg");
  textSvg.setAttribute("class", "gold-text-layer");
  textSvg.setAttribute("preserveAspectRatio", "none");
  const pageBox = el("div", { class: "gold-page-box" }, pageImage, textSvg);
  const docPages = el("div", { class: "gold-doc-pages", hidden: true });
  const docBanner = el(
    "div",
    { class: "gold-doc-banner", role: "status", hidden: true },
    "WHOLE PDF: showing every page of this document, not just the sampled page",
  );
  const noPdf = el("div", { hidden: true });
  const viewArea = el("div", { class: "gold-view-area" }, noPdf, pageBox, docPages);
  const showPage = el("button", { type: "button", "aria-pressed": "true", onclick: () => setView("page") }, "This page");
  const showDoc = el("button", { type: "button", "aria-pressed": "false", onclick: () => setView("doc") }, "Whole PDF");
  const toggleFeed = el(
    "button",
    { type: "button", "aria-pressed": "true", title: "Show or hide the page list", onclick: () => setFeedHidden(!root.classList.contains("feed-hidden")) },
    "☰ Pages",
  );
  const viewer = el(
    "section",
    { class: "gold-viewer", "aria-label": "Page viewer" },
    el(
      "div",
      { class: "gold-toolbar" },
      toggleFeed,
      pageTitle,
      el("span", { class: "gold-group", role: "group", "aria-label": "View" }, showPage, showDoc),
      el(
        "span",
        { class: "gold-group", role: "group", "aria-label": "Rotate and zoom" },
        el("button", { type: "button", title: "Rotate left", onclick: () => turnPage(-90) }, "⟲"),
        el("button", { type: "button", title: "Rotate right", onclick: () => turnPage(90) }, "⟳"),
        el("button", { type: "button", title: "Zoom out", onclick: () => zoomTo(state.zoom / 1.25) }, "−"),
        el("button", { type: "button", title: "Zoom in", onclick: () => zoomTo(state.zoom * 1.25) }, "+"),
        el("button", { type: "button", onclick: () => zoomTo(1) }, "Fit"),
      ),
      toast,
    ),
    docBanner,
    viewArea,
  );

  const tableEl = el("table", { class: "gold-table" });
  const keysEl = el("textarea", {
    class: "gold-keys",
    "aria-label": "Table keyboard input",
    tabindex: -1,
  });
  const grid = mountGrid(
    tableEl,
    keysEl,
    () => state.tables[state.active],
    () => scheduleSave(),
  );

  const tabs = el("div", { class: "gold-tabs", role: "group", "aria-label": "Tables on this page" });
  const lockColumn = el("button", { type: "button", "aria-pressed": "false", title: "Lock column: text you select on the page goes into the selected cell, then the selection moves down the column", onclick: () => setLock("column") }, "Lock column");
  const lockRow = el("button", { type: "button", "aria-pressed": "false", title: "Lock row: text you select on the page goes into the selected cell, then the selection moves right, wrapping to the next row", onclick: () => setLock("row") }, "Lock row");
  const doneBox = el("input", { type: "checkbox", id: "gold-done", onchange: onDone });
  const saveState = el("span", { class: "gold-save-state", role: "status" });
  const timerEl = el("span", { class: "gold-timer", title: "Time on this page, from when it is first opened until it is marked done (-- for pages finished before timing)" });
  const editor = el(
    "section",
    { class: "gold-editor", "aria-label": "Table" },
    el(
      "div",
      { class: "gold-toolbar" },
      el("button", { type: "button", onclick: () => grid.addColumn() }, "Add column"),
      el("button", { type: "button", onclick: () => grid.addRow() }, "New row"),
      lockColumn,
      lockRow,
      el("button", { type: "button", title: "Undo (⌘Z)", onclick: () => grid.undo() }, "Undo"),
      el("button", { type: "button", title: "Redo (⇧⌘Z or ⌘Y)", onclick: () => grid.redo() }, "Redo"),
      el("label", null, doneBox, " Page done"),
      saveState,
      el("button", { type: "button", class: "gold-reset", title: "Set this page's time back to 0 and start counting again", onclick: resetTimer }, "Reset timer"),
      timerEl,
    ),
    tabs,
    el(
      "p",
      { class: "gold-hint" },
      "Type every printed row of each table on this page. Name every column, even on continuation pages. ",
      "A page with no table: leave the editor empty and mark the page done. ",
      "Keys work as in a spreadsheet; double-click or Enter edits a cell, and Option+Enter adds a line break.",
    ),
    el("div", { class: "gold-table-wrap" }, tableEl),
    keysEl,
  );

  const root = el("div", { class: "gold-entry" }, offline, activity, feedNav, viewer, editor);
  if (storage?.getItem(FEED_KEY)) root.classList.add("feed-hidden");
  toggleFeed.setAttribute("aria-pressed", String(!root.classList.contains("feed-hidden")));

  // -- state helpers ------------------------------------------------------------------------
  const away = () => document.hidden || !document.hasFocus();
  const canRun = () => state.sha !== null && !state.done && !away();
  const currentEntry = () => state.pages.find((p) => p.sha256 === state.sha && p.page === state.page);
  const rotationKey = () => `quotable.gold.rot:${state.sha}:${state.page}`;
  const rotation = () => Number(storage?.getItem(rotationKey()) || 0);

  function say(message, error = false) {
    saveState.textContent = message;
    saveState.className = error ? "gold-save-state error" : "gold-save-state";
  }

  function notify(message) {
    toast.textContent = message;
    toast.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => (toast.hidden = true), 1500);
  }

  function setFeedHidden(hidden) {
    root.classList.toggle("feed-hidden", hidden);
    toggleFeed.setAttribute("aria-pressed", String(!hidden));
    try {
      if (hidden) storage?.setItem(FEED_KEY, "1");
      else storage?.removeItem(FEED_KEY);
    } catch {
      // a display preference; blocked storage just forgets it
    }
  }

  // -- progress, clock, list ----------------------------------------------------------------
  function renderActivity() {
    const records = state.pages.map((p) => ({ done: p.status === "done", seconds: p.seconds }));
    const line = progressLine(records, { notDone: !state.done && state.sha !== null, elapsed: timer.elapsed() ?? 0 });
    progress.value = line.fraction;
    progressText.textContent = line.text;
    feedCount.textContent = `${line.done} of ${line.total} done`;
  }

  function renderTimer() {
    timerEl.textContent = `⏱ ${clock(timer.elapsed())}`;
    timerEl.classList.toggle("running", timer.running);
    renderActivity();
  }

  function renderFeed() {
    feedList.replaceChildren(
      ...state.pages.map((p) => {
        const time = p.status === "done" || p.seconds ? ` · ${clock(p.seconds)}` : "";
        return el(
          "li",
          null,
          el(
            "button",
            {
              type: "button",
              class: `gold-feed-item ${p.status}`,
              "aria-current": keyOf(p) === `${state.sha}:${state.page}` ? "true" : "false",
              onclick: () => openPage(p.sha256, p.page),
            },
            el("span", { class: "doc" }, p.name),
            el("span", { class: "meta" }, `page ${p.page} · ${p.status}${time}`),
          ),
        );
      }),
    );
  }

  // -- the page viewer ----------------------------------------------------------------------
  async function loadWords(svg, img, sha, n, rot) {
    let data;
    try {
      data = await ctx.getJson(`${pagePath(sha, n)}/words`);
    } catch {
      return; // no PDF, so no text to select; the image says why
    }
    if (img.getAttribute("src") !== `${pagePath(sha, n)}.png?rot=${rot}`) return;
    renderTextLayer(svg, data, rot);
  }

  function renderViewer() {
    const isDoc = state.view === "doc";
    const rot = rotation();
    pageTitle.textContent = `${state.name} · page ${state.page}`;
    const broken = state.pdf !== "ok";
    noPdf.hidden = !broken;
    if (broken) {
      noPdf.replaceChildren(
        alertBox({
          headline: state.pdf === "missing" ? "The PDF is missing." : "The PDF has changed.",
          text: "The page cannot be shown. What you typed is kept; open the PDF again to carry on.",
        }),
      );
    }
    pageBox.hidden = isDoc || broken;
    docPages.hidden = !isDoc || broken;
    docBanner.hidden = !isDoc || broken;
    viewer.classList.toggle("doc-mode", isDoc);
    showPage.setAttribute("aria-pressed", String(!isDoc));
    showDoc.setAttribute("aria-pressed", String(isDoc));
    if (broken) return;
    if (isDoc) {
      renderDocPages(rot);
      return;
    }
    const src = `${pagePath(state.sha, state.page)}.png?rot=${rot}`;
    if (pageImage.getAttribute("src") !== src) {
      pageImage.setAttribute("src", src);
      loadWords(textSvg, pageImage, state.sha, state.page, rot);
    }
    pageBox.style.setProperty("width", `${state.zoom * 100}%`);
  }

  // Whole PDF: every page stacked, each an image with the same selectable text, loaded as it
  // scrolls near. All take the open page's turn.
  function renderDocPages(rot) {
    docPages.style.setProperty("width", `${state.zoom * 100}%`);
    const id = `${state.sha}:${rot}`;
    if (docPages.dataset.id !== id) {
      docPages.dataset.id = id;
      delete docPages.dataset.page;
      observer?.disconnect();
      observer = new IntersectionObserver(
        (entries) => {
          for (const entry of entries.filter((e) => e.isIntersecting)) {
            observer.unobserve(entry.target);
            const img = entry.target.querySelector("img");
            const svg = entry.target.querySelector("svg");
            const n = Number(entry.target.dataset.n);
            img.addEventListener("load", () => entry.target.classList.remove("waiting"), { once: true });
            img.setAttribute("src", `${pagePath(state.sha, n)}.png?rot=${rot}`);
            loadWords(svg, img, state.sha, n, rot);
          }
        },
        { root: viewArea, rootMargin: "1500px 0px" },
      );
      const boxes = Array.from({ length: state.docPages }, (_, i) => {
        const svg = document.createElementNS(SVG_NS, "svg");
        svg.setAttribute("class", "gold-text-layer");
        svg.setAttribute("preserveAspectRatio", "none");
        const box = el(
          "div",
          { class: "gold-page-box waiting", "data-n": i + 1 },
          el("span", { class: "gold-page-label" }, `page ${i + 1}`),
          el("img", { class: "gold-page-image", alt: `Page ${i + 1}` }),
          svg,
        );
        observer.observe(box);
        return box;
      });
      docPages.replaceChildren(...boxes);
    }
    if (docPages.dataset.page !== String(state.page)) {
      docPages.dataset.page = String(state.page);
      for (const box of docPages.children) box.classList.toggle("sampled", box.dataset.n === String(state.page));
      docPages.querySelector(".sampled")?.scrollIntoView({ block: "start" });
    }
  }

  function setView(view) {
    state.view = view;
    renderViewer();
  }

  function turnPage(step) {
    try {
      storage?.setItem(rotationKey(), String(nextRotation(rotation(), step)));
    } catch {
      // the turn is a display preference
    }
    renderViewer();
  }

  // Zoom the page image, keeping the point under the pointer (or the centre) still.
  function zoomTo(zoom, at) {
    const target = state.view === "doc" ? docPages : pageBox;
    const box = viewArea.getBoundingClientRect();
    const x = at ? at.clientX - box.left : viewArea.clientWidth / 2;
    const y = at ? at.clientY - box.top : viewArea.clientHeight / 2;
    const fx = (viewArea.scrollLeft + x) / (target.offsetWidth || 1);
    const fy = (viewArea.scrollTop + y) / (target.offsetHeight || 1);
    state.zoom = Math.min(6, Math.max(0.25, zoom));
    try {
      storage?.setItem(ZOOM_KEY, String(state.zoom));
    } catch {
      // a display preference
    }
    target.style.setProperty("width", `${state.zoom * 100}%`);
    viewArea.scrollLeft = fx * target.offsetWidth - x;
    viewArea.scrollTop = fy * target.offsetHeight - y;
  }

  // -- the tables ---------------------------------------------------------------------------
  function renderTabs() {
    const count = state.tables.length;
    tabs.replaceChildren(
      ...state.tables.map((t, i) =>
        el(
          "button",
          { type: "button", "aria-pressed": String(i === state.active), onclick: () => switchTable(i) },
          `Table ${i + 1}${isBlank(t) ? " (empty)" : ""}`,
        ),
      ),
      el("button", { type: "button", onclick: onAddTable }, "Add table"),
      el("button", { type: "button", disabled: count < 2 && isBlank(state.tables[0]), onclick: onRemoveTable }, "Remove table"),
    );
  }

  // shortcut: the undo history is the table on screen's, so switching, adding or removing a
  // table starts it again; upgrade to one history per table if typists ask to undo across them.
  function switchTable(index) {
    grid.commit();
    state.active = index;
    grid.reset();
    renderTabs();
  }

  function onAddTable() {
    grid.commit();
    state.active = addTable(state.tables);
    grid.reset();
    renderTabs();
    scheduleSave();
  }

  function onRemoveTable() {
    grid.commit();
    const table = state.tables[state.active];
    if (!isBlank(table) && !confirm(`Remove table ${state.active + 1} and everything typed in it?`)) return;
    state.active = removeTable(state.tables, state.active);
    grid.reset();
    renderTabs();
    scheduleSave();
  }

  function setLock(mode) {
    state.lock = state.lock === mode ? null : mode;
    lockColumn.setAttribute("aria-pressed", String(state.lock === "column"));
    lockRow.setAttribute("aria-pressed", String(state.lock === "row"));
    grid.setLock(state.lock);
  }

  // -- saving -------------------------------------------------------------------------------
  function scheduleSave() {
    clearTimeout(saveTimer);
    say("Unsaved");
    saveTimer = setTimeout(save, SAVE_DELAY_MS);
    renderTabs();
  }

  function serverDown(down, what = "") {
    offline.hidden = !down;
    if (down) {
      offline.textContent =
        `⚠ CANNOT REACH THE SERVER${what}. Your latest changes are NOT saved. ` +
        `Keep this tab open and restart \`quotable review\`; saving retries every ${RETRY_MS / 1000}s.`;
    }
  }

  // Returns true when saved, false when the server refused the page (the message is shown),
  // null when it could not be reached. The page's own table stays in the browser either way.
  async function save() {
    clearTimeout(saveTimer);
    saveTimer = null;
    clearTimeout(retryTimer);
    retryTimer = null;
    const elapsed = timer.elapsed();
    const body = {
      tables: toPayload(state.tables),
      done: state.done,
      seconds: elapsed === null ? null : Math.round(elapsed * 10) / 10,
    };
    const where = `${state.name} page ${state.page}`;
    let response;
    let data;
    try {
      response = await fetch(pagePath(state.sha, state.page), {
        method: "PUT",
        keepalive: true, // lets a save started as the tab is hidden or closed finish
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      data = await response.json();
      if (response.status >= 500) throw new Error(data?.error || String(response.status));
    } catch {
      state.unsaved = true;
      serverDown(true, ` (saving ${where})`);
      say("NOT SAVED: server unreachable", true);
      retryTimer = setTimeout(save, RETRY_MS);
      return null;
    }
    state.unsaved = false;
    serverDown(false);
    if (!response.ok) {
      say(`Not saved: ${data.error}`, true);
      return false;
    }
    const entry = currentEntry();
    if (entry) {
      entry.status = pageStatus(state.tables, state.done);
      entry.seconds = data.seconds;
    }
    say("Saved");
    renderFeed();
    renderActivity();
    return true;
  }

  async function onDone(event) {
    const checked = event.target.checked;
    if (checked) {
      grid.commit();
      const message = problem(state.tables);
      if (message) {
        event.target.checked = false;
        say(`Not saved: ${message}`, true);
        return;
      }
      state.done = true;
      timer.pause(); // marking done stops the clock
      for (const t of state.tables) trimBottom(t);
      grid.render();
    } else {
      state.done = false;
    }
    const ok = await save();
    // refused by the server: undo the tick; unreachable: keep it, the retry saves it
    if (ok === false) event.target.checked = state.done = false;
    timer.run(canRun()); // reopened: carry on
    renderTimer();
    if (checked && ok) {
      const at = state.pages.findIndex((p) => p.sha256 === state.sha && p.page === state.page);
      const order = [...state.pages.slice(at + 1), ...state.pages.slice(0, at)];
      const next = order.find((p) => p.status !== "done");
      if (next) openPage(next.sha256, next.page);
      else notify("All pages are done");
    }
  }

  function resetTimer() {
    const elapsed = timer.elapsed();
    if (elapsed && !confirm(`Reset this page's time (${clock(elapsed)}) to 0?`)) return;
    timer.reset();
    timer.run(canRun());
    renderTimer();
    save();
  }

  // -- opening a page -----------------------------------------------------------------------
  async function openPage(sha, n, { first = false } = {}) {
    if (!first) {
      grid.commit();
      const wasTiming = timer.pause();
      if ((saveTimer || wasTiming || state.unsaved) && (await save()) === null) {
        timer.run(canRun()); // stay on this page: its table is not on disk yet
        notify("Not switching pages: this page is not saved yet");
        return false;
      }
    }
    let data;
    try {
      data = await ctx.getJson(pagePath(sha, n));
    } catch (error) {
      if (first) throw error;
      notify(error.message);
      timer.run(canRun());
      return false;
    }
    const record = data.record;
    Object.assign(state, {
      sha,
      page: n,
      name: data.name,
      docPages: data.pages,
      pdf: data.pdf,
      done: Boolean(record?.done),
      active: 0,
    });
    state.tables = fromRecord(record, { pad: !state.done });
    // a page finished before timing existed shows "--" and is never timed again
    timer.set(record?.done && record.seconds == null ? null : (record?.seconds ?? 0));
    timer.run(canRun());
    loadedKey = `${sha}:${n}`;
    ctx.replace({ name: "goldpage", sha, page: n });
    say("");
    doneBox.checked = state.done;
    const noPdfToFinish = state.pdf !== "ok" && !state.done;
    doneBox.disabled = noPdfToFinish;
    doneBox.title = noPdfToFinish ? "The PDF is missing or has changed, so this page cannot be marked done" : "";
    renderTimer();
    renderFeed();
    renderTabs();
    renderViewer();
    grid.reset();
    return true;
  }

  // -- the keyboard -------------------------------------------------------------------------
  // Every key goes to the table, wherever the focus is (the page, the page list, a button), so
  // nothing scrolls the viewer or the lists. Only a text box being typed in keeps its own keys,
  // and browser shortcuts (⌘L, ⌘T, F5, ...) are left alone. Keys the table has no use for
  // (Home, End, Page Up/Down) are swallowed.
  let pageSelection = null; // the page highlight, put back after a clipboard shortcut
  function onKeyDown(e) {
    const active = document.activeElement;
    if (e.isComposing || active === keysEl) return;
    if (active?.matches('textarea, [contenteditable], input:not([type="checkbox"])')) return;
    const k = e.key.toLowerCase();
    // Arrows, Home, End and Page Up/Down are the table's with any modifier, so ⌘+arrow jumps
    // to the table's edge and never scrolls or goes back a page.
    if (k.startsWith("arrow") || KEYS_SCROLL.has(k)) {
      e.preventDefault();
      if (k.startsWith("arrow")) grid.key(e);
      return;
    }
    if (e.metaKey || e.ctrlKey) {
      if (k === "z" || k === "y") {
        e.preventDefault();
        if (k === "y" || e.shiftKey) grid.redo();
        else grid.undo();
      } else if (k.length === 1 && "cxv".includes(k)) {
        // copy, cut and paste work through the table's hidden text box, which needs the focus
        // for this one key; the highlight on the page is restored on key up
        const sel = window.getSelection();
        pageSelection = sel.rangeCount ? sel.getRangeAt(0).cloneRange() : null;
        keysEl.focus({ preventScroll: true });
        grid.key(e);
      } else if (k.length === 1 && "adr".includes(k)) {
        grid.key(e);
      }
      return;
    }
    if (e.altKey || !(KEYS_SWALLOWED.has(e.key) || e.key.length === 1)) return;
    e.preventDefault();
    grid.key(e);
  }

  function onKeyUp() {
    if (!pageSelection) return;
    const range = pageSelection;
    pageSelection = null;
    keysEl.blur();
    const sel = window.getSelection();
    sel.removeAllRanges();
    sel.addRange(range);
  }

  // Shift tints the target cell while it is held in a lock mode, since a copy then adds to the
  // cell ("A.B") instead of replacing it and moving on.
  const showAppend = (on) => tableEl.classList.toggle("append", on && Boolean(state.lock));

  // -- wiring -------------------------------------------------------------------------------
  listen(document, "keydown", onKeyDown);
  listen(document, "keyup", onKeyUp);
  listen(window, "keydown", (e) => e.key === "Shift" && showAppend(true));
  listen(window, "keyup", (e) => e.key === "Shift" && showAppend(false));
  listen(window, "blur", () => showAppend(false));
  listen(
    viewArea,
    "wheel",
    (e) => {
      if (!e.ctrlKey) return;
      e.preventDefault(); // trackpad pinch arrives as ctrl+wheel in Chrome and Firefox
      zoomTo(state.zoom * Math.exp(-e.deltaY * 0.01), e);
    },
    { passive: false },
  );
  let gestureStart = 1;
  listen(viewArea, "gesturestart", (e) => {
    e.preventDefault();
    gestureStart = state.zoom;
  });
  listen(viewArea, "gesturechange", (e) => {
    e.preventDefault();
    zoomTo(gestureStart * e.scale, e);
  });
  cleanups.push(
    watchSelection(viewArea, {
      shiftClears: () => Boolean(state.lock),
      onText: (text, shift) => {
        const short = shortNote(text);
        if (state.lock) {
          const where = grid.pasteNext(text, shift); // Shift on release adds to the cell
          notify(`${shift ? "Added to" : "Pasted into"} ${where}: ${short}`);
        } else {
          notify(`Copied: ${short}`);
        }
      },
      onFail: () => notify("Could not copy; press ⌘C"),
    }),
  );
  listen(window, "beforeunload", (e) => {
    if (saveTimer || state.unsaved) e.preventDefault();
  });
  // The clock stops when the tab is hidden or another window is in front, and the time so far is
  // saved then. It runs again when this window is back.
  const leave = () => {
    if (timer.pause() || saveTimer) save();
    renderTimer();
  };
  const back = () => {
    timer.run(canRun());
    renderTimer();
  };
  listen(document, "visibilitychange", () => (document.hidden ? leave() : back()));
  listen(window, "blur", leave);
  listen(window, "focus", back);
  const tick = setInterval(renderTimer, 1000);
  // A small request every few seconds, so a dead server shows even when idle.
  const heartbeat = setInterval(async () => {
    try {
      const res = await fetch("/", { method: "GET", cache: "no-store" });
      if (!res.ok) throw new Error(String(res.status));
      if (!state.unsaved) serverDown(false);
    } catch {
      serverDown(true);
    }
  }, 5000);

  function dispose() {
    clearInterval(tick);
    clearInterval(heartbeat);
    clearTimeout(toastTimer);
    clearTimeout(retryTimer);
    observer?.disconnect();
    grid.commit();
    if ((timer.pause() || saveTimer || state.unsaved) && loadedKey) save();
    clearTimeout(saveTimer);
    for (const stop of cleanups) stop();
  }

  return { root, open: openPage, name: () => state.name, dispose };
}
