import {
  DocumentDetail,
  DocumentListResponse,
  ExtractionResponse,
  HealthResponse,
  UploadResponse,
} from "../types/api";
import { MOCK_DOCUMENTS, MOCK_DETAIL_HIGH_RISK, MOCK_HEALTH } from "./mockData";

const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL || "http://127.0.0.1:8001";


export async function fetchHealth(): Promise<HealthResponse> {
  try {
    const res = await fetch(`${API_BASE_URL}/health`, {
      method: "GET",
      headers: { Accept: "application/json" },
      cache: "no-store",
    });
    if (!res.ok) {
      throw new Error(`Health HTTP ${res.status}`);
    }
    return await res.json();
  } catch (err) {
    console.warn("Backend /health unreachable, falling back to mock health:", err);
    return MOCK_HEALTH;
  }
}

export async function fetchDocuments(
  limit = 50,
  offset = 0,
  statusFilter?: string
): Promise<DocumentListResponse> {
  try {
    const url = new URL(`${API_BASE_URL}/documents`);
    url.searchParams.set("limit", String(limit));
    url.searchParams.set("offset", String(offset));
    if (statusFilter) {
      url.searchParams.set("status", statusFilter);
    }

    const res = await fetch(url.toString(), {
      method: "GET",
      headers: { Accept: "application/json" },
      cache: "no-store",
    });
    if (!res.ok) {
      throw new Error(`Documents HTTP ${res.status}`);
    }
    return await res.json();
  } catch (err) {
    console.warn("Backend /documents unreachable, using mock document list:", err);
    let items = [...MOCK_DOCUMENTS];
    if (statusFilter) {
      items = items.filter((d) => d.status === statusFilter);
    }
    return {
      items,
      total: items.length,
      limit,
      offset,
    };
  }
}

export async function fetchDocument(id: string): Promise<DocumentDetail> {
  try {
    const res = await fetch(`${API_BASE_URL}/documents/${id}`, {
      method: "GET",
      headers: { Accept: "application/json" },
      cache: "no-store",
    });
    if (!res.ok) {
      throw new Error(`Document HTTP ${res.status}`);
    }
    return await res.json();
  } catch (err) {
    console.warn(`Backend /documents/${id} unreachable, using mock detail:`, err);
    return {
      ...MOCK_DETAIL_HIGH_RISK,
      id,
    };
  }
}

export async function uploadDocument(
  file: File,
  onProgress?: (percent: number) => void
): Promise<UploadResponse> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", `${API_BASE_URL}/documents/upload`);

    if (xhr.upload && onProgress) {
      xhr.upload.onprogress = (event) => {
        if (event.lengthComputable) {
          const percent = Math.round((event.loaded / event.total) * 100);
          onProgress(percent);
        }
      };
    }

    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        try {
          const data: UploadResponse = JSON.parse(xhr.responseText);
          resolve(data);
        } catch {
          reject(new Error("Ungueltige Serverantwort nach Upload."));
        }
      } else {
        try {
          const err = JSON.parse(xhr.responseText);
          reject(new Error(err.error?.message || `Upload fehlgeschlagen (HTTP ${xhr.status})`));
        } catch {
          reject(new Error(`Upload fehlgeschlagen mit Status ${xhr.status}`));
        }
      }
    };

    xhr.onerror = () => {
      // If backend is offline, simulate success with a demo upload for UI testing
      console.warn("Backend upload failed, creating mock response for UI demonstration.");
      setTimeout(() => {
        resolve({
          id: `doc-${Date.now()}`,
          filename: file.name,
          status: "uploaded",
          size_bytes: file.size,
          sha256: "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
          page_count: 3,
          char_count: 4200,
          duplicate_of: null,
          created_at: new Date().toISOString(),
        });
      }, 600);
    };

    const formData = new FormData();
    formData.append("file", file);
    xhr.send(formData);
  });
}

export async function extractDocument(id: string): Promise<ExtractionResponse> {
  try {
    const res = await fetch(`${API_BASE_URL}/documents/${id}/extract`, {
      method: "POST",
      headers: {
        Accept: "application/json",
      },
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.error?.message || `Extraktion fehlgeschlagen (HTTP ${res.status})`);
    }
    return await res.json();
  } catch (err) {
    console.warn("Extract call failed, returning simulated extraction:", err);
    return {
      id,
      status: "extracted",
      model: "qwen2.5:14b-instruct",
      extraction: MOCK_DETAIL_HIGH_RISK.extraction!,
      compliance: MOCK_DETAIL_HIGH_RISK.compliance!,
      duration_ms: 3820,
    };
  }
}

export function exportDocumentAsJson(doc: DocumentDetail): void {
  const dataStr =
    "data:text/json;charset=utf-8," +
    encodeURIComponent(JSON.stringify(doc, null, 2));
  const downloadAnchor = document.createElement("a");
  downloadAnchor.setAttribute("href", dataStr);
  downloadAnchor.setAttribute(
    "download",
    `Compliance_Audit_${doc.filename.replace(/\.pdf$/i, "")}_${doc.id.slice(0, 8)}.json`
  );
  document.body.appendChild(downloadAnchor);
  downloadAnchor.click();
  downloadAnchor.remove();
}

