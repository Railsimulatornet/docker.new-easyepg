"""Exercise the real CodeQL gate offline; simulated PUTs are never real merges."""
import copy
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

import patch_policy
import verify_codeql_patch as verifier


ROOT = Path(__file__).resolve().parents[2]
REPO = 'Railsimulatornet/docker.new-easyepg'
HEAD, BASE, MERGED = 'a' * 40, 'b' * 40, 'c' * 40
OLD, NEW = '1' * 40, '2' * 40
BODY = ('Updates `github/codeql-action/init` from 4.39.3 to 4.39.4\n'
        'Updates `github/codeql-action/analyze` from 4.39.3 to 4.39.4')
BEFORE = ('name: CodeQL\npermissions:\n  contents: read\njobs:\n  analyze:\n    steps:\n'
          f'      - uses: github/codeql-action/init@{OLD} # v4.39.3\n'
          f'      - uses: github/codeql-action/analyze@{OLD} # v4.39.3\n')
# Production has a separate name line before uses; the verifier intentionally
# accepts only that existing syntax, not a broader YAML parser.
BEFORE = BEFORE.replace('      - uses:', '      - name: CodeQL action\n        uses:')
AFTER = BEFORE.replace(OLD, NEW).replace('v4.39.3', 'v4.39.4')
CHECK_NAMES = [
    'prep', 'assemble', 'CodeQL', 'description', 'Analyze (actions)', 'Analyze (python)',
    'build-arch (Dockerfile.amd64, linux/amd64, amd64, amd64)',
    'build-arch (Dockerfile.arm64v8, linux/arm64, arm64, arm64)',
    'build-arch (Dockerfile.arm32v7, linux/arm/v7, armv7, arm, v7)',
]
# Values recorded from fetch-metadata for the existing grouped CodeQL update.
RECORDED_METADATA = {'package_ecosystem': 'github_actions',
                     'update_type': 'version-update:semver-patch'}


def fixture():
    pr = {'number': 7, 'state': 'open', 'draft': False,
          'user': {'login': 'dependabot[bot]'}, 'body': BODY,
          'base': {'ref': 'master', 'sha': BASE},
          'head': {'sha': HEAD, 'ref': 'dependabot/github_actions/master/actions-test',
                   'repo': {'full_name': REPO}}, 'labels': [{'name': 'automerge:patch'}]}
    checks = [{'name': name, 'head_sha': HEAD, 'app': {'id': 57789 if name == 'CodeQL' else 15368},
               'status': 'completed', 'conclusion': 'success'} for name in CHECK_NAMES]
    checks += [{'name': name, 'head_sha': HEAD, 'app': {'id': 15368},
                'status': 'completed', 'conclusion': 'skipped'}
               for name in ('publish', 'classify', 'merge', 'codeql_candidates')]
    runs = [{'name': name, 'head_sha': HEAD, 'event': 'pull_request',
             'status': 'completed', 'conclusion': 'success'}
            for name in ('Build & Push to Docker Hub (multi-arch)', 'CodeQL')]
    return {
        'pr': pr, 'open_prs': [pr], 'before': BEFORE, 'after': AFTER,
        'files': [{'filename': '.github/workflows/codeql.yml', 'status': 'modified'}],
        'labels': [{'name': 'automerge:patch'}], 'behind_by': 0,
        'checks': {'total_count': len(checks), 'check_runs': checks},
        'runs': {'total_count': len(runs), 'workflow_runs': runs},
        'tags': {'v4.39.3': OLD, 'v4.39.4': NEW},
        'event': {'workflow_run': {'event': 'pull_request', 'actor': {'login': 'Railsimulatornet'},
                  'head_sha': HEAD, 'head_repository': {'full_name': REPO},
                  'pull_requests': [{'number': 7}]}},
    }


