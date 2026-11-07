# Image maintenance / Image-Wartung

## Deutsch

Die bisherigen Image-Namen, Compose-Einstellungen, Port `4000` und Mounts `/easyepg` sowie `/easyepg/xml` bleiben erhalten. Die drei Plattformen AMD64, ARM64 und ARMv7 werden weiterhin unterstützt.

### Tags

- `latest`: das zuletzt veröffentlichte, geprüfte Multi-Arch-Image.
- `DDMMYYYY`: der erste veröffentlichte Build des jeweiligen Tages, weiterhin in der Zeitzone Europe/Berlin. Bereits vorhandene Datumstags werden von diesem Workflow nicht mehr überschrieben.
- `YYYYMMDD-build.LAUF.VERSUCH`: eindeutiger Build-Tag mit Datum und Workflow-Laufnummer, beispielsweise `20260927-build.126.1`.

Es werden keine neuen öffentlichen `build-<SHA>-<Architektur>`-Kandidaten-Tags mehr angelegt. Bereits vorhandene Tags bleiben bestehen. Ein Datums-/Build-Tag fixiert das Image, nicht die unabhängig nachgeladenen EasyEPG-Skripte. Bei `UPDATE=yes` wird der Upstream-Code aus dem eingestellten Repository und Branch zunächst in einem getrennten Verzeichnis heruntergeladen und offline geprüft. Die vorherige Programmfassung wird für einen begrenzten Rückfall erhalten. Bestehende `settings.json`, `cache`, `epg.db`, XMLTV-Dateien und `resources/data/db/channels.db` werden vom Updater nicht überschrieben. Nach Änderungen am Upstream-Datenbankschema ist ein gesonderter Kompatibilitätstest erforderlich.

### Automatische Pflege

Der bisherige wöchentliche Ablauf bleibt erhalten. Jede Architektur wird zunächst lokal gebaut, ohne Veröffentlichung geprüft und erst nach erfolgreichen Prüfungen aller drei Plattformen zu einem gemeinsamen Image zusammengefasst. Docker Hub erhält genau diese geprüften Inhalte einschließlich SBOM und Build-Nachweisen, ohne zweiten Build.

Behebbare HIGH-/CRITICAL-Funde oder unvollständige Scans verhindern die Veröffentlichung. Die vollständigen JSON-Berichte enthalten auch derzeit nicht behebbare Funde und werden 30 Tage als Workflow-Artefakte aufbewahrt. Ein bestandener Scan bedeutet nicht, dass das Image frei von allen Schwachstellen ist.

Pull Requests sowie reine Dokumentations-/Workflow-Änderungen starten Tests, veröffentlichen aber kein neues Image. Änderungen an Dockerfiles, `requirements.txt` oder Startskripten auf `master` sowie der Wochenjob veröffentlichen nach bestandenen Prüfungen. Bei einem manuellen Lauf ist die Veröffentlichung standardmäßig deaktiviert und muss mit `publish` ausdrücklich ausgewählt werden. Der Workflow legt keine GitHub-Releases an.


### Freigegebene Python-Abhängigkeiten

Die Python-Pakete einschließlich ihrer Unterabhängigkeiten sind in `requirements.txt` mit exakten Versionen festgelegt. So kann ein wöchentlicher Build nicht heimlich eine neue Minor- oder Major-Version übernehmen. Die aktuelle Liste enthält `pytz 2026.6` und `curl-cffi 0.17.0`. Der Build installiert mit `--no-deps`, prüft die Abhängigkeitskonsistenz mittels `pip check` und gleicht **sämtliche** im Python-Laufzeitsystem installierten Pakete gegen diese Liste ab. Zusätzliche Pakete und Versionsabweichungen stoppen den Build. Die temporären Build-Werkzeuge sind ebenfalls festgelegt und werden aus dem Laufzeit-Image entfernt.

Die Offline-Laufzeittests prüfen zusätzlich echte HTTP-Anfragen über die lokale Loopback-Schnittstelle: GET/POST, Unicode, JSON, Cookies, Weiterleitungen, gzip und Brotli sowie HTTP- und JSON-Fehler. Sie laufen mit der installierten curl-cffi-Bibliothek und Firefox-Imitation auf allen drei Plattformen. Externe Anbieteranmeldungen und deren TLS-/Anti-Bot-Verhalten werden dadurch nicht geprüft.

Dependabot darf weiterhin neue Versionen per Pull Request vorschlagen. Ein neuer Patch wird erst nach den bestehenden Sicherheits- und Kompatibilitätsprüfungen freigegeben; Minor-/Major-Versionen benötigen eine manuelle Prüfung. **Wichtig:** Die Basis `python:3.12-slim`, Debian-Pakete und der beim Start unabhängig aktualisierte EasyEPG-Quellcode sind dadurch noch nicht unveränderlich. Diese Änderung sichert die Python-Paketversionen, nicht das gesamte Image auf Byte-Ebene.


## English

Existing image names, Compose settings, port `4000` and the `/easyepg` and `/easyepg/xml` mounts remain unchanged. AMD64, ARM64 and ARMv7 remain supported.

- `latest` points to the most recently published, verified multi-platform image.
- `DDMMYYYY` identifies the first published build of that day in Europe/Berlin. Existing date tags are no longer overwritten by this workflow.
- `YYYYMMDD-build.RUN.ATTEMPT` identifies a specific build, for example `20260927-build.126.1`.

New public `build-<SHA>-<architecture>` candidate tags are no longer created. Existing tags are retained. Image tags do not pin the independently downloaded EasyEPG application: `UPDATE=yes` continues to fetch it from the configured repository and branch at startup.

The weekly workflow builds and checks all three platforms before publishing their verified contents, SBOM and provenance without rebuilding. Fixable HIGH/CRITICAL findings and incomplete scans block publication. Complete JSON reports retain unfixed findings and are stored as workflow artifacts for 30 days. Passing the gate does not imply an absence of all vulnerabilities.

PRs and documentation/workflow-only changes run tests without publishing. Runtime-source changes on `master` and scheduled runs publish after successful checks. Manual runs default to tests only; publication requires opting in with `publish`. This workflow does not create GitHub releases.

### Approved Python dependency versions

Every Python runtime package (including indirect dependencies) is pinned to an exact version in `requirements.txt`. Scheduled builds therefore cannot silently adopt a newer minor or major Python package. The current list includes `pytz 2026.6` and `curl-cffi 0.17.0`. Builds install with `--no-deps`, perform `pip check`, and reject any missing, unexpected or version-mismatched runtime package. Temporary build tools are also version-pinned and removed before runtime.

Offline runtime checks also exercise real loopback HTTP requests with the installed curl-cffi library and Firefox impersonation on all three platforms: GET/POST, Unicode, JSON, cookies, redirects, gzip, Brotli and error handling. These tests do not verify external provider logins or their TLS/anti-bot behavior.

Dependabot still proposes updates through pull requests; existing CI and auto-merge gates remain in force. Base-image and Debian packages, and upstream EasyEPG application code loaded at startup, are **not** pinned by this change. It guarantees the listed Python runtime versions, not byte-for-byte image reproducibility.
