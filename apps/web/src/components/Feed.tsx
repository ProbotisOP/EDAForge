import { useMemo, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { AlertTriangle, LayoutGrid, List, Search, X } from "lucide-react";
import { playTick } from "../lib/sound";
import type { FeedItem } from "../lib/types";
import { Chart } from "./Chart";
import { SpringSegmented } from "./kit";
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
    <article
      className="fcard bento-hit"
      onClick={() => {
        playTick();
        onOpen();
      }}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          playTick();
          onOpen();
        }
      }}
      tabIndex={0}
      aria-label={item.headline}
    >
      <div className="bento-inner fcard-inner">
        <div className="top">
          <div className="spread">
            <div className="row-wrap" style={{ gap: 6 }}>
              <EvidenceBadge item={item} />
              <span className="muted small">{item.family_label}</span>
            </div>
            <span className="rank">#{item.rank}</span>
          </div>
          <div className="headline">{item.headline}</div>
          <div className="vars">{item.variables.map((v) => (v === "__source__" ? "source file" : v)).join(" · ")}</div>
        </div>

        {item.chart ? (
          <div className="chart-box" onClick={(e) => e.stopPropagation()}>
            <div
              onClick={() => {
                playTick();
                onOpen();
              }}
              style={{ cursor: "pointer" }}
            >
              <Chart chart={item.chart} height={176} compact />
            </div>
          </div>
        ) : item.summary ? (
          <p className="fcard-summary">{item.summary}</p>
        ) : null}

        <div className="foot">
          {item.effect_text ? (
            <span>
              {item.effect_label}: <b className="tabular-nums">{item.effect_text}</b>
            </span>
          ) : null}
          {item.records_label ? <span className="tabular-nums">{item.records_label}</span> : null}
          {item.evidence.basis === "inferential" ? <span>{item.evidence.confirmation}</span> : null}
          {item.merged?.length ? <span>+{item.merged.length} similar</span> : null}
          {item.caveats.length ? (
            <span className="row" style={{ gap: 4 }} title={item.caveats.join("\n")}>
              <AlertTriangle size={12} style={{ color: "var(--warn)" }} />
              {item.caveats.length} caveat{item.caveats.length > 1 ? "s" : ""}
            </span>
          ) : null}
        </div>
      </div>
    </article>
  );
}

const EVIDENCE_ORDER = ["A", "B", "C", "D", "E", "fact"];

