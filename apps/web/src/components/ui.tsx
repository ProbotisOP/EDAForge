import { useId, type KeyboardEvent, type ReactNode } from "react";
import * as Dialog from "@radix-ui/react-dialog";
import { motion, useReducedMotion } from "motion/react";
import {
  AlertCircle,
  AlertTriangle,
  CheckCircle2,
  Database,
  FileSpreadsheet,
  FolderOpen,
  GitMerge,
  Info,
  SlidersHorizontal,
} from "lucide-react";
import { playDetent } from "../lib/sound";

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
      <AlertCircle size={16} className="notice-icon" aria-hidden />
      <div className="grow">{message}</div>
      {onRetry ? (
        <button className="btn btn-sm" onClick={onRetry}>
          Try again
        </button>
      ) : null}
    </div>
  );
}

export function Notice({ tone, children }: { tone: "info" | "warn" | "bad" | "ok"; children: ReactNode }) {
  const Icon = { info: Info, warn: AlertTriangle, bad: AlertCircle, ok: CheckCircle2 }[tone];
  return (
    <div className={`notice ${tone}`}>
      <Icon size={16} className="notice-icon" aria-hidden />
      <div className="grow">{children}</div>
    </div>
  );
}

export function Empty({
  icon,
  title,
  children,
}: {
  icon?: ReactNode;
  title: string;
  children?: ReactNode;
}) {
  return (
    <div className="empty">
      <div className="empty-glyph" aria-hidden>
        {typeof icon === "string" || !icon ? <FolderOpen size={20} /> : icon}
      </div>
      <h2>{title}</h2>
      <div className="empty-sub">{children}</div>
    </div>
  );
}

export type Tone = "gray" | "brand" | "ok" | "warn" | "bad" | "info" | "outline";

const HEALTH_LABEL = { green: "Clean", yellow: "Needs a look", red: "Serious issues" } as const;

export function HealthDot({ health, size = 9 }: { health?: import("../lib/types").ParseHealth | null; size?: number }) {
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
  return (
    <Dialog.Root open onOpenChange={(next) => !next && onClose()}>
      <Dialog.Portal>
        <Dialog.Overlay className="modal-back" />
        <Dialog.Content className="modal modal-fixed" aria-describedby={undefined}>
          <Dialog.Title asChild>
            <h2>{title}</h2>
          </Dialog.Title>
          <div>{children}</div>
          <div className="actions">{actions}</div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

export function FileIcon({ format }: { format?: string | null }) {
  const f = (format || "combined").toLowerCase();
  if (f === "combined") {
    return (
      <span className="file-icon" aria-hidden>
        <GitMerge size={14} />
      </span>
    );
  }
  if (f === "clean") {
    return (
      <span className="file-icon" aria-hidden>
        <SlidersHorizontal size={14} />
      </span>
    );
  }
  if (["access", "sqlite", "duckdb", "dbf"].includes(f)) {
    return (
      <span className="file-icon" aria-hidden>
        <Database size={14} />
      </span>
    );
  }
  const short: Record<string, string> = { parquet: "PQ" };
  const label = short[f] ?? (f ? f.toUpperCase().slice(0, 4) : "");
  return (
    <span className="file-icon" aria-hidden>
      {label || <FileSpreadsheet size={14} />}
    </span>
  );
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
  const tabId = useId();
  const reduce = useReducedMotion();

  const onKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    if (e.key !== "ArrowRight" && e.key !== "ArrowLeft") return;
    const idx = items.findIndex((it) => it.id === value);
    if (idx < 0) return;
    const nextIdx = (idx + (e.key === "ArrowRight" ? 1 : -1) + items.length) % items.length;
    const next = items[nextIdx];
    if (next) {
      e.preventDefault();
      playDetent();
      onChange(next.id);
      const buttons = e.currentTarget.querySelectorAll<HTMLButtonElement>('button[role="tab"]');
      buttons[nextIdx]?.focus();
    }
  };

  return (
    <div className="tabs" role="tablist" onKeyDown={onKeyDown}>
      {items.map((item) => {
        const active = value === item.id;
        return (
          <button
            key={item.id}
            type="button"
            role="tab"
            aria-selected={active}
            className={active ? "tab active" : "tab"}
            onClick={() => {
              if (!active) playDetent();
              onChange(item.id);
            }}
          >
            {active ? (
              <motion.span
                layoutId={`tab-pill-${tabId}`}
                className="tab-active-pill"
                transition={
                  reduce
                    ? { duration: 0 }
                    : { type: "spring", stiffness: 420, damping: 32, mass: 0.65 }
                }
              />
            ) : null}
            <span className="tab-label-inner">{item.label}</span>
          </button>
        );
      })}
    </div>
  );
}
