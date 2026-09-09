import { DocumentDetail, DocumentSummary, HealthResponse } from "../types/api";

export const MOCK_HEALTH: HealthResponse = {
  status: "ok",
  version: "1.0.0",
  environment: "development",
  auth_enabled: false,
  timestamp: new Date().toISOString(),
  database: {
    status: "ok",
    dialect: "sqlite",
    documents: 4,
    latency_ms: 1.8,
  },
  ollama: {
    status: "ok",
    base_url: "http://127.0.0.1:11434",
    model: "qwen2.5:14b-instruct",
    model_available: true,
    available_models: ["qwen2.5:14b-instruct", "llama3.1:8b"],
    latency_ms: 12.4,
  },
};

export const MOCK_DOCUMENTS: DocumentSummary[] = [
  {
    id: "doc-8f2a1b94-c817-4e92-91bf-3132bb82a410",
    filename: "SaaS_Vendor_Agreement_TalentAI_Screening_2024.pdf",
    status: "extracted",
    size_bytes: 1845230,
    page_count: 8,
    doc_type: "contract",
    sender: "TalentMetrics Cognitive Solutions GmbH",
    document_date: "2024-07-15",
    total_amount: 145000.0,
    currency: "EUR",
    ai_act_risk_level: "high",
    gdpr_risk_level: "high",
    contains_special_categories: true,
    created_at: "2024-09-08T10:14:22Z",
    updated_at: "2024-09-08T10:15:05Z",
  },
  {
    id: "doc-3c99df02-7108-4122-b5e1-881a7428c055",
    filename: "Rechnung_RE-2024-88412_Cloud_Infrastructure.pdf",
    status: "extracted",
    size_bytes: 420110,
    page_count: 2,
    doc_type: "invoice",
    sender: "Nordic Hyperscale Cloud AG",
    document_date: "2024-08-01",
    total_amount: 24890.5,
    currency: "EUR",
    ai_act_risk_level: "minimal",
    gdpr_risk_level: "low",
    contains_special_categories: false,
    created_at: "2024-09-07T14:20:11Z",
    updated_at: "2024-09-07T14:21:02Z",
  },
  {
    id: "doc-a1104e77-9092-4f3d-8e41-6543bca71199",
    filename: "Biometric_Access_Gate_Specification_Terminal_3.pdf",
    status: "extracted",
    size_bytes: 2840192,
    page_count: 14,
    doc_type: "contract",
    sender: "VisionGuard Security Tech Ltd.",
    document_date: "2024-06-20",
    total_amount: 420000.0,
    currency: "EUR",
    ai_act_risk_level: "high",
    gdpr_risk_level: "high",
    contains_special_categories: true,
    created_at: "2024-09-06T09:12:44Z",
    updated_at: "2024-09-06T09:14:00Z",
  },
  {
    id: "doc-512bc900-1123-42cc-a291-0987dfea2211",
    filename: "Incoming_Audit_Pending_Vendor_Terms.pdf",
    status: "uploaded",
    size_bytes: 891200,
    page_count: 4,
    doc_type: "other",
    sender: "FinScale Analytics Europe B.V.",
    document_date: "2024-09-01",
    total_amount: null,
    currency: null,
    ai_act_risk_level: null,
    gdpr_risk_level: null,
    contains_special_categories: null,
    created_at: "2024-09-09T01:30:00Z",
    updated_at: "2024-09-09T01:30:00Z",
  },
];