GH_STUB = r'''
import base64, json, os, subprocess, sys
from pathlib import Path
p = Path(os.environ['PATCH_TEST_DIR'])
data = json.loads((p / 'fixture.json').read_text())
args = sys.argv[1:]
head = data.get('fixture_head', 'a' * 40)
base = data.get('fixture_base', 'b' * 40)
merged = data.get('fixture_merge', 'c' * 40)
with (p / 'calls.jsonl').open('a') as stream:
    stream.write(json.dumps(args) + '\n')
def count(name):
    file = p / name
    value = int(file.read_text()) + 1 if file.exists() else 1
    file.write_text(str(value))
    return value
if args[0] in ('workflow', 'label', 'pr'):
    raise SystemExit(0)
route = next(arg for arg in args if arg.startswith('repos/'))
if '-X' in args and args[args.index('-X') + 1] == 'PUT':
    (p / 'merged').touch()
    value = data.get('merge_result', {'merged': True, 'sha': merged})
elif '/git/ref/heads/master' in route:
    n = count('master_reads')
    value = {'object': {'sha': (data.get('postmerge_master', merged) if (p / 'merged').exists()
                                else data.get('final_master', base) if n > 1
                                else data.get('master', base))}}
elif '/git/ref/tags/' in route:
    tag = route.rsplit('/', 1)[1]
    value = {'object': {'type': 'commit', 'sha': data['tags'][tag]}}
elif '/contents/.github/workflows/codeql.yml?ref=' in route:
    content = data['after' if route.endswith(head) else 'before'].encode()
    value = {'encoding': 'base64', 'content': base64.b64encode(content).decode(), 'size': len(content)}
elif '/pulls?' in route:
    value = data['open_prs']
elif route.endswith('/pulls/7'):
    n = count('pr_reads')
    value = data.get('final_pr', data['pr']) if n >= 3 else data['pr']
elif '/compare/' in route:
    value = {'behind_by': data['behind_by'], 'ahead_by': 1}
elif '/labels' in route:
    value = data['labels']
elif '/files?' in route:
    number = route.split('/pulls/', 1)[1].split('/', 1)[0]
    value = data.get('files_by_number', {}).get(number, data['files'])
elif '/check-runs?' in route:
    value = data['checks']
elif '/actions/runs?' in route:
    value = data['runs']
elif route.endswith('/status') or '/status?' in route:
    value = data.get('legacy_status', {'sha': head, 'total_count': 0, 'statuses': [], 'state': 'pending'})
else:
    raise SystemExit('Unexpected offline route: ' + route)
if '--jq' in args:
    result = subprocess.run([os.environ['PATCH_TEST_JQ'], '-r', args[args.index('--jq') + 1]],
                            input=json.dumps(value), text=True, capture_output=True, check=True)
    print(result.stdout, end='')
else:
    print(json.dumps(value))
'''


def step_script(workflow, name):
    text = (ROOT / '.github/workflows' / workflow).read_text()
    marker = f'      - name: {name}\n'
    if text.count(marker) != 1:
        raise AssertionError('Expected exactly one actual workflow step')
    block = text.split(marker, 1)[1].split('        run: |\n', 1)[1]
    lines = []
    for line in block.split('\n'):
        if line and not line.startswith('          '):
            break
        lines.append(line[10:])
    return '\n'.join(lines)


