# EasyEPG Docker

[![Docker-Build und Sicherheitsprüfung](https://github.com/Railsimulatornet/docker.new-easyepg/actions/workflows/dockerhub.yml/badge.svg)](https://github.com/Railsimulatornet/docker.new-easyepg/actions/workflows/dockerhub.yml)
[![XML-/JSON-Kompatibilität](https://github.com/Railsimulatornet/docker.new-easyepg/actions/workflows/dependency-compatibility.yml/badge.svg)](https://github.com/Railsimulatornet/docker.new-easyepg/actions/workflows/dependency-compatibility.yml)
[![License: GPL-3.0](https://img.shields.io/badge/License-GPL--3.0-blue.svg)](LICENSE)

![EasyEPG](Templates/image.png)

[Deutsch](#deutsch) · [English](#english)

## Deutsch

Docker-Image für [EasyEPG lite](https://github.com/sunsettrack4/script.service.easyepg-lite). Das Image wird als inoffizieller Fork gepflegt und bietet aktuelle Laufzeit-Abhängigkeiten sowie Builds für AMD64, ARM64 und ARMv7.

- **Docker Hub:** [railsimulatornet/new-easyepg](https://hub.docker.com/r/railsimulatornet/new-easyepg)
- **Image:** `railsimulatornet/new-easyepg:latest`
- **Weboberfläche:** Port `4000`
- **Docker-Fork und Anpassungen:** Copyright (c) 2026 Roman Glos

Die EasyEPG-Anwendung stammt aus dem Originalprojekt von Jan-Luca Neumann. Grundlage des Docker-Forks ist [DeBaschdi/docker.new-easyepg](https://github.com/DeBaschdi/docker.new-easyepg). Dieses Repository ist kein offizielles Projekt der ursprünglichen Entwickler.

### Funktionen

- EasyEPG-Weboberfläche und XMLTV-Ausgabe im Docker-Container.
- Dauerhafte Ablage von Anwendung, Einstellungen und EPG-Dateien.
- Getrennte Aktualisierung von Docker-Image und EasyEPG-Anwendung.
- Geprüfte Builds für AMD64, ARM64 und ARMv7.

### Schnellstart

Du brauchst ein UGREEN NAS oder einen anderen Docker-Host. Die Host-Pfade im folgenden Beispiel bitte an die eigene Installation anpassen. Beim ersten Start lädt `UPDATE: "yes"` den EasyEPG-Anwendungscode von GitHub herunter.

```yaml
services:
  new-easyepg:
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

### Aktualisierung

**Docker-Image aktualisieren:** `latest` verweist auf den neuesten veröffentlichten und geprüften Image-Build. Ein neues Image auf Docker Hub aktualisiert aber keinen bereits laufenden Container. Für eine bestehende Compose-Installation:

```bash
docker compose pull new-easyepg
docker compose up -d new-easyepg
```

Verwende dabei den Dienstnamen aus deiner vorhandenen Compose-Datei. Wenn du eine ältere Vorlage mit `easyepg` nutzt, ersetze `new-easyepg` in diesen Befehlen durch `easyepg`.

Die neue Image-Version enthält aktualisierte System- und Python-Abhängigkeiten. Sie ersetzt nicht automatisch den unter `/easyepg` gespeicherten EasyEPG-Anwendungscode.

**EasyEPG-Anwendung aktualisieren:** Das steuert `UPDATE` unabhängig vom Docker-Image:

| Einstellung | Verhalten |
|---|---|
| `UPDATE: "yes"` | Lädt beim Containerstart den aktuellen Code aus `sunsettrack4/script.service.easyepg-lite`, Branch `main`, und kopiert ihn in `/easyepg`. |
| `UPDATE: "no"` | Verwendet den bereits vorhandenen Code aus `/easyepg` und lädt beim Start nichts neu herunter. |

Für eine erstmalige Installation mit leerem Datenordner wird `UPDATE: "yes"` benötigt. Danach kann `UPDATE: "no"` sinnvoll sein, wenn die vorhandene Anwendung unverändert weiterlaufen soll.

**Upstream-Updates werden zunächst getrennt heruntergeladen und geprüft.** Programmdateien werden erst danach übernommen; bestehende Einstellungen, Cache-Dateien, XMLTV-Ausgaben und `channels.db` bleiben erhalten. Bei einem Übernahmefehler wird der vorherige Programmstand wiederhergestellt. Schlägt der Start unmittelbar nach dem Update fehl, wird einmalig die vorherige Programmfassung gestartet. Eine ältere, fehlgeschlagene Revision wird nicht bei jedem Neustart erneut installiert. Das gespeicherte `channels.db` wird absichtlich nicht automatisch durch die mitgelieferte GitHub-Datenbank ersetzt. Für Änderungen an deren Datenstruktur sind eigene Prüfungen erforderlich.

**Vor Updates trotzdem eine Sicherung der EasyEPG-Nutzerdaten anlegen**, insbesondere wegen möglicher Datenbankmigrationen durch neue Anwendungsversionen. Die Wiederherstellung der Programmdateien macht Änderungen der Anwendung an Nutzerdaten nicht rückgängig.

### Konfiguration

| Variable | Vorgabe | Bedeutung |
|---|---|---|
| `USER_ID` | `99` | Benutzerkennung für den EasyEPG-Prozess |
| `GROUP_ID` | `100` | Gruppenzugehörigkeit für Dateien und Prozess |
| `TIMEZONE` | `Europe/Berlin` | Zeitzone des Containers |
| `UPDATE` | `yes` | EasyEPG-Code beim Start aktualisieren |
| `REPO` | `script.service.easyepg-lite` | Anwendungsrepository unter `sunsettrack4` |
| `BRANCH` | `main` | Upstream-Branch |

Die Mounts `/easyepg` und `/easyepg/xml` speichern den Anwendungscode, Einstellungen und erzeugte XMLTV-Dateien dauerhaft. Der Container benötigt Schreibrechte auf diesen Verzeichnissen. Die Beispiel-UID/GID `1009:10` gegebenenfalls an die eigenen Berechtigungen anpassen.

### Image-Tags

| Tag | Bedeutung |
|---|---|
| `latest` | Neuester veröffentlichter Multi-Arch-Build |
| `DDMMYYYY` | Erster veröffentlichter Build dieses Tages, z. B. `17102026`; bestehende Datumstags werden nicht überschrieben |
| `YYYYMMDD-build.LAUF.VERSUCH` | Eindeutig zuordenbarer Build, z. B. `20261017-build.167.1` |

Verfügbar für `linux/amd64`, `linux/arm64` und `linux/arm/v7`. Neue Builds werden vor der Veröffentlichung auf allen drei Architekturen getestet und mit Trivy geprüft. Ein erfolgreicher Scan bedeutet nicht, dass es keine noch ungepatchten Schwachstellen gibt.

Weitere Einzelheiten zum Build- und Sicherheitsworkflow stehen in [MAINTENANCE.md](MAINTENANCE.md).

### Fehlersuche

```bash
docker logs --tail 100 new-easyepg
docker inspect --format '{{.Config.Image}}' new-easyepg
```

Wenn eine frische Installation mit `UPDATE: "no"` nicht startet, prüfen, ob in `/easyepg` bereits der Anwendungscode vorhanden ist. Bei fehlenden Dateien zuerst die Mounts und Berechtigungen kontrollieren. Nicht die produktiven EPG-Daten löschen, nur um einen Startfehler zu beheben.

### Herkunft, Lizenz und Copyright

- **Docker-Fork und eigene Anpassungen:** Copyright (c) 2026 Roman Glos
- **EasyEPG-Anwendung:** [Jan-Luca Neumann / sunsettrack4](https://github.com/sunsettrack4/script.service.easyepg-lite)
- **Ursprüngliche Docker-Vorlage:** [DeBaschdi/docker.new-easyepg](https://github.com/DeBaschdi/docker.new-easyepg)
- **Lizenz des Docker-Forks:** [GNU GPL v3](LICENSE)

Die Rechte und Urheberhinweise der ursprünglichen Projekte bleiben bestehen. EasyEPG und die verwendeten EPG-Datenquellen gehören den jeweiligen Rechteinhabern.

## English

Docker image for [EasyEPG lite](https://github.com/sunsettrack4/script.service.easyepg-lite). This maintained, unofficial fork provides current runtime dependencies and builds for AMD64, ARM64 and ARMv7.

- **Docker Hub:** [railsimulatornet/new-easyepg](https://hub.docker.com/r/railsimulatornet/new-easyepg)
- **Image:** `railsimulatornet/new-easyepg:latest`
- **Web interface:** Port `4000`
- **Docker fork and modifications:** Copyright (c) 2026 Roman Glos

The EasyEPG application originates from Jan-Luca Neumann's project. The Docker fork is based on [DeBaschdi/docker.new-easyepg](https://github.com/DeBaschdi/docker.new-easyepg). This is not an official project of the original developers.

### Features

- EasyEPG web interface and XMLTV output in a Docker container.
- Persistent storage for the application, settings and EPG files.
- Separate updates for the Docker image and EasyEPG application.
- Verified builds for AMD64, ARM64 and ARMv7.

### Quickstart

Use UGREEN NAS or another Docker host. Adjust the host paths in this example to your installation. On the first start, `UPDATE: "yes"` downloads the EasyEPG application code from GitHub.

```yaml
services:
  new-easyepg:
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

After deployment, open `http://NAS-IP:4000`. Do not expose port `4000` directly to the internet without additional protection.

**Existing installations:** Keep your own host paths, configuration and XMLTV files. Redeploying the container must not replace the existing data with empty directories.

### Updates

**Update the Docker image:** `latest` points to the latest published and verified image build. Publishing a new image on Docker Hub does not update an already running container. For an existing Compose installation, run:

```bash
docker compose pull new-easyepg
docker compose up -d new-easyepg
```

Use the service name from your existing Compose file. If an older template names the service `easyepg`, replace `new-easyepg` with `easyepg` in these commands.

The new image contains updated system and Python dependencies. It does not automatically replace the EasyEPG application code stored in `/easyepg`.

**Update the EasyEPG application:** `UPDATE` controls this independently of the Docker image.

| Setting | Behaviour |
| --- | --- |
| `UPDATE: "yes"` | On container startup, download the current code from the `main` branch of `sunsettrack4/script.service.easyepg-lite` and copy it to `/easyepg`. |
| `UPDATE: "no"` | Use the existing code in `/easyepg` without downloading it again on startup. |

An initial installation with an empty data directory requires `UPDATE: "yes"`. Afterwards, `UPDATE: "no"` can be useful when you want to keep the installed application unchanged.

**Upstream updates are downloaded and checked separately before application files are replaced.** Existing settings, cache files, XMLTV output and `channels.db` are preserved. If replacing the application files fails, the previous application files are restored. If the updated application fails immediately after startup, the previous application is started once as a fallback. A known failed revision is not installed again on every restart. The stored `channels.db` is deliberately not replaced with the database shipped on GitHub; schema changes require separate checks.

**Back up the EasyEPG user data before updating.** A new application version may migrate its databases or change user data. Restoring application files does not undo those changes.

### Configuration

| Variable | Default | Purpose |
| --- | --- | --- |
| `USER_ID` | `99` | User ID for the EasyEPG process |
| `GROUP_ID` | `100` | Group ID for files and the process |
| `TIMEZONE` | `Europe/Berlin` | Container time zone |
| `UPDATE` | `yes` | Update EasyEPG code on startup |
| `REPO` | `script.service.easyepg-lite` | Application repository under `sunsettrack4` |
| `BRANCH` | `main` | Upstream branch |

The `/easyepg` and `/easyepg/xml` mounts persist application code, settings and generated XMLTV files. The container needs write access to these directories. Adjust the example UID/GID `1009:10` to match your permissions.

### Image tags

| Tag | Purpose |
| --- | --- |
| `latest` | Latest published multi-architecture build |
| `DDMMYYYY` | First published build of that day, for example `17102026`; existing date tags are not overwritten |
| `YYYYMMDD-build.RUN.ATTEMPT` | Identifiable build, for example `20261017-build.167.1` |

Images are available for `linux/amd64`, `linux/arm64` and `linux/arm/v7`. Each architecture is tested and scanned with Trivy before publication. A successful scan does not mean that no unpatched vulnerabilities remain.

See [MAINTENANCE.md](MAINTENANCE.md) for details about the build and security workflow.

### Troubleshooting

```bash
docker logs --tail 100 new-easyepg
docker inspect --format '{{.Config.Image}}' new-easyepg
```

If a new installation with `UPDATE: "no"` does not start, check whether `/easyepg` already contains the application code. When files are missing, check mounts and permissions first. Do not delete production EPG data to resolve a startup failure.

### Attribution and license

- **Docker fork and modifications:** Copyright (c) 2026 Roman Glos
- **EasyEPG application:** [Jan-Luca Neumann / sunsettrack4](https://github.com/sunsettrack4/script.service.easyepg-lite)
- **Original Docker template:** [DeBaschdi/docker.new-easyepg](https://github.com/DeBaschdi/docker.new-easyepg)
- **Docker fork license:** [GNU GPL v3](LICENSE)

The rights and attribution of the original projects remain in force. EasyEPG and its EPG data sources belong to their respective rights holders.

