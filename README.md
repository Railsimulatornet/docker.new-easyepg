# EasyEPG Docker

[![Docker-Build und Sicherheitsprüfung](https://github.com/Railsimulatornet/docker.new-easyepg/actions/workflows/dockerhub.yml/badge.svg)](https://github.com/Railsimulatornet/docker.new-easyepg/actions/workflows/dockerhub.yml)
[![XML-/JSON-Kompatibilität](https://github.com/Railsimulatornet/docker.new-easyepg/actions/workflows/dependency-compatibility.yml/badge.svg)](https://github.com/Railsimulatornet/docker.new-easyepg/actions/workflows/dependency-compatibility.yml)

Docker-Image für [EasyEPG lite](https://github.com/sunsettrack4/script.service.easyepg-lite). Das Image wird als inoffizieller Fork gepflegt und bietet aktuelle Laufzeit-Abhängigkeiten sowie Builds für AMD64, ARM64 und ARMv7.

- **Docker Hub:** [railsimulatornet/new-easyepg](https://hub.docker.com/r/railsimulatornet/new-easyepg)
- **Image:** `railsimulatornet/new-easyepg:latest`
- **Weboberfläche:** Port `4000`
- **Docker-Fork und Anpassungen:** Copyright (c) 2026 Roman Glos

Die EasyEPG-Anwendung stammt aus dem Originalprojekt von Jan-Luca Neumann. Grundlage des Docker-Forks ist [DeBaschdi/docker.new-easyepg](https://github.com/DeBaschdi/docker.new-easyepg). Dieses Repository ist kein offizielles Projekt der ursprünglichen Entwickler.

## Installation auf UGREEN NAS oder anderen Docker-Hosts

Die Host-Pfade im folgenden Beispiel bitte an die eigene Installation anpassen. Beim ersten Start lädt `UPDATE: "yes"` den EasyEPG-Anwendungscode von GitHub herunter.

```yaml
services:
  easyepg:
    image: railsimulatornet/new-easyepg:latest
    container_name: new-easyepg
    ports:
      - "4000:4000"
    environment:
      USER_ID: "1009"
      GROUP_ID: "10"
      TIMEZONE: Europe/Berlin
      UPDATE: "yes"
      REPO: script.service.easyepg-lite
      BRANCH: main
    volumes:
      - /volume2/docker/easyepg/data:/easyepg
      - /volume2/docker/easyepg/xml:/easyepg/xml
    restart: unless-stopped
```

Nach der Bereitstellung ist die Oberfläche unter `http://NAS-IP:4000` erreichbar. Port `4000` nicht ohne zusätzliche Absicherung direkt im Internet freigeben.

**Bestehende Installation:** Eigene Host-Pfade, Konfiguration und XMLTV-Dateien beibehalten. Ein erneutes Bereitstellen des Containers darf diese Daten nicht durch leere Verzeichnisse ersetzen.

## Zwei verschiedene Arten von Updates

**Docker-Image aktualisieren:** `latest` verweist auf den neuesten veröffentlichten und geprüften Image-Build. Ein neues Image auf Docker Hub aktualisiert aber keinen bereits laufenden Container. Für eine bestehende Compose-Installation:

```bash
docker compose pull easyepg
docker compose up -d easyepg
```

Die neue Image-Version enthält aktualisierte System- und Python-Abhängigkeiten. Sie ersetzt nicht automatisch den unter `/easyepg` gespeicherten EasyEPG-Anwendungscode.

**EasyEPG-Anwendung aktualisieren:** Das steuert `UPDATE` unabhängig vom Docker-Image:

| Einstellung | Verhalten |
|---|---|
| `UPDATE: "yes"` | Lädt beim Containerstart den aktuellen Code aus `sunsettrack4/script.service.easyepg-lite`, Branch `main`, und kopiert ihn in `/easyepg`. |
| `UPDATE: "no"` | Verwendet den bereits vorhandenen Code aus `/easyepg` und lädt beim Start nichts neu herunter. |

Für eine erstmalige Installation mit leerem Datenordner wird `UPDATE: "yes"` benötigt. Danach kann `UPDATE: "no"` sinnvoll sein, wenn die vorhandene Anwendung unverändert weiterlaufen soll.

**Vor Upstream-Updates die eigenen EasyEPG-Daten sichern.** Das bestehende Update-Skript übernimmt neue Dateien direkt; ein automatischer Funktionstest mit Rückfall auf die vorherige Version findet beim Containerstart nicht statt.

## Einstellungen und Verzeichnisse

| Variable | Vorgabe | Bedeutung |
|---|---|---|
| `USER_ID` | `99` | Benutzerkennung für den EasyEPG-Prozess |
| `GROUP_ID` | `100` | Gruppenzugehörigkeit für Dateien und Prozess |
| `TIMEZONE` | `Europe/Berlin` | Zeitzone des Containers |
| `UPDATE` | `yes` | EasyEPG-Code beim Start aktualisieren |
| `REPO` | `script.service.easyepg-lite` | Anwendungsrepository unter `sunsettrack4` |
| `BRANCH` | `main` | Upstream-Branch |

Die Mounts `/easyepg` und `/easyepg/xml` speichern den Anwendungscode, Einstellungen und erzeugte XMLTV-Dateien dauerhaft. Der Container benötigt Schreibrechte auf diesen Verzeichnissen. Die Beispiel-UID/GID `1009:10` gegebenenfalls an die eigenen Berechtigungen anpassen.

## Image-Tags

| Tag | Bedeutung |
|---|---|
| `latest` | Neuester veröffentlichter Multi-Arch-Build |
| `DDMMYYYY` | Erster veröffentlichter Build dieses Tages, z. B. `17102026`; bestehende Datumstags werden nicht überschrieben |
| `YYYYMMDD-build.LAUF.VERSUCH` | Eindeutig zuordenbarer Build, z. B. `20261017-build.167.1` |

Verfügbar für `linux/amd64`, `linux/arm64` und `linux/arm/v7`. Neue Builds werden vor der Veröffentlichung auf allen drei Architekturen getestet und mit Trivy geprüft. Ein erfolgreicher Scan bedeutet nicht, dass es keine noch ungepatchten Schwachstellen gibt.

Weitere Einzelheiten zum Build- und Sicherheitsworkflow stehen in [MAINTENANCE.md](MAINTENANCE.md).

## Bei Problemen

```bash
docker logs --tail 100 new-easyepg
docker inspect --format '{{.Config.Image}}' new-easyepg
```

Wenn eine frische Installation mit `UPDATE: "no"` nicht startet, prüfen, ob in `/easyepg` bereits der Anwendungscode vorhanden ist. Bei fehlenden Dateien zuerst die Mounts und Berechtigungen kontrollieren. Nicht die produktiven EPG-Daten löschen, nur um einen Startfehler zu beheben.

## Herkunft, Lizenz und Copyright

- **Docker-Fork und eigene Anpassungen:** Copyright (c) 2026 Roman Glos
- **EasyEPG-Anwendung:** [Jan-Luca Neumann / sunsettrack4](https://github.com/sunsettrack4/script.service.easyepg-lite)
- **Ursprüngliche Docker-Vorlage:** [DeBaschdi/docker.new-easyepg](https://github.com/DeBaschdi/docker.new-easyepg)
- **Lizenz des Docker-Forks:** [GNU GPL v3](LICENSE)

Die Rechte und Urheberhinweise der ursprünglichen Projekte bleiben bestehen. EasyEPG und die verwendeten EPG-Datenquellen gehören den jeweiligen Rechteinhabern.

---

## English

This is an unofficial, maintained Docker fork for [EasyEPG lite](https://github.com/sunsettrack4/script.service.easyepg-lite), published as `railsimulatornet/new-easyepg:latest` for AMD64, ARM64 and ARMv7. Use the Compose example above and replace the host paths and UID/GID with your own values.

- **Web UI:** `http://NAS-IP:4000`. Do not expose the web interface directly to the internet.
- **Image update:** Run `docker compose pull easyepg` followed by `docker compose up -d easyepg` to use the latest published image.
- **Upstream source:** `UPDATE=yes` downloads the EasyEPG application on startup; `UPDATE=no` uses the existing files in `/easyepg`. For a new, empty installation start with `UPDATE=yes`.
- **Backups:** Back up your EasyEPG data before updating upstream application files. Startup updates do not have an automatic rollback.
- **Credits:** Docker modifications Copyright (c) 2026 Roman Glos. EasyEPG originates from Jan-Luca Neumann; the Docker fork is based on DeBaschdi's work. Original attribution and GPL terms remain in force.
