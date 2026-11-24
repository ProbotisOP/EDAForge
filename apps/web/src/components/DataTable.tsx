import { useCallback, useEffect, useMemo, useState } from "react";
import { ArrowDown, ArrowUp, ChevronLeft, ChevronRight, Search } from "lucide-react";
import { api } from "../lib/api";
import { fmtCell, fmtInt, ROLE_LABEL } from "../lib/format";
import type { RowsPage } from "../lib/types";
import { SpringSegmented } from "./kit";
import { Badge, ErrorBox, Spinner } from "./ui";

const PAGE = 50;

/**
 * Kibo UI inspired high-density sortable & filterable dataset grid.
 */
export function DataTable({ projectId, datasetId }: { projectId: string; datasetId: string }) {
  const [page, setPage] = useState<RowsPage | null>(null);
  const [offset, setOffset] = useState(0);
  const [sort, setSort] = useState<{ column: string; desc: boolean } | null>(null);
  const [filterText, setFilterText] = useState("");
  const [density, setDensity] = useState<"compact" | "comfortable">("compact");
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
    setFilterText("");
  }, [datasetId]);
  useEffect(load, [load]);

  const filteredRows = useMemo(() => {
    if (!page) return [];
    const q = filterText.trim().toLowerCase();
    if (!q) return page.rows;
    return page.rows.filter((row) => row.some((v) => v !== null && v !== undefined && String(v).toLowerCase().includes(q)));
  }, [page, filterText]);

  if (error) return <ErrorBox error={error} onRetry={load} />;
  if (!page) return <Spinner label="Loading rows…" />;

  const end = Math.min(page.total, offset + page.rows.length);
  const toggleSort = (column: string) =>
    setSort((s) => (s?.column === column ? (s.desc ? null : { column, desc: true }) : { column, desc: false }));

  return (
    <div className="stack">
      <div className="spread" style={{ flexWrap: "wrap", gap: 10 }}>
        <div className="row-wrap" style={{ gap: 10 }}>
          <span className="muted small mono">
            Rows {fmtInt(page.total ? offset + 1 : 0)}–{fmtInt(end)} of {fmtInt(page.total)}
            {sort ? ` · sorted by ${sort.column} ${sort.desc ? "↓" : "↑"}` : ""}
            {loading ? " · loading…" : ""}
          </span>
          <Badge tone="outline">{page.columns.filter((c) => !c.internal).length} cols</Badge>
        </div>

        <div className="row-wrap" style={{ gap: 8 }}>
          <div className="search-field">
            <Search size={13} className="search-icon" />
            <input
              type="search"
              placeholder="Filter visible rows…"
              value={filterText}
              onChange={(e) => setFilterText(e.target.value)}
              style={{ height: 28, paddingLeft: 28, width: 175, fontSize: 12 }}
              aria-label="Filter visible rows"
            />
          </div>

          <SpringSegmented<"compact" | "comfortable">
            size="xs"
            role="group"
            ariaLabel="Row density"
            value={density}
            onChange={setDensity}
            items={[
              { id: "compact", label: "Dense" },
              { id: "comfortable", label: "Roomy" },
            ]}
          />

          <div className="row" style={{ gap: 4 }}>
            <button
              className="btn btn-sm"
              disabled={offset === 0}
              onClick={() => setOffset(Math.max(0, offset - PAGE))}
            >
              <ChevronLeft size={13} /> Previous
            </button>
            <button className="btn btn-sm" disabled={end >= page.total} onClick={() => setOffset(offset + PAGE)}>
              Next <ChevronRight size={13} />
            </button>
          </div>
        </div>
      </div>

      <div className="table-wrap" style={{ maxHeight: 540 }}>
        <table className={`data density-${density}`}>
          <thead>
            <tr>
              {page.columns.map((c) => {
                const isSorted = sort?.column === c.name;
                return (
                  <th
                    key={c.name}
                    className={`sortable ${c.dtype === "integer" || c.dtype === "float" ? "num" : ""}`}
                    onClick={() => toggleSort(c.name)}
                    title={`Sort by ${c.name}`}
                  >
                    <span className="th-inner">
                      <span>{c.internal ? "#" : c.name}</span>
                      {isSorted ? sort.desc ? <ArrowDown size={11} /> : <ArrowUp size={11} /> : null}
                    </span>
                    <span className="col-type mono">
                      {c.internal ? "row#" : `${ROLE_LABEL[c.role] ?? c.role} · ${c.dtype}`}
                      {c.pii ? " · PII" : ""}
                    </span>
                  </th>
                );
              })}
            </tr>
          </thead>
          <tbody>
            {filteredRows.map((row, i) => (
              <tr key={offset + i}>
                {row.map((value, j) => {
                  const column = page.columns[j];
                  const numeric = column.dtype === "integer" || column.dtype === "float";
                  const text = fmtCell(value);
                  return (
                    <td key={j} className={column.internal ? "rownum num" : numeric ? "num" : ""} title={text}>
                      {value === null || value === undefined ? <span className="null-pill">null</span> : text}
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
