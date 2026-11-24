import { useCallback, useRef, useState } from "react";
import { Upload as UploadIcon } from "lucide-react";
import { uploadFile } from "../lib/api";
import { fmtBytes, fmtInt } from "../lib/format";
import { playConfirm, playTick } from "../lib/sound";
import type { Project, Upload } from "../lib/types";
import { Badge, HealthDot, Spinner } from "./ui";

const ACCEPT =
  ".csv,.tsv,.tab,.xlsx,.parquet,.pq,.json,.jsonl,.ndjson,.sqlite,.sqlite3,.db,.duckdb,.mdb,.accdb,.dbf";

export interface UploadItem {
  key: string;
  name: string;
  size: number;
  sent: number;
  phase: "uploading" | "parsing" | "done" | "failed";
  upload?: Upload;
  datasets?: import("../lib/types").Dataset[];
  error?: string;
}

export interface Uploader {
  items: UploadItem[];
  start: (files: FileList | File[]) => void;
}

export function useUploader(projectId: string, onUploaded: (project: Project, uploads: Upload[]) => void): Uploader {
  const [items, setItems] = useState<UploadItem[]>([]);
  const update = (key: string, patch: Partial<UploadItem>) =>
    setItems((list) => list.map((it) => (it.key === key ? { ...it, ...patch } : it)));
  const start = useCallback(
    (files: FileList | File[]) => {
      playTick();
      const batch = Array.from(files).map((file, i) => ({
        file,
        item: {
          key: `${Date.now()}-${i}-${file.name}`,
          name: file.name,
          size: file.size,
          sent: 0,
          phase: "uploading" as const,
        },
      }));
      setItems((list) => [...batch.map((b) => b.item), ...list].slice(0, 30));
      for (const { file, item } of batch) {
        uploadFile(projectId, file, (sent, total) => {
          update(item.key, { sent, size: total, phase: sent >= total ? "parsing" : "uploading" });
        })
          .then(({ uploads, project }) => {
            const upload = uploads[0];
            if (upload?.status === "parsed") playConfirm();
            update(item.key, {
              phase: upload?.status === "parsed" ? "done" : "failed",
              upload,
              datasets: project.datasets.filter((d) => upload?.dataset_ids.includes(d.id)),
              error: upload?.error ?? undefined,
            });
            onUploaded(project, uploads);
          })
          .catch((e: Error) => update(item.key, { phase: "failed", error: e.message }));
      }
    },
    [projectId, onUploaded],
  );
  return { items, start };
}

export function UploadZone({ uploader, compact = false }: { uploader: Uploader; compact?: boolean }) {
  const [drag, setDrag] = useState(false);
  const input = useRef<HTMLInputElement>(null);
  const { items, start } = uploader;

  return (
    <div className="stack">
      <div
        className={`dropzone${drag ? " drag" : ""}${compact ? " compact" : ""}`}
        onDragOver={(e) => {
          e.preventDefault();
          setDrag(true);
        }}
        onDragLeave={() => setDrag(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDrag(false);
          if (e.dataTransfer.files.length) start(e.dataTransfer.files);
        }}
        onClick={() => input.current?.click()}
        role="button"
        tabIndex={0}
        onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && input.current?.click()}
        aria-label="Upload files"
      >
        <div className="row" style={{ justifyContent: "center", gap: 7 }}>
          <UploadIcon size={15} style={{ color: "var(--brand)", flexShrink: 0 }} aria-hidden />
          <span style={{ fontSize: compact ? 13 : 14 }}>
            <strong>{compact ? "Add files" : "Choose files"}</strong> or drop them here
          </span>
        </div>

        <div className="muted small" style={{ marginTop: 3 }}>
          {compact
            ? "CSV, Excel, Parquet, JSON, SQLite, DuckDB"
            : "CSV, TSV, Excel, Parquet, JSON, Access (.mdb/.accdb), SQLite, DuckDB, dBase"}
        </div>

        <input
          ref={input}
          type="file"
          multiple
          accept={ACCEPT}
          hidden
          data-testid="file-input"
          onChange={(e) => {
            if (e.target.files?.length) start(e.target.files);
            e.target.value = "";
          }}
        />
      </div>

      {items.filter((it) => !compact || it.phase !== "done").length > 0 ? (
        <div className="card" aria-live="polite">
          {items
            .filter((it) => !compact || it.phase !== "done")
            .map((it) => (
            <div key={it.key} className="upload-item">
              <div className="grow">
                <div className="row">
                  <strong style={{ wordBreak: "break-all" }}>{it.name}</strong>
                  <span className="muted small tabular-nums">{fmtBytes(it.size)}</span>
                </div>
                {it.phase === "uploading" ? (
                  <div className="progress" style={{ marginTop: 6 }}>
                    <div style={{ width: `${it.size ? Math.round((100 * it.sent) / it.size) : 0}%` }} />
                  </div>
                ) : null}
                {it.phase === "failed" ? (
                  <div className="small" style={{ color: "var(--bad)" }}>
                    {it.error}
                  </div>
                ) : null}
                {it.phase === "done" && it.datasets?.length ? (
                  <div className="row-wrap" style={{ gap: 5, marginTop: 4 }}>
                    {it.datasets.map((d) => (
                      <HealthDot key={d.id} health={d.health} />
                    ))}
                  </div>
                ) : null}
                {it.phase === "done" && it.upload ? (
                  <div className="small muted">
                    {it.upload.dataset_ids.length > 1
                      ? `${it.upload.dataset_ids.length} ${["access", "sqlite", "duckdb"].includes(it.upload.format ?? "") ? "tables" : "sheets"} read`
                      : "Read"}
                    {it.upload.issues.length ? ` · ${it.upload.issues.map((i) => i.message).join(" ")}` : ""}
                  </div>
                ) : null}
              </div>
              <div>
                {it.phase === "uploading" ? (
                  <span className="muted small tabular-nums">{Math.round((100 * it.sent) / Math.max(it.size, 1))}%</span>
                ) : it.phase === "parsing" ? (
                  <Spinner label="Reading…" />
                ) : it.phase === "done" ? (
                  <Badge tone="ok">Read</Badge>
                ) : (
                  <Badge tone="bad">Failed</Badge>
                )}
              </div>
            </div>
          ))}
        </div>
      ) : null}

      {items.some((i) => i.phase === "done") ? (
        <div className="muted small tabular-nums">
          {fmtInt(items.filter((i) => i.phase === "done").length)} of {fmtInt(items.length)} files read.
        </div>
      ) : null}
    </div>
  );
}