export function InsightFeed({ items, basePath }: { items: FeedItem[]; basePath: string }) {
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();

  const families = useMemo(
    () => new Set((searchParams.get("fam") ?? "").split(",").filter(Boolean)),
    [searchParams],
  );
  const grades = useMemo(
    () => new Set((searchParams.get("gr") ?? "").split(",").filter(Boolean)),
    [searchParams],
  );
  const variable = searchParams.get("col") ?? "";
  const query = searchParams.get("q") ?? "";
  const viewMode: "grid" | "table" = searchParams.get("view") === "table" ? "table" : "grid";

  const [showMerged, setShowMerged] = useState(false);
  const [showWeak, setShowWeak] = useState(false);
  const [limit, setLimit] = useState(30);

  const patchParams = (patch: Record<string, string | null>) => {
    const next = new URLSearchParams(searchParams);
    for (const [k, v] of Object.entries(patch)) {
      if (!v) next.delete(k);
      else next.set(k, v);
    }
    setSearchParams(next, { replace: true });
    setLimit(30);
  };

  const gradeOf = (i: FeedItem) => (i.evidence.basis === "descriptive" ? "fact" : (i.evidence.grade ?? "E"));
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
    if (query && !`${i.headline} ${i.variables.join(" ")} ${i.family_label}`.toLowerCase().includes(query.toLowerCase()))
      return false;
    return true;
  });
  const hiddenWeak = items.filter((i) => gradeOf(i) === "E" && (showMerged || !i.merged_into)).length;
  const hiddenMerged = items.filter((i) => i.merged_into).length;

  const toggleSetParam = (paramKey: string, current: Set<string>, value: string) => {
    playTick();
    const next = new Set(current);
    if (next.has(value)) next.delete(value);
    else next.add(value);
    patchParams({ [paramKey]: next.size ? [...next].join(",") : null });
  };

  return (
    <div className="feed-layout">
      <aside className="filters bento-tile bento-surface-card" style={{ padding: "16px 16px" }} aria-label="Filters">
        <h2 className="sr-only">Filter findings</h2>
        <div className="group">
          <div className="search-field">
            <Search size={14} className="search-icon" />
            <input
              type="search"
              placeholder="Search findings…"
              value={query}
              onChange={(e) => patchParams({ q: e.target.value || null })}
              style={{ width: "100%", paddingLeft: 30 }}
              aria-label="Search findings"
            />
          </div>
        </div>
        <div className="group">
          <h3 className="filter-heading">Pattern type</h3>
          {[...counts.fam.entries()]
            .sort((a, b) => b[1].n - a[1].n)
            .map(([key, f]) => (
              <label key={key} className="check">
                <input type="checkbox" checked={families.has(key)} onChange={() => toggleSetParam("fam", families, key)} />
                <span>{f.label}</span>
                <span className="n">{f.n}</span>
              </label>
            ))}
        </div>
        <div className="group">
          <h3 className="filter-heading">Evidence grade</h3>
          {EVIDENCE_ORDER.filter((g) => counts.gr.has(g)).map((g) => (
            <label key={g} className="check">
              <input type="checkbox" checked={grades.has(g)} onChange={() => toggleSetParam("gr", grades, g)} />
              <span>{g === "fact" ? "Facts (data checks)" : `Grade ${g}`}</span>
              <span className="n">{counts.gr.get(g)}</span>
            </label>
          ))}
        </div>
        <div className="group">
          <h3 className="filter-heading">Column</h3>
          <select
            value={variable}
            onChange={(e) => patchParams({ col: e.target.value || null })}
            style={{ width: "100%" }}
            aria-label="Filter by column"
          >
            <option value="">Any column</option>
            {[...counts.vars.entries()]
              .sort((a, b) => a[0].localeCompare(b[0]))
              .map(([v, n]) => (
                <option key={v} value={v}>
                  {v === "__source__" ? "source file" : v} ({n})
                </option>
              ))}
          </select>
        </div>
        <div className="group">
          <label className="check">
            <input type="checkbox" checked={showWeak} onChange={(e) => setShowWeak(e.target.checked)} />
            <span>Unconfirmed / Grade E</span>
            <span className="n">{hiddenWeak}</span>
          </label>
          <label className="check">
            <input type="checkbox" checked={showMerged} onChange={(e) => setShowMerged(e.target.checked)} />
            <span>Near-duplicates</span>
            <span className="n">{hiddenMerged}</span>
          </label>
        </div>
        {families.size || grades.size || variable || query ? (
          <button
            className="btn btn-sm"
            style={{ width: "100%", marginTop: 10 }}
            onClick={() => patchParams({ fam: null, gr: null, col: null, q: null })}
          >
            <X size={13} /> Clear filters
          </button>
        ) : null}
      </aside>

      <div>
        {filtered.length === 0 ? (
          <div className="card">
            <Empty icon={<Search size={20} />} title="No findings match these filters">
              Clear a filter to see more. Results that did not hold up are hidden unless toggled on.
            </Empty>
          </div>
        ) : (
          <>
            <div className="spread" style={{ marginBottom: 12 }}>
              <div className="muted small tabular-nums">
                Showing {Math.min(limit, filtered.length)} of {filtered.length}, ranked by evidence, effect size,
                coverage, and robustness.
              </div>
              <SpringSegmented<"grid" | "table">
                size="xs"
                role="group"
                ariaLabel="Feed layout"
                value={viewMode}
                onChange={(v) => patchParams({ view: v === "table" ? "table" : null })}
                items={[
                  { id: "grid", label: <LayoutGrid size={13} />, title: "Cards grid" },
                  { id: "table", label: <List size={13} />, title: "Table view" },
                ]}
              />
            </div>

            {viewMode === "grid" ? (
              <div className="feed">
                {filtered.slice(0, limit).map((item) => (
                  <FindingCard key={item.id} item={item} onOpen={() => navigate(`${basePath}/${item.id}`)} />
                ))}
              </div>
            ) : (
              <div className="table-wrap">
                <table className="plain">
                  <thead>
                    <tr>
                      <th>#</th>
                      <th>Headline</th>
                      <th>Variables</th>
                      <th>Type</th>
                      <th>Effect</th>
                      <th>Evidence</th>
                    </tr>
                  </thead>
                  <tbody>
                    {filtered.slice(0, limit).map((item) => (
                      <tr key={item.id} className="clickable fcard" onClick={() => navigate(`${basePath}/${item.id}`)}>
                        <td className="rank">#{item.rank}</td>
                        <td style={{ fontWeight: 600 }}>{item.headline}</td>
                        <td className="small muted">{item.variables.map((v) => (v === "__source__" ? "source file" : v)).join(", ")}</td>
                        <td className="small muted">{item.family_label}</td>
                        <td className="mono small">{item.effect_text ?? "—"}</td>
                        <td>
                          <EvidenceBadge item={item} />
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}

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
