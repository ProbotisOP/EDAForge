// Typed client for the local EDAForge API. Every state-changing request carries the
// x-edaforge-client header that the server requires (cross-site pages cannot send it).
import type {
  Dataset,
  DatasetProfile,
  FindingDetail,
  LinkPreview,
  LinkSpec,
  LinkSuggestion,
  Project,
  ProjectSummary,
  Role,
  RowsPage,
  RunEvent,
  RunResultView,
  RunSettings,
  Upload,
} from "./types";

const CLIENT = { "x-edaforge-client": "1" };

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

function detailOf(body: unknown, fallback: string): string {
  if (body && typeof body === "object" && "detail" in body) {
    const detail = (body as { detail: unknown }).detail;
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail)) {
      return detail
        .map((d) => (d && typeof d === "object" && "msg" in d ? String((d as { msg: unknown }).msg) : String(d)))
        .join("; ");
    }
  }
  return fallback;
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const init: RequestInit = { method, headers: { ...CLIENT } };
  if (body !== undefined) {
    init.body = JSON.stringify(body);
    (init.headers as Record<string, string>)["content-type"] = "application/json";
  }
  let response: Response;
  try {
    response = await fetch(path, init);
  } catch {
    throw new ApiError(0, "Cannot reach the EDAForge server. Is it still running?");
  }
  if (response.status === 204) return undefined as T;
  const text = await response.text();
  let parsed: unknown = undefined;
  try {
    parsed = text ? JSON.parse(text) : undefined;
  } catch {
    parsed = undefined;
  }
  if (!response.ok) throw new ApiError(response.status, detailOf(parsed, `${response.status} ${response.statusText}`));
  return parsed as T;
}

const get = <T,>(path: string) => request<T>("GET", path);
const post = <T,>(path: string, body?: unknown) => request<T>("POST", path, body ?? {});
const patch = <T,>(path: string, body: unknown) => request<T>("PATCH", path, body);
const del = <T,>(path: string) => request<T>("DELETE", path);

const p = (projectId: string) => `/api/projects/${encodeURIComponent(projectId)}`;

export const api = {
  listProjects: () => get<ProjectSummary[]>("/api/projects"),
  createProject: (name: string) => post<Project>("/api/projects", { name }),
  getProject: (id: string) => get<Project>(p(id)),
  renameProject: (id: string, name: string) => patch<Project>(p(id), { name }),
  deleteProject: (id: string) => del<void>(p(id)),
  deleteUpload: (id: string, uploadId: string) => del<Project>(`${p(id)}/uploads/${uploadId}`),
  rows: (id: string, datasetId: string, offset: number, limit: number, sort?: string | null, desc?: boolean) => {
    const q = new URLSearchParams({ offset: String(offset), limit: String(limit) });
    if (sort) {
      q.set("sort", sort);
      q.set("desc", desc ? "true" : "false");
    }
    return get<RowsPage>(`${p(id)}/datasets/${datasetId}/rows?${q}`);
  },
  setRole: (id: string, datasetId: string, column: string, role: Role | null) =>
    patch<Dataset>(`${p(id)}/datasets/${datasetId}/columns`, { column, role }),
  profile: (id: string, datasetId: string) => get<DatasetProfile>(`${p(id)}/datasets/${datasetId}/profile`),
  suggestions: (id: string) => get<LinkSuggestion[]>(`${p(id)}/links/suggestions`),
  previewLink: (id: string, spec: LinkSpec) => post<LinkPreview>(`${p(id)}/links/preview`, spec),
  confirmLink: (id: string, spec: LinkSpec, acknowledged: boolean) =>
    post<{ project: Project; dataset: Dataset }>(`${p(id)}/links`, { spec, acknowledged }),
  rejectLink: (id: string, spec: LinkSpec) => post<Project>(`${p(id)}/links/reject`, spec),
  deleteLink: (id: string, linkId: string) => del<Project>(`${p(id)}/links/${linkId}`),
  startRun: (id: string, settings: RunSettings) => post<{ run_id: string; project: Project }>(`${p(id)}/runs`, settings),
  planRun: (id: string, settings: RunSettings) => post<{ plan: import("./types").PlanItem[]; notes: string[] }>(`${p(id)}/runs/plan`, settings),
  run: (id: string, runId: string) => get<RunResultView>(`${p(id)}/runs/${runId}`),
  cancelRun: (id: string, runId: string) => post<void>(`${p(id)}/runs/${runId}/cancel`),
  scopePlan: (id: string, datasetIds: string[]) => post<import("./types").ScopePlan>(`${p(id)}/scope/plan`, { dataset_ids: datasetIds }),
  cleanSuggestions: (id: string, datasetId: string) => get<import("./types").CleanStep[]>(`${p(id)}/datasets/${datasetId}/clean/suggestions`),
  cleanPreview: (id: string, datasetId: string, steps: import("./types").CleanStep[]) =>
    post<import("./types").CleanPreview>(`${p(id)}/datasets/${datasetId}/clean/preview`, { steps }),
  cleanCreate: (id: string, datasetId: string, steps: import("./types").CleanStep[]) =>
    post<{ project: Project; dataset: Dataset }>(`${p(id)}/datasets/${datasetId}/clean`, { steps }),
  deleteDataset: (id: string, datasetId: string) => del<Project>(`${p(id)}/datasets/${datasetId}`),
  universe: (id: string, runId: string) => get<import("./types").Universe>(`${p(id)}/runs/${runId}/universe`),
  finding: (id: string, runId: string, findingId: string) =>
    get<FindingDetail>(`${p(id)}/runs/${runId}/findings/${findingId}`),
  eventsUrl: (id: string, runId: string) => `${p(id)}/runs/${runId}/events`,
  exportUrl: (id: string, runId: string, format: "json" | "csv" | "quality.csv") =>
    `${p(id)}/runs/${runId}/export/${format}`,
  reportHtml: (id: string, runId: string, charts: Record<string, string>) =>
    requestText("POST", `${p(id)}/runs/${runId}/report`, { charts }),
};

