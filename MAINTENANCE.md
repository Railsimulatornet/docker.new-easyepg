# Image maintenance / Image-Wartung

## Deutsch

Die bisherigen Image-Namen, Compose-Einstellungen, Port `4000` und Mounts `/easyepg` sowie `/easyepg/xml` bleiben erhalten. Die drei Plattformen AMD64, ARM64 und ARMv7 werden weiterhin unterstützt.

### Tags

- `latest`: das zuletzt veröffentlichte, geprüfte Multi-Arch-Image.
- `DDMMYYYY`: der erste veröffentlichte Build des jeweiligen Tages, weiterhin in der Zeitzone Europe/Berlin. Bereits vorhandene Datumstags werden von diesem Workflow nicht mehr überschrieben.
- `YYYYMMDD-build.LAUF.VERSUCH`: eindeutiger Build-Tag mit Datum und Workflow-Laufnummer, beispielsweise `20260927-build.126.1`.

Es werden keine neuen öffentlichen `build-<SHA>-<Architektur>`-Kandidaten-Tags mehr angelegt. Bereits vorhandene Tags bleiben bestehen. Ein Datums-/Build-Tag fixiert das Image, nicht die unabhängig nachgeladenen EasyEPG-Skripte: `UPDATE=yes` lädt diese beim Start weiterhin aus dem eingestellten Repository und Branch.

### Automatische Pflege

Der bisherige wöchentliche Ablauf bleibt erhalten. Jede Architektur wird zunächst lokal gebaut, ohne Veröffentlichung geprüft und erst nach erfolgreichen Prüfungen aller drei Plattformen zu einem gemeinsamen Image zusammengefasst. Docker Hub erhält genau diese geprüften Inhalte einschließlich SBOM und Build-Nachweisen, ohne zweiten Build.

Behebbare HIGH-/CRITICAL-Funde oder unvollständige Scans verhindern die Veröffentlichung. Die vollständigen JSON-Berichte enthalten auch derzeit nicht behebbare Funde und werden 30 Tage als Workflow-Artefakte aufbewahrt. Ein bestandener Scan bedeutet nicht, dass das Image frei von allen Schwachstellen ist.

Pull Requests sowie reine Dokumentations-/Workflow-Änderungen starten Tests, veröffentlichen aber kein neues Image. Änderungen an Dockerfiles, `requirements.txt` oder Startskripten auf `master` sowie der Wochenjob veröffentlichen nach bestandenen Prüfungen. Bei einem manuellen Lauf ist die Veröffentlichung standardmäßig deaktiviert und muss mit `publish` ausdrücklich ausgewählt werden. Der Workflow legt keine GitHub-Releases an.

## English

Existing image names, Compose settings, port `4000` and the `/easyepg` and `/easyepg/xml` mounts remain unchanged. AMD64, ARM64 and ARMv7 remain supported.

- `latest` points to the most recently published, verified multi-platform image.
- `DDMMYYYY` identifies the first published build of that day in Europe/Berlin. Existing date tags are no longer overwritten by this workflow.
- `YYYYMMDD-build.RUN.ATTEMPT` identifies a specific build, for example `20260927-build.126.1`.

New public `build-<SHA>-<architecture>` candidate tags are no longer created. Existing tags are retained. Image tags do not pin the independently downloaded EasyEPG application: `UPDATE=yes` continues to fetch it from the configured repository and branch at startup.

The weekly workflow builds and checks all three platforms before publishing their verified contents, SBOM and provenance without rebuilding. Fixable HIGH/CRITICAL findings and incomplete scans block publication. Complete JSON reports retain unfixed findings and are stored as workflow artifacts for 30 days. Passing the gate does not imply an absence of all vulnerabilities.

PRs and documentation/workflow-only changes run tests without publishing. Runtime-source changes on `master` and scheduled runs publish after successful checks. Manual runs default to tests only; publication requires opting in with `publish`. This workflow does not create GitHub releases.
