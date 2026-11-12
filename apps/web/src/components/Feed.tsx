import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import type { FeedItem } from "../lib/types";
import { Chart } from "./Chart";
import { Badge, Empty } from "./ui";

export function EvidenceBadge({ item }: { item: FeedItem }) {
  const ev = item.evidence;
  if (ev.basis === "descriptive") {
    const tone = item.severity === "critical" ? "bad" : item.severity === "warning" ? "warn" : "info";
    return (
      <Badge tone={tone} title="An exact data check, not a statistical test">
        Fact · {item.severity}
      </Badge>
    );
  }
  const tone = ev.grade === "A" || ev.grade === "B" ? "ok" : ev.grade === "C" ? "warn" : "gray";
  return (
    <Badge tone={tone} title={`${ev.wording}; ${ev.confirmation}`}>
      Grade {ev.grade} · {ev.label}
    </Badge>
  );
}

export function FindingCard({ item, onOpen }: { item: FeedItem; onOpen: () => void }) {
  return (
    <article className="fcard" onClick={onOpen} onKeyDown={(e) => e.key === "Enter" && onOpen()} tabIndex={0} aria-label={item.headline}>
      <div className="top">
        <div className="spread">
          <div className="row-wrap" style={{ gap: 6 }}>
            <Badge tone="brand">{item.family_label}</Badge>
            <EvidenceBadge item={item} />
          </div>
          <span className="rank">#{item.rank}</span>
        </div>
        <div className="headline">{item.headline}</div>
        <div className="vars">{item.variables.join(" · ")}</div>
      </div>
      {item.chart ? (
        <div className="chart-box">
          <Chart chart={item.chart} height={150} compact />
        </div>
      ) : null}
      <div className="foot">
        {item.effect_text ? (
          <span>
            {item.effect_label}: <b>{item.effect_text}</b>
          </span>
        ) : null}
        {item.records_label ? <span>{item.records_label}</span> : null}
        {item.evidence.basis === "inferential" ? <span>{item.evidence.confirmation}</span> : null}
        {item.merged?.length ? <span>+{item.merged.length} similar</span> : null}
        {item.caveats.length ? <span title={item.caveats.join("\n")}>⚠ {item.caveats.length} caveat{item.caveats.length > 1 ? "s" : ""}</span> : null}
      </div>
    </article>
  );
}

const EVIDENCE_ORDER = ["A", "B", "C", "D", "E", "fact"];

