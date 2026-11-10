// Spreadsheet-style editor for one gold table (spec 016; ported from the VRA gold annotation app).
//
// Model: {columns: [...names], rows: [{cells: [...], ghost: bool}], done}.
// Grid rows: -1 is the column-name row, 0..rows.length-1 the data rows, and
// rows.length the always-empty ghost row. Writing into the ghost row makes a real
// row marked ghost; if the bottom row is a ghost row and becomes empty again it is
// dropped. Rows made with "New row", and rows blanked higher up, are kept.
//
// Cells are selected like a spreadsheet: click, drag or Shift+arrows to select a
// block; type to replace a cell, Enter/F2/double-click to edit it (paste keeps line
// breaks while editing); Delete clears the block; Cmd+C/X/V copy, cut and paste
// tab-separated blocks. The pure functions below have no DOM, so node can test them.

import { el } from "./dom.js";

// -- model ---------------------------------------------------------------------

export function cellValue(t, r, c) {
  if (r < 0) return t.columns[c] ?? "";
  return t.rows[r]?.cells[c] ?? "";
}

export function trim(t) {
  while (t.rows.length && t.rows.at(-1).ghost && t.rows.at(-1).cells.every((v) => v === "")) {
    t.rows.pop();
  }
}

export function setCell(t, r, c, v) {
  if (r < 0) t.columns[c] = v;
  else if (r < t.rows.length) t.rows[r].cells[c] = v;
  else if (v !== "") {
    while (t.rows.length < r) t.rows.push({ cells: t.columns.map(() => ""), ghost: true });
    const cells = t.columns.map(() => "");
    cells[c] = v;
    t.rows.push({ cells, ghost: true });
  }
}

export function clearRange(t, [r0, c0, r1, c1]) {
  for (let r = r0; r <= r1; r++) for (let c = c0; c <= c1; c++) setCell(t, r, c, "");
  trim(t);
}

// Paste a block at (r0, c0), adding columns as needed. Returns the block's range.
export function pasteAt(t, r0, c0, block) {
  const width = c0 + Math.max(...block.map((line) => line.length));
  while (t.columns.length < width) {
    t.columns.push("");
    t.rows.forEach((row) => row.cells.push(""));
  }
  block.forEach((line, i) => line.forEach((v, j) => setCell(t, r0 + i, c0 + j, v)));
  trim(t);
  return [r0, c0, r0 + block.length - 1, width - 1];
}

// Fill ``dst`` by repeating the ``src`` block, as Excel's fill handle copies cells.
// Values are copied as they are; numbers are not turned into a series.
export function fillRange(t, [sr0, sc0, sr1, sc1], [dr0, dc0, dr1, dc1]) {
  const h = sr1 - sr0 + 1;
  const w = sc1 - sc0 + 1;
  const mod = (n, m) => ((n % m) + m) % m;
  for (let r = dr0; r <= dr1; r++) {
    for (let c = dc0; c <= dc1; c++) {
      setCell(t, r, c, cellValue(t, sr0 + mod(r - sr0, h), sc0 + mod(c - sc0, w)));
    }
  }
  trim(t);
}

// Tab-separated text as spreadsheets copy it: a cell holding a tab, line break or
// quote is wrapped in quotes, with inner quotes doubled.
export function parseTsv(raw) {
  const text = raw.replace(/\r\n?/g, "\n").replace(/\n$/, "");
  const out = [[]];
  let i = 0;
  while (i <= text.length) {
    let value = "";
    if (text[i] === '"') {
      i++;
      while (i < text.length) {
        if (text[i] === '"' && text[i + 1] === '"') {
          value += '"';
          i += 2;
        } else if (text[i] === '"') {
          i++;
          break;
        } else value += text[i++];
      }
    }
    while (i < text.length && text[i] !== "\t" && text[i] !== "\n") value += text[i++];
    out.at(-1).push(value);
    if (text[i] === "\n") out.push([]);
    i++;
  }
  return out;
}

