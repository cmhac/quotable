// Plain functions that turn the API's numbers and timestamps into the words the screens show.

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const FLAGGED_ORDER = ["fuzzy", "misplaced", "ungrounded", "untokenized"];
const pad = (n) => String(n).padStart(2, "0");

export const number = (n) => n.toLocaleString("en-US");

export const plural = (n, word) => `${number(n)} ${word}${n === 1 ? "" : "s"}`;

const clock = (d) => `${pad(d.getHours())}:${pad(d.getMinutes())}`;
const sameDay = (a, b) =>
  a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate();

export function formatTime(iso, now = new Date()) {
  const d = new Date(iso);
  if (sameDay(d, now)) return `Today ${clock(d)}`;
  const year = d.getFullYear() === now.getFullYear() ? "" : `${d.getFullYear()}, `;
  return `${MONTHS[d.getMonth()]} ${d.getDate()}, ${year}${clock(d)}`;
}

export function formatSpan(started, ended, now = new Date()) {
  const [a, b] = [new Date(started), new Date(ended)];
  return `${formatTime(started, now)}–${sameDay(a, b) ? clock(b) : formatTime(ended, now)}`;
}

export function utcSpan(started, ended) {
  const stamp = (iso) => iso.replace("T", " ");
  const sameDate = started.slice(0, 10) === ended.slice(0, 10);
  return `${stamp(started)} · ${sameDate ? ended.slice(11) : stamp(ended)}`;
}

export function costText(cost) {
  if (cost.kind === "usd") return `$${cost.usd > 0 && cost.usd < 0.1 ? cost.usd.toFixed(4) : cost.usd.toFixed(2)}`;
  return cost.kind;
}

export function sizeText(bytes) {
  return bytes >= 100_000 ? `${(bytes / 1e6).toFixed(1)} MB` : `${(bytes / 1e3).toFixed(1)} KB`;
}

export const shortSha = (sha, head = 4, tail = 4) => `${sha.slice(0, head)}…${sha.slice(-tail)}`;

function pageRanges(pages) {
  const ranges = [];
  for (const page of [...new Set(pages)].sort((a, b) => a - b)) {
    const last = ranges[ranges.length - 1];
    if (last && page === last[1] + 1) last[1] = page;
    else ranges.push([page, page]);
  }
  return ranges.map(([a, b]) => (a === b ? `${a}` : `${a}–${b}`)).join(", ");
}

export function pagesText(pages) {
  if (!pages.length) return "";
  return `${new Set(pages).size > 1 ? "pages" : "page"} ${pageRanges(pages)}`;
}

export function pagesAbbr(pages) {
  if (!pages.length) return "";
  return `${new Set(pages).size > 1 ? "pp." : "p."} ${pageRanges(pages)}`;
}

export function settingValue(value) {
  if (value === true) return "True";
  if (value === false) return "False";
  if (value === null || value === undefined) return "None";
  return typeof value === "number" ? String(value) : JSON.stringify(value);
}

export function flaggedParts(flagged) {
  const keys = [...FLAGGED_ORDER, ...Object.keys(flagged).filter((k) => !FLAGGED_ORDER.includes(k)).sort()];
  return keys.filter((k) => flagged[k] > 0).map((k) => [k, flagged[k]]);
}

export function progressWidth({ reviewed, flagged }) {
  if (flagged <= 0 || reviewed <= 0) return "0%";
  const percent = Math.min(100, Math.round((100 * reviewed) / flagged));
  return percent === 0 ? "1px" : `${percent}%`;
}
