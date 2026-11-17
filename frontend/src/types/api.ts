// Typen spiegeln die Pydantic-Modelle aus app/schemas.py.

export type DocumentStatus = "uploaded" | "processing" | "extracted" | "failed";
export type DocType = "invoice" | "contract" | "offer" | "reminder" | "other";
export type AIActRiskLevel = "unacceptable" | "high" | "limited" | "minimal" | "not_applicable";
export type RiskLevel = "none" | "low" | "medium" | "high";
export type DetectionSource = "llm" | "rule_based" | "both" | "xml" | "xml_rule";
export type CheckStatus = "pass" | "warn" | "fail" | "not_applicable";
export type ScoreBand = "green" | "amber" | "red";
export type InferenceMode = "local" | "gemini" | "anthropic" | "openai";
export type PiiStrictness = "strict" | "standard" | "audit_only";
export type SignOffDecision = "SEALED_APPROVED" | "SEALED_REJECTED";

export interface AISystemFinding {
  name: string;
  purpose: string;
  risk_level: AIActRiskLevel;
  annex_iii_categories: string[];
  annex_iii_labels: string[];
  evidence: string;
  confidence: number;
}

export interface AIActAssessment {
  describes_ai_system: boolean;
  overall_risk_level: AIActRiskLevel;
  systems: AISystemFinding[];
  reasoning: string;
  obligations: string[];
  is_high_risk: boolean;
}

export interface PIIFinding {
  category: string;
  category_label: string;
  masked_value: string;
  context: string;
  confidence: number;
  source: DetectionSource;
  is_special_category: boolean;
}

export interface GDPRAssessment {
  contains_personal_data: boolean;
  findings: PIIFinding[];
  risk_level: RiskLevel;
  reasoning: string;
  recommendations: string[];
  contains_special_categories: boolean;
}

export interface ComplianceAudit {
  ai_act: AIActAssessment;
  gdpr: GDPRAssessment;
  model: string;
  audited_at: string;
  duration_ms: number;
  provider: InferenceMode | string;
  privacy_gateway: Record<string, number> | null;
  /** Provider-Wechsel waehrend der Analyse (Ausweich-Kaskade). */
  failover?: FailoverSwitch[] | null;
  /** Alle KI-Stufen ausgefallen: das Regelwerk hat die Pruefung abgeschlossen. */
  heuristic?: boolean;
  fallback_reason?: string | null;
  headline: string;
}

export interface FailoverSwitch {
  from_provider: string;
  from_model: string;
  to_provider: string;
  to_model: string;
  reason_code: string;
  reason: string;
  at: string;
  from_stage?: string;
  to_stage?: string;
}

export type Money = number | string | null;

export interface ExtractionResult {
  doc_type: DocType;
  sender: string | null;
  recipient: string | null;
  document_number: string | null;
  document_date: string | null;
  due_date: string | null;
  total_amount: Money;
  currency: string | null;
  iban: string | null;
  iban_valid: boolean | null;
  sender_address: string | null;
  recipient_address: string | null;
  sender_tax_number: string | null;
  sender_vat_id: string | null;
  service_date: string | null;
  service_period: string | null;
  items_description: string | null;
  net_amount: Money;
  tax_rate: Money;
  tax_amount: Money;
  tax_exemption_note: string | null;
  summary: string;
  issues: string[];
}

export interface ScoreCheck {
  id: string;
  label: string;
  legal_reference: string | null;
  status: CheckStatus;
  deduction: number;
  detail: string | null;
  evidence_source: DetectionSource | null;
  risk_note: string | null;
  note: string | null;
}

export interface ScoreTile {
  key: "formal" | "regulatory" | "privacy" | "math";
  title: string;
  status: CheckStatus;
  headline: string;
  deduction: number;
  checks: ScoreCheck[];
}

export interface HumanOverride {
  auditor_name: string;
  previous_risk_level: AIActRiskLevel;
  new_risk_level: AIActRiskLevel;
  previous_score: number | null;
  new_score: number;
  reason: string;
  legal_basis: string;
  overridden_at: string;
  ledger_entry_id: string;
  ledger_entry_hash: string;
}

export interface RetentionInfo {
  years: number;
  until: string;
  financial_sector_until: string;
  basis: string;
  note: string;
}

export interface OverrideRequest {
  auditor_name: string;
  risk_level: AIActRiskLevel;
  reason: string;
  legal_basis: string;
}