export function toTsv(block) {
  const quote = (v) => (/[\t\n"]/.test(v) ? `"${v.replace(/"/g, '""')}"` : v);
  return block.map((line) => line.map(quote).join("\t")).join("\n");
}

// -- DOM -----------------------------------------------------------------------

export function mountGrid(table, keys, getTable, onChange) {
  // Undo history: a snapshot of the table and selection after each change.
  const HISTORY = 200;
  let past = [];
  let future = [];
  let now = null;
  const snap = () =>
    structuredClone({ columns: getTable().columns, rows: getTable().rows, active, extent });
  function changed() {
    // undo goes back to the selection as it was just before this change
    past = [...past, { ...now, active, extent }].slice(-HISTORY);
    future = [];
    now = snap();
    onChange();
  }
  function travel(from, to) {
    if (!from.length) return;
    to.push(now);
    now = from.pop();
    const { columns, rows, active: a, extent: x } = structuredClone(now);
    Object.assign(getTable(), { columns, rows });
    active = a;
    extent = x;
    onChange();
    render();
    table
      .querySelector(`.cell[data-r="${active[0]}"][data-c="${active[1]}"]`)
      ?.scrollIntoView({ block: "nearest", inline: "nearest" });
  }

  let active = [-1, 0];
  let extent = [-1, 0];
  let edit = null; // {r, c, typed, el}
  let dragging = false;
  let lock = null; // "column" or "row" lock mode: page copies go into the active cell
  let fill = null; // {src, dst} while the fill handle is dragged

  const inside = ([r0, c0, r1, c1], r, c) => r >= r0 && r <= r1 && c >= c0 && c <= c1;
  const range = () => [
    Math.min(active[0], extent[0]),
    Math.min(active[1], extent[1]),
    Math.max(active[0], extent[0]),
    Math.max(active[1], extent[1]),
  ];
  const clamp = ([r, c]) => {
    const t = getTable();
    return [Math.max(-1, Math.min(r, t.rows.length)), Math.max(0, Math.min(c, t.columns.length - 1))];
  };
  const select = (pos, extend = false) => {
    if (!extend) active = clamp(pos);
    extent = clamp(pos);
    render();
  };
  const block = () => {
    const [r0, c0, r1, c1] = range();
    const out = [];
    for (let r = r0; r <= r1; r++) {
      const line = [];
      for (let c = c0; c <= c1; c++) line.push(cellValue(getTable(), r, c));
      out.push(line);
    }
    return out;
  };

  const removeButton = (label, onClick) =>
    el(
      "button",
      { type: "button", class: "remove", tabindex: -1, title: label, "aria-label": label, onclick: onClick },
      "×",
    );

  function render() {
    const t = getTable();
    const [r0, c0, r1, c1] = range();
    const cell = (tag, r, c) => {
      const lane = lock === "row" ? r === active[0] : c === active[1];
      const classes = ["cell"];
      if (lock && lane) classes.push("lock-lane");
      if (r >= r0 && r <= r1 && c >= c0 && c <= c1) classes.push("sel");
      if (r === active[0] && c === active[1]) classes.push("active");
      if (fill && inside(fill.dst, r, c) && !inside(fill.src, r, c)) classes.push("fill");
      return el(
        tag,
        { class: classes.join(" "), "data-r": r, "data-c": c },
        el("span", { class: "text" }, cellValue(t, r, c)),
        !edit && !fill && r === r1 && c === c1
          ? el("div", { class: "fill-handle", title: "Drag to fill; double-click to fill down" })
          : null,
      );
    };
    const head = el("tr", null, el("th"));
    t.columns.forEach((_, c) => {
      const th = cell("th", -1, c);
      th.append(removeButton(`Delete column ${c + 1}`, () => deleteColumn(c)));
      head.append(th);
    });
    const body = [];
    for (let r = 0; r <= t.rows.length; r++) {
      const lead = el(
        "td",
        { class: r >= r0 && r <= r1 ? "lead sel" : "lead", "data-row": r },
        el("span", { class: "row-number" }, r + 1),
        r < t.rows.length ? removeButton(`Delete row ${r + 1}`, () => deleteRow(r)) : null,
      );
      body.push(
        el("tr", { class: r < t.rows.length ? null : "ghost" }, lead, ...t.columns.map((_, c) => cell("td", r, c))),
      );
    }
    table.replaceChildren(head, ...body);
    const current = table.querySelector(".cell.active");
    if (edit && current) {
      const ta = el("textarea", { class: "editor", "aria-label": "Edit cell" });
      current.append(ta);
      edit.el = ta;
    } else if (document.activeElement === keys && !dragging && !fill) {
      // keep the moving corner in view (Shift+arrows move the extent, not the
      // active cell); mouse drags scroll themselves, see autoScroll
      table
        .querySelector(`.cell[data-r="${extent[0]}"][data-c="${extent[1]}"]`)
        ?.scrollIntoView({ block: "nearest", inline: "nearest" });
    }
  }

  function startEdit(value, typed) {
    edit = { r: active[0], c: active[1], typed };
    extent = active;
    render();
    const ta = edit.el;
    ta.value = value;
    ta.rows = Math.max(2, value.split("\n").length);
    ta.focus();
    ta.setSelectionRange(value.length, value.length);
    ta.addEventListener("keydown", onEditKey);
    ta.addEventListener("input", () => (ta.rows = Math.max(2, ta.value.split("\n").length)));
    ta.addEventListener("blur", () => commit());
  }

  function commit(move) {
    if (!edit) return;
    const { r, c, el } = edit;
    edit = null;
    setCell(getTable(), r, c, el.value);
    trim(getTable());
    changed();
    keys.focus({ preventScroll: true });
    if (typeof move === "function") select(move(r, c));
    else if (move) select([r + move[0], c + move[1]]);
    else select(active);
  }

  // Tab past the last column wraps to the next row's first cell; below the last
  // row that is the empty bottom row, so typing there starts a new row.
  // Shift+Tab wraps back the same way. In a lock mode, Tab from the last column
  // adds a new column instead (its own undo step).
  const tabFrom = (back) => (r, c) => {
    const t = getTable();
    const last = t.columns.length - 1;
    if (back) return c > 0 ? [r, c - 1] : r > -1 ? [r - 1, last] : [r, c];
    if (c < last) return [r, c + 1];
    if (!lock) return [r + 1, 0];
    t.columns.push("");
    t.rows.forEach((row) => row.cells.push(""));
    changed();
    return [r, c + 1];
  };

  function onEditKey(e) {
    const ta = e.target;
    const mod = e.metaKey || e.ctrlKey;
    if (e.key === "Escape") {
      e.preventDefault();
      edit = null;
      keys.focus({ preventScroll: true });
      render();
    } else if (e.key === "Enter" && (e.altKey || e.shiftKey || mod)) {
      e.preventDefault(); // a line break inside the cell
      ta.setRangeText("\n", ta.selectionStart, ta.selectionEnd, "end");
      ta.dispatchEvent(new Event("input"));
    } else if (e.key === "Enter") {
      e.preventDefault();
      commit([1, 0]);
    } else if (e.key === "Tab") {
      e.preventDefault();
      commit(tabFrom(e.shiftKey));
    } else if (edit.typed && !mod && !e.shiftKey && ARROWS[e.key]) {
      e.preventDefault(); // typing over a cell: arrows move on, as in a spreadsheet
      commit(ARROWS[e.key]);
    }
  }

  function onKey(e) {
    const t = getTable();
    const mod = e.metaKey || e.ctrlKey;
    const k = e.key;
    if (mod && (k === "c" || k === "x")) {
      keys.value = toTsv(block()); // the browser copies the selected hidden text
      keys.select();
      if (k === "x")
        setTimeout(() => {
          clearRange(t, range());
          changed();
          render();
        });
    } else if (mod && k === "v") {
      keys.value = ""; // the paste event does the work
    } else if (mod && (k.toLowerCase() === "z" || k === "y")) {
      e.preventDefault(); // Cmd+Z undo; Cmd+Shift+Z or Cmd+Y redo
      if (k === "y" || e.shiftKey) travel(future, past);
      else travel(past, future);
    } else if (mod && (k === "d" || k === "r")) {
      e.preventDefault(); // instead of bookmarking / reloading the page
      fillShortcut(k === "d");
    } else if (mod && k === "a") {
      e.preventDefault();
      active = [-1, 0];
      select([t.rows.length, t.columns.length - 1], true);
    } else if (ARROWS[k]) {
      e.preventDefault();
      const [dr, dc] = ARROWS[k];
      const from = e.shiftKey ? extent : active;
      const far = [dr ? (dr < 0 ? -1 : t.rows.length) : from[0], dc ? (dc < 0 ? 0 : t.columns.length - 1) : from[1]];
      select(mod ? far : [from[0] + dr, from[1] + dc], e.shiftKey);
    } else if (k === "Tab") {
      e.preventDefault();
      select(tabFrom(e.shiftKey)(...active));
    } else if (k === "Enter" || k === "F2") {
      e.preventDefault();
      startEdit(cellValue(t, ...active), false);
    } else if (k === "Delete" || k === "Backspace") {
      e.preventDefault();
      clearRange(t, range());
      changed();
      select(active, true);
    } else if (k === "Escape") {
      select(active);
    } else if (k.length === 1 && !mod) {
      e.preventDefault();
      startEdit(k, true);
    }
  }

  function onPaste(e) {
    e.preventDefault();
    const [r0, c0] = range();
    const [, , r1, c1] = pasteAt(getTable(), r0, c0, parseTsv(e.clipboardData.getData("text/plain")));
    changed();
    active = clamp([r0, c0]);
    extent = clamp([r1, c1]);
    render();
  }

  function deleteColumn(c) {
    const t = getTable();
    const used = t.rows.some((r) => r.cells[c] !== "");
    if (used && !confirm(`Delete column "${t.columns[c] || c + 1}" and its values?`)) return;
    t.columns.splice(c, 1);
    t.rows.forEach((r) => r.cells.splice(c, 1));
    if (!t.columns.length) t.columns.push("");
    changed();
    select(active);
  }

  function deleteRow(r) {
    getTable().rows.splice(r, 1);
    changed();
    select(active);
  }

  // Drag the fill handle: the target grows along whichever axis the pointer has
  // moved further outside the selection, as in Excel.
  function fillTo([r, c]) {
    const [r0, c0, r1, c1] = fill.src;
    const dr = r < r0 ? r - r0 : r > r1 ? r - r1 : 0;
    const dc = c < c0 ? c - c0 : c > c1 ? c - c1 : 0;
    fill.dst =
      Math.abs(dr) >= Math.abs(dc)
        ? [Math.min(r0, r), c0, Math.max(r1, r), c1]
        : [r0, Math.min(c0, c), r1, Math.max(c1, c)];
    render();
  }

  function applyFill(dst) {
    const src = fill.src;
    fill = null;
    fillRange(getTable(), src, dst);
    changed();
    active = clamp([dst[0], dst[1]]);
    select([dst[2], dst[3]], true);
  }

  // Cmd/Ctrl+D fills down and Cmd/Ctrl+R fills right: from the top row (or left
  // column) of the selection, or from the cell above (or left) of a single row.
  function fillShortcut(down) {
    const [r0, c0, r1, c1] = range();
    const [a, b] = down ? [r0, r1] : [c0, c1];
    const lo = a === b ? a - 1 : a;
    if (lo < (down ? -1 : 0)) return;
    fill = { src: down ? [lo, c0, lo, c1] : [r0, lo, r1, lo] };
    applyFill(down ? [lo, c0, r1, c1] : [r0, lo, r1, c1]);
  }

  const cellAt = (e) => (e.target.closest("button") ? null : e.target.closest(".cell"));
  const posOf = (el) => [Number(el.dataset.r), Number(el.dataset.c)];
  // Every click re-renders the table, so the two clicks of a double-click land on
  // different elements and the browser's dblclick event is unreliable; count our own.
  let lastDown = { at: 0, where: "" };
  const isDouble = (where) => {
    const now = Date.now();
    const double = where === lastDown.where && now - lastDown.at < 500;
    lastDown = { at: double ? 0 : now, where };
    return double;
  };

  function fillDown() {
    // As Excel: fill down as far as the longest of the other columns runs (its
    // last non-empty row), ignoring empty rows below. No data there, no fill.
    const [r0, c0, r1, c1] = range();
    const t = getTable();
    let last = -1;
    t.rows.forEach((row, r) => {
      if (row.cells.some((v, c) => v !== "" && (c < c0 || c > c1))) last = r;
    });
    if (last <= r1) return;
    fill = { src: [r0, c0, r1, c1] };
    applyFill([r0, c0, last, c1]);
  }

  table.addEventListener("mousedown", (e) => {
    if (e.target.classList.contains("fill-handle")) {
      e.preventDefault();
      if (isDouble("handle")) return fillDown();
      fill = { src: range(), dst: range() };
      keys.focus({ preventScroll: true });
      render();
      return;
    }
    const lead = !e.target.closest("button") && e.target.closest(".lead");
    if (lead) {
      // clicking a row number selects the whole row (Shift extends), as in Excel
      e.preventDefault();
      commit();
      keys.focus({ preventScroll: true });
      const r = Number(lead.dataset.row);
      active = clamp([e.shiftKey ? active[0] : r, 0]);
      select([r, getTable().columns.length - 1], true);
      return;
    }
    const el = cellAt(e);
    if (!el || e.target === edit?.el) return;
    e.preventDefault();
    commit();
    const pos = [Number(el.dataset.r), Number(el.dataset.c)];
    keys.focus({ preventScroll: true });
    if (isDouble(pos.join()) && !e.shiftKey) {
      active = extent = clamp(pos);
      startEdit(cellValue(getTable(), ...active), false);
      return;
    }
    dragging = true;
    select(pos, e.shiftKey);
  });
  // While dragging a selection or the fill handle, follow the pointer even outside
  // the table: the cell under it is found with the pointer pinned inside the visible
  // part of the table, and the panel scrolls when the pointer nears or passes an
  // edge, as in Excel.
  let pointer = null;
  let frame = 0;
  let lastCell = "";
  const scrollers = () => {
    const out = [];
    for (let el = table.parentElement; el && el !== document.body; el = el.parentElement) {
      const style = getComputedStyle(el);
      if (/(auto|scroll)/.test(style.overflow + style.overflowX + style.overflowY)) out.push(el);
    }
    return out;
  };
  function followPointer() {
    let { left, top, right, bottom } = table.getBoundingClientRect();
    for (const s of scrollers()) {
      const r = s.getBoundingClientRect();
      [left, top, right, bottom] = [Math.max(left, r.left), Math.max(top, r.top), Math.min(right, r.right), Math.min(bottom, r.bottom)];
    }
    const x = Math.min(Math.max(pointer.x, left + 2), right - 2);
    const y = Math.min(Math.max(pointer.y, top + 2), bottom - 2);
    const el = document.elementFromPoint(x, y)?.closest(".cell");
    if (!el || !table.contains(el)) return;
    const pos = posOf(el);
    if (pos.join() === lastCell) return;
    lastCell = pos.join();
    if (fill) fillTo(pos);
    else select(pos, true);
  }
  function autoScroll() {
    frame = 0;
    if (!pointer || !(dragging || fill)) return;
    const EDGE = 30;
    const speed = (d) => Math.sign(d) * Math.min(40, Math.ceil(Math.abs(d) / 3));
    for (const s of scrollers()) {
      const r = s.getBoundingClientRect();
      const dy = pointer.y < r.top + EDGE ? pointer.y - r.top - EDGE : pointer.y > r.bottom - EDGE ? pointer.y - r.bottom + EDGE : 0;
      const dx = pointer.x < r.left + EDGE ? pointer.x - r.left - EDGE : pointer.x > r.right - EDGE ? pointer.x - r.right + EDGE : 0;
      if (dy) s.scrollTop += speed(dy);
      if (dx) s.scrollLeft += speed(dx);
    }
    followPointer();
    frame = requestAnimationFrame(autoScroll);
  }
  document.addEventListener("mousemove", (e) => {
    if (!(dragging || fill)) return;
    pointer = { x: e.clientX, y: e.clientY };
    followPointer();
    if (!frame) frame = requestAnimationFrame(autoScroll);
  });
  document.addEventListener("mouseup", () => {
    pointer = null;
    lastCell = "";
    cancelAnimationFrame(frame);
    frame = 0;
    dragging = false;
    if (!fill) return;
    if (fill.dst.join() === fill.src.join()) {
      fill = null;
      render();
    } else applyFill(fill.dst);
  });
  keys.addEventListener("keydown", onKey);
  keys.addEventListener("paste", onPaste);
  keys.addEventListener("focus", () => table.classList.add("focused"));
  keys.addEventListener("blur", () => table.classList.remove("focused"));

  return {
    render,
    commit,
    // Keys pressed while the focus is elsewhere (e.g. on the page) act on the
    // table. The focus is left alone so a highlight on the page stays.
    key(e) {
      if (edit) return;
      onKey(e);
      table
        .querySelector(`.cell[data-r="${extent[0]}"][data-c="${extent[1]}"]`)
        ?.scrollIntoView({ block: "nearest", inline: "nearest" });
    },
    setLock(mode) {
      lock = mode;
      table.classList.toggle("lock", Boolean(mode));
      render();
    },
    // Lock modes: put text in the active cell, then move down its column ("column")
    // or along its row, wrapping to the next row's first cell like Tab ("row").
    // One undoable change; undo returns to the cell it went into.
    // With append, the text is added to the cell after a "." (for multi-level
    // column names) and the selection stays on that cell.
    pasteNext(text, append = false) {
      commit();
      // Row mode may fill the column names (they are a row too). Column mode never
      // does: from the name row it starts at the first data row.
      const [r, c] = [lock === "row" ? active[0] : Math.max(active[0], 0), active[1]];
      active = extent = [r, c]; // so undo comes back to this cell
      const t = getTable();
      const old = r < 0 ? t.columns[c] : (t.rows[r]?.cells[c] ?? "");
      setCell(t, r, c, append && old ? `${old}.${text}` : text);
      trim(t);
      // Row mode on the last column name: add a column and move into it, so the
      // header can be copied across. Same undo step as the paste.
      const grow = !append && lock === "row" && r < 0 && c === t.columns.length - 1;
      if (grow) {
        t.columns.push("");
        t.rows.forEach((row) => row.cells.push(""));
      }
      changed();
      // Column mode: on reaching the last row the tallest other column fills, go
      // to the top of the next column. If no other column runs past row 1, rows
      // are still being built, so carry on down; the last column also carries on.
      let last = -1;
      t.rows.forEach((row, i) => {
        if (row.cells.some((v, j) => v !== "" && j !== c)) last = i;
      });
      const endOfColumn = last > 0 && r === last && c < t.columns.length - 1;
      if (append) select([r, c]);
      else if (grow) select([-1, c + 1]);
      else if (lock === "row") select(c < t.columns.length - 1 ? [r, c + 1] : [r + 1, 0]);
      else select(endOfColumn ? [0, c + 1] : [r + 1, c]);
      table
        .querySelector(`.cell[data-r="${active[0]}"][data-c="${active[1]}"]`)
        ?.scrollIntoView({ block: "nearest", inline: "nearest" });
      const name = getTable().columns[c] || `column ${c + 1}`;
      return r < 0 ? `column name ${c + 1}` : `row ${r + 1}, ${name}`;
    },
    undo: () => (commit(), travel(past, future)),
    redo: () => (commit(), travel(future, past)),
    reset() {
      edit = null;
      active = extent = [-1, 0];
      past = [];
      future = [];
      now = snap();
      render();
    },
    addRow() {
      const t = getTable();
      t.rows.push({ cells: t.columns.map(() => ""), ghost: false });
      changed();
      keys.focus({ preventScroll: true });
      select([t.rows.length - 1, 0]);
    },
    addColumn() {
      const t = getTable();
      t.columns.push("");
      t.rows.forEach((r) => r.cells.push(""));
      changed();
      active = extent = [-1, t.columns.length - 1];
      startEdit("", true);
    },
  };
}

const ARROWS = { ArrowUp: [-1, 0], ArrowDown: [1, 0], ArrowLeft: [0, -1], ArrowRight: [0, 1] };