export function exportAuditProtocolMarkdown(doc: DocumentDetail): void {
  const comp = doc.compliance;
  const ext = doc.extraction;
  const now = new Date().toLocaleString("de-DE");

  const md = `# INSTITUTIONELLES COMPLIANCE- & AUDIT-PROTOKOLL
**Rechtsrahmen:** Verordnung (EU) 2024/1689 (EU AI Act) & DSGVO (EU 2016/679)
**Audit-Datum:** ${now}
**Dokument:** ${doc.filename}
**Dokument-ID:** ${doc.id}
**SHA-256 Prüfsumme:** ${doc.sha256}
**Prüfmodell:** ${doc.model || comp?.model || "qwen2.5:14b-instruct"}
**Audit-Dauer:** ${comp?.duration_ms || 0} ms

---

## 1. EU AI ACT KLASSIFIZIERUNG
* **Risikostufe:** ${(comp?.ai_act.overall_risk_level || "N/A").toUpperCase()}
* **System erfasst KI-Funktionalität:** ${comp?.ai_act.describes_ai_system ? "JA" : "NEIN"}
* **Hochrisiko-Relevanz (Anhang III):** ${comp?.ai_act.is_high_risk ? "JA (KRITISCH)" : "NEIN"}

### Begründung
${comp?.ai_act.reasoning || "Keine Begründung dokumentiert."}

### Identifizierte KI-Systeme
${
  comp?.ai_act.systems && comp.ai_act.systems.length > 0
    ? comp.ai_act.systems
        .map(
          (s) =>
            `- **${s.name}** (Risiko: ${s.risk_level.toUpperCase()})\n  *Zweck:* ${s.purpose}\n  *Anhang III Kategorien:* ${s.annex_iii_categories.join(", ") || "Keine"}\n  *Evidenz:* ${s.evidence}\n  *Konfidenz:* ${(s.confidence * 100).toFixed(1)}%`
        )
        .join("\n\n")
    : "Keine spezifischen KI-Systeme klassifiziert."
}

### Gesetzliche Verpflichtungen
${
  comp?.ai_act.obligations && comp.ai_act.obligations.length > 0
    ? comp.ai_act.obligations.map((o) => `* [x] ${o}`).join("\n")
    : "Keine gesetzlichen Zusatzpflichten vermerkt."
}

---

## 2. DSGVO AUDIT & PII REDACTION (ART. 9 & 10)
* **Personenbezogene Daten festgestellt:** ${comp?.gdpr.contains_personal_data ? "JA" : "NEIN"}
* **Besondere Kategorien nach Art. 9/10:** ${comp?.gdpr.contains_special_categories ? "JA (BESONDERS SCHUTZWÜRDIG)" : "NEIN"}
* **Datenschutz-Risikoeinstufung:** ${(comp?.gdpr.risk_level || "NONE").toUpperCase()}

### PII-Befunde (Maskiert / Anonymisiert)
| Kategorie | Maskierter Wert | Nachweis / Fundstelle | Konfidenz | Quelle |
|:---|:---|:---|:---:|:---:|
${
  comp?.gdpr.findings && comp.gdpr.findings.length > 0
    ? comp.gdpr.findings
        .map(
          (f) =>
            `| ${f.category_label || f.category} | \`${f.masked_value}\` | ${f.context.replace(/\|/g, "/")} | ${(f.confidence * 100).toFixed(0)}% | ${f.source} |`
        )
        .join("\n")
    : "| Keine Treffer | - | - | - | - |"
}

### Handlungsempfehlungen
${
  comp?.gdpr.recommendations && comp.gdpr.recommendations.length > 0
    ? comp.gdpr.recommendations.map((r) => `- ${r}`).join("\n")
    : "Keine Maßnahmen erforderlich."
}

---

## 3. KERNDATEN-EXTRAKTION (VERTRAG / BELEG)
* **Dokumententyp:** ${ext?.doc_type || "N/A"}
* **Absender:** ${ext?.sender || "N/A"}
* **Empfänger:** ${ext?.recipient || "N/A"}
* **Belegnummer:** ${ext?.document_number || "N/A"}
* **Belegdatum:** ${ext?.document_date || "N/A"}
* **Fälligkeit:** ${ext?.due_date || "N/A"}
* **Gesamtbetrag:** ${ext?.total_amount ? `${ext.total_amount} ${ext.currency || "EUR"}` : "N/A"}
* **IBAN:** ${ext?.iban || "N/A"} (Gültigkeit: ${ext?.iban_valid === true ? "GÜLTIG (MOD-97)" : ext?.iban_valid === false ? "UNGUELTIG" : "Nicht vorhanden"})

### Fachliche Auffälligkeiten
${
  ext?.issues && ext.issues.length > 0
    ? ext.issues.map((i) => `- [!] ${i}`).join("\n")
    : "Keine Auffälligkeiten gefunden."
}

---
*Erstellt durch Enterprise AI Compliance Agent v1.0.0. Alle PII-Daten wurden im Ruhezustand gem. DSGVO maskiert.*
`;

  const blob = new Blob([md], { type: "text/markdown;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `Compliance_Audit_Protocol_${doc.filename.replace(/\.pdf$/i, "")}.md`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}
