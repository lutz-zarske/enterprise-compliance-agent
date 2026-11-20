"""Regressionstest: Namen mit Anrede, Titel oder Adresszusatz werden vollständig ersetzt.

Bis v2.8.4 blieben „Herrn Max Mustermann“ und „Familie Mustermann“ im Klartext,
und „z. Hd. Herrn Max Mustermann“ verlor nur den Vornamen. Die Tabelle enthält
auch die Formen, die schon vorher funktionierten, damit keine zurückfällt.
"""

from __future__ import annotations

import pytest

from app.privacy_vault import PrivacyVault
from app.redact import redact

# (Belegtext, Namensteile, die danach nicht mehr im Text stehen dürfen)
FAELLE: list[tuple[str, tuple[str, ...]]] = [
    # bis v2.8.4 nicht oder nur teilweise erkannt
    ("Rechnung an Herrn Max Mustermann, Musterweg 1", ("Max", "Mustermann")),
    ("z. Hd. Herrn Max Mustermann", ("Max", "Mustermann")),
    ("z.Hd. Herrn Max Mustermann", ("Max", "Mustermann")),
    ("zu Händen Herrn Max Mustermann", ("Max", "Mustermann")),
    ("zu Haenden Max Mustermann", ("Max", "Mustermann")),
    ("zu Händen Frau Erika Musterfrau", ("Erika", "Musterfrau")),
    ("Herrn Prof. Max Mustermann", ("Max", "Mustermann")),
    ("Familie Mustermann", ("Mustermann",)),
    ("Sehr geehrte Familie Mustermann,", ("Mustermann",)),
    ("Familie Max Mustermann", ("Max", "Mustermann")),
    # funktionierten schon vorher
    ("Herr Max Mustermann", ("Max", "Mustermann")),
    ("Frau Erika Musterfrau", ("Erika", "Musterfrau")),
    ("Hr. Max Mustermann", ("Max", "Mustermann")),
    ("Fr. Erika Musterfrau", ("Erika", "Musterfrau")),
    ("Herrn Dr. Max Mustermann", ("Max", "Mustermann")),
    ("Frau Prof. Dr. Erika Musterfrau", ("Erika", "Musterfrau")),
    ("Sehr geehrter Herr Max Mustermann,", ("Max", "Mustermann")),
    ("Ansprechpartner: Max Mustermann", ("Max", "Mustermann")),
    ("z. Hd. Max Mustermann", ("Max", "Mustermann")),
]


@pytest.mark.parametrize(("text", "namensteile"), FAELLE, ids=[f[0] for f in FAELLE])
def test_name_wird_vollstaendig_ersetzt(text: str, namensteile: tuple[str, ...]) -> None:
    vault = PrivacyVault()
    pseudo = vault.pseudonymize(text)

    for teil in namensteile:
        assert teil not in pseudo, f"{teil!r} steht noch im Text: {pseudo!r}"
    assert pseudo.count("{{PERSON_1}}") == 1
    assert "{{PERSON_2}}" not in pseudo
    assert vault.reidentify(pseudo) == text


@pytest.mark.parametrize(("text", "namensteile"), FAELLE, ids=[f[0] for f in FAELLE])
def test_dlp_gateway_schwaerzt_dieselben_namen(text: str, namensteile: tuple[str, ...]) -> None:
    result = redact(text)

    for teil in namensteile:
        assert teil not in result.text, f"{teil!r} steht noch im Text: {result.text!r}"
    assert result.counts.get("PERSON") == 1


@pytest.mark.parametrize(
    "text",
    [
        "Familienbetrieb seit 1950",
        "Die Produktfamilie Alpha ist lieferbar.",
        "Herrnhuter Sterne, 12 Stück",
    ],
)
def test_keine_person_ohne_anrede(text: str) -> None:
    assert PrivacyVault().pseudonymize(text) == text
