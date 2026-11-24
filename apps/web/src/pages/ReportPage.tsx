import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { Download, FileSpreadsheet, FileText } from "lucide-react";
import { chartToSvg } from "../components/Chart";
import { EvidenceBadge } from "../components/Feed";
import { Empty, ErrorBox, Loading, Notice } from "../components/ui";
import { api } from "../lib/api";
import { fmtDate, fmtInt } from "../lib/format";
import type { RunResultView } from "../lib/types";
import { useProject } from "./ProjectLayout";

function download(name: string, text: string, type: string) {
  const url = URL.createObjectURL(new Blob([text], { type }));
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 2000);
}

export function ReportPage() {
  const { project } = useProject();
  const { runId } = useParams();
  const navigate = useNavigate();
  const completed = [...project.runs].filter((r) => r.status === "completed").sort((a, b) => b.created_at.localeCompare(a.created_at));
  const chosen = runId ?? completed[0]?.id;
  const [view, setView] = useState<RunResultView | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [building, setBuilding] = useState<string | null>(null);

  useEffect(() => {
    if (!chosen) return;
    setView(null);
    setError(null);
    api.run(project.id, chosen).then(setView).catch(setError);
  }, [project.id, chosen]);

  if (!completed.length) {
    return (
      <>
        <Header />
        <div className="content">
          <div className="card">
            <Empty title="No completed analysis yet">
              Run discovery on the <Link to={`/p/${project.id}/discover`}>Discover</Link> page; its findings, data checks, and methods
              can then be exported here.
            </Empty>
          </div>
        </div>
      </>
    );
  }
  if (error) return <div className="content" style={{ paddingTop: 24 }}><ErrorBox error={error} /></div>;
  if (!view) return <Loading label="Loading results…" />;

  const leaders = view.feed.filter((i) => !i.merged_into && (i.evidence.basis === "descriptive" || i.evidence.grade !== "E"));
  const findings = leaders.filter((i) => i.evidence.basis === "inferential");
  const facts = leaders.filter((i) => i.evidence.basis === "descriptive");

  const buildHtml = async () => {
    setError(null);
    try {
      const charts: Record<string, string> = {};
      const withCharts = leaders.slice(0, 30).filter((i) => i.chart);
      let k = 0;
      for (const item of withCharts) {
        k += 1;
        setBuilding(`Drawing chart ${k} of ${withCharts.length}…`);
        try {
          charts[item.id] = await chartToSvg(item.chart!);
        } catch {
          /* a chart that cannot be drawn is left out; the report says so */
        }
      }
      setBuilding("Assembling the report…");
      const html = await api.reportHtml(project.id, view.run.id, charts);
      download(`edaforge-${view.run.id}-report.html`, html, "text/html");
    } catch (e) {
      setError(e);
    } finally {
      setBuilding(null);
    }
  };

  return (
    <>
      <Header
        action={
          completed.length > 1 ? (
            <select value={chosen} onChange={(e) => navigate(`/p/${project.id}/report/${e.target.value}`)} aria-label="Choose run">
              {completed.map((r) => (
                <option key={r.id} value={r.id}>
                  {String(r.summary.dataset ?? r.dataset_id)} · {fmtDate(r.created_at)}
                </option>
              ))}
            </select>
          ) : undefined
        }
      />
      <div className="content stack">
        <div className="report-hero-bento">
          <div className="bento-tile bento-petrol" style={{ padding: "22px 24px" }}>
            <div className="spread" style={{ alignItems: "flex-start", flexWrap: "wrap", gap: 16 }}>
              <div>
                <h2 style={{ fontSize: 20 }}>{String(view.dataset.name)}</h2>
                <div className="small bento-sub-on-dark tabular-nums" style={{ marginTop: 4 }}>
                  Run <span className="mono">{view.run.id}</span> · {fmtDate(view.run.created_at)} · {findings.length} findings ·{" "}
                  {facts.length} data facts · {fmtInt(view.searched.reduce((s, x) => s + x.tested, 0))} hypotheses tested
                </div>
              </div>
              <div className="stack" style={{ alignItems: "flex-end", gap: 6 }}>
                <button className="btn btn-report-cta btn-hero" onClick={buildHtml} disabled={building !== null}>
                  <Download size={15} />
                  <span>{building ?? "Download HTML report"}</span>
                </button>
                <span className="tiny bento-sub-on-dark">
                  Self-contained inert HTML (0 scripts) with vector SVG charts, caveats, and statistical ledger.
                </span>
              </div>
            </div>

            <div className="row-wrap mt" style={{ gap: 8 }}>
              <a className="bento-dark-pill" href={api.exportUrl(project.id, view.run.id, "csv")} download>
                <FileSpreadsheet size={13} /> Findings (CSV)
              </a>
              <a className="bento-dark-pill" href={api.exportUrl(project.id, view.run.id, "json")} download>
                <FileText size={13} /> Methods &amp; provenance (JSON)
              </a>
              <a className="bento-dark-pill" href={api.exportUrl(project.id, view.run.id, "quality.csv")} download>
                <FileSpreadsheet size={13} /> Data-quality issues (CSV)
              </a>
            </div>
            {error ? <div className="mt"><ErrorBox error={error} /></div> : null}
          </div>
        </div>

        <div className="grid-2" style={{ alignItems: "start" }}>
          <div className="card">
            <div className="card-head">
              <h2>Key findings in the report</h2>
              <span className="small muted tabular-nums">Top {Math.min(12, leaders.length)}</span>
            </div>
            <table className="plain">
              <tbody>
                {leaders.slice(0, 12).map((i) => (
                  <tr key={i.id} className="clickable" onClick={() => navigate(`/p/${project.id}/discover/runs/${view.run.id}/${i.id}`)}>
                    <td className="faint tabular-nums">#{i.rank}</td>
                    <td>
                      <div style={{ fontWeight: 600 }}>{i.headline}</div>
                      <div className="muted small">
                        {i.family_label}
                        {i.effect_text ? ` · ${i.effect_text}` : ""}
                      </div>
                    </td>
                    <td>
                      <EvidenceBadge item={i} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {leaders.length > 12 ? (
              <div className="card-pad small muted">
                …and {leaders.length - 12} more (the HTML report includes the top 30).
              </div>
            ) : null}
          </div>

          <div className="stack">
            <div className="bento-tile bento-sage" style={{ padding: "18px 20px" }}>
              <h2 style={{ fontSize: 15.5, marginBottom: 8 }}>Methods used in this run</h2>
              <ul className="small" style={{ paddingLeft: 18, margin: 0, display: "grid", gap: 5 }}>
                {view.plan.filter((p) => p.status === "run").map((p) => (
                  <li key={p.analyzer}>
                    <b>{p.label}</b>: {p.method}
                  </li>
                ))}
              </ul>
            </div>

            <Notice tone="info">
              Exports keep each finding’s evidence grade, confirmation status, caveats, method, and provenance. Personal-data
              columns were excluded from the analysis and are masked in examples. Spreadsheet formulas in CSV cells are
              neutralized.
            </Notice>
          </div>
        </div>
      </div>
    </>
  );
}

function Header({ action }: { action?: React.ReactNode }) {
  return (
    <div className="topbar">
      <div>
        <h1>Report</h1>
        <div className="sub">Summary of the analysis, with exports that preserve evidence grades, caveats, and methods.</div>
      </div>
      {action}
    </div>
  );
}