def run_step(name, data, event_name='workflow_run', candidate_head=HEAD):
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder)
        stub = path / 'gh'
        stub.write_text('#!' + sys.executable + '\n' + GH_STUB)
        stub.chmod(0o755)
        (path / 'fixture.json').write_text(json.dumps(data))
        (path / 'event.json').write_text(json.dumps(data['event']))
        output = path / 'output'
        output.touch()
        env = {'PATH': str(path) + os.pathsep + '/usr/bin:/bin',
               'GITHUB_EVENT_NAME': event_name, 'GITHUB_EVENT_PATH': str(path / 'event.json'),
               'GITHUB_REPOSITORY': REPO, 'GITHUB_OUTPUT': str(output),
               'CANDIDATE_PR': '7', 'CANDIDATE_HEAD': candidate_head,
               'PATCH_TEST_DIR': str(path), 'PATCH_TEST_JQ': shutil.which('jq') or ''}
        metadata = data.get('metadata', RECORDED_METADATA)
        env.update(PR_NUMBER='7', ECOSYSTEM=metadata['package_ecosystem'],
                   UPDATE_TYPE=metadata['update_type'])
        if not env['PATCH_TEST_JQ']:
            raise AssertionError('The actual workflow requires jq')
        result = subprocess.run(['/bin/bash', '-c', step_script('dependabot-automerge.yml', name)],
                                env=env, cwd=ROOT, capture_output=True, text=True, timeout=30)
        calls_file = path / 'calls.jsonl'
        calls = [json.loads(line) for line in calls_file.read_text().splitlines()] if calls_file.exists() else []
        return result, calls, dict(line.split('=', 1) for line in output.read_text().splitlines())


GATE = 'Merge eligible patch update after all required checks pass'
SELECT = 'Select a bounded set of open CodeQL candidates'


class ActualCodeqlClassification(unittest.TestCase):
    def test_recorded_metadata_marks_only_the_codeql_patch_candidate(self):
        result, calls, _ = run_step('Mark eligible patch update', fixture())
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(sum(call[:2] == ['label', 'create'] for call in calls), 1)
        adds = [call for call in calls if '--add-label' in call]
        self.assertEqual(len(adds), 1)
        self.assertEqual(adds[0][adds[0].index('--add-label') + 1], 'automerge:patch')
        self.assertEqual(sum('/pulls/7/files?per_page=100' in ' '.join(call) for call in calls), 1)
        self.assertFalse(any('-X' in call or call[0] == 'workflow' for call in calls))

    def test_classification_rejects_other_versions_files_and_unknown_ecosystems(self):
        cases = []
        for version in ('version-update:semver-minor', 'version-update:semver-major'):
            data = fixture(); data['metadata'] = {**RECORDED_METADATA, 'update_type': version}; cases.append(data)
        data = fixture(); data['metadata'] = {**RECORDED_METADATA, 'package_ecosystem': 'github-actions'}; cases.append(data)
        data = fixture(); data['files'][0]['filename'] = '.github/workflows/dockerhub.yml'; cases.append(data)
        data = fixture(); data['files'][0]['status'] = 'added'; cases.append(data)
        data = fixture(); data['files'].append({'filename': 'README.md', 'status': 'modified'}); cases.append(data)
        for index, data in enumerate(cases):
            with self.subTest(case=index):
                result, calls, _ = run_step('Mark eligible patch update', data)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertFalse(any('--add-label' in call or call[:2] == ['label', 'create'] for call in calls))
                self.assertEqual(sum('--remove-label' in call for call in calls), 1)