export interface LedgerEntry {
  seq: number;
  entry_id: string;
  event_type: "analysis" | "sign_off" | "human_override" | string;
  document_id: string;
  sha256_hash: string;
  model_name: string;
  prompt_hash: string;
  timestamp_utc: string;
  result_summary: string;
  compliance_score: number | null;
  risk_tier: string;
  details: Record<string, unknown> & { signature?: { algorithm: string; fingerprint: string } };
  previous_hash: string;
  entry_hash: string;
  signature_status: "valid" | "invalid" | "unsigned";
}

export interface Scorecard {
  score: number;
  band: ScoreBand;
  band_label: string;
  cap_applied: string | null;
  tiles: ScoreTile[];
  release_recommendation: string;
  release_blocked: boolean;
  ustg_required_total: number;
  ustg_fulfilled: number;
  small_amount_invoice: boolean;
  structured_einvoice_detected: boolean;
  computed_at: string;
  ruleset_version: string;
  human_override: HumanOverride | null;
  retention: RetentionInfo | null;
}

export interface SignOff {
  status: SignOffDecision;
  auditor_name: string;
  note: string;
  sealed_at: string;
  ledger_entry_id: string;
  ledger_entry_hash: string;
  compliance_score: number | null;
}

export interface TextSpan {
  start: number;
  end: number;
  category: string;
  label: string;
  masked: boolean;
  source: DetectionSource;
}

export interface TextView {
  level: PiiStrictness;
  text: string;
  spans: TextSpan[];
  truncated: boolean;
}

export interface EInvoiceParty {
  name: string | null;
  vat_id: string | null;
  tax_number: string | null;
  street: string | null;
  postcode: string | null;
  city: string | null;
  country: string | null;
  electronic_address: string | null;
  electronic_address_scheme: string | null;
  address: string | null;
}

export interface EInvoiceVat {
  category: string | null;
  rate: Money;
  taxable_amount: Money;
  tax_amount: Money;
  exemption_reason: string | null;
}

export interface EInvoiceLine {
  line_id: string | null;
  name: string | null;
  quantity: Money;
  unit: string | null;
  net_amount: Money;
  vat_rate: Money;
}

export interface VisualCheck {
  bt: string;
  label: string;
  xml_value: string;
  status: "match" | "mismatch" | "not_found";
  visual_value: string | null;
}

export interface BusinessTermField {
  bt: string;
  label: string;
  value: string | null;
}

export interface EInvoiceData {
  source: "embedded" | "standalone";
  attachment_name: string | null;
  error: string | null;
  syntax: "CII" | "UBL" | null;
  specification_id: string | null;
  profile: string;
  profile_key: string;
  is_einvoice: boolean;
  invoice_number: string | null;
  issue_date: string | null;
  currency: string | null;
  buyer_reference: string | null;
  iban: string | null;
  seller: EInvoiceParty;
  buyer: EInvoiceParty;
  net_total: Money;
  tax_total: Money;
  grand_total: Money;
  due_payable: Money;
  vat_breakdown: EInvoiceVat[];
  lines: EInvoiceLine[];
  rule_violations: string[];
  leitweg: { value: string; valid: boolean; reason: string | null } | null;
  public_buyer: boolean;
  public_buyer_reason: string | null;
  visual_check: VisualCheck[];
  xml_sha256: string | null;
  xml_size: number | null;
  business_terms: BusinessTermField[];
}

export interface DocumentSummary {
  id: string;
  filename: string;
  status: DocumentStatus;
  size_bytes: number;
  page_count: number | null;
  doc_type: DocType | null;
  sender: string | null;
  document_number: string | null;
  document_date: string | null;
  total_amount: Money;
  currency: string | null;
  ai_act_risk_level: AIActRiskLevel | null;
  gdpr_risk_level: RiskLevel | null;
  contains_special_categories: boolean | null;
  compliance_score: number | null;
  score_band: ScoreBand | null;
  pii_findings: number | null;
  sealed: boolean;
  pinned: boolean;
  archived: boolean;
  provider: string | null;
  einvoice_profile: string | null;
  created_at: string;
  updated_at: string;
}

export interface DocumentListResponse {
  items: DocumentSummary[];
  total: number;
  limit: number;
  offset: number;
}

export interface DocumentDetail {
  id: string;
  filename: string;
  content_type: string;
  status: DocumentStatus;
  size_bytes: number;
  sha256: string;
  page_count: number | null;
  char_count: number | null;
  model: string | null;
  extraction: ExtractionResult | null;
  compliance: ComplianceAudit | null;
  text_preview: string | null;
  scorecard: Scorecard | null;
  sign_off: SignOff | null;
  text_view: TextView | null;
  einvoice: EInvoiceData | null;
  pinned: boolean;
  archived: boolean;
  archived_at: string | null;
  provider: string | null;
  error: string | null;
  created_at: string;
  updated_at: string;
  extracted_at: string | null;
}

