"""Exercise OCI input handling and failure propagation without running a scanner."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

BASE = Path(__file__).parent
MOCK = r'''#!/usr/bin/env python3
import json, os, sys
from pathlib import Path
args = sys.argv[1:]
kind = Path(sys.argv[0]).name
with open(os.environ['CALLS'], 'a') as out:
    print(json.dumps([kind, args]), file=out)
scenario = os.environ['CASE']
if kind == 'skopeo':
    if scenario == 'copy-fails': sys.exit(9)
    assert '--all' in args and '--preserve-digests' in args
    destination = Path(args[-1].removeprefix('oci:').removesuffix(':verified'))
    destination.mkdir()
    (destination / 'index.json').write_text('{}')
    sys.exit(0)
if args[0] == 'pull': sys.exit(1 if scenario == 'pull-fails' else 0)
if args[:2] == ['image', 'inspect']:
    print('sha256:' + 'a' * 64)
    sys.exit(0)
assert args[0] == 'run'
assert args[args.index('--user') + 1] == f'{os.getuid()}:{os.getgid()}'
assert '--cache-dir' in args and args[args.index('--cache-dir') + 1] == '/cache'
mounts = {}
for i, arg in enumerate(args):
    if arg == '--mount':
        values = dict(part.split('=', 1) for part in args[i+1].split(',') if '=' in part)
        mounts[values['dst']] = Path(values['src'])
assert mounts['/image'].is_dir() and (mounts['/image'] / 'index.json').is_file()
assert mounts['/cache'].is_dir()
if 'convert' in args:
    if scenario == 'convert-fails': sys.exit(9)
    print('Table created from full report')
    sys.exit(0)
assert args[args.index('--input') + 1] == '/image'
assert '--ignore-unfixed' not in args and '--severity' not in args
if scenario == 'scan-fails': sys.exit(9)
if scenario == 'no-report': sys.exit(0)
report = {'SchemaVersion': 2, 'Metadata': {'OS': {'Family': 'debian', 'Name': '13'}},
          'Results': [{'Class': 'os-pkgs', 'Vulnerabilities': []}]}
if scenario in ('fixed', 'unfixed'):
    report['Results'][0]['Vulnerabilities'] = [{'Severity': 'HIGH', 'FixedVersion': '2' if scenario == 'fixed' else ''}]
(mounts['/out'] / 'full.json').write_text('broken' if scenario == 'invalid-json' else json.dumps(report))
'''


class ScanCommandTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.bin = self.root / 'bin'
        self.bin.mkdir()
        self.calls = self.root / 'calls'
        self.output = self.root / 'reports'
        self.archive = self.root / 'image.tar'
        self.archive.write_bytes(b'OCI fixture')
        for name in ('docker', 'skopeo'):
            path = self.bin / name
            path.write_text(MOCK)
            path.chmod(0o755)

    def run_case(self, scenario, platform='linux/amd64'):
        env = os.environ | {'PATH': str(self.bin) + ':' + os.environ['PATH'],
                             'CALLS': str(self.calls), 'CASE': scenario}
        result = subprocess.run(['bash', str(BASE / 'scan-image.sh'), str(self.archive),
                                 platform, str(self.output)], env=env, capture_output=True, text=True)
        calls = [json.loads(v) for v in self.calls.read_text().splitlines()] if self.calls.exists() else []
        # Temporary layout and cache must be removable by the runner after any outcome.
        for tool, args in calls:
            if tool == 'skopeo':
                layout = Path(args[-1].removeprefix('oci:').removesuffix(':verified'))
                self.assertFalse(layout.parent.exists())
        return result, calls

    def test_layout_not_archive_scanned_as_runner_user(self):
        result, calls = self.run_case('clean')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(calls[0][0], 'skopeo')
        self.assertTrue((self.output / 'full.json').is_file())
        self.assertTrue((self.output / 'high-critical.txt').is_file())

    def test_supported_platforms_forwarded(self):
        for platform in ('linux/arm64', 'linux/arm/v7'):
            with self.subTest(platform=platform):
                self.output = self.root / platform.replace('/', '-')
                result, calls = self.run_case('clean', platform)
                self.assertEqual(result.returncode, 0, result.stderr)
                scan = [args for tool, args in calls if tool == 'docker' and '--input' in args][-1]
                self.assertEqual(scan[scan.index('--platform') + 1], platform)

    def test_fixable_finding_blocks(self):
        result, _ = self.run_case('fixed')
        self.assertEqual(result.returncode, 42)
        self.assertTrue((self.output / 'full.json').exists())

    def test_unfixed_finding_remains_in_report(self):
        result, _ = self.run_case('unfixed')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(json.loads((self.output / 'full.json').read_text())['Results'][0]['Vulnerabilities']), 1)

    def test_all_tool_and_report_failures_block(self):
        for scenario in ('copy-fails', 'pull-fails', 'scan-fails', 'no-report', 'convert-fails', 'invalid-json'):
            with self.subTest(scenario=scenario):
                self.output = self.root / scenario
                result, _ = self.run_case(scenario)
                self.assertNotEqual(result.returncode, 0)

    def test_stale_report_rejected_before_tools_run(self):
        self.output.mkdir()
        (self.output / 'full.json').write_text('{}')
        result, calls = self.run_case('clean')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(calls, [])

    def test_unknown_platform_rejected(self):
        result, calls = self.run_case('clean', 'linux/s390x')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(calls, [])


if __name__ == '__main__':
    unittest.main()
