# new-easyepg (Unofficial fork)

A Docker container for running the **NEW easyepg**.

> **Status:** Unofficial fork of `DeBaschdi/docker.new-easyepg`, providing reliability fixes and a multi-arch image. Not affiliated with DeBaschdi/Takealug.

---

## 🇩🇪 Kurzüberblick

- **Fixes:** `beautifulsoup4` (bs4) wird im Image installiert; Startskripte sind mit korrekten Rechten/Zeilenenden hinterlegt.  
- **Builds:** Multi-Arch Manifeste für **amd64 / arm64 / armv7** (GitHub Actions).  
- **Images:** `railsimulatornet/new-easyepg:bs4fix` auf Docker Hub.

---

## What’s changed vs. upstream

- ✅ **Fix:** add `beautifulsoup4` (bs4) – required by providers (e.g. `zttch.py`)
- ✅ **Fix:** normalize line endings (LF), ensure shebangs and `0755` for startup scripts  
  (`/usr/local/bin/easyepg.process`, `/usr/local/sbin/entrypoint`)
- ✅ **Clean:** remove legacy `qemu-*-static` cross-build remnants (Buildx/QEMU handles emulation)
- ✅ **Publish:** multi-arch manifests for **amd64 / arm64 / armv7**

## Tags

- `railsimulatornet/new-easyepg:bs4fix` – stable multi-arch tag with the fixes above  
- `railsimulatornet/new-easyepg:latest` – optional alias to `:bs4fix` (if enabled in CI)  
- `railsimulatornet/new-easyepg:vX.Y.Z` – optional version tags (if published)

---

## Quick start (docker run)

```bash
docker run -d --name new-easyepg   -p 4000:4000   -e TZ=Europe/Berlin   -e USER_ID="1009"   -e GROUP_ID="10"   -e TIMEZONE="Europe/Berlin"   -e UPDATE="yes"   -e REPO="script.service.easyepg-lite"   -e BRANCH="main"   -v /path/on/host/easyepg:/easyepg   -v /path/on/host/easyepg_xml:/easyepg/xml   --restart unless-stopped   railsimulatornet/new-easyepg:bs4fix
```

### docker-compose

```yaml
services:
  easyepg:
    image: railsimulatornet/new-easyepg:bs4fix
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

> **Note:** Replace the example host paths with real absolute paths and ensure permissions match the provided `USER_ID`/`GROUP_ID`.

### Example paths (Synology/Ugreen)

```yaml
volumes:
  - /volume2/docker/embyserver/takealug_new-easyepg/easyepg:/easyepg
  - /volume2/docker/embyserver/takealug_new-easyepg/easyepg_xml:/easyepg/xml
```

---

## Environment variables

| Variable   | Type    | Default          | Description                                    |
|------------|---------|------------------|------------------------------------------------|
| `USER_ID`  | int     | `99`             | UID to run easyepg as                          |
| `GROUP_ID` | int     | `100`            | GID to run easyepg as                          |
| `TIMEZONE` | string  | `Europe/Berlin`  | Container timezone                             |
| `REPO`     | string  | `script.service.easyepg-lite` | Git repo to clone (user `sunsettrack4`) |
| `BRANCH`   | string  | `main`           | Branch to clone                                |
| `UPDATE`   | yes/no  | `yes`            | Update easyepg scripts on each start           |

## Ports

| Host → Container | Purpose                   |
|------------------|---------------------------|
| `4000:4000`      | easyepg web interface     |

## Volumes

| Mount          | Required | Description                         |
|----------------|----------|-------------------------------------|
| `/easyepg`     | yes      | Persist easyepg program files       |
| `/easyepg/xml` | yes      | Persist the generated XML file      |

---

## Build & CI (optional)

This repository can build **multi-arch** images (amd64/arm64/armv7) via GitHub Actions and publish them to Docker Hub (`railsimulatornet/new-easyepg`).

**To reuse this setup:**
1. Create Docker Hub *Access Token* (Docker Hub → Account → **Security** → *New Access Token*).
2. Add GitHub repo secrets:  
   - `DOCKERHUB_USERNAME` → your Docker Hub username  
   - `DOCKERHUB_TOKEN` → the access token
3. Push to `main` or create a tag (e.g. `v0.0.5`).  
   CI builds arch-specific images and assembles a manifest under `:bs4fix` (and optionally `:latest` or the git tag).

---

## OCI Image Labels (recommended)

Add these labels to your Dockerfiles to improve traceability:

```dockerfile
LABEL org.opencontainers.image.title="new-easyepg (Unofficial fork)"       org.opencontainers.image.description="NEW EasyEPG with bs4 + permissions fixes; multi-arch"       org.opencontainers.image.source="https://github.com/Railsimulatornet/docker.new-easyepg"       org.opencontainers.image.url="https://hub.docker.com/r/railsimulatornet/new-easyepg"       org.opencontainers.image.licenses="GPL-3.0-only"

# ensure license gets into the image:
COPY LICENSE /usr/share/licenses/GPL-3.0.txt
```

> In CI, set a `VCS_REF` or embed `${{ github.sha }}` if you also want to track the exact revision.

---

## License

This repository is a fork of **DeBaschdi/docker.new-easyepg**. Unless noted otherwise, code is licensed under **GNU GPL-3.0**.

```
SPDX-License-Identifier: GPL-3.0-only
```

- Upstream: <https://github.com/DeBaschdi/docker.new-easyepg>  
- Fork (this repo): <https://github.com/Railsimulatornet/docker.new-easyepg>  
- A copy of the license should be present in `LICENSE` and is copied into the image at `/usr/share/licenses/GPL-3.0.txt`.

### Trademark & Data usage

“EasyEPG” and third-party names/logos belong to their respective owners.  
This project provides containerization only. Ensure your use of EPG/data sources complies with the providers’ terms.

---

## Credits

- Original work: DeBaschdi/docker.new-easyepg  
- Community & contributors
