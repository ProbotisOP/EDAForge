import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../lib/api";
import { fmtCell, fmtInt } from "../lib/format";
import type { CleanPreview, CleanStep, Dataset } from "../lib/types";
import { useProject } from "../pages/ProjectLayout";
import { ErrorBox, Notice, Spinner } from "./ui";

const KIND_LABEL: Record<CleanStep["kind"], string> = {
  drop_duplicates: "Remove duplicate rows",
  unify_labels: "Unify label spellings",
  fill_missing: "Fill empty cells",
  drop_missing: "Remove rows with an empty value",
  scale: "Rescale (unit change)",
  drop_column: "Remove column",
};

function describe(s: CleanStep): string {
  if (s.kind === "unify_labels") return `${s.column}: ${Object.entries(s.mapping ?? {}).map(([a, b]) => `'${a}' → '${b}'`).join(", ")}`;
  if (s.kind === "fill_missing") return `${s.column} with ${String(s.value)}${s.value_source ? ` (${s.value_source})` : ""}${s.flag ? ", flagged" : ""}`;
  if (s.kind === "scale") return `${s.column} × ${s.factor}${s.where_column ? ` where ${s.where_column} = ${s.where_value}` : ""}`;
  return s.column ?? "";
}

/** Choose fixes, preview exactly what they change, create a cleaned table, export data and code. */
export function CleanPanel({ dataset }: { dataset: Dataset }) {
  const { project, setProject } = useProject();
  const navigate = useNavigate();
  const [suggested, setSuggested] = useState<CleanStep[] | null>(null);
  const [chosen, setChosen] = useState<Set<number>>(new Set());
  const [extra, setExtra] = useState<CleanStep[]>([]);
  const [preview, setPreview] = useState<CleanPreview | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [manual, setManual] = useState<{ kind: CleanStep["kind"]; column: string; value: string }>({ kind: "drop_column", column: "", value: "" });
  const isCleaned = dataset.kind === "cleaned";
  const source = isCleaned ? project.datasets.find((d) => d.id === dataset.sources[0]) : undefined;

  useEffect(() => {
    setSuggested(null);
    setChosen(new Set());
    setExtra([]);
    setPreview(null);
    api.cleanSuggestions(project.id, dataset.id).then(setSuggested).catch(setError);
  }, [project.id, dataset.id]);

  const steps = useMemo(() => [...(suggested ?? []).filter((_, i) => chosen.has(i)), ...extra], [suggested, chosen, extra]);
  const key = JSON.stringify(steps);
  useEffect(() => {
    setPreview(null);
    if (!steps.length) {
      setBusy(false);
      return;
    }
    let cancelled = false;
    setBusy(true);
    setError(null);
    const t = setTimeout(() => {
      api
        .cleanPreview(project.id, dataset.id, steps)
        .then((p) => !cancelled && setPreview(p))
        .catch((e) => !cancelled && setError(e))
        .finally(() => !cancelled && setBusy(false));
    }, 250);
    return () => {
      cancelled = true;
      clearTimeout(t);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [project.id, dataset.id, key]);

  const create = async () => {
    setBusy(true);
    try {
      const { project: updated, dataset: made } = await api.cleanCreate(project.id, dataset.id, steps);
      setProject(updated);
      navigate(`/p/${project.id}/data/${made.id}`);
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  };
  const addManual = () => {
    if (!manual.column) return;
    const step: CleanStep = { kind: manual.kind, column: manual.column };
    if (manual.kind === "fill_missing") {
      const n = Number(manual.value);
      Object.assign(step, { value: manual.value !== "" && !Number.isNaN(n) ? n : manual.value, value_source: "typed", flag: true });
    }
    setExtra([...extra, step]);
  };
  const exportUrl = (fmt: string) => `/api/projects/${encodeURIComponent(project.id)}/datasets/${dataset.id}/export/${fmt}`;

  return (
    <div className="stack">
      {isCleaned ? (
        <div className="scope-panel">
          <div className="spread">
            <h3>Recipe of this cleaned table</h3>
            <span className="muted small">from {source?.name ?? "its source"} · the original is unchanged</span>
          </div>
          <ol className="scope-steps">
            {dataset.recipe.map((s, i) => (
              <li key={i}>
                <strong>{KIND_LABEL[s.kind]}</strong> <span className="muted small">{describe(s)}</span>
              </li>
            ))}
          </ol>
          <div className="row-wrap">
            <a className="btn btn-sm" href={exportUrl("recipe.py")} download>
              Recipe as Python (polars)
            </a>
            <a className="btn btn-sm" href={exportUrl("recipe.sql")} download>
              Recipe as SQL
            </a>
            <button className="btn btn-sm" onClick={() => navigate(`/p/${project.id}/discover?dataset=${dataset.id}`)}>
              Find patterns in the cleaned table →
            </button>
            <button
              className="btn btn-sm btn-danger"
              onClick={async () => {
                try {
                  setProject(await api.deleteDataset(project.id, dataset.id));
                  navigate(`/p/${project.id}/data/${dataset.sources[0]}`);
                } catch (e) {
                  setError(e);
                }
              }}
            >
              Remove this cleaned table
            </button>
          </div>
          <div className="tiny muted">The exported code replays these steps on the original file and gives the same table (checked by automated tests).</div>
        </div>
      ) : null}

      <div className="card card-pad stack">
        <div className="spread">
          <h3>{isCleaned ? "Add more fixes" : "Fix problems"}</h3>
          <span className="muted small">Nothing changes until you create the cleaned table</span>
        </div>
        {suggested === null ? <Spinner label="Looking for fixable problems…" /> : null}
        {suggested?.length === 0 ? <Notice tone="ok">No duplicates, label variants, empty columns or empty cells to fix.</Notice> : null}
        {suggested?.map((s, i) => (
          <label key={i} className="clean-row">
            <input type="checkbox" checked={chosen.has(i)} onChange={() => setChosen((c) => { const n = new Set(c); if (n.has(i)) n.delete(i); else n.add(i); return n; })} aria-label={`${KIND_LABEL[s.kind]} ${s.column ?? ""}`} />
            <span className="grow">
              <strong>{KIND_LABEL[s.kind]}</strong> <span className="muted">{describe(s)}</span>
              <div className="small muted">{s.note}</div>
            </span>
          </label>
        ))}
        {extra.map((s, i) => (
          <div key={`x${i}`} className="clean-row">
            <span className="grow">
              <strong>{KIND_LABEL[s.kind]}</strong> <span className="muted">{describe(s)}</span> <span className="tiny muted">(added by you)</span>
            </span>
            <button className="btn btn-sm btn-ghost" onClick={() => setExtra(extra.filter((_, j) => j !== i))} aria-label="remove step">
              ✕
            </button>
          </div>
        ))}
        <div className="row-wrap">
          <select value={manual.kind} onChange={(e) => setManual({ ...manual, kind: e.target.value as CleanStep["kind"] })} aria-label="Step type">
            <option value="drop_column">Remove column</option>
            <option value="drop_missing">Remove rows where empty</option>
            <option value="fill_missing">Fill empty cells with…</option>
          </select>
          <select value={manual.column} onChange={(e) => setManual({ ...manual, column: e.target.value })} aria-label="Step column">
            <option value="">— column —</option>
            {dataset.columns.map((c) => (
              <option key={c.name}>{c.name}</option>
            ))}
          </select>
          {manual.kind === "fill_missing" ? (
            <input type="text" placeholder="value" value={manual.value} onChange={(e) => setManual({ ...manual, value: e.target.value })} aria-label="Fill value" style={{ width: 120 }} />
          ) : null}
          <button className="btn btn-sm" onClick={addManual} disabled={!manual.column || (manual.kind === "fill_missing" && manual.value === "")}>
            + Add step
          </button>
        </div>
        {error ? <ErrorBox error={error} /> : null}
        {busy && !preview ? <Spinner label="Previewing…" /> : null}
        {preview ? (
          <div className="stack">
            <div className="grid-3">
              <div className="stat"><div className="v">{fmtInt(preview.n_before)}</div><div className="l">rows now</div></div>
              <div className="stat"><div className="v">{fmtInt(preview.n_after)}</div><div className="l">rows after</div></div>
              <div className="stat"><div className="v">{preview.effects.reduce((a, e) => a + e.cells_changed, 0).toLocaleString()}</div><div className="l">cells changed</div></div>
            </div>
            <ul className="small" style={{ margin: 0, paddingLeft: 18 }}>
              {preview.effects.map((e, i) => (
                <li key={i}>
                  {e.summary}
                  {e.rows_removed.length ? <span className="muted"> Rows {e.rows_removed.slice(0, 8).join(", ")}{e.rows_removed.length > 8 ? ", …" : ""}.</span> : null}
                </li>
              ))}
            </ul>
            <div className="table-wrap" style={{ maxHeight: 240 }}>
              <table className="data">
                <thead><tr>{preview.columns.map((c) => <th key={c}>{c}</th>)}</tr></thead>
                <tbody>
                  {preview.sample.map((r, i) => (
                    <tr key={i}>{r.map((v, j) => <td key={j}>{v === null ? <span className="null">missing</span> : fmtCell(v)}</td>)}</tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="row">
              <button className="btn btn-primary" disabled={busy} onClick={create}>
                Create cleaned table
              </button>
              <span className="muted small">A new table; {isCleaned ? "the recipe is extended from the original file" : "this file stays as it is"}.</span>
            </div>
          </div>
        ) : null}
      </div>

      <div className="card card-pad">
        <h3 style={{ marginBottom: 8 }}>Export this table</h3>
        <div className="row-wrap">
          <a className="btn btn-sm" href={exportUrl("csv")} download>CSV</a>
          <a className="btn btn-sm" href={exportUrl("parquet")} download>Parquet</a>
        </div>
        <div className="tiny muted mt">Text cells that start like a spreadsheet formula get a leading ' in the CSV so they cannot run.</div>
      </div>
    </div>
  );
}
