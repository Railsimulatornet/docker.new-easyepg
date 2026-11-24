import base64
import copy
import json
import unittest
from unittest.mock import patch

import patch_policy as p


def release(name, version):
    return {'name': name, 'version': version, 'dist': {
        'tarball': f'https://registry.npmjs.org/{name}/-/{name.rsplit("/", 1)[-1]}-{version}.tgz',
        'integrity': 'sha512-' + base64.b64encode((version.encode() * 64)[:64]).decode(),
    }}


def entry(name, version):
    dist = release(name, version)['dist']
    return {'version': version, 'resolved': dist['tarball'], 'integrity': dist['integrity'], 'license': 'MIT'}


def npm_case():
    manifest = {'name': 'app', 'version': '1.0.0', 'scripts': {'test': 'node test.js'},
                'dependencies': {'demo': '1.2.3'}}
    lock = {'name': 'app', 'version': '1.0.0', 'lockfileVersion': 3, 'requires': True,
            'packages': {'': {'name': 'app', 'version': '1.0.0', 'dependencies': {'demo': '1.2.3'}},
                         'node_modules/demo': entry('demo', '1.2.3'),
                         'node_modules/nested': entry('nested', '4.5.6')}}
    old = {'package.json': manifest, 'package-lock.json': lock}
    new = copy.deepcopy(old)
    new['package.json']['dependencies']['demo'] = '1.2.4'
    new['package-lock.json']['packages']['']['dependencies']['demo'] = '1.2.4'
    new['package-lock.json']['packages']['node_modules/demo'] = entry('demo', '1.2.4')
    return old, new


def verify_npm(old, new, lookup=release):
    p.verify('npm', {k: json.dumps(v) for k, v in old.items()},
             {k: json.dumps(v) for k, v in new.items()}, lookup)


class StableVersions(unittest.TestCase):
    def test_patch_and_two_component_baseline(self):
        for old, new in [('1.2.3', '1.2.4'), ('4.1', '4.1.2'), ('2.9.8', '2.9.11')]:
            with self.subTest(old=old, new=new):
                p.require_patch(old, new)

    def test_unproven_or_nonpatch_versions_rejected(self):
        for old, new in [('1.2.3', '2.0.0'), ('1.2.3', '1.3.0'), ('1.2.3', '1.2.3'),
                         ('1.2.3', '1.2.2'), ('1.2.3', '1.2.4rc1'), ('1.2.3', '1.2.4.post1'),
                         ('1.2.3', '^1.2.4'), ('1.2.3', '01.2.4'), ('1.2.3', '1.2.4+build'),
                         ('1', '1.0.1'), ('1.2.3', 4), ('1.2.3', '>=1.2.4,<2')]:
            with self.subTest(old=old, new=new), self.assertRaises(p.Rejected):
                p.require_patch(old, new)


class PipContents(unittest.TestCase):
    def test_existing_exact_patches_pass(self):
        p.verify_pip('# packages\na==1.2.3\nb==4.1\n', '# packages\na==1.2.4\nb==4.1.2\n')

    def test_major_minor_range_or_extra_changes_rejected(self):
        before = '# packages\na==1.2.3\n'
        for after in ['# packages\na==1.3.0\n', '# packages\na==2.0.0\n',
                      '# packages\na>=1.2.4\n', '# packages\na @ https://example.invalid/a.whl\n',
                      '# packages\nb==1.2.4\n', '# packages\na==1.2.4\nb==1.0.0\n',
                      '# changed\na==1.2.4\n', '# packages\na==1.2.4; python_version>="3.12"\n',
                      '# packages\na==1.2.4 --hash=sha256:value\n', '# packages\na==1.2.4rc1\n',
                      '# packages\n', before]:
            with self.subTest(after=after), self.assertRaises(p.Rejected):
                p.verify_pip(before, after)

    def test_manifest_file_changes_fail_closed(self):
        with self.assertRaises(p.Rejected):
            p.verify('pip', {'requirements.txt': 'a==1.2.3'}, {'other.txt': 'a==1.2.4'})
        with self.assertRaises(p.Rejected):
            p.verify('pip', {'pyproject.toml': 'a==1.2.3'}, {'pyproject.toml': 'a==1.2.4'})


