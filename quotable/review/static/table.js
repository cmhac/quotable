// The table screen (spec 013 C3, C6): a table's rows as a grid, with filters, sort and paging
// that live in the URL. The server filters, sorts and pages; this file only asks and draws.

import { apiUrl } from "./api.js";
import { alertBox } from "./chrome.js";
import { el } from "./dom.js";
import { number, pagesAbbr, pagesText, plural } from "./format.js";
import { hashFor } from "./route.js";
import { badge, STATUSES, statusText } from "./status.js";

const REVIEWS = [
  ["any", "Any review state"],
  ["unreviewed", "Not reviewed"],
  ["correct", "Correct"],
  ["changed", "Changed"],
  ["unsure", "Can’t tell"],
  ["note", "Has a note"],
];
const FLAGS = [
  ["flagged", "Flagged rows only"],
  ["recheck", "Changed by recheck"],
  ["ocr", "On OCR’d pages"],
  ["merged", "From a merged part"],
];
const MAIN_LABEL = {
  none: { text: "Not reviewed", tone: "none" },
  correct: { text: "✓ Correct", tone: "correct" },
  changed: { text: "✎ Changed", tone: "changed" },
  unsure: { text: "? Can’t tell", tone: "unsure" },
};
const PAUSE = 250;
const DIGITS = /^[0-9]+$/;

const classes = (...names) => names.filter(Boolean).join(" ") || null;

// --- the filters, sort and paging as one value -------------------------------------------------
export function parseState(query) {
  const given = (query?.status ?? "").split(",");
  const flag = (name) => query?.[name] === "1" || query?.[name] === "true";
  return {
    statuses: STATUSES.filter((status) => given.includes(status)),
    q: query?.q ?? "",
    column: query?.column ?? "",
    page: DIGITS.test(query?.page ?? "") ? query.page : "",
    review: REVIEWS.some(([value]) => value === query?.review)
      ? query.review
      : "any",
    flagged: flag("flagged"),
    recheck: flag("recheck"),
    ocr: flag("ocr"),
    merged: flag("merged"),
    sort: query?.sort ?? "",
    desc: flag("desc"),
    offset: DIGITS.test(query?.offset ?? "") ? Number(query.offset) : 0,
    open: query?.open ?? "",
  };
}

export function stateQuery(state) {
  const all = {
    status: state.statuses.join(","),
    q: state.q,
    column: state.column,
    page: state.page,
    review: state.review === "any" ? "" : state.review,
    flagged: state.flagged ? "1" : "",
    recheck: state.recheck ? "1" : "",
    ocr: state.ocr ? "1" : "",
    merged: state.merged ? "1" : "",
    sort: state.sort,
    desc: state.desc ? "1" : "",
    offset: state.offset ? String(state.offset) : "",
    open: state.open,
  };
  return Object.fromEntries(
    Object.entries(all).filter(([, value]) => value !== ""),
  );
}

export function apiQuery(state) {
  const { open: _open, ...query } = stateQuery(state);
  return query;
}

export function cellQuery(state) {
  const { open: _open, offset: _offset, ...query } = stateQuery(state);
  return query;
}

export function toggleStatus(state, status) {
  const statuses = STATUSES.filter(
    (s) => (s === status) !== state.statuses.includes(s),
  );
  return { ...state, statuses, offset: 0 };
}

export function hasFilters(state) {
  return Boolean(
    state.statuses.length ||
    state.q ||
    state.column ||
    state.page ||
    state.review !== "any" ||
    state.flagged ||
    state.recheck ||
    state.ocr ||
    state.merged,
  );
}

export function clearFilters(state) {
  return {
    ...state,
    statuses: [],
    q: "",
    column: "",
    page: "",
    review: "any",
    flagged: false,
    recheck: false,
    ocr: false,
    merged: false,
    offset: 0,
  };
}

export function nextSort(state, key, pageKey) {
  const reverse = (state.sort || pageKey) === key && !state.desc;
  return {
    ...state,
    sort: key === pageKey && !reverse ? "" : key,
    desc: reverse,
    offset: 0,
  };
}

