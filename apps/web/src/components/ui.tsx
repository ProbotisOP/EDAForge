import { useEffect, useRef, type ReactNode } from "react";

export function Spinner({ large = false, label }: { large?: boolean; label?: string }) {
  return (
    <span className="row" role="status" aria-live="polite">
      <span className={large ? "spinner lg" : "spinner"} />
      {label ? <span className="muted">{label}</span> : null}
    </span>
  );
}

export function Loading({ label = "Loading…" }: { label?: string }) {
  return (
    <div className="empty">
      <Spinner large label={label} />
    </div>
  );
}

export function ErrorBox({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const message = error instanceof Error ? error.message : String(error);
  return (
    <div className="notice bad" role="alert">
      <span>⚠</span>
      <div className="grow">
        <strong>Something went wrong.</strong> {message}
      </div>
      {onRetry ? (
        <button className="btn btn-sm" onClick={onRetry}>
          Try again
        </button>
      ) : null}
    </div>
  );
}

export function Notice({ tone, children }: { tone: "info" | "warn" | "bad" | "ok"; children: ReactNode }) {
  const icon = { info: "ℹ", warn: "⚠", bad: "⛔", ok: "✓" }[tone];
  return (
    <div className={`notice ${tone}`}>
      <span aria-hidden>{icon}</span>
      <div className="grow">{children}</div>
    </div>
  );
}

export function Empty({ icon, title, children }: { icon?: string; title: string; children?: ReactNode }) {
  return (
    <div className="empty">
      {icon ? <div className="icon" aria-hidden>{icon}</div> : null}
      <h3>{title}</h3>
      <div>{children}</div>
    </div>
  );
}

export type Tone = "gray" | "brand" | "ok" | "warn" | "bad" | "info" | "outline";

const HEALTH_LABEL = { green: "Clean", yellow: "Needs a look", red: "Serious issues" } as const;

/** Traffic light from the parse: missing cells, empty columns, duplicate rows (see ParseHealth). */
export function HealthDot({ health, size = 12 }: { health?: import("../lib/types").ParseHealth | null; size?: number }) {
  const status = health?.status ?? "unknown";
  const title = health ? `${HEALTH_LABEL[health.status]}: ${health.reasons.join("; ")}` : "Not checked yet";
  return <span className={`hdot hdot-${status}`} style={{ width: size, height: size }} title={title} aria-label={title} role="img" />;
}

export function Badge({ tone = "gray", children, title }: { tone?: Tone; children: ReactNode; title?: string }) {
  return (
    <span className={`badge b-${tone}`} title={title}>
      {children}
    </span>
  );
}

export function Modal({
  title,
  children,
  onClose,
  actions,
}: {
  title: string;
  children: ReactNode;
  onClose: () => void;
  actions: ReactNode;
}) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    ref.current?.querySelector<HTMLElement>("input, button")?.focus();
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  return (
    <div className="modal-back" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="modal" role="dialog" aria-modal="true" aria-label={title} ref={ref}>
        <h2>{title}</h2>
        <div>{children}</div>
        <div className="actions">{actions}</div>
      </div>
    </div>
  );
}

export function FileIcon({ format }: { format?: string | null }) {
  const f = (format || "combined").toLowerCase();
  const short: Record<string, string> = { access: "MDB", sqlite: "SQL", duckdb: "DUCK", dbf: "DBF" };
  const label = short[f] ?? (f === "combined" ? "⋈" : f === "clean" ? "✦" : f === "parquet" ? "PQ" : f.toUpperCase().slice(0, 4));
  return <span className={`file-icon ft-${f}`}>{label}</span>;
}

export function Tabs<T extends string>({
  value,
  onChange,
  items,
}: {
  value: T;
  onChange: (v: T) => void;
  items: { id: T; label: ReactNode }[];
}) {
  return (
    <div className="tabs" role="tablist">
      {items.map((item) => (
        <button
          key={item.id}
          role="tab"
          aria-selected={value === item.id}
          className={value === item.id ? "tab active" : "tab"}
          onClick={() => onChange(item.id)}
        >
          {item.label}
        </button>
      ))}
    </div>
  );
}
