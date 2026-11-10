// The gold check's sample screen (#/gold) and score screen (#/gold/score) (spec 016).

import { alertBox } from "./chrome.js";
import { clock } from "./clock.js";
import { el } from "./dom.js";
import { number, plural } from "./format.js";

const LEVEL_TEXT = { normal: "normal", fuzzy: "fuzzy", none: "no match" };
const DEFAULT_SIZE = 20;

export const percent = (share) => (share === null || share === undefined ? "n/a" : `${(share * 100).toFixed(1)}%`);

const gold = (crumb) => [{ text: "Runs", href: "#/" }, { text: "Gold check", href: crumb ? "#/gold" : null }];
const pageHref = (sha, page) => `#/gold/page/${sha}/${page}`;

// -- the sample screen ------------------------------------------------------------------------
export function documentRow(doc, chosen, onToggle) {
  const usable = doc.pdf === "ok";
  return el(
    "label",
    { class: `gold-doc${usable ? "" : " unusable"}` },
    el("input", {
      type: "checkbox",
      value: doc.sha256,
      checked: chosen && usable,
      disabled: !usable,
      onchange: onToggle,
    }),
    el("span", { class: "name" }, doc.name),
    el("span", { class: "facts" }, ` ${plural(doc.pages, "page")}`),
    usable ? null : el("span", { class: "unreadable" }, ` PDF ${doc.pdf}`),
  );
}

export function pageList(pages) {
  return el(
    "table",
    { class: "runs gold-pages" },
    el("thead", null, el("tr", null, ["Document", "Page", "Status", "Time"].map((h) => el("th", null, h)))),
    el(
      "tbody",
      null,
      pages.map((p) =>
        el(
          "tr",
          null,
          el("td", null, p.name),
          el("td", null, el("a", { href: pageHref(p.sha256, p.page) }, String(p.page))),
          el("td", null, el("span", { class: `gold-status ${p.status}` }, p.status)),
          el("td", null, p.status === "done" || p.seconds ? clock(p.seconds) : ""),
        ),
      ),
    ),
  );
}

function drawForm(data, ctx) {
  const usable = data.documents.filter((d) => d.pdf === "ok");
  const chosen = new Set(usable.map((d) => d.sha256));
  const total = () => usable.filter((d) => chosen.has(d.sha256)).reduce((n, d) => n + d.pages, 0);
  let typedSize = false;
  const sizeInput = el("input", {
    class: "input",
    type: "number",
    min: 1,
    value: Math.min(DEFAULT_SIZE, total()) || "",
    oninput: () => (typedSize = true),
  });
  const seedInput = el("input", { class: "input", type: "number", placeholder: "random" });
  const note = el("p", { class: "note" });
  const draw = el("button", { class: "btn primary", type: "button" }, data.sample ? "Draw a new sample" : "Draw a sample");
  const rows = data.documents.map((d) =>
    documentRow(d, true, (event) => {
      if (event.target.checked) chosen.add(d.sha256);
      else chosen.delete(d.sha256);
      if (!typedSize) sizeInput.value = Math.min(DEFAULT_SIZE, total()) || "";
      draw.disabled = chosen.size === 0;
    }),
  );
  draw.disabled = chosen.size === 0;
  draw.addEventListener("click", async () => {
    const replace = Boolean(data.sample);
    if (replace && !confirm("Draw a new sample? The tables you typed stay stored and are used again if their pages are drawn again.")) return;
    draw.disabled = true;
    try {
      await ctx.sendJson("POST", "/api/gold/sample", {
        documents: [...chosen],
        size: Number(sizeInput.value),
        seed: seedInput.value === "" ? null : Number(seedInput.value),
        replace,
      });
      ctx.refresh();
    } catch (error) {
      note.textContent = error.message;
      note.className = "note unreadable";
      draw.disabled = false;
    }
  });
  return el(
    "div",
    { class: "card gold-draw" },
    el("h2", null, data.sample ? "Draw a new sample" : "Draw a sample"),
    el("p", { class: "facts" }, "Pages are drawn at random from every page of the documents you choose, including pages where no table was found."),
    data.documents.length
      ? el("div", { class: "gold-docs" }, rows)
      : el("p", { class: "note" }, "No saved runs yet. Call extract_tables on a PDF to make one."),
    el(
      "div",
      { class: "gold-draw-fields" },
      el("label", { class: "field" }, el("span", null, "Pages in the sample"), sizeInput),
      el("label", { class: "field" }, el("span", null, "Seed (optional)"), seedInput),
      draw,
    ),
    note,
  );
}