export interface ExtractionResponse {
  id: string;
  status: DocumentStatus;
  model: string;
  extraction: ExtractionResult;
  compliance: ComplianceAudit;
  duration_ms: number;
  scorecard: Scorecard | null;
  provider: string | null;
  audit_entry_id: string | null;
}

export interface BatchUploadItem {
  filename: string;
  ok: boolean;
  id?: string;
  duplicate_of?: string | null;
  einvoice_profile?: string | null;
  error?: { code: string; message: string };
}

export interface BatchUploadResponse {
  items: BatchUploadItem[];
  succeeded: number;
  failed: number;
}

export interface SeedResponse {
  items: {
    id: string;
    filename: string;
    status: DocumentStatus;
    created: boolean;
    reference_audit: boolean;
    structured_audit: boolean;
    compliance_score: number | null;
  }[];
  created: number;
}

export interface ProgressStage {
  key: string;
  label: string;
  state: "pending" | "active" | "done";
}

export interface ProgressResponse {
  document_id: string;
  status: DocumentStatus;
  current_stage: string | null;
  stages: ProgressStage[];
}

export interface KpiResponse {
  documents_total: number;
  documents_analyzed: number;
  average_score: number | null;
  average_band: ScoreBand | null;
  pii_elements_masked: number;
  high_risk_count: number;
  high_risk_quota: number;
  sealed_count: number;
  reference_count: number;
  heuristic_count?: number;
  ruleset_version: string;
}

export interface RuntimeSettings {
  inference_mode: InferenceMode;
  active_provider_label: string;
  active_model: string;
  is_cloud: boolean;
  privacy_gateway_active: boolean;
  models: Record<InferenceMode, string>;
  suggested_models: Record<InferenceMode, string[]>;
  pii_strictness: PiiStrictness;
  enforce_ustg_check: boolean;
  ai_act_escalation: boolean;
  has_gemini_key: boolean;
  has_anthropic_key: boolean;
  has_openai_key: boolean;
  masked_keys: Record<string, string | null>;
  /** Anbieter-Fallbacks in Reihenfolge (ohne den primaeren), "local" = Ollama. */
  fallbacks: InferenceMode[];
  /** Ausweichmodell des aktiven Anbieters ("" = aus). */
  ausweich_modell: string;
  ausweich_modelle: Record<CloudMode, string>;
  ausweich_schluessel: BackupKey[];
  max_ausweich_schluessel: number;
  suggested_fallback_models: Record<string, string>;
  /** Effektive Kaskade in Reihenfolge (ohne Schluessel). */
  chain: ChainStage[];
  heuristic_fallback: boolean;
  retry_delays: number[];
  cloud_budget: CloudBudget | null;
  dlp: { ruleset_version: string; configured_terms: number; endpoint: string };
}

export type CloudMode = Exclude<InferenceMode, "local">;

export interface BackupKey {
  id: string;
  provider: CloudMode;
  model: string;
  has_key: boolean;
  key_hint: string | null;
}

export interface ChainStage {
  stage: "primary" | "ausweichmodell" | "ausweich_schluessel" | "fallback";
  provider: InferenceMode;
  model: string;
  backup_id?: string;
}

export interface CloudBudget {
  date: string;
  tokens: number;
  calls: number;
  limit: number;
  enabled: boolean;
  remaining: number | null;
  /** Obergrenze aus der Serverkonfiguration; null = frei wählbar. */
  max: number | null;
}

export type JobStatus = "queued" | "running" | "done" | "failed" | "cancelled";

export interface JobSnapshot {
  job_id: string;
  kind: string;
  document_id: string;
  title: string;
  status: JobStatus;
  phase: string | null;
  phase_label: string | null;
  phase_index: number;
  phases: { key: string; label: string }[];
  message: string;
  progress: number;
  eta_seconds: number | null;
  queue_position: number;
  created_at: number;
  started_at: number | null;
  finished_at: number | null;
  stalled: boolean;
  cancel_requested: boolean;
  events: { kind: "retry" | "switch"; at: number; [key: string]: unknown }[];
  result: {
    document_id: string;
    score: number | null;
    band: ScoreBand | null;
    release_recommendation: string | null;
    release_blocked: boolean | null;
    provider: string;
    model: string;
    heuristic: boolean;
    failover: FailoverSwitch[];
    duration_ms: number;
  } | null;
  error: { code: string; message: string; hint?: string | null } | null;
}

