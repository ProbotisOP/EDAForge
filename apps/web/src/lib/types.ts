// API types. They mirror the Python models in packages/edaforge/src/edaforge/server/store.py,
// edaforge/ingest/infer.py, edaforge/profile and edaforge/discovery.

export type Role = "numeric" | "categorical" | "boolean" | "datetime" | "identifier" | "text" | "empty";
export const ROLES: Role[] = ["numeric", "categorical", "boolean", "datetime", "identifier", "text"];

export interface ParseIssue {
  level: "error" | "warning" | "info";
  code: string;
  message: string;
  column?: string | null;
  count?: number | null;
  examples: string[];
  rows: number[];
}

export interface ColumnInfo {
  name: string;
  original_name: string;
  dtype: "integer" | "float" | "boolean" | "date" | "datetime" | "string";
  role: Role;
  role_reason: string;
  role_source: "inferred" | "user";
  pii?: string | null;
  n_missing: number;
  n_invalid: number;
  parse_note?: string | null;
}

export interface Upload {
  id: string;
  filename: string;
  format?: string | null;
  size_bytes: number;
  sha256: string;
  uploaded_at: string;
  status: "parsed" | "failed";
  error?: string | null;
  issues: ParseIssue[];
  dataset_ids: string[];
}

export interface ParseHealth {
  status: "green" | "yellow" | "red";
  missing_share: number;
  empty_columns: string[];
  duplicate_rows: number;
  reasons: string[];
}

export interface CleanStep {
  kind: "drop_duplicates" | "unify_labels" | "fill_missing" | "drop_missing" | "scale" | "drop_column";
  column?: string | null;
  mapping?: Record<string, string>;
  value?: number | string | boolean | null;
  value_source?: string | null;
  flag?: boolean;
  factor?: number | null;
  where_column?: string | null;
  where_value?: string | null;
  note?: string;
}

export interface CleanPreview {
  source: string;
  n_before: number;
  n_after: number;
  effects: { step: CleanStep; summary: string; rows_before: number; rows_after: number; cells_changed: number; rows_removed: number[] }[];
  columns: string[];
  sample: unknown[][];
}

export interface Dataset {
  health?: ParseHealth | null;
  recipe: CleanStep[];
  id: string;
  name: string;
  kind: "file" | "combined" | "cleaned";
  upload_id?: string | null;
  sheet?: string | null;
  n_rows: number;
  n_cols: number;
  columns: ColumnInfo[];
  issues: ParseIssue[];
  fingerprint: string;
  created_at: string;
  link_id?: string | null;
  sources: string[];
}

export interface LinkMeta {
  id: string;
  status: "confirmed" | "rejected";
  kind: "join" | "append" | "time_aligned";
  spec: LinkSpec;
  result_dataset_id?: string | null;
  report: Record<string, unknown>;
  created_at: string;
}

export interface RunMeta {
  id: string;
  dataset_id: string;
  status: "queued" | "running" | "completed" | "failed" | "cancelled";
  settings: RunSettings;
  created_at: string;
  finished_at?: string | null;
  summary: Record<string, unknown> & { n_findings?: number };
  error?: string | null;
}

export interface Project {
  id: string;
  name: string;
  created_at: string;
  updated_at: string;
  uploads: Upload[];
  datasets: Dataset[];
  links: LinkMeta[];
  runs: RunMeta[];
}

export interface ProjectSummary {
  id: string;
  name: string;
  created_at: string;
  updated_at: string;
  n_uploads: number;
  n_datasets: number;
  n_failed_uploads: number;
  latest_run: { id: string; status: string; created_at: string; n_findings?: number | null } | null;
}

export interface RowsPage {
  columns: { name: string; dtype: string; role: string; pii?: string | null; internal: boolean }[];
  rows: unknown[][];
  total: number;
  offset: number;
  limit: number;
}

// ---------------------------------------------------------------- profile (milestone 2)

export interface HistogramBin { x0: number | string; x1: number | string; count: number }
export interface TopValue { value: string; count: number }

