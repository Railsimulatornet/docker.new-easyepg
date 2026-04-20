# new-easyepg (Unofficial fork)

A Docker container for running the **NEW easyepg**.

> **Status:** Unofficial fork of `DeBaschdi/docker.new-easyepg`, providing reliability fixes and a multi-arch image. Not affiliated with DeBaschdi/Takealug.

---

## 🇩🇪 Kurzüberblick

- **Fixes:** `beautifulsoup4` (bs4) wird im Image installiert. Startskripte sind mit korrekten Rechten und Zeilenenden hinterlegt.
- **Builds:** Multi-Arch Manifeste für **amd64 / arm64 / armv7**.
- **Images:** Veröffentlichung auf Docker Hub als `latest` sowie mit Datums-Tags im Format **DDMMYYYY** wie zum Beispiel `20042026`.

---

## What’s changed vs. upstream

- ✅ **Fix:** add `beautifulsoup4` (bs4), required by providers such as `zttch.py`
- ✅ **Fix:** normalize line endings (LF), ensure shebangs and `0755` for startup scripts
  - `/usr/local/bin/easyepg.process`
  - `/usr/local/sbin/entrypoint`
- ✅ **Clean:** remove legacy `qemu-*-static` cross-build remnants, because Buildx/QEMU handles emulation cleanly
- ✅ **Publish:** multi-arch manifests for **amd64 / arm64 / armv7**

---

## Tags

The image is published under the following public tags:

- `railsimulatornet/new-easyepg:latest`
  - moving tag that always points to the newest published multi-arch image
- `railsimulatornet/new-easyepg:DDMMYYYY`
  - date-based release tag, for example `railsimulatornet/new-easyepg:20042026`

### Recommended usage

- Use **`latest`** if you want to stay on the newest published image
- Use a **date tag** if you want to pin a specific known-good release for reproducible deployments or rollback scenarios

---

## Quick start (docker run)

### Use the newest image

```bash
docker run -d \
  --name new-easyepg \
  -p 4000:4000 \
  -e TZ=Europe/Berlin \
  -e USER_ID="1009" \
  -e GROUP_ID="10" \
  -e TIMEZONE="Europe/Berlin" \
  -e UPDATE="yes" \
  -e REPO="script.service.easyepg-lite" \
  -e BRANCH="main" \
  -v /path/on/host/easyepg:/easyepg \
  -v /path/on/host/easyepg_xml:/easyepg/xml \
  --restart unless-stopped \
  railsimulatornet/new-easyepg:latest
```

### Use a fixed dated release

```bash
docker run -d \
  --name new-easyepg \
  -p 4000:4000 \
  -e TZ=Europe/Berlin \
  -e USER_ID="1009" \
  -e GROUP_ID="10" \
  -e TIMEZONE="Europe/Berlin" \
  -e UPDATE="yes" \
  -e REPO="script.service.easyepg-lite" \
  -e BRANCH="main" \
  -v /path/on/host/easyepg:/easyepg \
  -v /path/on/host/easyepg_xml:/easyepg/xml \
  --restart unless-stopped \
  railsimulatornet/new-easyepg:20042026
```

---

## docker-compose

### Track the newest published image

```yaml
services:
  easyepg:
    image: railsimulatornet/new-easyepg:latest
    container_name: new-easyepg
    restart: unless-stopped
    ports:
      - "4000:4000"
    environment:
      TZ: Europe/Berlin
      USER_ID: "1009"
      GROUP_ID: "10"
      TIMEZONE: Europe/Berlin
      UPDATE: "yes"
      REPO: script.service.easyepg-lite
      BRANCH: main
    volumes:
      - /path/on/host/easyepg:/easyepg
      - /path/on/host/easyepg_xml:/easyepg/xml
```

### Pin a fixed dated release

```yaml
services:
  easyepg:
    image: railsimulatornet/new-easyepg:20042026
    container_name: new-easyepg
    restart: unless-stopped
    ports:
      - "4000:4000"
    environment:
      TZ: Europe/Berlin
      USER_ID: "1009"
      GROUP_ID: "10"
      TIMEZONE: Europe/Berlin
      UPDATE: "yes"
      REPO: script.service.easyepg-lite
      BRANCH: main
    volumes:
      - /path/on/host/easyepg:/easyepg
      - /path/on/host/easyepg_xml:/easyepg/xml
```

