// The run screen (spec 013 C2): the run and its document, the tables, and the PDF alerts.

import { alertBox } from "./chrome.js";
import { el } from "./dom.js";
import {
  costText,
  formatSpan,
  number,
  pagesAbbr,
  pagesText,
  plural,
  settingValue,
  shortSha,
  sizeText,
  utcSpan,
} from "./format.js";
import { hashFor } from "./route.js";

const SETTINGS = [
  "discovery_pages",
  "recheck",
  "ocr",
  "merge_reworded",
  "max_requests",
];
const CANT_SHOW =
  "Page images can’t be shown. Values, statuses and text still can.";

export function pdfAlert(pdf) {
  if (pdf.status === "missing") {
    return alertBox({
      headline: "The PDF is missing.",
      text: CANT_SHOW,
      detail: `not found: ${pdf.path}`,
    });
  }
  if (pdf.status === "changed") {
    return alertBox({
      headline: "The PDF’s SHA-256 no longer matches.",
      text: CANT_SHOW,
      detail: `expected ${pdf.expected} · found ${pdf.found}`,
    });
  }
  return null;
}

function facts(run, now) {
  const cost =
    run.cost.kind === "unknown" ? "cost unknown" : costText(run.cost);
  return [
    formatSpan(run.started, run.ended, now),
    run.model,
    plural(run.summary.tables, "table"),
    plural(run.summary.rows, "row"),
    plural(run.summary.flagged_total, "flagged cell"),
    cost,
  ].join(" · ");
}

const pair = (term, value, attrs) => [
  el("dt", null, term),
  el("dd", attrs, value),
];

function settings(run) {
  const chips = SETTINGS.map((name) =>
    el(
      "span",
      { class: "chip mono" },
      `${name}=${settingValue(run.settings[name])}`,
    ),
  );
  const extra = run.settings.extra_fields?.fields ?? [];
  return [
    el("h3", { class: "label" }, "Settings that change results"),
    el("div", { class: "chips" }, chips),
    extra.map((field) =>
      el(
        "div",
        { class: "extra-field" },
        el("span", { class: "chip mono" }, "extra_fields"),
        el("span", { class: "mono" }, field.name),
        el(
          "span",
          { class: "desc" },
          `— “${field.description}”${field.group ? ` · group ${field.group}` : ""}`,
        ),
      ),
    ),
  ];
}

function runCard(run) {
  return el(
    "section",
    { class: "card" },
    el("h2", { class: "label" }, "Run"),
    el(
      "dl",
      { class: "kv" },
      pair("Run id", run.id, { class: "mono" }),
      pair("Started · ended", utcSpan(run.started, run.ended), {
        class: "mono",
      }),
      pair("Model", run.model, { class: "mono" }),
      pair("quotable", run.quotable, { class: "mono" }),
      pair("Format", `run format ${run.format}`, { class: "mono" }),
    ),
    settings(run),
  );
}

function documentCard(doc) {
  return el(
    "section",
    { class: "card" },
    el("h2", { class: "label" }, "Document"),
    el(
      "dl",
      { class: "kv" },
      pair("File", doc.name, { class: "mono" }),
      pair("Path", doc.path, { class: "mono path" }),
      pair(
        "Size · pages",
        `${sizeText(doc.size)} · ${plural(doc.pages, "page")}`,
        { class: "mono" },
      ),
      pair("SHA-256", shortSha(doc.sha256, 10, 8), {
        class: "mono",
        title: doc.sha256,
      }),
    ),
  );
}

const stat = (name, value) =>
  el(
    "div",
    { class: "stat" },
    el("span", { class: "k" }, name),
    el("span", { class: "v mono" }, value),
  );

function tableCard(run, table) {
  const extra = table.extra_names.map((name) => `${name} (extra)`);
  const columns =
    table.columns.join(" · ") + (extra.length ? ` + ${extra.join(" · ")}` : "");
  const ocr = table.ocr_pages.length
    ? `${number(table.ocr_pages.length)} (${pagesAbbr(table.ocr_pages)})`
    : "0";
  const where = [`Table ${table.number}`, pagesText(table.pages)]
    .filter(Boolean)
    .join(" · ");
  return el(
    "a",
    {
      class: "card table-card",
      href: hashFor({ name: "table", run: run.id, table: table.index }),
    },
    el(
      "div",
      { class: "info" },
      el("div", { class: "where mono" }, where),
      el("div", { class: "title" }, table.label || `Table ${table.number}`),
      el("div", { class: "columns mono" }, columns),
    ),
    el(
      "div",
      { class: "stats" },
      stat("Rows", number(table.rows)),
      stat("Flagged", number(table.flagged_total)),
      stat("Merged parts", number(table.merged)),
      stat("OCR pages", ocr),
    ),
    table.note.length
      ? el(
          "div",
          { class: "table-note" },
          table.note.map((n) => el("div", null, n.text)),
        )
      : null,
  );
}

export function runView(run, now = new Date()) {
  const { reviewed, flagged } = run.review;
  return el(
    "div",
    { class: "run-view" },
    el(
      "div",
      { class: "head" },
      el(
        "div",
        { class: "titles" },
        el("div", { class: "label" }, `Run ${run.short_id}`),
        el("h1", null, run.document.name),
        el("p", { class: "facts" }, facts(run, now)),
      ),
      el(
        "a",
        {
          class: "btn primary",
          href: hashFor({ name: "queue", query: { run: run.id } }),
        },
        `Review this run · ${number(reviewed)} / ${number(flagged)}`,
      ),
    ),
    pdfAlert(run.pdf),
    el("div", { class: "cards" }, runCard(run), documentCard(run.document)),
    el(
      "section",
      { class: "tables" },
      el(
        "h2",
        { class: "section-title" },
        el("b", null, "Tables"),
        el("span", null, "· in the order extract_tables returned them"),
      ),
      run.tables.map((table) => tableCard(run, table)),
    ),
  );
}

export async function show(route, ctx) {
  const run = await ctx.getJson(`/api/runs/${encodeURIComponent(route.run)}`);
  return {
    title: `${run.document.name} · run ${run.short_id}`,
    crumbs: [
      { text: "Runs", href: "#/" },
      { text: run.document.name, sub: run.short_id },
    ],
    content: el("div", { class: "page" }, runView(run)),
  };
}