export function sortText(sort, columns) {
  const name = (key) => columns.find((c) => c.key === key)?.name ?? key;
  const page = columns.find((c) => c.kind === "page");
  const row = columns.find((c) => c.kind === "row");
  const way = sort.desc ? "descending" : "ascending";
  const what =
    page && sort.column === page.key
      ? `${page.name}, ${row?.name ?? "row"}${sort.desc ? " (descending)" : ""}`
      : `${name(sort.column)} (${way})`;
  return `Sorted by ${what} · click a column heading to sort`;
}

// --- the heading -------------------------------------------------------------------------------
export function headView(runId, info, matched, state) {
  const where = [
    `Table ${info.number}`,
    pagesText(info.pages),
    plural(info.rows, "row"),
    info.merged ? plural(info.merged, "merged part") : "",
    info.ocr_pages.length ? `OCR on ${pagesAbbr(info.ocr_pages)}` : "",
  ].filter(Boolean);
  const csv = apiUrl(
    `/api/runs/${encodeURIComponent(runId)}/tables/${info.index}/rows.csv`,
    cellQuery(state),
  );
  return el(
    "div",
    { class: "head table-head" },
    el(
      "div",
      { class: "titles" },
      el("div", { class: "where mono" }, where.join(" · ")),
      el("h1", null, info.label || `Table ${info.number}`),
    ),
    el(
      "a",
      {
        class: "btn",
        href: hashFor({
          name: "queue",
          query: { run: runId, table: info.index },
        }),
      },
      "Review flagged cells",
    ),
    el(
      "a",
      { class: "btn download", href: csv, download: true },
      `Download ${plural(matched, "row")} as CSV`,
    ),
  );
}

// --- the summary -------------------------------------------------------------------------------
export function barParts(summary) {
  return STATUSES.filter((status) => (summary.statuses[status] ?? 0) > 0).map(
    (status) => ({
      status,
      count: summary.statuses[status],
      width: `${+((100 * summary.statuses[status]) / summary.cells).toFixed(2)}%`,
    }),
  );
}

export function summaryView(summary) {
  const accepted = summary.recheck?.accepted ?? 0;
  return el(
    "section",
    { class: "card summary", "aria-label": "Summary" },
    el(
      "div",
      { class: "status-bar" },
      el(
        "div",
        { class: "label" },
        `Cells by status · ${number(summary.cells)}`,
      ),
      el(
        "div",
        { class: "bar-stack", "aria-hidden": "true" },
        barParts(summary).map((part) =>
          el("span", {
            class: `seg seg-${part.status}`,
            style: { width: part.width },
          }),
        ),
      ),
      el(
        "div",
        { class: "counts" },
        STATUSES.map((status) =>
          el(
            "span",
            null,
            `${statusText(status)} `,
            el("b", { class: "mono" }, number(summary.statuses[status] ?? 0)),
          ),
        ),
      ),
    ),
    el(
      "div",
      { class: "checks" },
      el(
        "div",
        null,
        el("div", { class: "label" }, "Position check"),
        el(
          "div",
          { class: "value" },
          el(
            "span",
            { class: "mono" },
            number(summary.position?.misplaced ?? 0),
          ),
          " misplaced · ",
          el(
            "span",
            { class: "mono" },
            number(summary.position?.unchecked ?? 0),
          ),
          " unchecked",
        ),
      ),
      el(
        "div",
        null,
        el("div", { class: "label" }, "Recheck"),
        el(
          "div",
          { class: "value" },
          el("span", { class: "mono" }, number(accepted)),
          ` ${accepted === 1 ? "change" : "changes"} accepted`,
        ),
      ),
    ),
  );
}

// --- the filters card --------------------------------------------------------------------------
function option(value, label) {
  return el("option", { value }, label);
}

