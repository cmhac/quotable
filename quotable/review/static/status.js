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

export function badge(status, count) {
  const known = status in GLYPHS;
  return el(
    "span",
    { class: `badge ${known ? `s-${status}` : "s-unknown"}` },
    el("span", { class: "glyph", "aria-hidden": "true" }, known ? GLYPHS[status] : ""),
    el("span", { class: "word" }, status.replaceAll("_", " ")),
    count === undefined ? null : el("span", { class: "count" }, number(count)),
  );
}
