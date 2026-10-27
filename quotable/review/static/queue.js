// The queue screen (spec 013 D1, D2, E): what to review, how to sample it, and how good the
// extraction is so far. The numbers come from the server (queue.py); this file only draws them.

import { alertBox } from "./chrome.js";
import { el } from "./dom.js";
import { number } from "./format.js";
import { hashFor } from "./route.js";
import { badge } from "./status.js";

const KEY = "quotable.review.queue";
const FLAGGED = ["fuzzy", "misplaced", "ungrounded", "untokenized"];
const STATUSES = [...FLAGGED, "exact"];
const CONFIDENCES = [80, 90, 95, 99];
const SETTING_KEYS = [
  "statuses",
  "run",
  "table",
  "column",
  "extra_fields",
  "mode",
  "sample_size",
  "confidence",
  "margin",
  "seed",
];
const NOT_KEPT = ["run", "table", "column"];
const DIGITS = /^[0-9]+$/;
const INTEGER = /^-?[0-9]+$/;

// --- settings, as one value that the URL, the browser's storage and the server all read --------
export function parseSettings(query) {
  const given = String(query?.statuses ?? "").split(",");
  const statuses = STATUSES.filter((s) => given.includes(s));
  const size = Number(query?.sample_size);
  const margin = Number(query?.margin);
  const confidence = Number(query?.confidence);
  return {
    statuses: statuses.length ? statuses : [...FLAGGED],
    run: query?.run ?? "",
    table: DIGITS.test(query?.table ?? "") ? query.table : "",
    column: query?.column ?? "",
    extra_fields: !["0", "false"].includes(query?.extra_fields),
    mode: query?.mode === "sample" ? "sample" : "all",
    sample_size: Number.isInteger(size) && size >= 1 ? size : 100,
    confidence: CONFIDENCES.includes(confidence) ? confidence : 95,
    margin: margin > 0 ? margin : 8,
    seed: INTEGER.test(query?.seed ?? "") ? Number(query.seed) : 1,
  };
}

export function settingsQuery(settings) {
  const all = {
    statuses: settings.statuses.join(","),
    run: settings.run,
    table: settings.table,
    column: settings.column,
    extra_fields: settings.extra_fields ? "1" : "0",
    mode: settings.mode,
    sample_size: String(settings.sample_size),
    confidence: String(settings.confidence),
    margin: String(settings.margin),
    seed: String(settings.seed),
  };
  return Object.fromEntries(Object.entries(all).filter(([, v]) => v !== ""));
}

export const queueRouteQuery = (settings) => ({
  queue: "1",
  ...settingsQuery(settings),
});

export const inQueue = (query) => query?.queue === "1";

// The URL wins over what the browser kept, and that wins over the defaults. Which run, table and
// column a queue covers belong to the link that opened it, so they are not kept.
export function loadSettings(query, storage) {
  let kept = {};
  try {
    kept = JSON.parse(storage?.getItem(KEY) ?? "{}") ?? {};
  } catch {
    kept = {};
  }
  const base = parseSettings({ ...kept, statuses: kept.statuses?.join?.(",") });
  const fromUrl = parseSettings(query);
  const settings = { ...base, run: "", table: "", column: "" };
  for (const key of SETTING_KEYS)
    if (query?.[key] !== undefined) settings[key] = fromUrl[key];
  return settings;
}

export function saveSettings(storage, settings) {
  const kept = Object.fromEntries(
    Object.entries(settings).filter(([key]) => !NOT_KEPT.includes(key)),
  );
  try {
    storage?.setItem(KEY, JSON.stringify(kept));
  } catch {
    // Remembering the settings is a courtesy; the URL still holds them.
  }
}

export const newSeed = (random = Math.random) =>
  1 + Math.floor(random() * 1_000_000_000);