export function createFilters({ columns, summary, pages, state, onChange }) {
  let current = state;
  let timer;
  const emit = (next) => {
    clearTimeout(timer);
    current = next;
    paintState();
    onChange(current);
  };
  const change = (patch) => emit({ ...current, ...patch, offset: 0 });

  const chips = STATUSES.map((status) =>
    el(
      "button",
      {
        class: `fchip f-${status}`,
        type: "button",
        "aria-pressed": "false",
        onclick: () => emit(toggleStatus(current, status)),
      },
      `${statusText(status)} `,
      el("span", { class: "mono" }, number(summary.statuses[status] ?? 0)),
    ),
  );
  const search = el("input", {
    class: "search",
    type: "search",
    placeholder: "Search all values of a row",
    "aria-label": "Search",
    oninput: (event) => {
      clearTimeout(timer);
      current = { ...current, q: event.target.value, offset: 0 };
      paintState();
      timer = setTimeout(() => onChange(current), PAUSE);
    },
  });
  const column = el(
    "select",
    {
      class: "sel",
      "aria-label": "Column",
      onchange: (event) => change({ column: event.target.value }),
    },
    option("", "Any column"),
    columns
      .filter((c) => c.kind === "column" || c.kind === "extra")
      .map((c) => option(c.key, c.name)),
  );
  const page = el(
    "select",
    {
      class: "sel",
      "aria-label": "Page",
      onchange: (event) => change({ page: event.target.value }),
    },
    option("", "Any page"),
    [...new Set(pages)]
      .sort((a, b) => a - b)
      .map((p) => option(String(p), String(p))),
  );
  const review = el(
    "select",
    {
      class: "sel",
      "aria-label": "Review state",
      onchange: (event) => change({ review: event.target.value }),
    },
    REVIEWS.map(([value, label]) => option(value, label)),
  );
  const boxes = FLAGS.map(([name]) =>
    el("input", {
      type: "checkbox",
      onchange: (event) => change({ [name]: event.target.checked }),
    }),
  );
  const matches = el("span", { class: "matches" });
  const sorted = el("span", { class: "sorted" });
  const clear = el(
    "button",
    {
      class: "btn small clear",
      type: "button",
      onclick: () => {
        emit(clearFilters(current));
        fill();
      },
    },
    "Clear filters",
  );

  function fill() {
    search.value = current.q;
    column.value = current.column;
    page.value = current.page;
    review.value = current.review;
    FLAGS.forEach(([name], i) => (boxes[i].checked = current[name]));
  }

  function paintState() {
    chips.forEach((chip, i) =>
      chip.setAttribute(
        "aria-pressed",
        String(current.statuses.includes(STATUSES[i])),
      ),
    );
    if (hasFilters(current)) clear.removeAttribute("disabled");
    else clear.setAttribute("disabled", "");
  }

  const node = el(
    "section",
    { class: "card filters-card", "aria-label": "Filters" },
    el(
      "div",
      { class: "row" },
      el("span", { class: "label" }, "Status"),
      chips,
    ),
    el(
      "div",
      { class: "row" },
      el(
        "label",
        { class: "search-field" },
        el("span", { class: "sr" }, "Search"),
        search,
      ),
      column,
      page,
      review,
      FLAGS.map(([, label], i) =>
        el("label", { class: "chk" }, boxes[i], label),
      ),
    ),
    el("div", { class: "row line" }, matches, clear, sorted),
  );
  fill();
  paintState();

  return {
    node,
    sync(matched, total, sort) {
      matches.replaceChildren(
        el("b", { class: "mono" }, number(matched)),
        ` of ${number(total)} ${total === 1 ? "row" : "rows"} match`,
      );
      sorted.replaceChildren(sortText(sort, columns));
    },
  };
}

// --- the grid ----------------------------------------------------------------------------------
const isOpen = (row, open) => open === `${row.page}.${row.row}`;

export function reviewParts(row, open) {
  const r = row.review;
  let main = MAIN_LABEL[r.state] ?? MAIN_LABEL.none;
  if (r.state === "stale")
    main = { text: `Stale · was ${r.was}`, tone: "stale" };
  if (open) main = { text: "◉ Open in review", tone: "open" };
  const rest = [];
  if (r.state !== "none" && r.unreviewed)
    rest.push(`· ${number(r.unreviewed)} not reviewed`);
  if (r.note) rest.push("· note");
  if (r.ocr) rest.push("· OCR page");
  if (r.merged) rest.push("· merged part");
  return { main: { ...main }, rest };
}

