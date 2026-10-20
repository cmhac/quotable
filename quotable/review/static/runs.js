// The runs list (spec 013 C1): runs grouped by document, newest first, with two filters.

import { alertBox } from "./chrome.js";
import { el } from "./dom.js";
import { costText, flaggedParts, formatTime, number, plural, progressWidth, sizeText } from "./format.js";
import { hashFor } from "./route.js";
import { badge } from "./status.js";

const COLUMNS = [
  ["run", "Run"],
  ["time", "Time"],
  ["model", "Model"],
  ["tables", "Tables", true],
  ["rows", "Rows", true],
  ["cells", "Cells", true],
  ["flagged", "Flagged cells by status"],
  ["ocr", "OCR pages", true],
  ["cost", "Cost", true],
  ["review", "Reviewed / flagged"],
];

export function introView(data) {
  return el(
    "p",
    { class: "lede" },
    `${plural(data.runs, "run")} of ${plural(data.documents.length, "document")} in `,
    el("code", null, ".quotable/runs/"),
    ", newest first. Re-runs of the same PDF are grouped.",
  );
}

function unreadableNote(data) {
  if (!data.unreadable) return null;
  const folders = data.unreadable === 1 ? "run folder" : "run folders";
  return el("p", { class: "unreadable" }, `${number(data.unreadable)} ${folders} could not be read and ${data.unreadable === 1 ? "is" : "are"} not listed.`);
}

export function emptyView(data) {
  const filtered = data.total_runs > 0;
  return el(
    "div",
    { class: "groups" },
    el(
      "section",
      { class: "card empty" },
      filtered
        ? el("p", null, "No runs match the filters.")
        : [
            el("h2", null, "No runs yet."),
            el(
              "p",
              null,
              "Every call of ",
              el("code", null, "extract_tables"),
              " saves its run to ",
              el("code", null, ".quotable/runs/"),
              ". Run it on a PDF, then reload this page.",
            ),
          ],
    ),
    unreadableNote(data),
  );
}

function flaggedCell(run) {
  const parts = flaggedParts(run.flagged);
  if (!parts.length) return el("td", null, el("span", { class: "none" }, "—"));
  return el(
    "td",
    null,
    el(
      "div",
      { class: "chips" },
      parts.map(([status, count]) => badge(status, count)),
      el("span", { class: "total" }, `= ${number(run.flagged_total)}`),
    ),
  );
}

function reviewCell(review) {
  const label = `${number(review.reviewed)} of ${number(review.flagged)} flagged cells reviewed`;
  return el(
    "td",
    null,
    el(
      "div",
      { class: "review" },
      el(
        "span",
        { class: review.done ? "progress done" : "progress", role: "img", "aria-label": label },
        el("span", { class: "fill", style: { width: progressWidth(review) } }),
      ),
      el("span", { class: "count" }, `${number(review.reviewed)} / ${number(review.flagged)}`),
      review.done ? el("span", { class: "done" }, "· done") : null,
    ),
  );
}

function runRow(run, now) {
  const costClass = run.cost.kind === "usd" ? "num" : `num cost-${run.cost.kind}`;
  return el(
    "tr",
    null,
    el("td", null, el("a", { class: "mono", href: hashFor({ name: "run", run: run.id }) }, run.short_id)),
    el("td", null, formatTime(run.started, now)),
    el("td", { class: "mono model" }, run.model),
    el("td", { class: "num" }, number(run.tables)),
    el("td", { class: "num" }, number(run.rows)),
    el("td", { class: "num" }, number(run.cells)),
    flaggedCell(run),
    el("td", { class: "num" }, number(run.ocr_pages.length)),
    el("td", { class: costClass }, costText(run.cost)),
    reviewCell(run.review),
  );
}

function group(doc, now) {
  return el(
    "section",
    { class: "card group" },
    el(
      "div",
      { class: "group-head" },
      el("span", { class: "doc-icon", "aria-hidden": "true" }),
      el("h2", { class: "name" }, doc.name),
      el("span", { class: "sha mono" }, `sha256 ${doc.sha_short}`),
      el("span", { class: "facts" }, `· ${plural(doc.pages, "page")} · ${sizeText(doc.size)}`),
      el("span", { class: "count" }, plural(doc.runs.length, "run")),
    ),
    el(
      "div",
      { class: "table-wrap" },
      el(
        "table",
        { class: "runs" },
        el("colgroup", null, COLUMNS.map(([key]) => el("col", { class: `c-${key}` }))),
        el(
          "thead",
          null,
          el(
            "tr",
            null,
            COLUMNS.map(([, title, numeric]) => el("th", { scope: "col", class: numeric ? "num" : null }, title)),
          ),
        ),
        el("tbody", null, doc.runs.map((run) => runRow(run, now))),
      ),
    ),
  );
}

export function groupsView(data, now = new Date()) {
  return el(
    "div",
    { class: "groups" },
    data.documents.map((doc) => group(doc, now)),
    el(
      "p",
      { class: "note" },
      "Cost is the sum of the run’s records in ",
      el("code", null, ".quotable/cost/"),
      ". “free” = every answer came from the cache; “unknown” = a record has no price.",
    ),
    unreadableNote(data),
  );
}

function paint(data, intro, results) {
  intro.replaceChildren(introView(data));
  results.replaceChildren(data.documents.length ? groupsView(data) : emptyView(data));
}

export async function show(route, ctx) {
  let filters = { document: route.query.document ?? "", model: route.query.model ?? "" };
  const first = await ctx.getJson("/api/runs", filters);
  const models = first.models.includes(filters.model) || !filters.model ? first.models : [...first.models, filters.model];
  const intro = el("div", { class: "intro" });
  const results = el("div", { class: "results" });
  paint(first, intro, results);

  let timer;
  let latest = 0;
  const apply = async () => {
    const mine = ++latest;
    ctx.replace({ name: "runs", query: filters });
    try {
      const data = await ctx.getJson("/api/runs", filters);
      if (mine === latest) paint(data, intro, results);
    } catch (error) {
      if (mine === latest) {
        results.replaceChildren(alertBox({ headline: "The list could not be updated.", text: error.message }));
      }
    }
  };
  const documentInput = el("input", {
    class: "input",
    type: "search",
    placeholder: "Filter by file name",
    value: filters.document,
    oninput: (event) => {
      filters = { ...filters, document: event.target.value };
      clearTimeout(timer);
      timer = setTimeout(apply, 200);
    },
  });
  const modelSelect = el(
    "select",
    {
      class: "input",
      value: filters.model,
      onchange: (event) => {
        filters = { ...filters, model: event.target.value };
        apply();
      },
    },
    el("option", { value: "" }, "All models"),
    models.map((model) => el("option", { value: model }, model)),
  );
  const content = el(
    "div",
    { class: "page" },
    el(
      "div",
      { class: "runs-head" },
      el("div", null, el("h1", null, "Runs"), intro),
      el(
        "div",
        { class: "filters" },
        el("label", { class: "field" }, el("span", null, "Document"), documentInput),
        el("label", { class: "field" }, el("span", null, "Model"), modelSelect),
      ),
    ),
    results,
  );
  return { title: "Runs", crumbs: [{ text: "Runs" }], project: first.project, content };
}