export function sampleSummary(data) {
  const { sample } = data;
  return el(
    "div",
    { class: "card gold-sample" },
    el("h2", null, "Your sample"),
    el(
      "p",
      { class: "facts" },
      `${plural(sample.size, "page")} from ${plural(sample.documents.length, "document")}, seed ${sample.seed}. `,
      `${number(data.done)} of ${number(data.total)} pages done.`,
    ),
    el(
      "p",
      null,
      el("a", { class: "btn primary", href: "#/gold/score" }, data.done === data.total ? "Score the extraction" : `Score (${data.total - data.done} pages left)`),
      "  ",
      data.pages.length
        ? el("a", { class: "btn", href: pageHref(data.pages.find((p) => p.status !== "done")?.sha256 ?? data.pages[0].sha256, data.pages.find((p) => p.status !== "done")?.page ?? data.pages[0].page) }, "Open the next page")
        : null,
    ),
    pageList(data.pages),
  );
}

export async function showSample(route, ctx) {
  const data = await ctx.getJson("/api/gold");
  const notes = [];
  if (!data.tracked.ok) notes.push(alertBox({ headline: "The gold folder may be ignored by git.", text: data.tracked.note }));
  if (data.skipped.length) notes.push(alertBox({ headline: `${plural(data.skipped.length, "typed page")} could not be read and ${data.skipped.length === 1 ? "was" : "were"} left as it is.`, text: data.skipped.join(", ") }));
  const content = el(
    "div",
    { class: "page gold-page" },
    el("h1", null, "Gold check"),
    el(
      "p",
      { class: "lede" },
      "Type the tables a sample of pages really print, then score the extraction against them. ",
      "It never calls a model. The editor does not show the extraction.",
    ),
    notes,
    data.sample ? sampleSummary(data) : null,
    drawForm(data, ctx),
  );
  return { title: "Gold check", crumbs: gold(false), content };
}

// -- the score screen -------------------------------------------------------------------------
export function headlineTable(units) {
  return el(
    "table",
    { class: "runs gold-units" },
    el("thead", null, el("tr", null, ["unit", "correct", "gold", "extracted", "recall", "precision", "accuracy"].map((h) => el("th", null, h)))),
    el(
      "tbody",
      null,
      units.map((u) =>
        el("tr", null, el("td", null, u.name), el("td", null, number(u.correct)), el("td", null, number(u.gold)), el("td", null, number(u.extracted)), el("td", null, percent(u.recall)), el("td", null, percent(u.precision)), el("td", null, percent(u.accuracy))),
      ),
    ),
  );
}

export const DEFINITIONS = [
  "cell: a cell with text in the gold or the extraction. It is correct if the gold has text and the extraction matches it at the normal level.",
  "row: a gold row or an extracted row. It is correct if it pairs with a row on the other side and every cell in it is correct.",
  "page: a page where the gold or the extraction has rows. It is correct if every row on it is correct, with no missed or extra rows.",
  "recall = correct / gold, precision = correct / extracted, accuracy = correct / units in either the gold or the extraction.",
];

export function intervalText(interval) {
  if (!interval) return null;
  return (
    `Pages correct: ${percent(interval.share)} of ${number(interval.n)} counted pages, ` +
    `${interval.confidence}% interval ${percent(interval.low)} to ${percent(interval.high)}. ` +
    `${number(interval.sampled)} of the document's ${number(interval.pages)} pages were sampled, so this is an estimate for this document only. ` +
    "Cell and row figures have no interval: cells on one page are not independent."
  );
}