function reviewNode(row, open) {
  const { main, rest } = reviewParts(row, open);
  return el(
    "div",
    { class: "rv-label" },
    el("span", { class: `rv rv-${main.tone}` }, main.text),
    rest.map((text) => el("span", { class: "rv-rest" }, text)),
  );
}

function headings(data, onSort, firstExtra) {
  const cols = data.columns;
  const heads = cols.map((col) => {
    const active = data.sort.column === col.key;
    const arrow = active ? (data.sort.desc ? "▼" : "▲") : "↕";
    return el(
      "th",
      {
        scope: "col",
        class: classes(col.numeric && "num", col === firstExtra && "divider"),
        "aria-sort": active
          ? data.sort.desc
            ? "descending"
            : "ascending"
          : "none",
      },
      el(
        "button",
        { type: "button", class: "sort", onclick: () => onSort(col.key) },
        col.name,
        col.kind === "extra"
          ? [" ", el("span", { class: "tag" }, "extra")]
          : null,
        " ",
        el("span", { class: "arrow", "aria-hidden": "true" }, arrow),
      ),
    );
  });
  heads.push(el("th", { scope: "col", class: "review-head" }, "Review"));
  return heads;
}

function byStatusRow(data, firstExtra) {
  const lead = data.columns.filter(
    (c) => c.kind === "page" || c.kind === "row",
  ).length;
  return el(
    "tr",
    { class: "by-status" },
    el("td", { colspan: lead }, "By status"),
    data.columns.slice(lead).map((col) =>
      el(
        "td",
        {
          class: classes(col.numeric && "num", col === firstExtra && "divider"),
        },
        el(
          "div",
          { class: "status-counts mono" },
          STATUSES.filter((status) => col.statuses[status] > 0).map((status) =>
            el("span", null, statusText(status, col.statuses[status])),
          ),
        ),
      ),
    ),
    el("td"),
  );
}

function cellNode(cell, col, href, divider) {
  return el(
    "td",
    { class: classes(col.numeric && "num", divider && "divider") },
    el(
      "a",
      { class: "cell", href },
      el(
        "span",
        {
          class: classes(
            "mono",
            "value",
            cell.status === "ungrounded" && "ungrounded",
          ),
        },
        cell.value,
      ),
      badge(cell.status, undefined, cell.status === "exact"),
    ),
  );
}

function rowNode(row, data, { run, table, state, firstExtra }) {
  const open = isOpen(row, state.open);
  const lead = data.columns.filter(
    (c) => c.kind === "page" || c.kind === "row",
  ).length;
  const query = cellQuery(state);
  return el(
    "tr",
    { class: open ? "open" : null },
    el("td", { class: "num" }, String(row.page)),
    el("td", { class: "num" }, String(row.row)),
    row.cells.map((cell, i) => {
      const col = data.columns[lead + i];
      const href = hashFor({
        name: "cell",
        run,
        table,
        cell: {
          page: row.page,
          row: row.row,
          name: cell.name,
          extra: cell.extra,
        },
        query,
      });
      return cellNode(cell, col, href, col === firstExtra);
    }),
    el("td", { class: "review-cell" }, reviewNode(row, open)),
  );
}

export function gridView(data, { run, table, state, onSort }) {
  const firstExtra = data.columns.find((c) => c.kind === "extra");
  const width = data.columns.length + 1;
  const empty =
    data.total === 0 ? "This table has no rows." : "No rows match the filters.";
  return el(
    "div",
    { class: "grid-scroll" },
    el(
      "table",
      { class: "grid" },
      el(
        "thead",
        null,
        el("tr", null, headings(data, onSort, firstExtra)),
        byStatusRow(data, firstExtra),
      ),
      el(
        "tbody",
        null,
        data.rows.length
          ? data.rows.map((row) =>
              rowNode(row, data, { run, table, state, firstExtra }),
            )
          : el(
              "tr",
              { class: "none-row" },
              el("td", { colspan: width }, empty),
            ),
      ),
    ),
  );
}

