export type DocumentStatus = "uploaded" | "processing" | "extracted" | "failed";

export type DocType = "invoice" | "contract" | "offer" | "reminder" | "other";

export type AIActRiskLevel =
  | "unacceptable"
  | "high"
  | "limited"
  | "minimal"
  | "not_applicable";

export type AnnexIIICategory =
  | "biometrics"
  | "critical_infrastructure"
  | "education_and_vocational_training"
  | "employment_and_worker_management"
  | "essential_services_and_creditworthiness"
  | "law_enforcement"
  | "migration_asylum_border_control"
  | "justice_and_democratic_processes";

export type PIICategory =
  | "health_data"
  | "religious_belief"
  | "racial_or_ethnic_origin"
  | "political_opinion"
  | "trade_union_membership"
  | "biometric_data"
  | "genetic_data"
  | "sex_life_or_orientation"
  | "criminal_offence_data"
  | "id_document_number"
  | "social_security_number"
  | "tax_identification_number"
  | "bank_account"
  | "date_of_birth"
  | "name"
  | "address"
  | "contact_data"
  | "other_personal_data";

export type RiskLevel = "none" | "low" | "medium" | "high";

export type DetectionSource = "llm" | "rule_based" | "both";

export interface AISystemFinding {
  name: string;
  purpose: string;
  risk_level: AIActRiskLevel;
  annex_iii_categories: AnnexIIICategory[];
  evidence: string;
  confidence: number;
  annex_iii_labels?: string[];
}

export interface AIActAssessment {
  describes_ai_system: boolean;
  overall_risk_level: AIActRiskLevel;
  systems: AISystemFinding[];
  reasoning: string;
  obligations: string[];
  is_high_risk?: boolean;
}

export interface PIIFinding {
  category: PIICategory;
  masked_value: string;
  context: string;
  confidence: number;
  source: DetectionSource;
  is_special_category?: boolean;
  category_label?: string;
}

export interface GDPRAssessment {
  contains_personal_data: boolean;
  findings: PIIFinding[];
  risk_level: RiskLevel;
  reasoning: string;
  recommendations: string[];
  contains_special_categories?: boolean;
  findings_by_category?: Record<string, number>;
}

export interface ComplianceAudit {
  ai_act: AIActAssessment;
  gdpr: GDPRAssessment;
  model: string;
  audited_at: string;
  duration_ms: number;
  headline?: string;
}

export interface ExtractionResult {
  doc_type: DocType;
  sender: string | null;
  recipient: string | null;
  document_number: string | null;
  document_date: string | null;
  due_date: string | null;
  total_amount: number | string | null;
  currency: string | null;
  iban: string | null;
  iban_valid?: boolean | null;
  summary: string;
  issues: string[];
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
  total_amount: number | string | null;
  currency: string | null;
  ai_act_risk_level: AIActRiskLevel | null;
  gdpr_risk_level: RiskLevel | null;
  contains_special_categories: boolean | null;
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
  error: string | null;
  created_at: string;
  updated_at: string;
  extracted_at: string | null;
}

export interface UploadResponse {
  id: string;
  filename: string;
  status: DocumentStatus;
  size_bytes: number;
  sha256: string;
  page_count: number;
  char_count: number;
  duplicate_of: string | null;
  created_at: string;
}

export interface ExtractionResponse {
  id: string;
  status: DocumentStatus;
  model: string;
  extraction: ExtractionResult;
  compliance: ComplianceAudit;
  duration_ms: number;
}

export interface HealthResponse {
  status: "ok" | "degraded" | "unavailable";
  version: string;
  environment: string;
  auth_enabled: boolean;
  timestamp: string;
  database: {
    status: string;
    detail?: string | null;
    latency_ms?: number | null;
    dialect?: string | null;
    documents?: number | null;
  };
  ollama: {
    status: string;
    detail?: string | null;
    latency_ms?: number | null;
    base_url: string;
    model: string;
    model_available: boolean;
    available_models: string[];
  };
}
