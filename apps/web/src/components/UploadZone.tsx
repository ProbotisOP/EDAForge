import { useCallback, useRef, useState } from "react";
import { uploadFile } from "../lib/api";
import { fmtBytes, fmtInt } from "../lib/format";
import type { Project, Upload } from "../lib/types";
import { Badge, HealthDot, Spinner } from "./ui";

const ACCEPT = ".csv,.tsv,.tab,.xlsx,.parquet,.pq,.json,.jsonl,.ndjson,.sqlite,.sqlite3,.db,.duckdb,.mdb,.accdb,.dbf";

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

/**
 * Upload queue state. It lives in the page, not in the drop zone, so that the list of uploads
 * survives the page switching layout when the first file finishes.
 */
export function useUploader(projectId: string, onUploaded: (project: Project, uploads: Upload[]) => void): Uploader {
  const [items, setItems] = useState<UploadItem[]>([]);
  const update = (key: string, patch: Partial<UploadItem>) =>
    setItems((list) => list.map((it) => (it.key === key ? { ...it, ...patch } : it)));
  const start = useCallback(
    (files: FileList | File[]) => {
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

/** Multi-file upload with real byte progress, then the server's parse result per file. */
export function UploadZone({ uploader, compact = false }: { uploader: Uploader; compact?: boolean }) {
  const [drag, setDrag] = useState(false);
  const input = useRef<HTMLInputElement>(null);
  const { items, start } = uploader;

  return (
    <div className="stack">
      <div
        className={drag ? "dropzone drag" : "dropzone"}
        style={compact ? { padding: 14 } : undefined}
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
        <div style={{ fontSize: compact ? 13 : 15 }}>
          <strong>Choose files</strong> or drop them here
        </div>
        <div className="muted small">
          CSV, TSV, Excel, Parquet, JSON · databases: Access (.mdb/.accdb), SQLite, DuckDB, dBase · several at once · files stay on this computer
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
      {items.length > 0 ? (
        <div className="card" aria-live="polite">
          {items.map((it) => (
            <div key={it.key} className="upload-item">
              <div className="grow">
                <div className="row">
                  <strong style={{ wordBreak: "break-all" }}>{it.name}</strong>
                  <span className="muted small">{fmtBytes(it.size)}</span>
                </div>
                {it.phase === "uploading" ? (
                  <div className="progress" style={{ marginTop: 6 }}>
                    <div style={{ width: `${it.size ? Math.round((100 * it.sent) / it.size) : 0}%` }} />
                  </div>
                ) : null}
                {it.phase === "failed" ? <div className="small" style={{ color: "var(--bad)" }}>{it.error}</div> : null}
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
                      : "Read successfully"}
                    {it.upload.issues.length ? ` · ${it.upload.issues.map((i) => i.message).join(" ")}` : ""}
                  </div>
                ) : null}
              </div>
              <div>
                {it.phase === "uploading" ? (
                  <span className="muted small">{Math.round((100 * it.sent) / Math.max(it.size, 1))}%</span>
                ) : it.phase === "parsing" ? (
                  <Spinner label="Reading file…" />
                ) : it.phase === "done" ? (
                  <Badge tone="ok">Parsed</Badge>
                ) : (
                  <Badge tone="bad">Failed</Badge>
                )}
              </div>
            </div>
          ))}
        </div>
      ) : null}
      {items.some((i) => i.phase === "done") ? (
        <div className="muted small">
          {fmtInt(items.filter((i) => i.phase === "done").length)} of {fmtInt(items.length)} files read.
        </div>
      ) : null}
    </div>
  );
}