export const MOCK_DETAIL_HIGH_RISK: DocumentDetail = {
  id: "doc-8f2a1b94-c817-4e92-91bf-3132bb82a410",
  filename: "SaaS_Vendor_Agreement_TalentAI_Screening_2024.pdf",
  content_type: "application/pdf",
  status: "extracted",
  size_bytes: 1845230,
  sha256: "9e407d4b2e67a0a55e2b0235cb58ec87c4cf6d3b37060f781df030ec6099dfa1",
  page_count: 8,
  char_count: 16840,
  model: "qwen2.5:14b-instruct",
  extraction: {
    doc_type: "contract",
    sender: "TalentMetrics Cognitive Solutions GmbH",
    recipient: "Alpha Holding Global Enterprises SE",
    document_number: "VTR-2024-AI-8921",
    document_date: "2024-07-15",
    due_date: "2027-07-14",
    total_amount: 145000.0,
    currency: "EUR",
    iban: "DE89370400440532013000",
    iban_valid: true,
    summary:
      "Gegenstand des vorliegenden Vertrages ist die Bereitstellung eines KI-gestützten Bewerber-Screenings und automatisierter Video-Interviews zur Vorauswahl von Fachkräften. Das System analysiert Sprachmuster, Lebensläufe und psychometrische Eignungstests.",
    issues: [
      "Automatisierte Ablehnungsentscheidungen ohne dokumentierte menschliche Letztverantwortung (Human-in-the-loop)",
      "Verarbeitung biometrischer Sprach- und Mimikanalysedaten ohne explizite DSGVO Art. 9 Abs. 2 Einwilligungsklausel",
      "Fehlende Konformitätsbewertung nach EU AI Act Anhang VII",
    ],
  },
  compliance: {
    model: "qwen2.5:14b-instruct",
    audited_at: "2024-09-08T10:15:05Z",
    duration_ms: 3820,
    headline: "EU AI Act: Hochrisiko | DSGVO: besondere Kategorien (Art. 9/10)",
    ai_act: {
      describes_ai_system: true,
      overall_risk_level: "high",
      is_high_risk: true,
      systems: [
        {
          name: "TalentAI Candidate Ranker & Voice Scanner v4.2",
          purpose:
            "Automatisierte Priorisierung, Profilierung und Eignungsfilterung von Bewerbern im HR-Recruiting-Prozess mittels Algorithmen für Natural Language Processing und Stimmfrequenz-Analyse.",
          risk_level: "high",
          annex_iii_categories: ["employment_and_worker_management"],
          annex_iii_labels: [
            "Anhang III Nr. 4 - Beschäftigung und Personalmanagement",
          ],
          evidence:
            "Ziffer 3.1: 'Das System führt ein KI-gestütztes Vorab-Ranking aller eingehenden Bewerbungen durch und filtert die unteren 60% der Kandidaten ohne manuelle Interaktion heraus.'",
          confidence: 0.98,
        },
      ],
      reasoning:
        "Das beschriebene System fällt eindeutig unter Anhang III Punkt 4 Buchstabe a und b der Verordnung (EU) 2024/1689 (EU AI Act). KI-Systeme, die zur Einstellung oder Auswahl natürlicher Personen, insbesondere für die gezielte Platzierung von Stellenanzeigen, das Filtern von Bewerbungen und die Bewertung von Bewerbern eingesetzt werden, sind zwingend als Hochrisiko-KI-Systeme eingestuft.",
      obligations: [
        "Einrichtung und Dokumentation eines umfassenden Risikomanagementsystems (Art. 9 EU AI Act)",
        "Einhaltung strikter Daten-Governance-Kriterien gegen Diskriminierung und Bias in Trainingsdaten (Art. 10 EU AI Act)",
        "Detaillierte technische Dokumentation vor Inverkehrbringen / Einsatz (Art. 11 EU AI Act)",
        "Automatische Ereignisprotokollierung / Logging über den gesamten Lebenszyklus (Art. 12 EU AI Act)",
        "Gewährleistung wirksamer menschlicher Aufsicht (Human Oversight, Art. 14 EU AI Act)",
        "Registrierung in der EU-Datenbank für Hochrisiko-KI-Systeme (Art. 71 EU AI Act)",
      ],
    },
    gdpr: {
      contains_personal_data: true,
      risk_level: "high",
      contains_special_categories: true,
      findings_by_category: {
        health_data: 2,
        criminal_offence_data: 1,
        bank_account: 1,
        contact_data: 2,
        name: 3,
      },
      reasoning:
        "Es werden besondere Kategorien personenbezogener Daten gem. Art. 9 Abs. 1 DSGVO (Gesundheitsdaten / psychologische Stresstests) sowie strafrechtliche Führungszeugnis-Prüfungen nach Art. 10 DSGVO verarbeitet. Eine Datenschutz-Folgenabschätzung (DSFA gem. Art. 35 DSGVO) ist zwingend erforderlich.",
      recommendations: [
        "Abschluss einer AVV (Auftragsverarbeitungsvereinbarung gem. Art. 28 DSGVO) mit spezifischen TOMs für KI-Modelle",
        "Durchführung einer Datenschutz-Folgenabschätzung (DSFA) nach Art. 35 Abs. 3 lit. a DSGVO",
        "Strikte Löschkonzepte und automatische Schwärzung von Gesundheits- und Bankdaten",
        "Implementierung von Opt-In-Einwilligungen nach Art. 9 Abs. 2 lit. a DSGVO",
      ],
      findings: [
        {
          category: "health_data",
          masked_value: "Schwerbehindertengrad: [GESUNDHEIT_***]",
          context: "Angaben zur körperlichen Eignung und chronischen Vorerkrankungen: [GESUNDHEIT_***]",
          confidence: 0.96,
          source: "both",
          is_special_category: true,
          category_label: "Gesundheitsdaten (Art. 9 Abs. 1 DSGVO)",
        },
        {
          category: "criminal_offence_data",
          masked_value: "Führungszeugnis: [STRAFRECHT_***]",
          context: "Überprüfung amtlicher Register auf Vorstrafen: [STRAFRECHT_***]",
          confidence: 0.94,
          source: "llm",
          is_special_category: true,
          category_label: "Strafrechtliche Verurteilungen und Straftaten (Art. 10 DSGVO)",
        },
        {
          category: "bank_account",
          masked_value: "DE89 **** **** **** 3000",
          context: "Abrechnungskonto der Gesellschaft: DE89 **** **** **** 3000",
          confidence: 0.99,
          source: "rule_based",
          is_special_category: false,
          category_label: "Bankverbindung (IBAN/BIC)",
        },
        {
          category: "contact_data",
          masked_value: "c***@talentmetrics-solutions.de",
          context: "Datenschutzbeauftragter erreichbar unter c***@talentmetrics-solutions.de",
          confidence: 0.95,
          source: "rule_based",
          is_special_category: false,
          category_label: "Kontaktdaten (E-Mail, Telefon)",
        },
        {
          category: "name",
          masked_value: "Dr. K*** W***",
          context: "Vertraglich bevollmächtigt: Dr. K*** W***, Chief Risk Officer",
          confidence: 0.91,
          source: "llm",
          is_special_category: false,
          category_label: "Name einer natürlichen Person",
        },
      ],
    },
  },
  text_preview: `VERTRAG ÜBER DIE BEREITSTELLUNG VON TALENTAI ENTERPRISE EDITION
Zwischen der TalentMetrics Cognitive Solutions GmbH, Friedrichstraße 102, 10117 Berlin (Auftragnehmer)
und der Alpha Holding Global Enterprises SE, Ludwig-Erhard-Allee 15, 60314 Frankfurt am Main (Auftraggeber).

§ 1 Leistungsgegenstand & KI-Funktionalität
Der Auftragnehmer lizenziert dem Auftraggeber die SaaS-Lösung 'TalentAI Candidate Ranker & Voice Scanner v4.2'. 
Die Software verarbeitet eingehende Bewerberdaten vollautomatisiert. Unter Verwendung von neuronalen Netzen 
und Sprachfrequenzmodellen werden Stimmaufnahmen aus Video-Interviews auf Nervosität, kognitive Leistungsfähigkeit 
und Eignungsparameter hin quantifiziert.

§ 2 Risikoklassifizierung & EU AI Act
Beide Parteien nehmen zur Kenntnis, dass das System unter die Verordnung (EU) 2024/1689 (EU AI Act) 
Anhang III Nr. 4 (Beschäftigung und Personalmanagement) fällt. Der Einsatz begründet ein Hochrisiko-KI-System.
Besondere Sorgfaltspflichten bezüglich menschlicher Aufsicht (Human-in-the-loop) und Bias-Auditierung 
sind einzuhalten.

§ 3 Datenschutzrechtliche Bestimmungen (DSGVO)
1. Die Verarbeitung von Mitarbeiter- und Bewerberdaten erfolgt im Auftrag.
2. Soweit sensible Daten nach Art. 9 DSGVO (z.B. Gesundheitsdaten zur Arbeitsfähigkeit) erfasst werden, 
   ist eine gesonderte Einwilligung einzuholen.
3. Bankverbindung für monatliche Lizenzgebühren: DE89370400440532013000 bei der Deutschen Bank Berlin.
4. Kontakt des behördlichen Datenschutzbeauftragten: compliance-officer@talentmetrics-solutions.de.
Unterzeichnet von Dr. Klaus Weber am 15.07.2024.`,
  error: null,
  created_at: "2024-09-08T10:14:22Z",
  updated_at: "2024-09-08T10:15:05Z",
  extracted_at: "2024-09-08T10:15:05Z",
};