class CodeqlContentProof(unittest.TestCase):
    def test_aligned_patch_resolves_both_official_release_pins_once(self):
        requested = []
        def lookup(tag):
            requested.append(tag)
            return {'v4.39.3': OLD, 'v4.39.4': NEW}[tag]
        verifier.verify_workflow(BEFORE, AFTER, BODY, lookup)
        self.assertEqual(requested, ['v4.39.3', 'v4.39.4'])

    def test_non_patch_or_unrelated_workflow_edits_are_rejected(self):
        bad = [
            (AFTER, BODY.replace('4.39.4', '4.40.0')),
            (AFTER, BODY.replace('4.39.4', '5.0.0')),
            (AFTER, BODY.replace('4.39.4', '4.39.4-rc.1')),
            (AFTER, BODY.replace('4.39.3', '4.39')),
            (AFTER, ''),
            (AFTER.replace('contents: read', 'contents: write'), BODY),
            (AFTER.replace(NEW, OLD, 1), BODY),
            (AFTER.replace('/analyze@', '/upload-sarif@'), BODY),
            (AFTER + f'        uses: github/codeql-action/upload-sarif@{NEW}\n', BODY),
            (AFTER.replace('name: CodeQL\n', 'name: CodeQL\u2028'), BODY),
        ]
        for after, body in bad:
            with self.subTest(after=after, body=body), self.assertRaises(patch_policy.Rejected):
                verifier.verify_workflow(BEFORE, after, body,
                                         lambda tag: {'v4.39.3': OLD, 'v4.39.4': NEW}.get(tag, NEW))

    def test_both_official_tag_bindings_are_mandatory(self):
        for wrong in ('v4.39.3', 'v4.39.4'):
            with self.subTest(tag=wrong), self.assertRaises(patch_policy.Rejected):
                verifier.verify_workflow(BEFORE, AFTER, BODY,
                    lambda tag: 'f' * 40 if tag == wrong else {'v4.39.3': OLD, 'v4.39.4': NEW}[tag])

    def test_annotated_official_tag_resolution_is_bounded(self):
        calls = []
        def get(route):
            calls.append(route)
            return {'object': {'type': 'tag', 'sha': 'd' * 40}} if '/ref/' in route else {
                'object': {'type': 'commit', 'sha': NEW}}
        self.assertEqual(verifier.release_commit('v4.39.4', get), NEW)
        self.assertEqual(len(calls), 2)
        self.assertTrue(all(route.startswith('repos/github/codeql-action/git/') for route in calls))
        with self.assertRaises(patch_policy.Rejected):
            verifier.release_commit('v4.39.4', lambda route: {'object': {'type': 'tag', 'sha': 'd' * 40}})
        for tag in ('v4', 'v4.39', 'v4.39.4-rc.1'):
            with self.subTest(tag=tag), self.assertRaises(patch_policy.Rejected):
                verifier.release_commit(tag, get)