export function InsightFeed({ items, basePath }: { items: FeedItem[]; basePath: string }) {
  const navigate = useNavigate();
  const [families, setFamilies] = useState<Set<string>>(new Set());
  const [grades, setGrades] = useState<Set<string>>(new Set());
  const [variable, setVariable] = useState("");
  const [query, setQuery] = useState("");
  const [showMerged, setShowMerged] = useState(false);
  const [showWeak, setShowWeak] = useState(false);
  const [limit, setLimit] = useState(30);

  const gradeOf = (i: FeedItem) => (i.evidence.basis === "descriptive" ? "fact" : i.evidence.grade ?? "E");
  const counts = useMemo(() => {
    const fam = new Map<string, { label: string; n: number }>();
    const gr = new Map<string, number>();
    const vars = new Map<string, number>();
    for (const i of items) {
      if (!showMerged && i.merged_into) continue;
      const f = fam.get(i.family) ?? { label: i.family_label.split(" (")[0], n: 0 };
      f.n += 1;
      fam.set(i.family, f);
      gr.set(gradeOf(i), (gr.get(gradeOf(i)) ?? 0) + 1);
      for (const v of i.variables) vars.set(v, (vars.get(v) ?? 0) + 1);
    }
    return { fam, gr, vars };
  }, [items, showMerged]);

  const filtered = items.filter((i) => {
    if (!showMerged && i.merged_into) return false;
    if (!showWeak && gradeOf(i) === "E" && !grades.has("E")) return false;
    if (families.size && !families.has(i.family)) return false;
    if (grades.size && !grades.has(gradeOf(i))) return false;
    if (variable && !i.variables.includes(variable)) return false;
    if (query && !`${i.headline} ${i.variables.join(" ")} ${i.family_label}`.toLowerCase().includes(query.toLowerCase())) return false;
    return true;
  });
  const hiddenWeak = items.filter((i) => gradeOf(i) === "E" && (showMerged || !i.merged_into)).length;
  const hiddenMerged = items.filter((i) => i.merged_into).length;

  const toggle = (set: Set<string>, value: string, update: (s: Set<string>) => void) => {
    const next = new Set(set);
    if (next.has(value)) next.delete(value);
    else next.add(value);
    update(next);
    setLimit(30);
  };

  return (
    <div className="feed-layout">
      <aside className="card card-pad filters" aria-label="Filters">
        <div className="group">
          <input type="search" placeholder="Search findings" value={query} onChange={(e) => setQuery(e.target.value)} style={{ width: "100%" }} aria-label="Search findings" />
        </div>
        <div className="group">
          <h4>Pattern type</h4>
          {[...counts.fam.entries()].sort((a, b) => b[1].n - a[1].n).map(([key, f]) => (
            <label key={key} className="check">
              <input type="checkbox" checked={families.has(key)} onChange={() => toggle(families, key, setFamilies)} />
              {f.label}
              <span className="n">{f.n}</span>
            </label>
          ))}
        </div>
        <div className="group">
          <h4>Evidence</h4>
          {EVIDENCE_ORDER.filter((g) => counts.gr.has(g)).map((g) => (
            <label key={g} className="check">
              <input type="checkbox" checked={grades.has(g)} onChange={() => toggle(grades, g, setGrades)} />
              {g === "fact" ? "Facts (data checks)" : `Grade ${g}`}
              <span className="n">{counts.gr.get(g)}</span>
            </label>
          ))}
        </div>
        <div className="group">
          <h4>Column</h4>
          <select value={variable} onChange={(e) => setVariable(e.target.value)} style={{ width: "100%" }} aria-label="Filter by column">
            <option value="">Any column</option>
            {[...counts.vars.entries()].sort((a, b) => a[0].localeCompare(b[0])).map(([v, n]) => (
              <option key={v} value={v}>
                {v} ({n})
              </option>
            ))}
          </select>
        </div>
        <div className="group">
          <label className="check">
            <input type="checkbox" checked={showWeak} onChange={(e) => setShowWeak(e.target.checked)} />
            Show results that did not hold up (grade E)
            <span className="n">{hiddenWeak}</span>
          </label>
          <label className="check">
            <input type="checkbox" checked={showMerged} onChange={(e) => setShowMerged(e.target.checked)} />
            Show near-duplicates
            <span className="n">{hiddenMerged}</span>
          </label>
        </div>
        {families.size || grades.size || variable || query ? (
          <button className="link-btn small" onClick={() => { setFamilies(new Set()); setGrades(new Set()); setVariable(""); setQuery(""); }}>
            Clear filters
          </button>
        ) : null}
      </aside>
      <div>
        {filtered.length === 0 ? (
          <div className="card">
            <Empty icon="🔎" title="No findings match these filters">
              Clear a filter to see more. Results that did not hold up are hidden unless you ask for them.
            </Empty>
          </div>
        ) : (
          <>
            <div className="muted small" style={{ marginBottom: 8 }}>
              Showing {Math.min(limit, filtered.length)} of {filtered.length}, ranked by evidence, effect size, coverage, robustness and relevance.
            </div>
            <div className="feed">
              {filtered.slice(0, limit).map((item) => (
                <FindingCard key={item.id} item={item} onOpen={() => navigate(`${basePath}/${item.id}`)} />
              ))}
            </div>
            {filtered.length > limit ? (
              <div className="mt" style={{ textAlign: "center" }}>
                <button className="btn" onClick={() => setLimit(limit + 30)}>
                  Show more ({filtered.length - limit} left)
                </button>
              </div>
            ) : null}
          </>
        )}
      </div>
    </div>
  );
}
