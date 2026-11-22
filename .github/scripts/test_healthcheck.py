"""Exercise the read-only status probe against an actual loopback HTTP endpoint."""
import http.server
import importlib.util
import json
from pathlib import Path
import threading
import unittest

SOURCE = Path(__file__).resolve().parents[2] / 'root/easyepg.healthcheck.py'
spec = importlib.util.spec_from_file_location('easyepg_healthcheck', SOURCE)
health = importlib.util.module_from_spec(spec)
spec.loader.exec_module(health)
STATUS = {'success': True, 'result': {'grabbing': False, 'status': 'Idle', 'progress': 100}}


class HealthTests(unittest.TestCase):
    def test_idle_and_active_grab_are_valid(self):
        self.assertTrue(health.validate_status(STATUS))
        self.assertTrue(health.validate_status({'success': True, 'result': {
            'grabbing': True, 'status': 'Downloading EPG data...', 'progress': 31.25}}))

    def test_failed_or_incomplete_state_is_rejected(self):
        for result in (None, [], {'grabbing': 'false', 'status': 'Idle', 'progress': 1},
                       {'grabbing': False, 'status': '', 'progress': 1},
                       {'grabbing': False, 'status': 'Idle', 'progress': None},
                       {'grabbing': False, 'status': 'Idle', 'progress': float('nan')}):
            with self.assertRaises(ValueError):
                health.validate_status({'success': True, 'result': result})
        for value in (None, [], {}, {'success': False, 'result': STATUS['result']}):
            with self.assertRaises(ValueError):
                health.validate_status(value)

    def test_real_http_requires_correct_route_status_and_json(self):
        paths = []
        class Handler(http.server.BaseHTTPRequestHandler):
            status = 200
            body = json.dumps(STATUS).encode()
            def do_GET(self):
                paths.append(self.path)
                self.send_response(type(self).status)
                self.end_headers()
                self.wfile.write(type(self).body)
            def log_message(self, *_args): pass
        server = http.server.HTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            self.assertTrue(health.check_health(port=server.server_port))
            self.assertEqual(paths, ['/api/grabber-status'])
            for code, body in ((500, b'{}'), (302, json.dumps(STATUS).encode()),
                               (200, b'<html>not an API</html>'), (200, b'x' * 16385),
                               (200, b'{"success":false}')):
                Handler.status, Handler.body = code, body
                with self.assertRaises(ValueError):
                    health.check_health(port=server.server_port)
        finally:
            server.shutdown()
            server.server_close()
            thread.join()

    def test_all_architectures_include_identical_probe_and_base(self):
        root = SOURCE.parent.parent
        bases, probes = [], []
        for name in ('Dockerfile.amd64', 'Dockerfile.arm64v8', 'Dockerfile.arm32v7'):
            text = (root / name).read_text()
            bases.append(next(line for line in text.splitlines() if line.startswith('FROM ')))
            self.assertIn('COPY root/easyepg.healthcheck.py /usr/local/bin/easyepg.healthcheck.py', text)
            probes.append(text.split('HEALTHCHECK ', 1)[1].split('ENTRYPOINT', 1)[0].strip())
        self.assertEqual(len(set(bases)), 1)
        self.assertEqual(len(set(probes)), 1)


if __name__ == '__main__':
    unittest.main()
