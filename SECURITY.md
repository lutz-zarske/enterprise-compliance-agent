# Sicherheit

## Schwachstellen melden

Bitte Sicherheitslücken **nicht als öffentliches Issue** melden, sondern
vertraulich über GitHub: Reiter **Security → Report a vulnerability**.
Hilfreich sind betroffene Version, Schritte zum Nachstellen und die
erwartete Auswirkung.

## Unterstützte Versionen

| Version | Sicherheitskorrekturen |
|---|---|
| 2.5.x | ja |
| < 2.5 | nein |

## Hinweise für den Betrieb

- `API_KEY` setzen, sobald das System nicht nur lokal läuft; ohne Wert ist die
  Authentifizierung abgeschaltet.
- `CORS_ORIGINS` auf die Adresse des Frontends beschränken.
- `data/.settings.key` und `data/.signing.key` sichern und nie einchecken;
  `SETTINGS_ENCRYPTION_KEY` produktiv aus einem Secret-Store setzen.
- Cloud-Anbieter nur mit Auftragsverarbeitungsvertrag nutzen – pseudonymisierte
  Daten bleiben personenbezogen.

Das System ist eine technische Vorprüfung und kein zertifiziertes
Archivsystem; siehe [„Bekannte Grenzen“](README.md#bekannte-grenzen).
