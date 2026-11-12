import { useCallback, useEffect, useState } from "react";
import { api } from "../lib/api";
import { fmtCell, fmtInt, ROLE_LABEL } from "../lib/format";
import type { RowsPage } from "../lib/types";
import { ErrorBox, Spinner } from "./ui";

const PAGE = 50;

/** Paginated, sortable preview of a stored dataset (values as stored after parsing). */
export function DataTable({ projectId, datasetId }: { projectId: string; datasetId: string }) {
  const [page, setPage] = useState<RowsPage | null>(null);
  const [offset, setOffset] = useState(0);
  const [sort, setSort] = useState<{ column: string; desc: boolean } | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(() => {
    setLoading(true);
    setError(null);
    api
      .rows(projectId, datasetId, offset, PAGE, sort?.column, sort?.desc)
      .then(setPage)
      .catch(setError)
      .finally(() => setLoading(false));
  }, [projectId, datasetId, offset, sort]);

  useEffect(() => {
    setOffset(0);
    setSort(null);
  }, [datasetId]);
  useEffect(load, [load]);

  if (error) return <ErrorBox error={error} onRetry={load} />;
  if (!page) return <Spinner label="Loading rows…" />;

  const end = Math.min(page.total, offset + page.rows.length);
  const toggleSort = (column: string) =>
    setSort((s) => (s?.column === column ? (s.desc ? null : { column, desc: true }) : { column, desc: false }));

  return (
    <div className="stack">
      <div className="spread">
        <span className="muted">
          Rows {fmtInt(page.total ? offset + 1 : 0)}–{fmtInt(end)} of {fmtInt(page.total)}
          {sort ? ` · sorted by ${sort.column} ${sort.desc ? "↓" : "↑"}` : ""}
          {loading ? " · loading…" : ""}
        </span>
        <div className="row">
          <button className="btn btn-sm" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE))}>
            ← Previous
          </button>
          <button className="btn btn-sm" disabled={end >= page.total} onClick={() => setOffset(offset + PAGE)}>
            Next →
          </button>
        </div>
      </div>
      <div className="table-wrap" style={{ maxHeight: 520 }}>
        <table className="data">
          <thead>
            <tr>
              {page.columns.map((c) => (
                <th
                  key={c.name}
                  className={`sortable ${c.dtype === "integer" || c.dtype === "float" ? "num" : ""}`}
                  onClick={() => toggleSort(c.name)}
                  title={`Sort by ${c.name}`}
                >
                  {c.internal ? "#" : c.name}
                  {sort?.column === c.name ? (sort.desc ? " ↓" : " ↑") : ""}
                  <span className="col-type">
                    {c.internal ? "row in file" : `${ROLE_LABEL[c.role] ?? c.role} · ${c.dtype}`}
                    {c.pii ? " · personal data" : ""}
                  </span>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {page.rows.map((row, i) => (
              <tr key={offset + i}>
                {row.map((value, j) => {
                  const column = page.columns[j];
                  const numeric = column.dtype === "integer" || column.dtype === "float";
                  const text = fmtCell(value);
                  return (
                    <td key={j} className={column.internal ? "rownum num" : numeric ? "num" : ""} title={text}>
                      {value === null || value === undefined ? <span className="null">missing</span> : text}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