// --- the pager ---------------------------------------------------------------------------------
export function pagerView({ offset, limit, matched, shown }, onOffset) {
  const pages = Math.max(1, Math.ceil(matched / limit));
  const current = Math.floor(offset / limit) + 1;
  const go = (page) =>
    onOffset((Math.min(Math.max(page, 1), pages) - 1) * limit);
  const box = el("input", {
    class: "mono page-box",
    type: "text",
    inputmode: "numeric",
    "aria-label": "Page of rows",
    value: String(current),
    onchange: (event) => {
      const typed = event.target.value.trim();
      if (DIGITS.test(typed)) go(Number(typed));
      else event.target.value = String(current);
    },
  });
  const range =
    matched === 0 ? "0" : `${number(offset + 1)}–${number(offset + shown)}`;
  return el(
    "nav",
    { class: "pager", "aria-label": "Pages of rows" },
    el(
      "span",
      { class: "range" },
      "Rows ",
      el("b", { class: "mono" }, range),
      ` of ${number(matched)}`,
    ),
    el("span", { class: "spacer" }),
    el(
      "button",
      {
        class: "btn",
        type: "button",
        disabled: current <= 1,
        onclick: () => go(current - 1),
      },
      "‹ Previous",
    ),
    el("span", { class: "pages" }, "Page ", box, ` of ${number(pages)}`),
    el(
      "button",
      {
        class: "btn",
        type: "button",
        disabled: current >= pages,
        onclick: () => go(current + 1),
      },
      "Next ›",
    ),
  );
}

// --- the screen --------------------------------------------------------------------------------
export async function show(route, ctx) {
  const runId = route.run;
  const index = route.table;
  const rowsPath = `/api/runs/${encodeURIComponent(runId)}/tables/${index}/rows`;
  let state = parseState(route.query);
  const [run, first] = await Promise.all([
    ctx.getJson(`/api/runs/${encodeURIComponent(runId)}`),
    ctx.getJson(rowsPath, apiQuery(state)),
  ]);
  const info = run.tables.find((t) => t.index === index);
  if (!info) throw new Error("no such table");
  const pageKey = first.columns.find((c) => c.kind === "page")?.key;
  const name = info.label
    ? `Table ${info.number} · ${info.label}`
    : `Table ${info.number}`;

  const headSlot = el("div", { class: "head-slot" });
  const results = el("div", { class: "results" });
  let latest = 0;

  const apply = async (next) => {
    state = next;
    const mine = ++latest;
    ctx.replace({
      name: "table",
      run: runId,
      table: index,
      query: stateQuery(next),
    });
    try {
      const data = await ctx.getJson(rowsPath, apiQuery(next));
      if (mine === latest) paint(data, next);
    } catch (error) {
      if (mine === latest)
        results.replaceChildren(
          alertBox({
            headline: "The rows could not be loaded.",
            text: error.message,
          }),
        );
    }
  };
  const filters = createFilters({
    columns: first.columns,
    summary: first.summary,
    pages: info.pages,
    state,
    onChange: apply,
  });

  function paint(data, shown) {
    headSlot.replaceChildren(headView(runId, info, data.matched, shown));
    filters.sync(data.matched, data.total, data.sort);
    results.replaceChildren(
      el(
        "div",
        { class: "card grid-card" },
        gridView(data, {
          run: runId,
          table: index,
          state: shown,
          onSort: (key) => apply(nextSort(state, key, pageKey)),
        }),
        pagerView(
          {
            offset: data.offset,
            limit: data.limit,
            matched: data.matched,
            shown: data.rows.length,
          },
          (offset) => apply({ ...state, offset }),
        ),
      ),
      el(
        "p",
        { class: "note hint" },
        "Select any cell to open its cell view next to the PDF page.",
      ),
    );
  }
  paint(first, state);

  return {
    title: name,
    crumbs: [
      { text: "Runs", href: "#/" },
      {
        text: run.document.name,
        sub: run.short_id,
        href: hashFor({ name: "run", run: runId }),
      },
      { text: name },
    ],
    content: el(
      "div",
      { class: "page table-screen" },
      headSlot,
      summaryView(first.summary),
      filters.node,
      results,
    ),
  };
}