export function entryRoute(item, settings) {
  return {
    name: "cell",
    run: item.run,
    table: item.table,
    cell: {
      page: item.page,
      row: item.row ?? 1,
      name: item.column,
      extra: item.extra,
    },
    query: queueRouteQuery(settings),
  };
}

// --- numbers as the type board says ------------------------------------------------------------
const tenths = (fraction) => (fraction * 100).toFixed(1);
export const percent = (fraction) => `${tenths(fraction)}%`;
export const points = (margin) => `±${tenths(margin)} pts`;
export const range = ([low, high]) => `${tenths(low)}–${tenths(high)}%`;
export const estimate = (count) => `≈${number(Math.round(count))}`;
export const axisMax = ([, high]) => (high > 0.5 ? 1 : 0.5);

// --- statistics --------------------------------------------------------------------------------
export function headlineView(stats) {
  if (!stats.judged)
    return el(
      "div",
      { class: "headline" },
      el("div", { class: "big muted" }, "No cells judged yet"),
      el("div", { class: "note" }, "Review cells to see how many were wrong."),
    );
  return el(
    "div",
    { class: "headline" },
    el("div", { class: "label" }, "Share of judged cells changed"),
    el(
      "div",
      { class: "share" },
      el("span", { class: "big mono" }, percent(stats.share)),
      el(
        "span",
        { class: "of" },
        `${number(stats.changed)} of ${number(stats.judged)}`,
      ),
    ),
    el(
      "div",
      { class: "ci" },
      `${stats.confidence}% CI ${range(stats.interval)}`,
    ),
    el(
      "div",
      { class: "estimated" },
      "Estimated wrong cells ",
      el(
        "b",
        { class: "mono" },
        `${estimate(stats.estimated)} (${number(Math.round(stats.estimated_interval[0]))} – ${number(Math.round(stats.estimated_interval[1]))}) of ${number(stats.population)}`,
      ),
    ),
  );
}

export function chartView(stats) {
  if (!stats.interval) return null;
  const top = axisMax(stats.interval);
  const at = (fraction) => `${Math.min(100, (fraction / top) * 100)}%`;
  const label = `Share changed ${percent(stats.share)}, ${stats.confidence}% interval ${range(stats.interval)}, on a scale of 0 to ${Math.round(top * 100)}%`;
  return el(
    "div",
    { class: "chart", role: "img", "aria-label": label },
    el(
      "div",
      { class: "axis", "aria-hidden": "true" },
      el("div", {
        class: "band",
        style: {
          left: at(stats.interval[0]),
          width: `${((stats.interval[1] - stats.interval[0]) / top) * 100}%`,
        },
      }),
      el("div", { class: "point", style: { left: at(stats.share) } }),
    ),
    el(
      "div",
      { class: "ticks", "aria-hidden": "true" },
      el("span", null, "0%"),
      el("span", null, `${Math.round((top / 2) * 100)}%`),
      el("span", null, `${Math.round(top * 100)}%`),
    ),
  );
}

export function countsView(stats) {
  const count = (label, value) =>
    el(
      "div",
      { class: "count" },
      el("span", { class: "label" }, label),
      el("b", { class: "mono" }, value),
    );
  return el(
    "div",
    { class: "counts" },
    count("Population", number(stats.population)),
    count("Sample", number(stats.sample)),
    count(
      "Reviewed",
      `${number(stats.judged)} judged · ${number(stats.unsure)} can’t tell`,
    ),
  );
}

function tile(title, margin, p, n, population, correction) {
  return el(
    "div",
    { class: "tile" },
    el("div", { class: "label" }, title),
    el("div", { class: "big mono" }, margin === null ? "—" : points(margin)),
    el(
      "div",
      { class: "working mono" },
      `p = ${p}, n = ${number(n)}`,
      el("br"),
      `× √((N − n)/(N − 1)) = ${correction.toFixed(3)}, N = ${number(population)}`,
    ),
  );
}

