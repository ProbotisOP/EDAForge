// Display formatting only. Statistical values arrive computed (and, in explanations, already
// formatted) by the engine; these helpers only lay numbers out for tables and labels.

export function fmtInt(n: number | null | undefined): string {
  if (n === null || n === undefined || Number.isNaN(n)) return "—";
  return Math.round(n).toLocaleString("en-US");
}

export function fmtNum(n: number | null | undefined, digits = 4): string {
  if (n === null || n === undefined) return "—";
  if (typeof n !== "number" || !Number.isFinite(n)) return String(n);
  if (n === 0) return "0";
  const abs = Math.abs(n);
  if (abs >= 1e15 || abs < 1e-4) return n.toExponential(2);
  return n.toLocaleString("en-US", { maximumSignificantDigits: digits });
}

export function fmtPct(share: number | null | undefined, digits = 1): string {
  if (share === null || share === undefined || Number.isNaN(share)) return "—";
  if (share > 0 && share < 0.001) return "<0.1%";
  return `${(share * 100).toFixed(digits)}%`;
}

export function fmtBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  if (n < 1024 * 1024 * 1024) return `${(n / 1024 / 1024).toFixed(1)} MB`;
  return `${(n / 1024 / 1024 / 1024).toFixed(2)} GB`;
}

export function fmtDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString("en-US", { dateStyle: "medium", timeStyle: "short" });
}

export function fmtCell(value: unknown): string {
  if (value === null || value === undefined) return "";
  if (typeof value === "number") return Number.isInteger(value) ? String(value) : fmtNum(value, 6);
  if (typeof value === "boolean") return value ? "true" : "false";
  return String(value);
}

export function plural(n: number, one: string, many?: string): string {
  return `${fmtInt(n)} ${n === 1 ? one : many ?? one + "s"}`;
}

export const ROLE_LABEL: Record<string, string> = {
  numeric: "Number",
  categorical: "Category",
  boolean: "Yes/No",
  datetime: "Date/time",
  identifier: "Identifier",
  text: "Free text",
  empty: "Empty",
  internal: "Row #",
};