async function requestText(method: string, path: string, body: unknown): Promise<string> {
  const response = await fetch(path, {
    method,
    headers: { ...CLIENT, "content-type": "application/json" },
    body: JSON.stringify(body),
  });
  const text = await response.text();
  if (!response.ok) {
    let parsed: unknown;
    try {
      parsed = JSON.parse(text);
    } catch {
      parsed = undefined;
    }
    throw new ApiError(response.status, detailOf(parsed, `${response.status} ${response.statusText}`));
  }
  return text;
}

/** Upload one file with real byte-level progress (XMLHttpRequest exposes upload progress). */
export function uploadFile(
  projectId: string,
  file: File,
  onProgress: (sent: number, total: number) => void,
): Promise<{ uploads: Upload[]; project: Project }> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", `${p(projectId)}/uploads`);
    xhr.setRequestHeader("x-edaforge-client", "1");
    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable) onProgress(e.loaded, e.total);
    };
    xhr.onerror = () => reject(new ApiError(0, "The upload was interrupted. Is the server running?"));
    xhr.onload = () => {
      let body: unknown;
      try {
        body = JSON.parse(xhr.responseText);
      } catch {
        body = undefined;
      }
      if (xhr.status >= 200 && xhr.status < 300) resolve(body as { uploads: Upload[]; project: Project });
      else reject(new ApiError(xhr.status, detailOf(body, `Upload failed (${xhr.status})`)));
    };
    const form = new FormData();
    form.append("files", file, file.name);
    xhr.send(form);
  });
}

/** Subscribe to a run's server-sent events. Returns a function that closes the stream. */
export function subscribeRun(
  projectId: string,
  runId: string,
  onEvent: (event: RunEvent) => void,
  onEnd: () => void,
): () => void {
  const source = new EventSource(api.eventsUrl(projectId, runId));
  source.onmessage = (message) => {
    try {
      const event = JSON.parse(message.data) as RunEvent;
      onEvent(event);
      if (event.kind === "run_finished" || event.kind === "run_failed" || event.kind === "run_cancelled") {
        source.close();
        onEnd();
      }
    } catch {
      /* ignore malformed frames */
    }
  };
  source.onerror = () => {
    source.close();
    onEnd();
  };
  return () => source.close();
}
