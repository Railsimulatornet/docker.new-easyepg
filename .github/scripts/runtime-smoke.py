"""Offline dependency and privilege-drop checks; never downloads provider data."""
import importlib
import importlib.metadata
import importlib.util
import io
import os
from pathlib import Path
import shutil
import subprocess
import sys
from unittest.mock import patch

import bottle
import cheroot.wsgi
from bs4 import BeautifulSoup
from curl_cffi import Curl
from curl_cffi import requests as fingerprint_requests
import pytz
import certifi
import cffi
import idna
import requests
import simplejson
import urllib3
import xmltodict

assert os.getuid() == int(os.environ["USER_ID"]), "Configured UID was not applied"
assert os.getgid() == int(os.environ["GROUP_ID"]), "Configured GID was not applied"
assert sys.prefix == "/opt/venv", f"Unexpected Python environment: {sys.prefix}"
assert importlib.util.find_spec("pip") is None
assert importlib.util.find_spec("setuptools") is None
assert Path(certifi.where()).is_file()
for package in ("bottle", "requests", "urllib3", "certifi", "idna", "xmltodict", "beautifulsoup4", "simplejson", "cffi", "cheroot", "curl-cffi", "pytz"):
    print(f"{package}={importlib.metadata.version(package)}")

assert BeautifulSoup("<title>EPG fixture</title>", "html.parser").title.string == "EPG fixture"
assert xmltodict.parse("<tv><channel id='demo'/></tv>")["tv"]["channel"]["@id"] == "demo"
assert simplejson.loads(simplejson.dumps({"epg": "OK"}))["epg"] == "OK"
assert idna.decode(idna.encode("example.invalid")) == "example.invalid"
assert requests.Request("GET", "http://127.0.0.1/fixture").prepare().path_url == "/fixture"
assert urllib3.util.parse_url("http://127.0.0.1/fixture").path == "/fixture"
assert cffi.FFI().sizeof("int") >= 2

app = bottle.Bottle()
@app.get("/fixture")
def fixture():
    return {"ok": True}

status = []
environ = {"REQUEST_METHOD": "GET", "PATH_INFO": "/fixture", "SCRIPT_NAME": "",
           "QUERY_STRING": "", "SERVER_NAME": "localhost", "SERVER_PORT": "4000",
           "SERVER_PROTOCOL": "HTTP/1.1", "wsgi.version": (1, 0), "wsgi.url_scheme": "http",
           "wsgi.input": io.BytesIO(), "wsgi.errors": sys.stderr, "wsgi.multithread": False,
           "wsgi.multiprocess": False, "wsgi.run_once": True}
body = b"".join(app(environ, lambda s, h, exc_info=None: status.append(s)))
assert status[0].startswith("200 "), status
assert simplejson.loads(body)["ok"] is True
Path("/easyepg/xml/fixture.xml").write_text("<tv/>\n", encoding="utf-8")
assert Path("/easyepg/xml/fixture.xml").read_text() == "<tv/>\n"

# Exercise the upstream runtime prerequisites without contacting any EPG provider.
assert pytz.timezone("Europe/Berlin").zone == "Europe/Berlin"
assert callable(cheroot.wsgi.Server)
curl_bin = shutil.which("curl")
assert curl_bin, "Required curl command is missing"
curl_version = subprocess.run(
    [curl_bin, "--version"], check=True, capture_output=True, text=True, timeout=10
)
assert curl_version.stdout.startswith("curl "), "Unexpected curl executable"
native_curl = Curl()
native_curl.close()
with fingerprint_requests.Session(impersonate="firefox") as session:
    assert callable(session.get)

source = Path(os.environ["EASYEPG_UPSTREAM_SOURCE"])
assert (source / "main.py").is_file(), "Pinned upstream source unavailable"
assert (source / "resources/lib/db.py").is_file()
sys.path.insert(0, str(source))
from resources.lib import db as upstream_db, web as upstream_web

assert upstream_db.requests is fingerprint_requests, "Upstream fell back from curl-cffi"
for provider in ("canal", "cpsol", "tkmde", "tvmat", "tvspf"):
    module = importlib.import_module("resources.lib.providers." + provider)
    assert module.requests is fingerprint_requests, provider + " fell back from curl-cffi"

# Confirm the actual upstream WebServer prefers Cheroot. Do not bind a port.
with patch.object(upstream_web, "init_config"), patch.object(upstream_web, "run") as start_web:
    upstream_web.WebServer(None, None).start()
    assert start_web.call_count == 1
    assert start_web.call_args.kwargs.get("server") == "cheroot"

print("Offline upstream imports, curl-cffi native library, Cheroot and curl: OK")

# Test the actual updater against the pinned upstream source without network access.
import hashlib
import sqlite3
from importlib.util import module_from_spec, spec_from_file_location

fixture = Path("/easyepg/main.py")
original_fixture = fixture.read_bytes()
local_settings = Path("/easyepg/settings.json")
local_settings.write_text('{"fixture":"keep"}', encoding="utf-8")

local_db = Path("/easyepg/resources/data/db/channels.db")
local_db.parent.mkdir(parents=True, exist_ok=True)
with sqlite3.connect(local_db) as connection:
    connection.execute("CREATE TABLE channels (channel_id TEXT, channel_name TEXT, provider_name TEXT, provider_id TEXT, country TEXT, config TEXT)")
    connection.execute("INSERT INTO channels (channel_id) VALUES ('local-user-data')")
before_db = hashlib.sha256(local_db.read_bytes()).hexdigest()

