"""Execute the real merge step against an offline, recording GitHub stub."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
GH_STUB = r'''
import base64, json, os, subprocess, sys
from pathlib import Path
p = Path(os.environ['PATCH_TEST_DIR'])
args = sys.argv[1:]
head, base, merged = 'a' * 40, 'b' * 40, 'c' * 40
with (p / 'calls.jsonl').open('a') as stream:
    stream.write(json.dumps(args) + '\n')
if args[0] == 'workflow':
    raise SystemExit(0)
route = next(arg for arg in args if arg.startswith('repos/'))
if '-X' in args and args[args.index('-X') + 1] == 'PUT':
    (p / 'merged').touch()
    value = {'merged': True, 'sha': merged}
elif '/git/ref/heads/master' in route:
    value = {'object': {'sha': merged if (p / 'merged').exists() else base}}
elif '/contents/requirements.txt?ref=' in route:
    file = 'after.txt' if route.endswith(head) else 'before.txt'
    content = (p / file).read_bytes()
    value = {'encoding': 'base64', 'content': base64.b64encode(content).decode(), 'size': len(content)}
elif route.endswith('/pulls/7'):
    value = {'state': 'open', 'draft': False, 'user': {'login': 'dependabot[bot]'},
             'base': {'ref': 'master', 'sha': base},
             'head': {'sha': head, 'ref': 'dependabot/pip/update',
                      'repo': {'full_name': 'Railsimulatornet/docker.new-easyepg'}}}
elif '/compare/' in route:
    value = {'behind_by': 0, 'ahead_by': 1}
elif '/labels' in route:
    value = [{'name': 'automerge:patch'}]
elif '/pulls/7/files' in route:
    value = [{'filename': 'requirements.txt', 'status': 'modified', 'additions': 1, 'deletions': 1,
              'patch': '@@ -1 +1 @@\n-demo==1.2.3\n+demo==1.2.4'}]
elif '/check-runs' in route:
    names = ['prep', 'assemble', 'compare-parsers', 'Analyze (actions)', 'Analyze (python)',
             'build-arch (Dockerfile.amd64, linux/amd64, amd64, amd64)',
             'build-arch (Dockerfile.arm64v8, linux/arm64, arm64, arm64)',
             'build-arch (Dockerfile.arm32v7, linux/arm/v7, armv7, arm, v7)']
    value = {'check_runs': [{'name': name, 'status': 'completed', 'conclusion': 'success'} for name in names]}
elif '/actions/runs?' in route:
    names = ['Build & Push to Docker Hub (multi-arch)', 'EasyEPG XML and JSON compatibility', 'CodeQL']
    value = {'workflow_runs': [{'name': name, 'status': 'completed', 'conclusion': 'success'} for name in names]}
elif route.endswith('/status'):
    value = {'statuses': []}
else:
    raise SystemExit('Unexpected read in offline fixture: ' + route)
if '--jq' in args:
    result = subprocess.run([os.environ['PATCH_TEST_JQ'], '-r', args[args.index('--jq') + 1]],
                            input=json.dumps(value), text=True, capture_output=True, check=True)
    print(result.stdout, end='')
else:
    print(json.dumps(value))
'''


class ActualMergeStep(unittest.TestCase):
    def run_gate(self, after):
        workflow = (ROOT / '.github/workflows/dependabot-automerge.yml').read_text()
        marker = '      - name: Merge eligible patch update after all required checks pass\n'
        self.assertEqual(workflow.count(marker), 1)
        block = workflow.split(marker, 1)[1].split('        run: |\n', 1)[1]
        script = '\n'.join(line[10:] if line.startswith('          ') else line for line in block.splitlines())
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)
            stub = path / 'gh'
            stub.write_text('#!' + sys.executable + '\n' + GH_STUB)
            stub.chmod(0o755)
            (path / 'before.txt').write_text('demo==1.2.3\n')
            (path / 'after.txt').write_text(after)
            (path / 'event.json').write_text(json.dumps({'workflow_run': {
                'head_sha': 'a' * 40, 'pull_requests': [{'number': 7}]}}))
            env = {'PATH': str(path) + os.pathsep + '/usr/bin:/bin',
                   'GITHUB_EVENT_PATH': str(path / 'event.json'),
                   'GITHUB_REPOSITORY': 'Railsimulatornet/docker.new-easyepg',
                   'PATCH_TEST_DIR': str(path), 'PATCH_TEST_JQ': shutil.which('jq') or ''}
            self.assertTrue(env['PATCH_TEST_JQ'], 'The workflow requires jq')
            result = subprocess.run(['/bin/bash', '-c', script], env=env, cwd=ROOT,
                                    capture_output=True, text=True, timeout=20)
            calls = [json.loads(line) for line in (path / 'calls.jsonl').read_text().splitlines()]
            self.assertEqual(result.returncode, 0, result.stderr)
            return calls

    def test_exact_patch_reaches_only_the_simulated_merge(self):
        calls = self.run_gate('demo==1.2.4\n')
        self.assertEqual(sum('-X' in call and call[call.index('-X') + 1] == 'PUT' for call in calls), 1)

    def test_label_or_diff_cannot_override_actual_contents(self):
        for after in ['demo==1.3.0\n', 'demo==2.0.0\n', 'demo==1.2.4rc1\n',
                      'demo>=1.2.4\n', 'other==1.2.4\n', 'demo==1.2.4\nextra==1.0.0\n']:
            with self.subTest(after=after):
                calls = self.run_gate(after)
                self.assertFalse(any('-X' in call for call in calls))
                self.assertFalse(any(call[0] == 'workflow' for call in calls))


if __name__ == '__main__':
    unittest.main()
