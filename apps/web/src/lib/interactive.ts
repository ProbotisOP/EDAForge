// Helpers for chart interaction modes and CSV data export.

type Obj = Record<string, unknown>;
const isObj = (v: unknown): v is Obj => !!v && typeof v === "object" && !Array.isArray(v);

export type Interaction = "none" | "hover" | "full";

/** The rows embedded in the chart (the first data set found), for "download data". */
export function chartRows(spec: Obj): Obj[] {
  const pick = (o: Obj): Obj[] | null =>
    isObj(o.data) && Array.isArray(o.data.values) ? (o.data.values as Obj[]) : null;
  const top = pick(spec);
  if (top) return top;
  for (const l of Array.isArray(spec.layer) ? spec.layer : []) {
    if (isObj(l)) {
      const rows = pick(l);
      if (rows) return rows;
    }
  }
  return [];
}

export function toCsv(rows: Obj[]): string {
  const cols = [...new Set(rows.flatMap((r) => Object.keys(r)))];
  const cell = (v: unknown) => {
    let s =
      v === null || v === undefined
        ? ""
        : typeof v === "object"
          ? JSON.stringify(v)
          : String(v);
    if (typeof v === "string" && /^[=+\-@\t\r]/.test(s)) s = `'${s}`; // spreadsheet formula injection
    return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
  };
  return [
    cols.map(cell).join(","),
    ...rows.map((r) => cols.map((c) => cell(r[c])).join(",")),
  ].join("\n");
}