export function countsTable(heading, rows) {
  return el(
    "table",
    { class: "runs gold-counts" },
    el("thead", null, el("tr", null, [heading, "cells correct", "gold cells", "rows correct", "gold rows", "extracted rows", "missed cells", "extra cells"].map((h) => el("th", null, h)))),
    el(
      "tbody",
      null,
      rows.map((r) => {
        const c = r.counts;
        return el("tr", null, el("td", null, r.label), el("td", null, number(c.cells_correct)), el("td", null, number(c.cells - c.extra)), el("td", null, number(c.rows_correct)), el("td", null, number(c.gold_rows)), el("td", null, number(c.pred_rows)), el("td", null, number(c.missed)), el("td", null, number(c.extra)));
      }),
    ),
  );
}

export function pairingList(pages, names) {
  const lines = [];
  for (const page of pages) {
    const where = `${names[page.sha256]} · page ${page.page}`;
    for (const pair of page.pairs) {
      const parts = pair.columns.map((c) => {
        if (c.gold === null) return `(extra column ${c.extracted})`;
        if (c.extracted === null) return `${c.gold} (no partner)`;
        return `${c.gold} = ${c.extracted} [${c.how}]`;
      });
      lines.push(el("li", null, el("b", null, `${where}, gold table ${pair.gold} = ${pair.label}: `), parts.join("; ")));
    }
    for (const number_ of page.unmatched_gold) {
      lines.push(el("li", null, el("b", null, `${where}, gold table ${number_}: `), "no extracted table matched it"));
    }
  }
  return el("ul", { class: "gold-pairing" }, lines);
}

export function differenceRows(cells, level) {
  return cells.filter((c) => level === "all" || c.best === level);
}

export function differencesTable(cells, level = "all") {
  const shown = differenceRows(cells, level);
  return el(
    "table",
    { class: "runs gold-differences" },
    el("thead", null, el("tr", null, ["document", "page", "table", "column", "row", "gold", "extracted", "match"].map((h) => el("th", null, h)))),
    el(
      "tbody",
      null,
      shown.map((c) =>
        el(
          "tr",
          null,
          el("td", null, c.document),
          el("td", null, el("a", { href: pageHref(c.sha256, c.page) }, String(c.page))),
          el("td", null, c.table),
          el("td", null, c.column),
          el("td", null, c.gold_row === null ? "extra" : String(c.gold_row)),
          el("td", { class: "mono" }, c.gold),
          el("td", { class: "mono" }, c.extracted),
          el("td", null, LEVEL_TEXT[c.best] ?? c.best),
        ),
      ),
    ),
  );
}

export function incompleteView(result) {
  return el(
    "div",
    { class: "page gold-page" },
    el("h1", null, "Score"),
    alertBox({
      headline: `${number(result.done)} of ${number(result.total)} sampled pages are done.`,
      text: "A score is shown only when every sampled page is done, so the pages scored are the random sample.",
    }),
    el("h2", null, "Still to do"),
    el("ul", { class: "gold-left" }, result.left.map((p) => el("li", null, el("a", { href: pageHref(p.sha256, p.page) }, `${p.name} · page ${p.page}`)))),
    result.total - result.done > result.left.length ? el("p", { class: "note" }, `and ${result.total - result.done - result.left.length} more`) : null,
    el("p", null, el("a", { href: "#/gold" }, "Back to the sample")),
  );
}

// One selector per document: which of its runs is scored. Changing one reloads the score with the
// others as they are.
export function runChoices(report, go) {
  const selects = Object.entries(report.runs).map(([sha, used]) => {
    const select = el(
      "select",
      { class: "input", "aria-label": `Run scored for ${used.name}`, "data-sha": sha },
      (report.choices?.[sha] ?? [{ id: used.id, started: used.started, model: used.model }]).map((r) =>
        el("option", { value: r.id, selected: r.id === used.id }, `${r.id.slice(0, 8)} · ${r.model} · ${r.started}`),
      ),
    );
    select.value = used.id;
    return { sha, name: used.name, select };
  });
  const onChange = () => go({ name: "goldscore", query: { run: selects.map((s) => s.select.value).join(",") } });
  for (const { select } of selects) select.addEventListener("change", onChange);
  return el(
    "ul",
    { class: "facts gold-runs" },
    selects.map(({ name, select }) => el("li", null, el("span", null, `${name}: `), select)),
  );
}