class ActualCodeqlGate(unittest.TestCase):
    def assert_blocked(self, data, **kwargs):
        result, calls, _ = run_step(GATE, data, **kwargs)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(any('-X' in call for call in calls), result.stdout)
        self.assertFalse(any(call[0] == 'workflow' for call in calls), result.stdout)

    def test_human_synchronized_bot_patch_and_scheduled_candidate_use_exact_nonpublishing_dispatch(self):
        workflow = (ROOT / '.github/workflows/dependabot-automerge.yml').read_text()
        job_if = workflow.split('  merge:\n', 1)[1].split('    runs-on:', 1)[0]
        self.assertNotIn('workflow_run.actor', job_if)
        for event in ('workflow_run', 'schedule'):
            data = fixture()
            if event == 'schedule':
                data['event'] = {}
            with self.subTest(event=event):
                result, calls, _ = run_step(GATE, data, event_name=event)
                self.assertEqual(result.returncode, 0, result.stderr)
                puts = [call for call in calls if '-X' in call]
                self.assertEqual(len(puts), 1, result.stdout)
                self.assertIn('sha=' + HEAD, puts[0])
                dispatches = [call for call in calls if call[0] == 'workflow']
                self.assertEqual(len(dispatches), 2)
                self.assertIn('publish=false', dispatches[0])
                self.assertTrue(all('expected_sha=' + MERGED in call for call in dispatches))

    def test_author_repository_head_and_base_are_required(self):
        cases = []
        for key, value in [('user', {'login': 'human'}), ('draft', True), ('state', 'closed')]:
            data = fixture(); data['pr'][key] = value; cases.append(data)
        data = fixture(); data['pr']['head']['repo']['full_name'] = 'elsewhere/repo'; cases.append(data)
        data = fixture(); data['pr']['head']['ref'] = 'feature/test'; cases.append(data)
        data = fixture(); data['event']['workflow_run']['head_sha'] = 'e' * 40; cases.append(data)
        data = fixture(); data['event']['workflow_run']['head_repository']['full_name'] = 'elsewhere/repo'; cases.append(data)
        data = fixture(); data['event']['workflow_run']['event'] = 'push'; cases.append(data)
        data = fixture(); data['master'] = 'e' * 40; cases.append(data)
        data = fixture(); data['behind_by'] = 1; cases.append(data)
        data = fixture(); data['labels'] = []; cases.append(data)
        for index, data in enumerate(cases):
            with self.subTest(case=index):
                self.assert_blocked(data)

    def test_required_checks_need_complete_exact_successful_app_evidence(self):
        cases = []
        for name in ('CodeQL', 'description'):
            data = fixture()
            data['checks']['check_runs'] = [check for check in data['checks']['check_runs'] if check['name'] != name]
            data['checks']['total_count'] -= 1
            cases.append(data)
        for change in ({'conclusion': 'neutral'}, {'conclusion': 'skipped'},
                       {'status': 'in_progress', 'conclusion': None}, {'app': {'id': 1}},
                       {'head_sha': 'e' * 40}):
            data = fixture()
            next(check for check in data['checks']['check_runs'] if check['name'] == 'CodeQL').update(change)
            cases.append(data)
        data = fixture(); data['checks']['total_count'] += 1; cases.append(data)
        data = fixture(); data['checks']['check_runs'][0]['app']['id'] = 57789; cases.append(data)
        data = fixture(); data['checks']['check_runs'].append({
            'name': 'compare-parsers', 'head_sha': HEAD, 'app': {'id': 15368},
            'status': 'completed', 'conclusion': 'failure'}); data['checks']['total_count'] += 1; cases.append(data)
        for index, data in enumerate(cases):
            with self.subTest(case=index):
                self.assert_blocked(data)

    def test_required_runs_need_complete_exact_success(self):
        cases = []
        for change in ({'head_sha': 'e' * 40}, {'event': 'push'}, {'conclusion': 'failure'},
                       {'status': 'in_progress', 'conclusion': None}):
            data = fixture(); data['runs']['workflow_runs'][0].update(change); cases.append(data)
        for index in (0, 1):
            data = fixture(); data['runs']['workflow_runs'].pop(index); data['runs']['total_count'] -= 1; cases.append(data)
        data = fixture(); data['runs']['total_count'] += 1; cases.append(data)
        for index, data in enumerate(cases):
            with self.subTest(case=index):
                self.assert_blocked(data)

    def test_legacy_status_collection_is_complete_and_bound_to_the_verified_head(self):
        cases = [{'sha': HEAD, 'total_count': 1, 'statuses': []},
                 {'sha': 'e' * 40, 'total_count': 0, 'statuses': []}]
        cases += [{'sha': HEAD, 'total_count': 1, 'statuses': [{'state': state}]}
                  for state in ('pending', 'failure', 'error')]
        for index, statuses in enumerate(cases):
            data = fixture(); data['legacy_status'] = statuses
            with self.subTest(case=index):
                self.assert_blocked(data)

    def test_content_identity_is_not_replaced_by_label_or_file_name(self):
        cases = []
        data = fixture(); data['after'] = AFTER.replace('contents: read', 'contents: write'); cases.append(data)
        data = fixture(); data['tags']['v4.39.3'] = 'f' * 40; cases.append(data)
        data = fixture(); data['files'].append({'filename': 'README.md', 'status': 'modified'}); cases.append(data)
        for index, data in enumerate(cases):
            with self.subTest(case=index):
                self.assert_blocked(data)

    def test_final_identity_and_master_races_block_merge(self):
        for field in ('author', 'head', 'base', 'master'):
            data = fixture(); data['final_pr'] = copy.deepcopy(data['pr'])
            if field == 'author':
                data['final_pr']['user']['login'] = 'human'
            elif field in ('head', 'base'):
                data['final_pr'][field]['sha'] = 'e' * 40
            else:
                data['final_master'] = 'e' * 40
            with self.subTest(field=field):
                self.assert_blocked(data)

    def test_unconfirmed_merge_or_advanced_master_never_dispatches(self):
        for key, value in (('merge_result', {'merged': False}), ('postmerge_master', 'e' * 40)):
            data = fixture(); data[key] = value
            with self.subTest(case=key):
                result, calls, _ = run_step(GATE, data)
                self.assertEqual(result.returncode, 1)
                self.assertFalse(any(call[0] == 'workflow' for call in calls))

    def test_schedule_never_substitutes_for_other_event_head_or_pip_actor(self):
        data = fixture(); data['event']['workflow_run']['head_sha'] = None
        self.assert_blocked(data)
        self.assert_blocked(fixture(), event_name='schedule', candidate_head='e' * 40)
        self.assert_blocked(fixture(), event_name='pull_request_target')
        for event in ('schedule', 'workflow_run'):
            data = fixture()
            data['files'] = [{'filename': 'requirements.txt', 'status': 'modified',
                              'additions': 1, 'deletions': 1, 'patch': 'offline fixture'}]
            with self.subTest(event=event):
                self.assert_blocked(data, event_name=event)


