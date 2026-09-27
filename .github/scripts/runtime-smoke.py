"""Offline dependency and privilege-drop checks; never downloads provider data."""
import importlib.metadata
import importlib.util
import io
import os
from pathlib import Path
import sys

import bottle
from bs4 import BeautifulSoup
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
for package in ("bottle", "requests", "urllib3", "certifi", "idna", "xmltodict", "beautifulsoup4", "simplejson", "cffi"):
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
print("Offline runtime, configured UID/GID and XML directory: OK")