export function marginsView(stats) {
  return el(
    "div",
    { class: "margins" },
    tile(
      "Before reviewing",
      stats.margin_before,
      "0.5",
      stats.sample,
      stats.population,
      stats.correction_before,
    ),
    tile(
      "So far",
      stats.margin_so_far,
      stats.share === null ? "—" : stats.share.toFixed(3),
      stats.judged,
      stats.population,
      stats.correction_so_far,
    ),
  );
}

export function byStatusView(stats) {
  const line = (row, first) =>
    el(
      "tr",
      { class: row === stats.total ? "all" : null },
      el("td", null, first),
      el("td", { class: "num" }, number(row.population)),
      el("td", { class: "num" }, number(row.sampled)),
      el("td", { class: "num" }, number(row.reviewed)),
      el("td", { class: "num" }, number(row.changed)),
      el("td", { class: "num" }, row.share === null ? "—" : percent(row.share)),
    );
  const left = stats.unsure;
  return el(
    "div",
    { class: "by-status" },
    el("h3", { class: "label" }, "By status"),
    el(
      "table",
      null,
      el(
        "thead",
        null,
        el(
          "tr",
          null,
          [
            "Status",
            "Population",
            "Sampled",
            "Reviewed",
            "Changed",
            "Share changed",
          ].map((name) => el("th", null, name)),
        ),
      ),
      el(
        "tbody",
        null,
        stats.by_status.map((row) => line(row, badge(row.status))),
        line(stats.total, "All"),
      ),
    ),
    el(
      "p",
      { class: "note" },
      `${number(left)} can’t tell ${left === 1 ? "verdict is" : "verdicts are"} left out of every share.`,
    ),
  );
}

export function categoriesView(stats) {
  if (!stats.categories.length) return null;
  const most = Math.max(...stats.categories.map(([, count]) => count));
  return el(
    "div",
    { class: "categories" },
    el("h3", { class: "label" }, "Error categories"),
    stats.categories.map(([name, count]) =>
      el(
        "div",
        { class: "cat-row" },
        el("span", { class: "mono" }, name),
        el(
          "span",
          { class: "bar", "aria-hidden": "true" },
          el("span", { style: { width: `${(count / most) * 100}%` } }),
        ),
        el("b", { class: "mono" }, String(count)),
      ),
    ),
    el(
      "p",
      { class: "note" },
      "Verdicts are saved to .quotable/review/verdicts.jsonl; the numbers can be rebuilt from that file.",
    ),
  );
}

function statsCard(stats) {
  return el(
    "section",
    { class: "card stats-card" },
    el("h2", null, "How good is this extraction?"),
    el("p", { class: "note" }, "Updates after each verdict"),
    headlineView(stats),
    chartView(stats),
    countsView(stats),
    marginsView(stats),
    byStatusView(stats),
    categoriesView(stats),
  );
}

// --- the settings card -------------------------------------------------------------------------
const option = (value, label, selected) =>
  el("option", { value, selected }, label);
const field = (label, control) =>
  el(
    "label",
    { class: "field" },
    el("span", { class: "label" }, label),
    control,
  );

function statusesCard(settings, counts, apply) {
  const only = settings.statuses.length === 1 ? settings.statuses[0] : null;
  const box = (status) =>
    el(
      "label",
      { class: "status-box" },
      el("input", {
        type: "checkbox",
        checked: settings.statuses.includes(status),
        disabled: only === status,
        onchange: (event) =>
          apply({
            ...settings,
            statuses: STATUSES.filter((s) =>
              s === status
                ? event.target.checked
                : settings.statuses.includes(s),
            ),
          }),
      }),
      badge(status, counts[status] ?? 0, status === "exact"),
    );
  return el(
    "section",
    { class: "card statuses" },
    el("h3", { class: "label" }, "Statuses"),
    FLAGGED.map(box),
    el("hr"),
    box("exact"),
    el(
      "p",
      { class: "note" },
      "add to estimate the error rate of cells that passed",
    ),
  );
}