safe_spec = spec_from_file_location(
    "easyepg_safe_update", "/usr/local/bin/easyepg.safe_update.py"
)
safe_module = module_from_spec(safe_spec)
safe_spec.loader.exec_module(safe_module)
safe_updater = safe_module.Updater("/easyepg")
assert safe_updater.apply(source, "ci-pinned-upstream", runtime=True)
assert fixture.read_bytes() == (source / "main.py").read_bytes()
assert local_settings.read_text() == '{"fixture":"keep"}'
assert hashlib.sha256(local_db.read_bytes()).hexdigest() == before_db
assert Path("/easyepg/xml/fixture.xml").read_text() == "<tv/>\n"
assert safe_updater.rollback_recent()
assert fixture.read_bytes() == original_fixture
assert local_settings.read_text() == '{"fixture":"keep"}'
assert hashlib.sha256(local_db.read_bytes()).hexdigest() == before_db
print("Offline staged update, local DB preservation and rollback: OK")

# Exercise provider-style HTTP exchanges using the installed native curl library.
# The container still runs with --network none; only loopback is used.
import base64
import gzip
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from threading import Thread
from urllib.parse import parse_qs, urlsplit

PAYLOAD = {"channels": [{"id": "demo", "name": "Grüße & Musik"}], "number": 42}
BROTLI_PAYLOAD = base64.b64decode(
    "CyCAeyJjaGFubmVscyI6W3siaWQiOiJkZW1vIiwibmFtZSI6Ikdyw7zDn2UgJiBNdXNpayJ9XSwibnVtYmVyIjo0Mn0D"
)


class ProviderFixture(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *_):
        pass

    def send_fixture(self, body, status=200, headers=None):
        self.send_response(status)
        self.send_header("Content-Type", 'application/json; charset="UTF-8"')
        self.send_header("Content-Length", str(len(body)))
        for name, value in (headers or {}).items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = urlsplit(self.path)
        raw = json.dumps(PAYLOAD, ensure_ascii=False, separators=(",", ":")).encode()
        if path.path == "/redirect":
            self.send_fixture(b"", 302, {"Location": "/channels", "Set-Cookie": "fixture=ok; Path=/"})
        elif path.path == "/gzip":
            self.send_fixture(gzip.compress(raw), headers={"Content-Encoding": "gzip"})
        elif path.path == "/br":
            self.send_fixture(BROTLI_PAYLOAD, headers={"Content-Encoding": "br"})
        elif path.path == "/echo":
            self.send_fixture(json.dumps({"query": parse_qs(path.query),
                "cookie": self.headers.get("Cookie", ""),
                "header": self.headers.get("X-Fixture", "")}).encode())
        elif path.path == "/channels":
            self.send_fixture(raw)
        elif path.path == "/invalid":
            self.send_fixture(b"{invalid}")
        else:
            self.send_fixture(b'{"error":"not found"}', 404)

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        if not 0 <= length <= 4096:
            self.send_fixture(b'{"error":"size"}', 413)
            return
        body = self.rfile.read(length)
        if "application/json" in self.headers.get("Content-Type", ""):
            data = json.loads(body)
        else:
            data = parse_qs(body.decode())
        self.send_fixture(json.dumps(data, ensure_ascii=False).encode())


def check_http_backend(backend, *, impersonate=False):
    server = ThreadingHTTPServer(("127.0.0.1", 0), ProviderFixture)
    server.daemon_threads = True
    thread = Thread(target=lambda: server.serve_forever(poll_interval=0.05), daemon=True)
    thread.start()
    root = "http://127.0.0.1:" + str(server.server_port)
    try:
        options = {"impersonate": "firefox"} if impersonate else {}
        with backend.Session(**options) as client:
            client.trust_env = False
            response = client.get(root + "/channels", timeout=5)
            assert response.status_code == 200
            assert response.json() == PAYLOAD
            assert "Grüße & Musik" in response.text
            assert response.json(parse_int=str)["number"] == "42"
            echo = client.get(root + "/echo", params={"lang": "de", "search": "Grüße"},
                headers={"X-Fixture": "provider-style"}, cookies={"synthetic": "only-a-test"}, timeout=5).json()
            assert echo["query"] == {"lang": ["de"], "search": ["Grüße"]}
            assert echo["header"] == "provider-style"
            assert "synthetic=only-a-test" in echo["cookie"]
            assert client.post(root + "/epg", json=PAYLOAD, timeout=5).json() == PAYLOAD
            assert client.post(root + "/login", data={"fixture": "Grüße"}, timeout=5).json() == {"fixture": ["Grüße"]}
            assert client.get(root + "/redirect", allow_redirects=False, timeout=5).status_code == 302
            assert client.get(root + "/redirect", timeout=5).json() == PAYLOAD
            assert "fixture=ok" in client.get(root + "/echo", timeout=5).json()["cookie"]
            for encoding in ("gzip", "br"):
                assert client.get(root + "/" + encoding, timeout=5).json() == PAYLOAD, encoding
            failed = client.get(root + "/missing", timeout=5)
            assert failed.status_code == 404
            try:
                failed.raise_for_status()
            except Exception:
                pass
            else:
                raise AssertionError("HTTP error did not raise")
            try:
                client.get(root + "/invalid", timeout=5).json()
            except ValueError:
                pass
            else:
                raise AssertionError("Invalid JSON was accepted")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
        assert not thread.is_alive(), "Fixture server did not stop"


check_http_backend(fingerprint_requests, impersonate=True)
print("Offline curl-cffi HTTP, cookies, redirects, JSON, gzip and Brotli: OK")
print("Offline runtime, configured UID/GID and XML directory: OK")