export interface JobListResponse {
  jobs: JobSnapshot[];
  open: number;
}

export interface LocalAiStatus {
  services: { key: string; name: string; port: number; running: boolean; installed: boolean; startable: boolean; stoppable: boolean }[];
  running: boolean;
  startable: boolean;
  stoppable: boolean;
  controllable: boolean;
  control_allowed: boolean;
  text: string;
}

export interface LocalAiResult {
  ok: boolean;
  message: string;
  already_running?: boolean;
}

export interface CopilotProgress {
  current: string | null;
  steps: string[];
  done: boolean;
  cancelled?: boolean;
  started_at: number | null;
}

export type ThinkingLevel = "low" | "medium" | "high";

export interface RedactResult {
  redacted_text: string;
  counts: Record<string, number>;
  total: number;
  ruleset_version: string;
}

export interface ModelCatalog {
  provider: InferenceMode;
  current: string;
  /** Neueste zuerst. */
  models: string[];
  /** Neueres Modell derselben Klasse - nur Vorschlag, nie automatisch. */
  upgrade: string | null;
  source: "api" | "suggested";
  message?: string;
}

export interface ReleaseInfo {
  tag: string;
  version: string;
  commit: string;
  signature: "valid" | "invalid" | "unsigned";
  message: string;
  changelog: string[];
  fast_forward: boolean;
}

export interface ReleaseStatus {
  git: boolean;
  current_version: string;
  current_commit: string | null;
  latest: ReleaseInfo | null;
  update_available: boolean;
  dirty?: boolean;
  busy?: boolean;
  checked_at?: string;
  message: string | null;
}

export interface ReleaseApplyResult {
  ok: boolean;
  from_commit: string;
  to_tag: string;
  to_commit: string;
  database_backup: string | null;
  restart_required: boolean;
  message: string;
}

export interface SettingsUpdate {
  inference_mode?: InferenceMode;
  models?: Partial<Record<InferenceMode, string>>;
  api_keys?: Partial<Record<Exclude<InferenceMode, "local">, string>>;
  pii_strictness?: PiiStrictness;
  enforce_ustg_check?: boolean;
  ai_act_escalation?: boolean;
  /** Tageslimit für Cloud-Tokens; -1 = ohne Limit. */
  cloud_daily_token_limit?: number;
  fallbacks?: InferenceMode[];
  ausweich_modelle?: Partial<Record<CloudMode, string>>;
  ausweich_schluessel?: { id: string; provider: CloudMode; model?: string; api_key?: string }[];
}

export interface ConnectionTestResult {
  ok: boolean;
  provider: InferenceMode;
  model: string;
  message: string;
  code?: string;
  suggested_model?: string | null;
}

export interface CopilotTurn {
  role: "user" | "assistant";
  content: string;
}

export interface CopilotResponse {
  answer: string;
  model: string;
  provider: string;
  duration_ms: number;
  reference: boolean;
  heuristic?: boolean;
  failover?: FailoverSwitch[] | null;
  notice?: string | null;
}

/** POST /api/vat/verify - VIES-Momentaufnahme, nicht gespeichert, ohne Score-Einfluss. */
export interface VatVerification {
  country_code: string;
  vat_number: string;
  valid: boolean;
  name: string | null;
  address: string | null;
  request_date: string | null;
  request_identifier: string | null;
  source: string;
}

export interface LedgerVerification {
  valid: boolean;
  entries: number;
  head_hash: string;
  broken_at_seq: number | null;
  reason: string | null;
  verified_at: string;
  signed_entries: number;
}

export interface HealthResponse {
  status: "ok" | "degraded";
  version: string;
  environment: string;
  auth_enabled: boolean;
  timestamp: string;
  database: { status: string; detail?: string | null; dialect?: string | null; documents?: number | null };
  ollama: {
    status: string;
    detail?: string | null;
    base_url: string;
    model: string;
    model_available: boolean;
    available_models: string[];
    suggested_model?: string | null;
  };
  inference: {
    mode: InferenceMode;
    model: string;
    is_cloud: boolean;
    privacy_gateway_active: boolean;
    configured: boolean;
    uses_local?: boolean;
    chain_length?: number;
    heuristic_fallback?: boolean;
    open_jobs?: number;
  } | null;
}
