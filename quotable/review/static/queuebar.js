// The queue bar (spec 013 D3): where you are in the queue, and the strip of one mark per cell.

import { el } from "./dom.js";
import { number } from "./format.js";
import { range, percent, settingsQuery } from "./queue.js";
import { hashFor } from "./route.js";

const REVIEWED = ["correct", "changed", "unsure"];
const LEGEND = [
  ["correct", "correct"],
  ["changed", "changed"],
  ["unsure", "can’t tell"],
  ["none", "not reviewed"],
  ["current", "current"],
];

export function describe(settings, queue) {
  const what = settings.statuses.includes("exact") ? "Cells" : "Flagged cells";
  const size = number(queue.length);
  return `${what} · ${settings.mode === "sample" ? `sample of ${size}` : `all ${size}`}`;
}

export const markState = (entry, current) =>
  current
    ? "current"
    : REVIEWED.includes(entry.review.state)
      ? entry.review.state
      : "none";

export function hoverText(entry) {
  const where = entry.extra
    ? `extra field ${entry.column}`
    : `row ${entry.row}, column ${entry.column}`;
  return `run ${entry.short_run}, table ${entry.table_number}, page ${entry.page}, ${where}, ${entry.status}`;
}

export function neighbour(queue, index, step) {
  return queue[index + step] ?? null;
}

export function nextUnreviewed(queue, index) {
  for (let step = 1; step <= queue.length; step++) {
    const found = queue[(index + step) % queue.length];
    if (found && !REVIEWED.includes(found.review.state) && step < queue.length)
      return found;
  }
  return null;
}

export const indexOf = (queue, { run, table, page, row, name, extra }) =>
  queue.findIndex(
    (e) =>
      e.run === run &&
      e.table === table &&
      e.page === page &&
      e.column === name &&
      e.extra === extra &&
      (extra || e.row === row),
  );

function changedLine(stats) {
  if (!stats.judged) return "No cells judged yet";
  return `Changed ${percent(stats.share)} (${stats.confidence}% CI ${range(stats.interval)}, ${number(stats.changed)} of ${number(stats.judged)} judged)`;
}

export function barView({ data, index, settings, hrefFor }) {
  const { queue, stats } = data;
  const marks = queue.map((entry, i) =>
    el("a", {
      class: `mark m-${markState(entry, i === index)}`,
      href: hrefFor(entry),
      title: hoverText(entry),
      "aria-current": i === index ? "true" : null,
      "aria-label": hoverText(entry),
    }),
  );
  return el(
    "section",
    { class: "queue-bar", "aria-label": "Queue" },
    el(
      "div",
      { class: "line" },
      el("b", null, "Queue"),
      el("span", { class: "desc" }, describe(settings, queue)),
      el(
        "a",
        {
          class: "btn small",
          href: hashFor({ name: "queue", query: settingsQuery(settings) }),
        },
        "Edit queue",
      ),
      el("span", { class: "spacer" }),
      el(
        "span",
        { class: "reviewed mono" },
        `${number(stats.reviewed)} / ${number(queue.length)} reviewed`,
      ),
      el("span", { class: "changed" }, changedLine(stats)),
    ),
    el("div", { class: "strip" }, marks),
    el(
      "div",
      { class: "legend" },
      LEGEND.map(([state, word]) =>
        el(
          "span",
          { class: "key-item" },
          el("span", { class: `mark m-${state}`, "aria-hidden": "true" }),
          word,
        ),
      ),
      el(
        "span",
        { class: "hint" },
        "Hover a mark for run, table, page, row, column, status · click to jump",
      ),
    ),
  );
}