export interface ColumnProfile {
  name: string;
  dtype: string;
  role: Role;
  pii?: string | null;
  n: number;
  n_missing: number;
  missing_share: number;
  n_distinct: number;
  distinct_share: number;
  min?: number | string | null;
  max?: number | string | null;
  mean?: number | null;
  median?: number | null;
  std?: number | null;
  q1?: number | null;
  q3?: number | null;
  n_zero?: number | null;
  n_negative?: number | null;
  n_outliers?: number | null;
  histogram: HistogramBin[];
  top_values: TopValue[];
  flags: string[];
}

export interface QualityIssue {
  id: string;
  severity: "critical" | "warning" | "info";
  category: string;
  title: string;
  detail: string;
  column?: string | null;
  columns: string[];
  count?: number | null;
  share?: number | null;
  method: string;
  examples: string[];
  rows: number[];
}

export interface HealthScore {
  score: number;
  label: string;
  method: string;
  components: { category: string; penalty: number; cap: number; issues: number; explanation: string }[];
}

export interface DatasetProfile {
  dataset_id: string;
  n_rows: number;
  n_cols: number;
  n_duplicate_rows: number;
  columns: ColumnProfile[];
  issues: QualityIssue[];
  health: HealthScore;
  roles: Record<string, number>;
}

// ---------------------------------------------------------------- links (milestone 3)

export interface KeyPair { left: string; right: string }

export interface Rescale {
  column: string;
  side: "left" | "right";
  factor: number;
}

export interface LinkSpec {
  kind: "join" | "append" | "time_aligned";
  left: string;
  right: string;
  keys: KeyPair[];
  how: "left" | "inner";
  right_mode: "lookup" | "aggregate" | "expand";
  time_grain?: "day" | "week" | "month" | null;
  name?: string | null;
  rescale?: Rescale[];
}

export interface UnitMismatch {
  column: string;
  median_left: number;
  median_right: number;
  ratio: number;
  hint: string;
  options: Rescale[];
  applied: Rescale | null;
}

export interface LinkSuggestion {
  id: string;
  kind: "join" | "append" | "time_aligned" | "unrelated";
  left: string;
  right: string;
  keys: KeyPair[];
  confidence: number;
  cardinality?: "1:1" | "m:1" | "1:m" | "m:m" | null;
  reasons: string[];
  warnings: string[];
  evidence: Record<string, number | string | null>;
  spec?: LinkSpec | null;
  status?: "confirmed" | "rejected" | null;
  link_id?: string | null;
}

export interface LinkPreview {
  spec: LinkSpec;
  kind: string;
  n_left: number;
  n_right: number;
  n_result: number;
  matched_left: number;
  matched_right: number;
  unmatched_left: number;
  unmatched_right: number;
  cardinality: string;
  max_right_per_key: number;
  duplicate_keys_left: number;
  duplicate_keys_right: number;
  row_multiplication: number;
  warnings: { severity: "critical" | "warning" | "info"; message: string }[];
  overlap_columns: { column: string; compared: number; agree: number; agree_share: number | null; examples: string[][] }[];
  unit_mismatches: UnitMismatch[];
  columns: string[];
  sample: unknown[][];
  requires_ack: boolean;
  ack_reasons: string[];
}

// ---------------------------------------------------------------- discovery (milestones 4-5)

export type Intent = "auto" | "target" | "compare" | "anomalies" | "health";

export interface ScopePlan {
  tables: string[];
  steps: {
    spec: LinkSpec;
    left_name: string;
    right_name: string;
    kind: string;
    confidence: number;
    reasons: string[];
    n_left: number;
    n_right: number;
    n_result: number;
    row_multiplication: number;
    warnings: { severity: string; message: string }[];
    requires_ack: boolean;
    ack_reasons: string[];
    result_name: string;
  }[];
  unconnected: { table: string; reason: string }[];
  relations: { left: string; right: string; kind: string; confidence: number; keys: string[] }[];
  result_rows: number;
  result_name: string;
  requires_ack: boolean;
  columns: { name: string; role: string; pii?: unknown }[];
}

export interface RunSettings {
  dataset_id: string;
  scope?: string[];
  acknowledged?: boolean;
  target?: string | null;
  focus: string[];
  exclude: string[];
  time_column?: string | null;
  group_column?: string | null;
  min_group_size?: number;
  intent: Intent;
}

export interface PlanItem {
  analyzer: string;
  label: string;
  family: string;
  status: "run" | "skipped";
  reason: string;
  n_tests?: number | null;
  method: string;
}