export function reportView(report, query, go = () => {}) {
  const names = Object.fromEntries(report.documents.map((d) => [d.sha256, d.name]));
  const level = el("select", { class: "input", "aria-label": "Match level" }, ["all", "normal", "fuzzy", "none"].map((l) => el("option", { value: l }, l === "all" ? "all differences" : (LEVEL_TEXT[l]))));
  const holder = el("div", null, differencesTable(report.cells));
  level.addEventListener("change", () => holder.replaceChildren(differencesTable(report.cells, level.value)));
  const csv = (kind) => `/api/gold/score.csv?kind=${kind}${(query.run ?? []).map((r) => `&run=${encodeURIComponent(r)}`).join("")}`;
  const total = report.total;
  return el(
    "div",
    { class: "page gold-page" },
    el("h1", null, "Score"),
    el("p", { class: "lede" }, `${plural(report.pages.length, "gold page")} from ${plural(report.documents.length, "document")}, scored at the ${report.benchmark} cell level.`),
    runChoices(report, go),
    report.not_scored.length ? alertBox({ headline: "Not scored (no usable run):", text: report.not_scored.join(", ") }) : null,
    report.notes.map((n) => el("p", { class: "note" }, n)),
    el("div", { class: "card gold-headline" }, headlineTable(report.units), el("ul", { class: "gold-definitions" }, DEFINITIONS.map((d) => el("li", null, d)))),
    report.interval ? el("p", { class: "note gold-interval" }, intervalText(report.interval)) : null,
    el(
      "div",
      { class: "card" },
      el("h2", null, "Rows and cells"),
      el("p", { class: "facts" }, `Rows: gold ${number(total.gold_rows)}, extracted ${number(total.pred_rows)}, paired ${number(total.matched_rows)}, missed ${number(total.gold_rows - total.matched_rows)}, extra ${number(total.pred_rows - total.matched_rows)}.`),
      el("p", { class: "facts" }, `Cell accuracy: exact ${percent(total.cells ? total.hits.exact / total.cells : null)}, normal ${percent(total.cells ? total.hits.normal / total.cells : null)}, fuzzy ${percent(total.cells ? total.hits.fuzzy / total.cells : null)}. Missed cells ${number(total.missed)}, extra cells ${number(total.extra)}.`),
    ),
    el("h2", null, "By document"),
    countsTable("document", report.documents.map((d) => ({ label: d.name, counts: d.counts }))),
    el("h2", null, "By extracted table"),
    countsTable("table", report.tables.map((t) => ({ label: `${t.name} · ${t.label}`, counts: t.counts }))),
    el("h2", null, "Column pairing"),
    el("p", { class: "facts" }, "Columns are paired by name where the names match, and by their values otherwise ([values])."),
    pairingList(report.pages, names),
    el(
      "h2",
      null,
      "Cells that are not an exact match",
    ),
    el("p", { class: "facts" }, `${plural(report.cells.length, "cell")}. `, el("a", { href: csv("cells"), download: "gold_cells.csv" }, "Download CSV"), " · ", el("a", { href: csv("pages"), download: "gold_pages.csv" }, "Download the pages CSV")),
    el("label", { class: "field" }, el("span", null, "Show"), level),
    holder,
    el("p", null, el("a", { href: "#/gold" }, "Back to the sample")),
  );
}

export async function showScore(route, ctx) {
  const runs = route.query.run ? route.query.run.split(",") : [];
  const result = await ctx.getJson("/api/gold/score", { run: runs });
  const crumbs = [...gold(true), { text: "Score" }];
  const content = result.complete
    ? reportView(result.report, { run: runs }, (route_) => ctx.go(route_))
    : incompleteView(result);
  return { title: "Gold score", crumbs, content };
}