> **Note:** Replace the example host paths with real absolute paths and ensure permissions match the provided `USER_ID` and `GROUP_ID`.

---

## Example paths (Synology / UGREEN)

```yaml
volumes:
  - /volume2/docker/embyserver/takealug_new-easyepg/easyepg:/easyepg
  - /volume2/docker/embyserver/takealug_new-easyepg/easyepg_xml:/easyepg/xml
```

---

## Environment variables

| Variable   | Type   | Default                    | Description |
|------------|--------|----------------------------|-------------|
| `USER_ID`  | int    | `99`                       | UID to run easyepg as |
| `GROUP_ID` | int    | `100`                      | GID to run easyepg as |
| `TIMEZONE` | string | `Europe/Berlin`            | Container timezone |
| `REPO`     | string | `script.service.easyepg-lite` | Git repo to clone (user `sunsettrack4`) |
| `BRANCH`   | string | `main`                     | Branch to clone |
| `UPDATE`   | yes/no | `yes`                      | Update easyepg scripts on each start |

---

## Ports

| Host → Container | Purpose |
|------------------|---------|
| `4000:4000`      | easyepg web interface |

---

## Volumes

| Mount          | Required | Description |
|----------------|----------|-------------|
| `/easyepg`     | yes      | Persist easyepg program files |
| `/easyepg/xml` | yes      | Persist the generated XML file |

---

## Build & CI

This repository builds **multi-arch** images for:

- `linux/amd64`
- `linux/arm64`
- `linux/arm/v7`

The CI publishes the image to Docker Hub as:

- `latest`
- a **date-based tag** in the format `DDMMYYYY`

### Publishing behavior

- Pushes to `main` update `latest`
- Scheduled or manual builds also publish `latest`
- Each published build additionally creates a dated release tag such as `20042026`

### Why date tags?

Date tags make it easy to:

- pin a known-good release
- roll back quickly
- identify when an image was published at a glance

### To reuse this setup

1. Create a Docker Hub **Access Token**
2. Add these GitHub repository secrets:
   - `DOCKERHUB_USERNAME`
   - `DOCKERHUB_TOKEN`
3. Run the GitHub Actions workflow by:
   - pushing to `main`
   - running it manually
   - or waiting for the scheduled run

---

## Update note for WUD users

If you use **What's Up Docker (WUD)** with `latest`, digest-based watching is recommended for this container.

Reason:

- `latest` is a moving tag
- date tags like `20042026` are not SemVer tags
- digest watching is the most reliable way to detect updates for moving Docker tags

If you prefer fixed and reproducible deployments, use a dated tag instead of `latest`.

---

## OCI Image Labels

Add these labels to your Dockerfiles to improve traceability:

```dockerfile
LABEL org.opencontainers.image.title="new-easyepg (Unofficial fork)" \
      org.opencontainers.image.description="NEW EasyEPG with bs4 + permissions fixes; multi-arch" \
      org.opencontainers.image.source="https://github.com/Railsimulatornet/docker.new-easyepg" \
      org.opencontainers.image.url="https://hub.docker.com/r/railsimulatornet/new-easyepg" \
      org.opencontainers.image.licenses="GPL-3.0-only"

COPY LICENSE /usr/share/licenses/GPL-3.0.txt
```

> If needed, you can also embed the Git commit SHA in CI for additional traceability.

---

## License

This repository is a fork of **DeBaschdi/docker.new-easyepg**. Unless noted otherwise, code is licensed under **GNU GPL-3.0**.

```text
SPDX-License-Identifier: GPL-3.0-only
```

- Upstream: <https://github.com/DeBaschdi/docker.new-easyepg>
- Fork: <https://github.com/Railsimulatornet/docker.new-easyepg>
- A copy of the license should be present in `LICENSE` and is copied into the image at `/usr/share/licenses/GPL-3.0.txt`.

### Trademark & data usage

“EasyEPG” and third-party names or logos belong to their respective owners.

This project provides containerization only. Ensure your use of EPG and data sources complies with the respective providers’ terms.

---

## Credits

- Original work: DeBaschdi/docker.new-easyepg
- Community and contributors
