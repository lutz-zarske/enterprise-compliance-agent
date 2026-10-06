"""Unveraenderbares Pruefprotokoll (Audit Ledger) mit Hash-Verkettung.

Rechtlicher Hintergrund
-----------------------
* **EU AI Act Art. 12** verlangt fuer Hochrisiko-KI-Systeme die automatische
  Protokollierung von Ereignissen ueber den gesamten Lebenszyklus.
* **DSGVO Art. 5 Abs. 2** (Rechenschaftspflicht) verlangt, die Einhaltung der
  Grundsaetze nachweisen zu koennen.
* **GoBD Rz. 58 ff.** fordern die Unveraenderbarkeit aufzeichnungspflichtiger
  Daten; die Hash-Kette ist eine technische Massnahme dafuer (die GoBD
  schreiben kein bestimmtes Verfahren vor).

Verfahren
---------
Jeder Eintrag speichert den Hash seines Vorgaengers (``previous_hash``) und
seinen eigenen Hash (``entry_hash``) ueber den kanonischen JSON-Inhalt.  Wer
einen historischen Eintrag aendert oder loescht, bricht die Kette ab dieser
Stelle - ``verify_chain`` weist das mit Sequenznummer nach.  Das ist eine
lineare Hash-Kette (wie bei einem Blockchain-Ledger), kein Merkle-Baum.

Zusaetzlich verhindern Datenbank-Trigger jedes ``UPDATE``/``DELETE`` auf der
Tabelle.  Gegen einen Angreifer mit Vollzugriff auf die Datenbankdatei hilft
kein Trigger; deshalb sollte der Kopf-Hash (``GET /api/audit/head``)
regelmaessig ausserhalb des Systems verankert werden (Ticket, E-Mail,
WORM-Speicher, qualifizierter Zeitstempel nach eIDAS).  Erst dann ist auch
das Abschneiden der juengsten Eintraege nachweisbar.
"""

from __future__ import annotations

import hashlib
import json
import threading
import uuid
from dataclasses import asdict, dataclass, field
from functools import partial
from typing import Any

import anyio.to_thread
import sqlalchemy as sa
from sqlalchemy import Engine

from app.db import audit_trails_table, utcnow

#: Vorgaenger-Hash des allerersten Eintrags.
GENESIS_HASH = "0" * 64

#: Prozessweite Sperre: Lesen des Kopf-Hashes und Anhaengen muessen atomar sein.
_APPEND_LOCK = threading.Lock()


class AuditEventType:
    """Stabile Ereignistypen im Ledger.

    Die Werte sind Teil gespeicherter, gehashter Eintraege und werden nie
    umbenannt.  ``SIGN_OFF`` ist das Pruefer-Siegel (Freigabe/Ablehnung),
    ``HUMAN_OVERRIDE`` die Uebersteuerung einer KI-Einstufung durch eine
    natuerliche Person (Art. 14 Abs. 4 lit. d VO (EU) 2024/1689).
    """

    ANALYSIS = "analysis"
    SIGN_OFF = "sign_off"
    HUMAN_OVERRIDE = "human_override"

    #: Ereignisse natuerlicher Personen - werden zusaetzlich Ed25519-signiert.
    HUMAN = frozenset({SIGN_OFF, HUMAN_OVERRIDE})


#: Schluessel der Signatur innerhalb von ``details``.
SIGNATURE_FIELD = "signature"