function scopeCard(settings, run, apply) {
  const tables = run?.tables ?? [];
  const chosen = tables.find((t) => String(t.index) === settings.table);
  const columns = [
    ...new Set((chosen ? [chosen] : tables).flatMap((t) => t.columns)),
  ];
  return el(
    "section",
    { class: "card scope" },
    el("h3", { class: "label" }, "Scope"),
    field(
      "Run",
      el(
        "select",
        {
          class: "input",
          onchange: (event) =>
            apply({
              ...settings,
              run: event.target.value,
              table: "",
              column: "",
            }),
        },
        option("", "All runs (newest of each document)", !settings.run),
        run ? option(run.id, `This run · ${run.short_id}`, true) : null,
      ),
    ),
    field(
      "Table",
      el(
        "select",
        {
          class: "input",
          disabled: !tables.length,
          onchange: (event) =>
            apply({ ...settings, table: event.target.value, column: "" }),
        },
        option("", "All tables", !settings.table),
        tables.map((t) =>
          option(
            String(t.index),
            t.label ? `Table ${t.number} · ${t.label}` : `Table ${t.number}`,
            String(t.index) === settings.table,
          ),
        ),
      ),
    ),
    field(
      "Column",
      el(
        "select",
        {
          class: "input",
          disabled: !columns.length,
          onchange: (event) =>
            apply({ ...settings, column: event.target.value }),
        },
        option("", "All columns", !settings.column),
        columns.map((c) => option(c, c, c === settings.column)),
      ),
    ),
    el(
      "label",
      { class: "check" },
      el("input", {
        type: "checkbox",
        checked: settings.extra_fields,
        onchange: (event) =>
          apply({ ...settings, extra_fields: event.target.checked }),
      }),
      " Include extra fields",
    ),
  );
}

function matchingView(settings, matching) {
  const flagged = !settings.statuses.includes("exact");
  const noun = `${flagged ? "flagged " : ""}cell${matching === 1 ? " matches" : "s match"}`;
  return el(
    "div",
    { class: "matching", "aria-live": "polite" },
    el("span", { class: "big mono" }, number(matching)),
    ` ${noun}`,
  );
}

function samplingCard(settings, data, apply) {
  const sample = settings.mode === "sample";
  const size = (type) =>
    el("input", {
      type,
      name: "sample_size",
      class: type === "number" ? "input" : null,
      min: 1,
      max: type === "range" ? Math.max(data.matching, 1) : null,
      value: String(settings.sample_size),
      disabled: !sample,
      "aria-label": "Sample size",
      onchange: (event) => {
        const n = Math.floor(Number(event.target.value));
        if (n >= 1) apply({ ...settings, sample_size: n });
      },
    });
  return el(
    "section",
    { class: "card sampling" },
    el("h3", { class: "label" }, "Sampling"),
    ["all", "sample"].map((mode) =>
      el(
        "label",
        { class: "radio" },
        el("input", {
          type: "radio",
          name: "mode",
          value: mode,
          checked: settings.mode === mode,
          onchange: () => apply({ ...settings, mode }),
        }),
        mode === "all"
          ? ` Review all ${number(data.matching)}`
          : " Random sample",
      ),
    ),
    el("div", { class: "size" }, size("range"), size("number")),
    el(
      "div",
      {
        class: "confidence",
        role: "radiogroup",
        "aria-label": "Confidence level",
      },
      el("span", { class: "label" }, "Confidence"),
      CONFIDENCES.map((level) =>
        el(
          "label",
          { class: "radio" },
          el("input", {
            type: "radio",
            name: "confidence",
            value: String(level),
            checked: settings.confidence === level,
            disabled: !sample,
            onchange: () => apply({ ...settings, confidence: level }),
          }),
          ` ${level}%`,
        ),
      ),
    ),
    field(
      "Target margin of error (points)",
      el("input", {
        type: "number",
        name: "margin",
        class: "input",
        min: 0.5,
        step: 0.5,
        value: String(settings.margin),
        disabled: !sample,
        onchange: (event) => {
          const m = Number(event.target.value);
          if (m > 0) apply({ ...settings, margin: m });
        },
      }),
    ),
    el(
      "div",
      { class: "suggest" },
      "suggests ",
      el(
        "button",
        {
          class: "link",
          type: "button",
          disabled: !sample,
          onclick: () => apply({ ...settings, sample_size: data.suggested }),
        },
        `${number(data.suggested)} cells`,
      ),
    ),
    el(
      "div",
      { class: "seed" },
      field(
        "Seed",
        el("input", {
          type: "number",
          name: "seed",
          class: "input",
          value: String(settings.seed),
          disabled: !sample,
          onchange: (event) => {
            const s = Number(event.target.value);
            if (Number.isInteger(s)) apply({ ...settings, seed: s });
          },
        }),
      ),
      el(
        "button",
        {
          class: "btn",
          type: "button",
          disabled: !sample,
          onclick: () => apply({ ...settings, seed: newSeed() }),
        },
        "New seed",
      ),
    ),
    el(
      "p",
      { class: "note" },
      "The same seed and filters always give the same sample.",
    ),
  );
}

