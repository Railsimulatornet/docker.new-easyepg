"""Exercise the real pip gate offline; simulated PUTs are never real merges."""
import copy
import unittest

from test_dependabot_automerge_codeql import fixture, run_step, GATE, HEAD, MERGED


def pip_fixture(after='demo==1.2.4\n'):
    data = fixture()
    data['final_pr_after'] = 2
    data['before'] = 'demo==1.2.3\n'
    data['after'] = after
    data['files'] = [{'filename': 'requirements.txt', 'status': 'modified',
                      'additions': 1, 'deletions': 1,
                      'patch': '@@ -1 +1 @@\n-demo==1.2.3\n+demo==1.2.4'}]
    data['pr']['head']['ref'] = 'dependabot/pip/update'
    data['checks']['check_runs'].append({'name': 'compare-parsers', 'head_sha': HEAD,
        'app': {'id': 15368}, 'status': 'completed', 'conclusion': 'success'})
    data['checks']['total_count'] += 1
    data['runs']['workflow_runs'].append({'name': 'EasyEPG XML and JSON compatibility',
        'head_sha': HEAD, 'event': 'pull_request', 'status': 'completed', 'conclusion': 'success'})
    data['runs']['total_count'] += 1
    data['event']['workflow_run']['actor']['login'] = 'dependabot[bot]'
    return data


class ActualMergeStep(unittest.TestCase):
    def reject(self, data):
        result, calls, _ = run_step(GATE, data)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(any('-X' in call for call in calls), result.stdout)
        self.assertFalse(any(call[0] == 'workflow' for call in calls), result.stdout)

    def test_exact_patch_reaches_only_the_simulated_merge(self):
        result, calls, _ = run_step(GATE, pip_fixture())
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(sum('-X' in call and call[call.index('-X') + 1] == 'PUT' for call in calls), 1)
        dispatches = [call for call in calls if call[0] == 'workflow']
        self.assertEqual(len(dispatches), 2)
        self.assertIn('publish=true', dispatches[0])
        self.assertTrue(all('expected_sha=' + MERGED in call for call in dispatches))

    def test_label_or_diff_cannot_override_actual_contents(self):
        for after in ['demo==1.3.0\n', 'demo==2.0.0\n', 'demo==1.2.4rc1\n',
                      'demo>=1.2.4\n', 'other==1.2.4\n', 'demo==1.2.4\nextra==1.0.0\n']:
            with self.subTest(after=after):
                self.reject(pip_fixture(after))

    def test_partial_or_mismatched_checks_cannot_authorize_pip_merge(self):
        for change in ('partial', 'wrong_head', 'wrong_app'):
            data = pip_fixture()
            if change == 'partial': data['checks']['total_count'] += 1
            if change == 'wrong_head': data['checks']['check_runs'][0]['head_sha'] = 'e' * 40
            if change == 'wrong_app': data['checks']['check_runs'][0]['app']['id'] = 1
            with self.subTest(change=change): self.reject(data)

    def test_partial_or_mismatched_workflow_evidence_cannot_authorize_pip_merge(self):
        for change in ('partial', 'wrong_head', 'wrong_event'):
            data = pip_fixture()
            if change == 'partial': data['runs']['total_count'] += 1
            if change == 'wrong_head': data['runs']['workflow_runs'][0]['head_sha'] = 'e' * 40
            if change == 'wrong_event': data['runs']['workflow_runs'][0]['event'] = 'push'
            with self.subTest(change=change): self.reject(data)

    def test_neutral_skipped_or_missing_required_checks_block(self):
        for name in ('CodeQL', 'compare-parsers', 'description', 'assemble'):
            for conclusion in ('neutral', 'skipped', 'failure'):
                data = pip_fixture()
                next(check for check in data['checks']['check_runs'] if check['name'] == name)['conclusion'] = conclusion
                with self.subTest(name=name, conclusion=conclusion): self.reject(data)
            data = pip_fixture()
            data['checks']['check_runs'] = [check for check in data['checks']['check_runs'] if check['name'] != name]
            data['checks']['total_count'] -= 1
            with self.subTest(name=name, conclusion='missing'): self.reject(data)

    def test_legacy_statuses_must_be_complete_successful_and_bound(self):
        variants = [{'sha': HEAD, 'total_count': 31, 'statuses': [{'state': 'success'}] * 30},
                    {'sha': 'e' * 40, 'total_count': 0, 'statuses': []},
                    {'sha': HEAD, 'total_count': 1, 'statuses': [{'state': 'failure'}]}]
        for index, status in enumerate(variants):
            data = pip_fixture(); data['legacy_status'] = status
            with self.subTest(case=index): self.reject(data)

    def test_pr_identity_is_revalidated_before_merge(self):
        for path, value in (('state', 'closed'), ('user', {'login': 'someone'}), ('draft', True)):
            data = pip_fixture()
            data['final_pr'] = copy.deepcopy(data['pr'])
            data['final_pr'][path] = value
            with self.subTest(field=path): self.reject(data)

    def test_postmerge_main_advance_stops_both_dispatches(self):
        data = pip_fixture(); data['postmerge_master'] = 'e' * 40
        result, calls, _ = run_step(GATE, data)
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertFalse(any(call[0] == 'workflow' for call in calls))


if __name__ == '__main__':
    unittest.main()