export interface RunEvent {
  seq: number;
  kind: string;
  stage?: string | null;
  message: string;
  data: Record<string, unknown>;
}

export interface Effect {
  measure: string;
  estimate: number;
  ci_low?: number | null;
  ci_high?: number | null;
  ci_level: number;
  units?: string | null;
  sesoi?: number | null;
  ci_method?: string | null;
  split?: string | null;
}

export interface AssumptionCheck {
  name: string;
  description: string;
  status: "pass" | "warn" | "fail" | "not_checked" | "untestable";
  severity: string;
  statistic?: number | null;
  p_value?: number | null;
  detail: string;
  action: string;
  fallback_to?: string | null;
}

export interface ChartSpec { kind: string; title: string; alt_text: string; spec: Record<string, unknown> }

export interface FeedItem {
  id: string;
  rank: number;
  kind: string;
  family: string;
  family_label: string;
  headline: string;
  summary: string;
  variables: string[];
  datasets: string[];
  effect_label?: string | null;
  effect_text?: string | null;
  direction?: string | null;
  records?: number | null;
  records_label?: string | null;
  evidence: {
    basis: "inferential" | "descriptive";
    grade?: string | null;
    label: string;
    wording: string;
    confirmation: string;
    q_value?: number | null;
    exploratory: boolean;
  };
  severity?: "critical" | "warning" | "info" | null;
  caveats: string[];
  score: number;
  score_components: Record<string, number>;
  score_weights?: Record<string, number>;
  chart?: ChartSpec | null;
  merged?: string[];
  merged_into?: string | null;
}

export interface FindingDetail extends FeedItem {
  lenses: Record<"plain" | "analyst" | "scientist", { markdown: string; html: string }>;
  charts: ChartSpec[];
  method: {
    analyzer: string;
    analyzer_version: string;
    test?: string | null;
    statistic?: number | null;
    p_value?: number | null;
    q_value?: number | null;
    n: number;
    effect?: Effect | null;
    secondary_effects: Effect[];
    assumptions: AssumptionCheck[];
    confirmation: Record<string, unknown>;
    grade_reasons: string[];
    rung: string;
    rung_reasons: string[];
    params: Record<string, unknown>;
    hypothesis_ids: string[];
    ledger: Record<string, unknown>[];
    facts: Record<string, unknown>;
    stability?: number | null;
    specs_consistent?: number | null;
    specs_total?: number | null;
    rule?: string;
  };
  provenance: Record<string, unknown>;
  related: { id: string; type: string; headline: string }[];
}

export interface RunResultView {
  run: RunMeta;
  dataset: { id: string; name: string; n_rows: number; n_cols: number };
  plan: PlanItem[];
  feed: FeedItem[];
  searched: { analyzer: string; label: string; tested: number; promoted: number; confirmed: number }[];
  split: Record<string, unknown>;
  warnings: string[];
  manifest: Record<string, unknown>;
  null_results: { analyzer: string; label: string; message: string }[];
  notes: string[];
  spec?: Record<string, unknown>;
}

// ---------------------------------------------------------------- data universe

export interface UniverseNode {
  id: string;
  role: string;
  is_target: boolean;
  degree: number;
  alerts: { finding: string; headline: string; severity: string | null }[];
  findings: string[];
  story: string;
  derived: { finding: string; inputs: string[]; formula_text: string } | null;
  stats: UniverseStats | null;
}

export interface UniverseStats {
  n: number;
  missing: number;
  distinct: number;
  kind?: "numeric" | "labels";
  min?: number;
  q1?: number;
  median?: number;
  q3?: number;
  max?: number;
  mean?: number;
  std?: number;
  hist?: number[];
  edges?: number[];
  top?: { label: string; count: number }[];
}

export interface UniverseEdge {
  id: string;
  finding: string;
  source: string;
  target: string;
  via: string | null;
  kind: string;
  family: string;
  family_label: string;
  headline: string;
  effect_text: string | null;
  grade: string | null;
  confirmed: boolean;
  exploratory: boolean;
  strength: number;
  score: number;
  rank: number | null;
  sign: -1 | 0 | 1;
  estimate: number | null;
  effect_label: string | null;
}

export interface Universe {
  target: string | null;
  nodes: UniverseNode[];
  edges: UniverseEdge[];
  rows: number | null;
  dataset: string | null;
}