class BoundedDailySelection(unittest.TestCase):
    def test_only_open_bot_codeql_candidates_are_selected(self):
        data = fixture()
        for number, changed in enumerate(('human', 'draft', 'pip', 'other-file'), 8):
            pr = copy.deepcopy(data['pr']); pr['number'] = number
            if changed == 'human': pr['user']['login'] = 'human'
            if changed == 'draft': pr['draft'] = True
            if changed == 'pip': pr['head']['ref'] = 'dependabot/pip/test'
            data['open_prs'].append(pr)
        data['files_by_number'] = {'11': [{'filename': '.github/workflows/dockerhub.yml', 'status': 'modified'}]}
        result, calls, output = run_step(SELECT, data, event_name='schedule')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(output['matrix']), [{'number': 7, 'head': HEAD}])
        self.assertEqual(output['present'], 'true')
        self.assertEqual(sum('/pulls?' in ' '.join(call) for call in calls), 1)
        self.assertFalse(any('/check-runs?' in ' '.join(call) or '-X' in call for call in calls))

    def test_empty_truncated_or_excessive_candidate_sets_are_bounded(self):
        data = fixture(); data['open_prs'] = []
        result, _, output = run_step(SELECT, data, event_name='schedule')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(output, {'matrix': '[]', 'present': 'false'})
        for count in (6, 100):
            data = fixture(); data['open_prs'] = [copy.deepcopy(data['pr']) for _ in range(count)]
            for number, pr in enumerate(data['open_prs'], 1): pr['number'] = number
            with self.subTest(count=count):
                result, calls, output = run_step(SELECT, data, event_name='schedule')
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(len(calls), 1)
                self.assertEqual(output, {})


class ExactPostmergeCodeqlSource(unittest.TestCase):
    def test_actual_checkout_uses_the_pr_head_or_guarded_dispatch_sha(self):
        workflow = (ROOT / '.github/workflows/codeql.yml').read_text()
        checkout = workflow.split('      - name: Check out repository\n', 1)[1].split('      - name:', 1)[0]
        refs = [line for line in checkout.splitlines() if line.strip().startswith('ref:')]
        self.assertEqual(refs, ['          ref: ${{ github.event.pull_request.head.sha || github.sha }}'])
        self.assertIn('          persist-credentials: false', checkout)

    def test_dispatch_guard_accepts_only_expected_sha_or_existing_manual_default(self):
        script = step_script('codeql.yml', 'Verify requested source commit')
        for expected, actual, succeeds in ((MERGED, MERGED, True), ('', HEAD, True),
                                           (MERGED, HEAD, False), ('master', HEAD, False)):
            with self.subTest(expected=expected, actual=actual):
                result = subprocess.run(['/bin/bash', '-c', script],
                    env={'EXPECTED_SHA': expected, 'GITHUB_SHA': actual}, capture_output=True, timeout=5)
                self.assertEqual(result.returncode == 0, succeeds)


if __name__ == '__main__':
    unittest.main()