class DockerContents(unittest.TestCase):
    def test_same_image_variant_and_stage_patch_passes(self):
        p.verify_docker('FROM python:3.12.9-slim AS base\nRUN true\n',
                        'FROM python:3.12.10-slim AS base\nRUN true\n')

    def test_changed_source_digest_or_instructions_rejected(self):
        before = 'FROM python:3.12.9-slim\nRUN true\n'
        for after in ['FROM python:3.13.0-slim\nRUN true\n',
                      'FROM other/python:3.12.10-slim\nRUN true\n',
                      'FROM python:3.12.10-alpine\nRUN true\n',
                      'FROM python:3.12.10-slim@sha256:' + 'a' * 64 + '\nRUN true\n',
                      'FROM python:3.12.10-slim\nRUN false\n',
                      'FROM python:3.12.10-slim\nRUN true\nRUN echo changed\n',
                      'FROM ${BASE_IMAGE}\nRUN true\n']:
            with self.subTest(after=after), self.assertRaises(p.Rejected):
                p.verify_docker(before, after)

    def test_unknown_or_prerelease_variants_rejected(self):
        for variant in ['rc.1', 'preview', 'canary', 'unknown', 'slim-rc1']:
            with self.subTest(variant=variant), self.assertRaises(p.Rejected):
                p.verify_docker(f'FROM node:24.0.0-{variant}\n', f'FROM node:24.0.1-{variant}\n')
        p.verify_docker('FROM python:3.14.0-alpine\n', 'FROM python:3.14.1-alpine\n')

    def test_floating_minor_tag_cannot_be_assumed_to_mean_patch_zero(self):
        with self.assertRaises(p.Rejected):
            p.verify_docker('FROM python:3.12-slim\n', 'FROM python:3.12.1-slim\n')


class PhysicalLines(unittest.TestCase):
    def check(self, family, before, after):
        if family == 'codeql':
            tags = {'v4.38.1': 'a' * 40, 'v4.38.2': 'b' * 40}
            return p.verify_codeql({'workflow.yml': before}, {'workflow.yml': after}, '', tags.__getitem__)
        return {'pip': p.verify_pip, 'docker': p.verify_docker}[family](before, after)

    def fixtures(self):
        return [('pip', 'a==1.2.3', 'a==1.2.4', 'b==4.5.6'),
                ('docker', 'FROM alpine:3.24.1', 'FROM alpine:3.24.2', 'RUN echo hardening'),
                ('codeql', '  uses: github/codeql-action/init@v4.38.1',
                 '  uses: github/codeql-action/init@v4.38.2', 'timeout-minutes: 5')]

    def test_consistent_existing_crlf_is_preserved(self):
        for family, old, new, retained in self.fixtures():
            with self.subTest(family=family):
                self.check(family, old + '\r\n# comment\r\n' + retained + '\r\n',
                           new + '\r\n# comment\r\n' + retained + '\r\n')

    def test_nonphysical_separators_cannot_hide_removed_instructions(self):
        for family, old, new, retained in self.fixtures():
            before = old + '\n# comment\n' + retained + '\n'
            for separator in ['\u2028', '\v', '\f']:
                after = new + '\n# comment' + separator + retained + '\n'
                with self.subTest(family=family, separator=repr(separator)), self.assertRaises(p.Rejected):
                    self.check(family, before, after)

    def test_line_ending_changes_are_rejected(self):
        for family, old, new, _ in self.fixtures():
            for ending in ['', '\r\n', '\r']:
                with self.subTest(family=family, ending=repr(ending)), self.assertRaises(p.Rejected):
                    self.check(family, old + '\n', new + ending)


