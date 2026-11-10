// The gold page in the browser: the tables being typed, as the editor (grid.js) holds them
// ({columns, rows: [{cells, ghost}]}), and how they turn into what the server stores. Pure.

export const START_ROWS = 20;

// A table to type into: one unnamed column and empty rows. Nothing typed in it means "no table".
export const blankTable = () => ({
  columns: [""],
  rows: Array.from({ length: START_ROWS }, () => ({ cells: [""], ghost: false })),
});

export function padRows(table, count = START_ROWS) {
  while (table.rows.length < count) {
    table.rows.push({ cells: table.columns.map(() => ""), ghost: false });
  }
}

// A stored page (or none) as editor tables; there is always at least one to type into.
export function fromRecord(record, { pad = true } = {}) {
  const tables = (record?.tables ?? []).map((t) => ({
    columns: [...t.columns],
    rows: t.rows.map((cells) => ({ cells: [...cells], ghost: false })),
  }));
  if (!tables.length) tables.push(blankTable());
  if (pad) for (const t of tables) padRows(t);
  return tables;
}

export const isBlank = (t) =>
  t.columns.every((c) => !c.trim()) && t.rows.every((r) => r.cells.every((v) => v === ""));

function trimmedRows(table) {
  const rows = table.rows.map((r) => [...r.cells]);
  while (rows.length && rows.at(-1).every((v) => v === "")) rows.pop();
  return rows;
}

// What the server is sent: the tables with anything in them, empty rows at the bottom cut.
export const toPayload = (tables) =>
  tables.filter((t) => !isBlank(t)).map((t) => ({ columns: [...t.columns], rows: trimmedRows(t) }));

// The server's rule for a done page, checked first so the message comes without a round trip.
export function problem(tables) {
  const used = tables.filter((t) => !isBlank(t));
  for (const [i, t] of used.entries()) {
    const names = t.columns.map((c) => c.trim());
    if (!names.every(Boolean) || new Set(names).size !== names.length) {
      return `Name every column of table ${i + 1}, each name once, before marking the page done.`;
    }
  }
  return null;
}

export function status(tables, done) {
  if (done) return "done";
  return tables.some((t) => !isBlank(t)) ? "started" : "new";
}

export function addTable(tables) {
  tables.push(blankTable());
  return tables.length - 1;
}

// Returns the table to show next; the last table removed leaves a blank one.
export function removeTable(tables, index) {
  tables.splice(index, 1);
  if (!tables.length) tables.push(blankTable());
  return Math.min(index, tables.length - 1);
}

export function trimBottom(table) {
  while (table.rows.length && table.rows.at(-1).cells.every((v) => v === "")) table.rows.pop();
}
