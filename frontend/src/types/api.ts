// Typen spiegeln die Pydantic-Modelle aus app/schemas.py (Backend v2.0).

export type DocumentStatus = "uploaded" | "processing" | "extracted" | "failed";
export type DocType = "invoice" | "contract" | "offer" | "reminder" | "other";
export type AIActRiskLevel = "unacceptable" | "high" | "limited" | "minimal" | "not_applicable";
export type RiskLevel = "none" | "low" | "medium" | "high";
export type DetectionSource = "llm" | "rule_based" | "both";
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
  headline: string;
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

export interface DocumentSummary {
  id: string;
  filename: string;
  status: DocumentStatus;
  size_bytes: number;
  page_count: number | null;
  doc_type: DocType | null;
  sender: string | null;
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
  provider: string | null;
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
  pinned: boolean;
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
}

export interface SettingsUpdate {
  inference_mode?: InferenceMode;
  models?: Partial<Record<InferenceMode, string>>;
  api_keys?: Partial<Record<Exclude<InferenceMode, "local">, string>>;
  pii_strictness?: PiiStrictness;
  enforce_ustg_check?: boolean;
  ai_act_escalation?: boolean;
}

export interface ConnectionTestResult {
  ok: boolean;
  provider: InferenceMode;
  model: string;
  message: string;
  code?: string;
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
  };
  inference: {
    mode: InferenceMode;
    model: string;
    is_cloud: boolean;
    privacy_gateway_active: boolean;
    configured: boolean;
  } | null;
}
