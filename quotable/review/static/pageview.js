// The page view's pieces: which boxes to draw for a cell, where they go at a zoom, the text layer.
// Everything here is in PDF points (y down) until `place` turns a box into pixels.

import { el } from "./dom.js";

export const HIGHLIGHTS = [
  { key: "matched", label: "Matched words" },
  { key: "also", label: "Other places found" },
  { key: "area", label: "Cell area" },
  { key: "row", label: "Row window" },
  { key: "column", label: "Column range" },
  { key: "header", label: "Header & column centres" },
  { key: "band", label: "Table band" },
];

const STORAGE_KEY = "quotable.review.highlights";
const MIN_ZOOM = 0.25;
const MAX_ZOOM = 4;
const STEP = 0.25;
const SCROLL_ORDER = ["matched", "area", "row"];

export const defaultToggles = () =>
  Object.fromEntries(HIGHLIGHTS.map((h) => [h.key, h.key !== "header"]));

export const shownToggles = (sharedPage) =>
  HIGHLIGHTS.filter((h) => h.key !== "band" || sharedPage);

// A display preference, so it lives in the browser; blocked or broken storage means the defaults.
export function loadToggles(storage) {
  const toggles = defaultToggles();
  try {
    const saved = JSON.parse(storage.getItem(STORAGE_KEY) ?? "null");
    if (saved && typeof saved === "object")
      for (const key of Object.keys(toggles))
        if (typeof saved[key] === "boolean") toggles[key] = saved[key];
  } catch {
    return defaultToggles();
  }
  return toggles;
}

export function saveToggles(storage, toggles) {
  try {
    storage.setItem(STORAGE_KEY, JSON.stringify(toggles));
  } catch {
    // A display preference; losing it costs nothing.
  }
}

// --- which boxes -------------------------------------------------------------------------------
function headerBoxes(header, width, height) {
  if (!header) return [];
  return [
    {
      kind: "header",
      toggle: "header",
      box: [0, header.line, width, header.bottom],
      label: "header · column centres",
    },
    ...Object.values(header.x ?? {}).map((x) => ({
      kind: "centre",
      toggle: "header",
      box: [x, header.line, x, height],
      label: null,
    })),
  ];
}

function cellBoxes(cell, width, height) {
  const h = cell.highlights;
  const boxes = [];
  if (h.cell_area)
    boxes.push({ kind: "area", toggle: "area", box: h.cell_area, label: null });
  if (h.row_window)
    boxes.push({
      kind: "row",
      toggle: "row",
      box: [0, h.row_window[0], width, h.row_window[1]],
      label: `${h.row_label} window`,
    });
  if (h.column_range)
    boxes.push({
      kind: "column",
      toggle: "column",
      box: [h.column_range[0], 0, h.column_range[1], height],
      label: "column range",
    });
  for (const box of h.candidates ?? [])
    boxes.push({ kind: "also", toggle: "also", box, label: "also found" });
  if (h.matched)
    boxes.push({
      kind: "matched",
      toggle: "matched",
      box: h.matched,
      label: "matched words",
    });
  return boxes;
}

// The boxes of one page for one cell. Cell highlights show only on the cell's own page.
export function boxesFor({ cell, page, data, table }) {
  const [width, height] = data.size;
  const mine = data.tables.find((t) => t.index === table);
  const boxes = [];
  if (mine?.band && data.tables.length > 1)
    boxes.push({
      kind: "band",
      toggle: "band",
      box: [0, mine.band[0], width, mine.band[1]],
      label: null,
    });
  if (page === cell.highlights.page)
    boxes.push(...cellBoxes(cell, width, height));
  boxes.push(...headerBoxes(mine?.header, width, height));
  return boxes;
}

export const visible = (boxes, toggles) =>
  boxes.filter((b) => toggles[b.toggle]);

export function scrollTarget(boxes) {
  for (const kind of SCROLL_ORDER) {
    const found = boxes.find((b) => b.kind === kind);
    if (found) return found;
  }
  return null;
}

// The cell under a point: the row whose window and the column whose range both hold it.
export function cellAt(data, table, x, y) {
  const mine = data.tables.find((t) => t.index === table);
  if (!mine) return null;
  const row = Object.entries(mine.rows ?? {}).find(
    ([, [top, bottom]]) => y >= top && y <= bottom,
  );
  const column = Object.entries(mine.columns ?? {}).find(
    ([, [left, right]]) => x >= left && x <= right,
  );
  return row && column ? { row: Number(row[0]), name: column[0] } : null;
}

// --- zoom --------------------------------------------------------------------------------------
const clamp = (zoom) => Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, zoom));
export const zoomIn = (zoom) => clamp(zoom + STEP);
export const zoomOut = (zoom) => clamp(zoom - STEP);
export const zoomText = (zoom) => `${Math.round(zoom * 100)}%`;
export const fitZoom = (available, pageWidth) =>
  available > 0 && pageWidth > 0 ? clamp(available / pageWidth) : 1;

export function place([x0, y0, x1, y1], zoom) {
  return {
    left: x0 * zoom,
    top: y0 * zoom,
    width: Math.max(x1 - x0, 0) * zoom || zoom,
    height: Math.max(y1 - y0, 0) * zoom || zoom,
  };
}

const px = (box, zoom) =>
  Object.fromEntries(
    Object.entries(place(box, zoom)).map(([k, v]) => [k, `${v}px`]),
  );

// --- drawing -----------------------------------------------------------------------------------
export function textLayer(words, zoom) {
  return words.map(([text, x0, y0, x1, y1]) =>
    el(
      "span",
      {
        class: "word",
        style: {
          ...px([x0, y0, x1, y1], zoom),
          "font-size": `${(y1 - y0) * zoom * 0.85}px`,
        },
      },
      text,
    ),
  );
}

function boxNode(box, zoom) {
  return el(
    "div",
    {
      class: `hl hl-${box.kind}`,
      style: px(box.box, zoom),
    },
    box.label ? el("span", { class: "hl-label" }, box.label) : null,
  );
}

// The page: the image (or a blank page of the stored size), the highlights over it, and, when
// asked, the stored words laid at their boxes with the image dimmed under them.
export function surface({
  size,
  zoom,
  imageSrc,
  words,
  boxes,
  toggles,
  textLayer: layer,
  onPick,
  alt,
}) {
  const [width, height] = size;
  return el(
    "div",
    {
      class: ["surface", imageSrc ? null : "blank", layer ? "dim" : null]
        .filter(Boolean)
        .join(" "),
      style: { width: `${width * zoom}px`, height: `${height * zoom}px` },
      onclick: onPick
        ? (event) => {
            const at = event.currentTarget?.getBoundingClientRect?.();
            if (at)
              onPick(event, null, [
                (event.clientX - at.left) / zoom,
                (event.clientY - at.top) / zoom,
              ]);
          }
        : null,
    },
    imageSrc
      ? el("img", {
          src: imageSrc,
          alt: alt ?? "The PDF page",
          draggable: "false",
        })
      : null,
    visible(boxes, toggles).map((box) => boxNode(box, zoom)),
    layer ? el("div", { class: "textlayer" }, textLayer(words, zoom)) : null,
  );
}
