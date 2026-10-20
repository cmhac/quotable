// Hash routes: one place that reads and writes the URL, so reload, back and a copied link work.

const NOT_FOUND = (hash) => ({ name: "notfound", hash });
const DIGITS = /^[0-9]+$/;

export function parseHash(hash) {
  const [path, ...rest] = String(hash ?? "")
    .replace(/^#/, "")
    .split("?");
  const query = Object.fromEntries(new URLSearchParams(rest.join("?")));
  let parts;
  try {
    parts = path.split("/").slice(1).map(decodeURIComponent);
  } catch {
    return NOT_FOUND(hash);
  }
  if (path !== "" && !path.startsWith("/")) return NOT_FOUND(hash);
  const [head, run, word, table, kind, page, row, name, tail] = parts;
  if (parts.length === 0 || (parts.length === 1 && head === ""))
    return { name: "runs", query };
  if (head === "queue" && parts.length === 1) return { name: "queue", query };
  if (head !== "run" || !run) return NOT_FOUND(hash);
  if (parts.length === 2) return { name: "run", run, query };
  if (word !== "table" || !DIGITS.test(table ?? "")) return NOT_FOUND(hash);
  if (parts.length === 4)
    return { name: "table", run, table: Number(table), query };
  if (kind !== "cell" || !DIGITS.test(page ?? "") || !DIGITS.test(row ?? ""))
    return NOT_FOUND(hash);
  const base = { name: "cell", run, table: Number(table), query };
  const at = { page: Number(page), row: Number(row) };
  if (parts.length === 8 && name)
    return { ...base, cell: { ...at, name, extra: false } };
  if (parts.length === 9 && name === "extra" && tail)
    return { ...base, cell: { ...at, name: tail, extra: true } };
  return NOT_FOUND(hash);
}

export function hashFor(route) {
  const part = encodeURIComponent;
  let path = "/";
  if (route.name === "run") path = `/run/${part(route.run)}`;
  else if (route.name === "table")
    path = `/run/${part(route.run)}/table/${route.table}`;
  else if (route.name === "cell") {
    const { page, row, name, extra } = route.cell;
    path = `/run/${part(route.run)}/table/${route.table}/cell/${page}/${row}/${extra ? "extra/" : ""}${part(name)}`;
  } else if (route.name === "queue") path = "/queue";
  const entries = Object.entries(route.query ?? {}).filter(
    ([, v]) => v !== null && v !== undefined && v !== "",
  );
  return `#${path}${entries.length ? `?${new URLSearchParams(entries)}` : ""}`;
}