function startButton(settings, data) {
  const at = data.first_unreviewed;
  if (at === null || at === undefined || !data.queue[at])
    return el(
      "span",
      { class: "btn primary start", "aria-disabled": "true" },
      data.queue.length ? "All reviewed" : "Nothing to review",
    );
  return el(
    "a",
    {
      class: "btn primary start",
      href: hashFor(entryRoute(data.queue[at], settings)),
    },
    data.stats.reviewed > 0 ? "Resume review" : "Start review",
  );
}

// --- the screen --------------------------------------------------------------------------------
export async function show(route, ctx) {
  let settings = loadSettings(route.query, ctx.storage);
  const runPath = (id) => `/api/runs/${encodeURIComponent(id)}`;
  const ask = (s) => ctx.getJson("/api/queue", settingsQuery(s));
  const [first, run] = await Promise.all([
    ask(settings),
    settings.run ? ctx.getJson(runPath(settings.run)) : null,
  ]);

  const alerts = el("div", { class: "alert-slot" });
  const layout = el("div", { class: "queue-layout" });
  const results = el("div", { class: "queue-results" }, alerts, layout);
  let latest = 0;

  const apply = async (next) => {
    settings = next;
    const mine = ++latest;
    saveSettings(ctx.storage, next);
    ctx.replace({ name: "queue", query: settingsQuery(next) });
    try {
      const data = await ask(next);
      if (mine !== latest) return;
      alerts.replaceChildren();
      paint(data, next);
    } catch (error) {
      if (mine === latest)
        alerts.replaceChildren(
          alertBox({
            headline: "The queue could not be loaded.",
            text: error.message,
          }),
        );
    }
  };

  function paint(data, shown) {
    layout.replaceChildren(
      el(
        "div",
        { class: "settings" },
        statusesCard(shown, data.counts, apply),
        scopeCard(shown, run, apply),
        matchingView(shown, data.matching),
        samplingCard(shown, data, apply),
        startButton(shown, data),
      ),
      statsCard(data.stats),
    );
  }
  paint(first, settings);

  const crumbs = [{ text: "Runs", href: "#/" }];
  if (run)
    crumbs.push({
      text: run.document.name,
      sub: run.short_id,
      href: hashFor({ name: "run", run: run.id }),
    });
  crumbs.push({ text: "Review" });
  return {
    title: "Review",
    crumbs,
    content: el(
      "div",
      { class: "page queue-screen" },
      el("h1", null, "What to review"),
      el(
        "p",
        { class: "lede" },
        "Your settings are remembered between visits. The same seed and filters always give the same sample.",
      ),
      results,
    ),
  };
}