class NpmContents(unittest.TestCase):
    def test_known_release_bound_direct_patch_passes(self):
        verify_npm(*npm_case())

    def test_transitive_patch_is_checked_and_allowed(self):
        old, new = npm_case()
        new['package-lock.json']['packages']['node_modules/nested'] = entry('nested', '4.5.7')
        verify_npm(old, new)

    def test_transitive_minor_or_major_rejected(self):
        for version in ['4.6.0', '5.0.0', '4.5.7-beta.1']:
            old, new = npm_case()
            new['package-lock.json']['packages']['node_modules/nested'] = entry('nested', version)
            with self.subTest(version=version), self.assertRaises(p.Rejected):
                verify_npm(old, new)

    def test_release_lookups_are_cached_and_bounded(self):
        old, new = npm_case()
        for data in (old, new):
            packages = data['package-lock.json']['packages']
            packages['node_modules/nested/node_modules/demo'] = copy.deepcopy(packages['node_modules/demo'])
        calls = []

        def lookup(name, version):
            calls.append((name, version))
            return release(name, version)

        verify_npm(old, new, lookup)
        self.assertEqual(calls, [('demo', '1.2.3'), ('demo', '1.2.4')])
        for number in range(p.MAX_NPM_RELEASES // 2):
            name = 'extra' + str(number)
            old['package-lock.json']['packages']['node_modules/' + name] = entry(name, '1.2.3')
            new['package-lock.json']['packages']['node_modules/' + name] = entry(name, '1.2.4')
        calls.clear()
        with self.assertRaises(p.Rejected):
            verify_npm(old, new, lookup)
        self.assertEqual(calls, [])

    def test_script_changes_rejected(self):
        old, new = npm_case()
        new['package.json']['scripts']['test'] = 'node changed.js'
        with self.assertRaises(p.Rejected):
            verify_npm(old, new)

    def test_added_or_removed_locked_dependencies_rejected(self):
        for remove in [False, True]:
            old, new = npm_case()
            if remove:
                new['package-lock.json']['packages'].pop('node_modules/nested')
            else:
                new['package-lock.json']['packages']['node_modules/extra'] = entry('extra', '1.0.0')
            with self.subTest(remove=remove), self.assertRaises(p.Rejected):
                verify_npm(old, new)

    def test_unrelated_lock_metadata_change_rejected(self):
        old, new = npm_case()
        new['package-lock.json']['packages']['node_modules/demo']['hasInstallScript'] = True
        with self.assertRaises(p.Rejected):
            verify_npm(old, new)

    def test_manifest_and_lock_must_agree(self):
        for target in ['manifest', 'root', 'installed']:
            old, new = npm_case()
            if target == 'manifest':
                new['package.json']['dependencies']['demo'] = '1.2.5'
            elif target == 'root':
                new['package-lock.json']['packages']['']['dependencies']['demo'] = '1.2.5'
            else:
                new['package-lock.json']['packages']['node_modules/demo']['version'] = '1.2.5'
            with self.subTest(target=target), self.assertRaises(p.Rejected):
                verify_npm(old, new)

    def test_unverifiable_registry_metadata_rejected(self):
        for field, value in [('resolved', 'https://example.invalid/demo.tgz'),
                             ('integrity', 'sha512-' + base64.b64encode(b'x' * 64).decode()),
                             ('integrity', 'sha512-invalid'), ('integrity', None)]:
            old, new = npm_case()
            new['package-lock.json']['packages']['node_modules/demo'][field] = value
            with self.subTest(field=field, value=value), self.assertRaises(p.Rejected):
                verify_npm(old, new)

    def test_same_version_with_new_integrity_rejected(self):
        old, new = npm_case()
        new['package-lock.json']['packages']['node_modules/nested']['integrity'] = entry('nested', '4.5.7')['integrity']
        with self.assertRaises(p.Rejected):
            verify_npm(old, new)

    def test_duplicate_keys_rejected(self):
        old, new = npm_case()
        encoded_old = {k: json.dumps(v) for k, v in old.items()}
        encoded_new = {k: json.dumps(v) for k, v in new.items()}
        encoded_new['package.json'] = encoded_new['package.json'].replace('"version":', '"version":"9.9.9", "version":', 1)
        with self.assertRaises(p.Rejected):
            p.verify('npm', encoded_old, encoded_new, release)

    def test_registry_release_identity_must_match(self):
        def wrong(name, version):
            return {**release(name, version), 'name': 'another-package'}
        with self.assertRaises(p.Rejected):
            verify_npm(*npm_case(), lookup=wrong)

    def test_alternate_lockfile_or_range_changes_rejected(self):
        old, new = npm_case()
        new['package.json']['dependencies']['demo'] = '^1.2.4'
        with self.assertRaises(p.Rejected):
            verify_npm(old, new)
        old, new = npm_case()
        old['package-lock.json']['lockfileVersion'] = 2
        new['package-lock.json']['lockfileVersion'] = 2
        with self.assertRaises(p.Rejected):
            verify_npm(old, new)


class RegistryBoundary(unittest.TestCase):
    def test_public_lookup_omits_credentials_and_rejects_redirect(self):
        payload = json.dumps(release('demo', '1.2.4')).encode()
        with patch.dict('os.environ', {'GH_TOKEN': 'never-forward'}), patch.object(p.urllib.request, 'build_opener') as make:
            make.return_value.open.return_value.__enter__.return_value.read.return_value = payload
            p.npm_release('demo', '1.2.4')
            request = make.return_value.open.call_args.args[0]
            self.assertEqual(request.full_url, 'https://registry.npmjs.org/demo/1.2.4')
            self.assertIsNone(request.get_header('Authorization'))
        with self.assertRaises(p.Rejected):
            p._NoRedirect().redirect_request(None, None, 302, '', {}, 'https://example.invalid')


class CodeqlReleaseBinding(unittest.TestCase):
    def check(self, old_ref, new_ref, body='', old_prefix='  uses: ', new_prefix='  uses: '):
        old = {'workflow.yml': old_prefix + 'github/codeql-action/init@' + old_ref}
        new = {'workflow.yml': new_prefix + 'github/codeql-action/init@' + new_ref}
        tags = {'v4.38': 'a' * 40, 'v4.38.1': 'a' * 40, 'v4.38.2': 'b' * 40, 'v4.39.0': 'c' * 40}
        p.verify_codeql(old, new, body, tags.__getitem__)

    def test_explicit_tags_and_verified_sha_release_pair(self):
        self.check('v4.38.1', 'v4.38.2')
        self.check('a' * 40, 'b' * 40, 'Updates `github/codeql-action` from 4.38.1 to 4.38.2')

    def test_minor_alias_cannot_be_assumed_to_mean_patch_zero(self):
        with self.assertRaises(p.Rejected):
            self.check('a' * 40, 'b' * 40, 'Updates `github/codeql-action` from 4.38 to 4.38.2')
        with self.assertRaises(p.Rejected):
            self.check('v4.38', 'v4.38.2')

    def test_unverified_or_nonpatch_pin_changes_rejected(self):
        cases = [('a' * 40, 'b' * 40, ''),
                 ('a' * 40, 'c' * 40, 'Updates `github/codeql-action` from 4.38.1 to 4.38.2'),
                 ('a' * 40, 'c' * 40, 'Updates `github/codeql-action` from 4.38.1 to 4.39.0'),
                 ('v4.38.1', 'v4.39.0', ''),
                 ('a' * 40, 'b' * 40, 'Updates `github/codeql-action` from 4.38.1 to 4.38.2-beta.1')]
        for args in cases:
            with self.subTest(args=args), self.assertRaises(p.Rejected):
                self.check(*args)

    def test_indentation_change_rejected(self):
        with self.assertRaises(p.Rejected):
            self.check('v4.38.1', 'v4.38.2', new_prefix='    uses: ')


if __name__ == '__main__':
    unittest.main()
