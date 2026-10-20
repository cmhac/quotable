// The cell view (right half of the cell screen): heading, status, value, row and the sections.
// Values come from a PDF and a model, so they only ever go in as text.

import { el } from "./dom.js";
import { badge } from "./status.js";
import { number, pagesAbbr } from "./format.js";

const CUT = 40;
const MOVES = [
  ["previous", "K", "Previous cell"],
  ["next", "J", "Next cell"],
  ["previous_row", "[", "Previous row"],
  ["next_row", "]", "Next row"],
  ["next_unreviewed", "N", "Next unreviewed"],
];

const classes = (...names) => names.filter(Boolean).join(" ") || null;
const cut = (value) =>
  value.length > CUT ? `${value.slice(0, CUT - 1)}…` : value;
const decimals = (n) => (n === null || n === undefined ? "—" : n.toFixed(2));

export function moveTargets(cell) {
  return Object.fromEntries(
    MOVES.map(([name]) => [name, cell.nav?.[name] ?? null]),
  );
}

export function headingView(cell, hrefFor) {
  const { n, of } = cell.nav ?? {};
  const targets = moveTargets(cell);
  return el(
    "div",
    { class: "cell-head" },
    el("h2", null, n ? `Cell ${number(n)} of ${number(of)}` : "Cell"),
    el(
      "div",
      { class: "where" },
      el("b", null, cell.name),
      cell.kind === "extra" ? el("span", { class: "tag" }, "extra") : null,
      ` · page ${cell.page} · row ${cell.row}`,
    ),
    el(
      "div",
      { class: "moves" },
      MOVES.map(([name, key, label]) => {
        const target = targets[name];
        const inner = [el("span", { class: "key" }, key), label];
        return target
          ? el("a", { class: "btn small move", href: hrefFor(target) }, inner)
          : el(
              "span",
              { class: "btn small move", "aria-disabled": "true" },
              inner,
            );
      }),
    ),
  );
}

export function statusView(cell) {
  return el(
    "div",
    { class: "status-line" },
    badge(cell.status),
    el("span", { class: "explain" }, cell.explanation),
  );
}

export function valueCard(cell) {
  const line = (label, value, mono = true) =>
    el(
      "div",
      { class: "line" },
      el("span", { class: "label" }, label),
      el("span", { class: mono ? "mono value" : "value" }, value),
    );
  return el(
    "div",
    { class: "card value-card" },
    line("Extracted", cell.value),
    cell.matched_text ? line("Matched", cell.matched_text) : null,
    el(
      "div",
      { class: "numbers" },
      line("Coverage", decimals(cell.coverage), false),
      line("Density", decimals(cell.density), false),
      line("Places found", String(cell.places ?? 0), false),
    ),
  );
}

export function rowTable(cell) {
  return el(
    "div",
    { class: "card row-card" },
    el("h3", { class: "label" }, `Row ${cell.row}`),
    el(
      "div",
      { class: "table-wrap" },
      el(
        "table",
        { class: "row-table" },
        el(
          "thead",
          null,
          el(
            "tr",
            null,
            cell.row_cells.map((c) =>
              el(
                "th",
                { class: classes(c.selected && "selected") },
                c.name,
                c.extra ? el("span", { class: "tag" }, "extra") : null,
              ),
            ),
          ),
        ),
        el(
          "tbody",
          null,
          el(
            "tr",
            null,
            cell.row_cells.map((c) =>
              el(
                "td",
                { class: classes(c.selected && "selected") },
                el(
                  "span",
                  { class: "mono value", title: c.value },
                  cut(c.value),
                ),
                c.status === "exact" ? null : badge(c.status),
              ),
            ),
          ),
        ),
      ),
    ),
  );
}

// --- collapsible sections, each only when it applies -------------------------------------------
function section(title, outcome, ...body) {
  return el(
    "details",
    { class: "card section" },
    el(
      "summary",
      null,
      el("span", { class: "label" }, title),
      outcome ? el("span", { class: "outcome" }, outcome) : null,
    ),
    el("div", { class: "section-body" }, body),
  );
}

const fact = (label, ...value) =>
  el("div", { class: "fact" }, el("span", { class: "label" }, label), value);

function recheck(proposal) {
  return section(
    "Recheck history",
    proposal.outcome,
    fact(
      "Original",
      el("span", { class: "mono" }, proposal.original),
      badge(proposal.status_before),
    ),
    fact(
      "Proposed",
      el("span", { class: "mono" }, proposal.proposed),
      proposal.status_after ? badge(proposal.status_after) : null,
    ),
    fact("Outcome", proposal.outcome),
  );
}

function ocr() {
  return section(
    "OCR",
    null,
    el(
      "p",
      null,
      "This page’s text came from OCR, so grounding can pass OCR errors into the output.",
    ),
  );
}

function merge(part) {
  const e = part.evidence;
  return section(
    "Merge",
    null,
    fact("Absorbed part", pagesAbbr(part.pages)),
    fact("Original columns", part.columns.join(" · ")),
    part.original_column ? fact("This column was", part.original_column) : null,
    fact(
      "Header words equal at",
      `${e.equal_positions} of ${e.shapes.length} columns`,
    ),
    fact("Largest x-grid difference", `${e.max_x_difference} pt`),
    fact("Value shapes", e.shapes.join(" · ")),
    fact("Cells compared", e.cells.map(([a, b]) => `${a}/${b}`).join(" · ")),
  );
}

function extra(info) {
  return section(
    "Extra field",
    null,
    fact(
      "Printed on",
      `p. ${info.source_page}`,
      info.carried ? " (carried forward to this row)" : null,
    ),
    info.change
      ? fact(
          "Recheck change",
          el("span", { class: "mono" }, info.change.original),
          " → ",
          el("span", { class: "mono" }, info.change.new),
        )
      : null,
  );
}

export function sections(cell) {
  return [
    cell.proposal ? recheck(cell.proposal) : null,
    cell.ocr ? ocr() : null,
    cell.merge ? merge(cell.merge) : null,
    cell.extra ? extra(cell.extra) : null,
  ].filter(Boolean);
}

export function cellView(cell, hrefFor) {
  return el(
    "div",
    { class: "cell-view" },
    headingView(cell, hrefFor),
    statusView(cell),
    valueCard(cell),
    rowTable(cell),
    sections(cell),
  );
}
