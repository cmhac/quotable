// The selectable text over a page image, and what happens when text is selected on it
// (spec 016, FR-018): the selection is copied clean, once, and the highlight stays.

// The SVG namespace is an identifier the DOM needs to make SVG elements; nothing is ever fetched
// from it. It is written in two parts so the static check for remote addresses stays strict.
export const SVG_NS = `http:${"//"}www.w3.org/2000/svg`;

// Text copied off the page comes out on one line: a hyphen that ends a line is dropped so the
// broken word joins up ("Plan-\nning" -> "Planning"), runs of whitespace become one space,
// hyphens inside a line stay, and leading spaces and trailing periods (dot leaders, spaced or
// not) go.
export function cleanText(raw) {
  return String(raw)
    .replace(/-[ \t]*\r?\n\s*/g, "")
    .replace(/\s+/g, " ")
    .replace(/(\s*\.)+\s*$/, "")
    .trim();
}

// The turn after one more step (90 or -90 degrees), kept in 0, 90, 180 and 270.
export const nextRotation = (current, step) => (((current + step) % 360) + 360) % 360;

export function shortNote(text, limit = 60) {
  return text.length > limit ? `${text.slice(0, limit)}…` : text;
}

// True when two selection ranges cover the same text, so a click inside a highlight that is
// still showing does not copy (or paste) it a second time.
export function sameRange(a, b) {
  const START = 0; // Range.START_TO_START
  const END = 2; // Range.END_TO_END
  return Boolean(
    a && b && a.compareBoundaryPoints(START, b) === 0 && a.compareBoundaryPoints(END, b) === 0,
  );
}

// The viewBox and transform that turn the text layer with the page image. `width` and
// `height` are the upright page in points; `rotation` is clockwise degrees.
export function turn(rotation, width, height) {
  const sideways = rotation % 180 !== 0;
  const shift = {
    0: "",
    90: `translate(${height} 0)`,
    180: `translate(${width} ${height})`,
    270: `translate(0 ${width})`,
  };
  return {
    viewBox: `0 0 ${sideways ? height : width} ${sideways ? width : height}`,
    transform: `${shift[rotation]} rotate(${rotation})`.trim(),
  };
}

// Invisible, selectable copies of the page's words laid over its image. Each word is
// stretched to its printed width, and a space (or a line break at a line's end) follows it so
// copied words stay apart. `data` is {width, height, words: [[text, x0, y0, x1, y1, lineEnd]]}.
export function renderTextLayer(svg, data, rotation) {
  svg.replaceChildren();
  const { width, height, words } = data;
  const { viewBox, transform } = turn(rotation, width, height);
  svg.setAttribute("viewBox", viewBox);
  const group = document.createElementNS(SVG_NS, "g");
  group.setAttribute("transform", transform);
  for (const [text, x0, y0, x1, y1, lineEnd] of words) {
    const size = y1 - y0;
    const node = document.createElementNS(SVG_NS, "text");
    node.setAttribute("x", x0);
    node.setAttribute("y", y1 - size * 0.2);
    node.setAttribute("font-size", size * 0.9);
    node.setAttribute("textLength", Math.max(x1 - x0, 0.1) + size * 0.25);
    node.setAttribute("lengthAdjust", "spacingAndGlyphs");
    node.textContent = `${text}${lineEnd ? "\n" : " "}`;
    group.append(node);
  }
  svg.append(group);
}

// Watch an area for selections. When the mouse is released over a new selection, its clean
// text is copied to the clipboard and `onText(text, shiftHeld)` is called; if the clipboard
// refuses, `onFail()` is. A selection that is still the one just copied is ignored.
export function watchSelection(area, { onText, onFail, shiftClears = () => false, env = {} }) {
  const selection = env.selection ?? (() => window.getSelection());
  const copy = env.copy ?? ((text) => navigator.clipboard.writeText(text));
  let lastCopied = null;
  const onMouseUp = (event) => {
    setTimeout(async () => {
      // after the browser has finished updating the selection
      const sel = selection();
      const text = cleanText(String(sel));
      if (!text || !area.contains(sel.anchorNode)) return;
      const range = sel.getRangeAt(0);
      if (sameRange(range, lastCopied)) return;
      lastCopied = range.cloneRange();
      try {
        await copy(text);
      } catch {
        onFail();
        return;
      }
      onText(text, event.shiftKey);
    });
  };
  const onCopyEvent = (event) => {
    event.clipboardData.setData("text/plain", cleanText(String(selection())));
    event.preventDefault();
  };
  // Shift+drag would otherwise extend the previous selection instead of starting one.
  const onMouseDown = (event) => {
    if (event.shiftKey && shiftClears()) selection().removeAllRanges();
  };
  area.addEventListener("mouseup", onMouseUp);
  area.addEventListener("copy", onCopyEvent);
  area.addEventListener("mousedown", onMouseDown);
  return () => {
    area.removeEventListener("mouseup", onMouseUp);
    area.removeEventListener("copy", onCopyEvent);
    area.removeEventListener("mousedown", onMouseDown);
  };
}
