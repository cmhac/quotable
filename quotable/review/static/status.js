// The seven statuses: a glyph, a word and a tone together, never colour alone.

import { el } from "./dom.js";
import { number } from "./format.js";

const GLYPHS = {
  exact: "✓",
  fuzzy: "≈",
  misplaced: "⇄",
  ungrounded: "×",
  untokenized: "#",
  empty: "∅",
  not_on_page: "—",
};

export const STATUSES = Object.keys(GLYPHS);

export function statusText(status, count) {
  const word = status.replaceAll("_", " ");
  const glyph = GLYPHS[status];
  return [glyph, word, count === undefined ? null : number(count)]
    .filter(Boolean)
    .join(" ");
}

export function badge(status, count, quiet = false) {
  const known = status in GLYPHS;
  return el(
    "span",
    {
      class: `badge ${known ? `s-${status}` : "s-unknown"}${quiet ? " quiet" : ""}`,
    },
    el(
      "span",
      { class: "glyph", "aria-hidden": "true" },
      known ? GLYPHS[status] : "",
    ),
    el("span", { class: "word" }, status.replaceAll("_", " ")),
    count === undefined ? null : el("span", { class: "count" }, number(count)),
  );
}