def canonical_json(payload: dict[str, Any]) -> str:
    """Deterministische JSON-Serialisierung - Grundlage jedes Hashes."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def compute_entry_hash(content: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_json(content).encode("utf-8")).hexdigest()


@dataclass(slots=True)
class LedgerEntry:
    """Ein Eintrag im Pruefprotokoll."""

    entry_id: str
    event_type: str
    document_id: str
    sha256_hash: str
    model_name: str
    prompt_hash: str
    timestamp_utc: str
    result_summary: str
    compliance_score: int | None
    risk_tier: str
    details: dict[str, Any] = field(default_factory=dict)
    previous_hash: str = GENESIS_HASH
    entry_hash: str = ""
    seq: int | None = None

    def hashed_content(self) -> dict[str, Any]:
        """Alle Felder, die in den Hash eingehen (ohne ``seq`` und ``entry_hash``)."""
        data = asdict(self)
        data.pop("seq", None)
        data.pop("entry_hash", None)
        return data

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def signed_content(self) -> bytes:
        """Signierter Inhalt: alle gehashten Felder inkl. ``previous_hash``, ohne die Signatur selbst."""
        content = self.hashed_content()
        content["details"] = {k: v for k, v in (content.get("details") or {}).items() if k != SIGNATURE_FIELD}
        return canonical_json(content).encode("utf-8")

    @property
    def signature(self) -> dict[str, Any] | None:
        value = (self.details or {}).get(SIGNATURE_FIELD)
        return value if isinstance(value, dict) else None


@dataclass(slots=True)
class ChainVerification:
    """Ergebnis einer vollstaendigen Kettenpruefung."""

    valid: bool
    entries: int
    head_hash: str
    broken_at_seq: int | None = None
    reason: str | None = None
    verified_at: str = field(default_factory=lambda: utcnow().isoformat())
    #: Anzahl der Ed25519-signierten Pruefer-Eintraege, die geprueft wurden.
    signed_entries: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _row_to_entry(row: Any) -> LedgerEntry:
    m = row._mapping  # noqa: SLF001
    return LedgerEntry(
        seq=m["seq"],
        entry_id=m["entry_id"],
        event_type=m["event_type"],
        document_id=m["document_id"],
        sha256_hash=m["sha256_hash"],
        model_name=m["model_name"],
        prompt_hash=m["prompt_hash"],
        timestamp_utc=m["timestamp_utc"],
        result_summary=m["result_summary"],
        compliance_score=m["compliance_score"],
        risk_tier=m["risk_tier"],
        details=m["details"] or {},
        previous_hash=m["previous_hash"],
        entry_hash=m["entry_hash"],
    )


class AuditLedger:
    """Append-only-Protokoll auf Basis von SQLAlchemy Core.

    Mit ``signer`` werden Eintraege natuerlicher Personen (Siegel, Override)
    zusaetzlich Ed25519-signiert.  Die Signatur entsteht unter derselben Sperre
    wie die Verkettung und deckt ``previous_hash`` ab; ``entry_hash`` deckt
    wiederum die Signatur ab.  Wer die Kette vollstaendig neu berechnet, kann
    diese Eintraege ohne den privaten Schluessel nicht neu signieren.
    """

    def __init__(self, engine: Engine, signer: Any | None = None) -> None:
        self._engine = engine
        self._signer = signer

    @property
    def signer(self) -> Any | None:
        return self._signer

    # --- synchron -----------------------------------------------------------
    def _append(self, entry: LedgerEntry) -> LedgerEntry:
        with _APPEND_LOCK, self._engine.begin() as connection:
            if self._engine.dialect.name == "postgresql":
                # Serialisiert das Anhaengen auch ueber mehrere Prozesse/Replikas.
                connection.execute(sa.text("SELECT pg_advisory_xact_lock(424242)"))
            last = connection.execute(
                sa.select(audit_trails_table.c.entry_hash)
                .order_by(audit_trails_table.c.seq.desc())
                .limit(1)
            ).scalar_one_or_none()
            entry.previous_hash = last or GENESIS_HASH
            if self._signer is not None and entry.event_type in AuditEventType.HUMAN:
                entry.details = {k: v for k, v in entry.details.items() if k != SIGNATURE_FIELD}
                entry.details[SIGNATURE_FIELD] = self._signer.sign_bytes(entry.signed_content())
            entry.entry_hash = compute_entry_hash(entry.hashed_content())
            values = entry.to_dict()
            values.pop("seq")
            result = connection.execute(sa.insert(audit_trails_table).values(**values))
            entry.seq = int(result.inserted_primary_key[0])
        return entry

    def _list(self, document_id: str | None, limit: int) -> list[LedgerEntry]:
        statement = sa.select(audit_trails_table).order_by(audit_trails_table.c.seq.desc())
        if document_id:
            statement = statement.where(audit_trails_table.c.document_id == document_id)
        with self._engine.connect() as connection:
            rows = connection.execute(statement.limit(limit)).fetchall()
        return [_row_to_entry(row) for row in rows]

    def _verify(self) -> ChainVerification:
        statement = sa.select(audit_trails_table).order_by(audit_trails_table.c.seq.asc())
        previous = GENESIS_HASH
        expected_seq: int | None = None
        count = 0
        signed = 0
        with self._engine.connect() as connection:
            for row in connection.execute(statement):
                entry = _row_to_entry(row)
                count += 1
                if expected_seq is not None and entry.seq != expected_seq:
                    return ChainVerification(
                        False, count, previous, entry.seq,
                        f"Luecke in der Sequenz: erwartet {expected_seq}, gefunden {entry.seq} "
                        "(Eintrag geloescht).",
                    )
                if entry.previous_hash != previous:
                    return ChainVerification(
                        False, count, previous, entry.seq,
                        "previous_hash passt nicht zum Vorgaenger (Eintrag entfernt oder eingefuegt).",
                    )
                recomputed = compute_entry_hash(entry.hashed_content())
                if recomputed != entry.entry_hash:
                    return ChainVerification(
                        False, count, previous, entry.seq,
                        "Inhalt veraendert: neu berechneter Hash weicht vom gespeicherten ab.",
                    )
                if entry.signature is not None:
                    ok, message = self.verify_entry_signature(entry)
                    if not ok:
                        return ChainVerification(
                            False, count, previous, entry.seq, f"Pruefer-Signatur: {message}", signed_entries=signed
                        )
                    signed += 1
                previous = entry.entry_hash
                expected_seq = (entry.seq or 0) + 1
        return ChainVerification(True, count, previous, signed_entries=signed)

    def verify_entry_signature(self, entry: LedgerEntry) -> tuple[bool, str]:
        """Prueft die Ed25519-Signatur eines Eintrags gegen den System-Schluessel."""
        from app.signing import verify_signature

        signature = entry.signature
        if signature is None:
            return False, "Eintrag ist nicht signiert."
        expected = self._signer.public_info()["fingerprint"] if self._signer is not None else None
        return verify_signature(signature, entry.signed_content(), expected_fingerprint=expected)

    def signature_status(self, entry: LedgerEntry) -> str:
        """``valid`` | ``invalid`` | ``unsigned`` - fuer die Ledger-Historie im Frontend."""
        if entry.signature is None:
            return "unsigned"
        return "valid" if self.verify_entry_signature(entry)[0] else "invalid"

    def _head(self) -> tuple[str, int]:
        with self._engine.connect() as connection:
            row = connection.execute(
                sa.select(audit_trails_table.c.entry_hash, audit_trails_table.c.seq)
                .order_by(audit_trails_table.c.seq.desc())
                .limit(1)
            ).first()
        return (row[0], int(row[1])) if row else (GENESIS_HASH, 0)

    # --- asynchron ----------------------------------------------------------
    async def append(
        self,
        *,
        event_type: str,
        document_id: str,
        sha256_hash: str,
        model_name: str,
        prompt_hash: str,
        result_summary: str,
        compliance_score: int | None,
        risk_tier: str,
        details: dict[str, Any] | None = None,
    ) -> LedgerEntry:
        entry = LedgerEntry(
            entry_id=str(uuid.uuid4()),
            event_type=event_type,
            document_id=document_id,
            sha256_hash=sha256_hash,
            model_name=model_name,
            prompt_hash=prompt_hash,
            timestamp_utc=utcnow().isoformat(),
            result_summary=result_summary[:1000],
            compliance_score=compliance_score,
            risk_tier=risk_tier,
            details=details or {},
        )
        return await anyio.to_thread.run_sync(partial(self._append, entry))

    async def list(self, *, document_id: str | None = None, limit: int = 100) -> list[LedgerEntry]:
        return await anyio.to_thread.run_sync(partial(self._list, document_id, limit))

    async def verify_chain(self) -> ChainVerification:
        return await anyio.to_thread.run_sync(self._verify)

    async def signature_statuses(self, entries: list[LedgerEntry]) -> list[str]:
        return await anyio.to_thread.run_sync(lambda: [self.signature_status(entry) for entry in entries])

    async def head(self) -> tuple[str, int]:
        return await anyio.to_thread.run_sync(self._head)
