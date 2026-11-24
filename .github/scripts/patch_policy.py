"""Verify immutable manifest contents before considering a patch merge.

Only the explicitly supported formats are automatic. Ambiguous versions,
source changes, dependency-set changes and extra edits require manual review.
"""
import base64
import json
import re
import urllib.error
import urllib.parse
import urllib.request


class Rejected(ValueError):
    pass


VERSION = r'(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)(?:\.(?:0|[1-9][0-9]*))?'
DEPENDENCY_GROUPS = ('dependencies', 'devDependencies', 'optionalDependencies', 'peerDependencies')
MAX_NPM_RELEASES = 20
REQUIREMENT = re.compile(r'(?P<name>[A-Za-z0-9][A-Za-z0-9_.-]*)==(?P<version>' + VERSION + r')')
FROM = re.compile(r'(?P<prefix>FROM [A-Za-z0-9][A-Za-z0-9._:/-]*:)'
                  r'(?P<version>' + VERSION + r')'
                  r'(?P<suffix>(?P<variant>-[A-Za-z0-9._-]+)?(?: AS [A-Za-z0-9_.-]+)?)')
DOCKER_VARIANTS = {None, '-slim', '-alpine'}
NPM_NAME = re.compile(r'(?:@[a-z0-9][a-z0-9._-]*/)?[a-z0-9][a-z0-9._-]*')
CODEQL = re.compile(r'(?P<prefix>[ \t]*uses:[ \t]*github/codeql-action/'
                    r'(?P<action>init|analyze|upload-sarif)@)'
                    r'(?P<ref>[0-9a-f]{40}|v' + VERSION + r')'
                    r'(?P<suffix>[ \t]*(?:#.*)?)')
REPORTED_CODEQL = re.compile(r'Updates `github/codeql-action(?:/(?:init|analyze|upload-sarif))?` '
                            r'from (' + VERSION + r') to (' + VERSION + r')(?![.A-Za-z0-9+-])')


def require_patch(before, after):
    if not isinstance(before, str) or not isinstance(after, str):
        raise Rejected('Version must be an exact stable release')
    if not re.fullmatch(VERSION, before) or not re.fullmatch(VERSION, after):
        raise Rejected('Ranges, prereleases and nonstandard versions require manual review')
    old = tuple(map(int, before.split('.'))) + (0,) * (3 - len(before.split('.')))
    new = tuple(map(int, after.split('.'))) + (0,) * (3 - len(after.split('.')))
    if old[:2] != new[:2] or new[2] <= old[2]:
        raise Rejected('Not a strictly increasing patch release')


def changed_lines(before, after):
    # Unicode separators and control characters are not physical file lines.
    # Preserve LF positions, the final newline, and every existing CRLF ending.
    if any('\r' in text.replace('\r\n', '') for text in (before, after)):
        raise Rejected('Unrecognized line endings require manual review')
    old, new = before.split('\n'), after.split('\n')
    if len(old) != len(new):
        raise Rejected('Added or removed lines require manual review')
    if any(a.endswith('\r') != b.endswith('\r') for a, b in zip(old, new)):
        raise Rejected('Line endings changed')
    changed = [(a.removesuffix('\r'), b.removesuffix('\r'))
               for a, b in zip(old, new) if a != b]
    if not changed:
        raise Rejected('No verifiable version change')
    return changed


def verify_pip(before, after):
    for old, new in changed_lines(before, after):
        a, b = REQUIREMENT.fullmatch(old), REQUIREMENT.fullmatch(new)
        if not a or not b or a['name'] != b['name']:
            raise Rejected('Only existing exact requirement pins may change')
        require_patch(a['version'], b['version'])


def verify_docker(before, after):
    for old, new in changed_lines(before, after):
        a, b = FROM.fullmatch(old), FROM.fullmatch(new)
        if not a or not b or a['prefix'] != b['prefix'] or a['suffix'] != b['suffix']:
            raise Rejected('Only the patch tag of the same literal image may change')
        if a['variant'] not in DOCKER_VARIANTS:
            raise Rejected('Unrecognized image variants require manual review')
        if any(version.count('.') != 2 for version in (a['version'], b['version'])):
            raise Rejected('Floating image tags do not prove a concrete patch version')
        require_patch(a['version'], b['version'])


def verify_codeql(before, after, body, tag_lookup):
    """Bind each changed action pin to both official stable release tags."""
    if not before or set(before) != set(after):
        raise Rejected('Workflow file set changed')
    reported = set(REPORTED_CODEQL.findall(body or ''))
    for path in before:
        for old, new in changed_lines(before[path], after[path]):
            a, b = CODEQL.fullmatch(old), CODEQL.fullmatch(new)
            if not a or not b or a['prefix'] != b['prefix'] or a['ref'] == b['ref']:
                raise Rejected('Workflow changed beyond an existing CodeQL pin')
            if a['ref'].startswith('v') and b['ref'].startswith('v'):
                old_version, new_version = a['ref'][1:], b['ref'][1:]
            elif not a['ref'].startswith('v') and not b['ref'].startswith('v') and len(reported) == 1:
                old_version, new_version = next(iter(reported))
            else:
                raise Rejected('Cannot independently identify the CodeQL release pair')
            if any(version.count('.') != 2 for version in (old_version, new_version)):
                raise Rejected('CodeQL aliases do not prove a concrete patch version')
            require_patch(old_version, new_version)
            expected_old, expected_new = tag_lookup('v' + old_version), tag_lookup('v' + new_version)
            if not all(isinstance(sha, str) and re.fullmatch(r'[a-f0-9]{40}', sha)
                       for sha in (expected_old, expected_new)):
                raise Rejected('Official CodeQL release references are not verifiable')
            if not a['ref'].startswith('v') and (a['ref'] != expected_old or b['ref'] != expected_new):
                raise Rejected('Changed pins do not match the official CodeQL releases')
            if b['suffix'] not in (a['suffix'], a['suffix'].replace('v' + old_version, 'v' + new_version, 1)):
                raise Rejected('Unrelated action comment changed')


def _unique_object(items):
    result = {}
    for key, value in items:
        if key in result:
            raise Rejected('Duplicate JSON keys are not verifiable')
        result[key] = value
    return result


def _json_object(text):
    try:
        value = json.loads(text, object_pairs_hook=_unique_object)
    except (json.JSONDecodeError, TypeError) as exc:
        raise Rejected('Invalid manifest JSON') from exc
    if not isinstance(value, dict):
        raise Rejected('Expected a manifest object')
    return value


def _dependency_changes(before, after):
    if not isinstance(before, dict) or not isinstance(after, dict) or before.keys() != after.keys():
        raise Rejected('Added or removed dependencies require manual review')
    changed = 0
    for name, version in before.items():
        if version != after[name]:
            require_patch(version, after[name])
            changed += 1
    return changed


def _manifest_changes(before, after):
    old, new = dict(before), dict(after)
    changed = 0
    for group in DEPENDENCY_GROUPS:
        if (group in old) != (group in new):
            raise Rejected('Dependency groups changed')
        changed += _dependency_changes(old.pop(group, {}), new.pop(group, {}))
    if old != new:
        raise Rejected('Non-dependency manifest fields changed')
    return changed


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise Rejected('Registry redirects require manual review')


def npm_release(name, version):
    """Read public registry data without sending a GitHub credential."""
    if not NPM_NAME.fullmatch(name) or not re.fullmatch(VERSION, version):
        raise Rejected('Unsupported npm package identity')
    url = 'https://registry.npmjs.org/' + urllib.parse.quote(name, safe='') + '/' + version
    request = urllib.request.Request(url, headers={'Accept': 'application/json'})
    with urllib.request.build_opener(_NoRedirect()).open(request, timeout=10) as response:
        raw = response.read(1024 * 1024 + 1)
    if len(raw) > 1024 * 1024:
        raise Rejected('Registry response exceeds the verification limit')
    return _json_object(raw)


def _registry_binding(name, entry, lookup):
    version = entry.get('version')
    if not isinstance(version, str) or not re.fullmatch(VERSION, version):
        raise Rejected('Unsupported locked npm version')
    expected = 'https://registry.npmjs.org/' + name + '/-/' + name.rsplit('/', 1)[-1] + '-' + version + '.tgz'
    integrity = entry.get('integrity', '')
    if not isinstance(integrity, str):
        raise Rejected('Invalid npm integrity value')
    try:
        digest = base64.b64decode(integrity.removeprefix('sha512-'), validate=True)
    except (ValueError, TypeError):
        raise Rejected('Invalid npm integrity value') from None
    if not integrity.startswith('sha512-') or len(digest) != 64 or entry.get('resolved') != expected:
        raise Rejected('Unverifiable npm tarball source or integrity')
    release = lookup(name, version)
    if not isinstance(release, dict) or not isinstance(release.get('dist'), dict):
        raise Rejected('Registry release metadata is not verifiable')
    if (release.get('name') != name or release.get('version') != version
            or release['dist'].get('tarball') != expected
            or release['dist'].get('integrity') != integrity):
        raise Rejected('Lockfile does not match the official registry release')


def _root_matches(manifest, packages):
    root = packages.get('')
    if not isinstance(root, dict):
        raise Rejected('Missing lockfile root')
    for group in DEPENDENCY_GROUPS:
        declared = manifest.get(group, {})
        if declared != root.get(group, {}):
            raise Rejected('Manifest and lockfile root disagree')
        for name, version in declared.items():
            if isinstance(version, str) and re.fullmatch(VERSION, version):
                if packages.get('node_modules/' + name, {}).get('version') != version:
                    raise Rejected('Exact declared dependency differs from its installed lock entry')


def verify_npm(before, after, lookup=npm_release):
    required = {'package.json', 'package-lock.json'}
    if set(before) != required or set(after) != required:
        raise Rejected('Only package.json with a version-3 package-lock is supported')
    old_manifest, new_manifest = _json_object(before['package.json']), _json_object(after['package.json'])
    _manifest_changes(old_manifest, new_manifest)
    old, new = _json_object(before['package-lock.json']), _json_object(after['package-lock.json'])
    if old.get('lockfileVersion') != 3 or new.get('lockfileVersion') != 3:
        raise Rejected('Unsupported lockfile format')
    a, b = old.pop('packages', None), new.pop('packages', None)
    if old != new or not isinstance(a, dict) or not isinstance(b, dict) or a.keys() != b.keys():
        raise Rejected('Lockfile structure or dependency set changed')
    _root_matches(old_manifest, a)
    _root_matches(new_manifest, b)
    _manifest_changes(a[''], b[''])
    releases = []
    for path in a:
        if path == '' or a[path] == b[path]:
            continue
        if not path.startswith('node_modules/') or not isinstance(a[path], dict) or not isinstance(b[path], dict):
            raise Rejected('Unsupported locked dependency location')
        name = path.split('node_modules/')[-1]
        if not NPM_NAME.fullmatch(name):
            raise Rejected('Unsupported locked package name')
        if a[path].get('name', name) != name or b[path].get('name', name) != name:
            raise Rejected('Package aliases require manual review')
        require_patch(a[path].get('version'), b[path].get('version'))
        allowed = {'version', 'resolved', 'integrity'}
        if ({k: v for k, v in a[path].items() if k not in allowed}
                != {k: v for k, v in b[path].items() if k not in allowed}):
            raise Rejected('Locked dependency metadata changed beyond its release identity')
        releases.extend(((name, a[path]), (name, b[path])))
    if not releases:
        raise Rejected('No locked patch upgrade found')
    if len({(name, entry['version']) for name, entry in releases}) > MAX_NPM_RELEASES:
        raise Rejected('Large dependency groups require manual review')
    cache = {}

    def cached_release(name, version):
        key = (name, version)
        if key not in cache:
            cache[key] = lookup(name, version)
        return cache[key]

    for name, entry in releases:
        _registry_binding(name, entry, cached_release)


def verify(family, before, after, lookup=npm_release):
    if not before or set(before) != set(after):
        raise Rejected('Manifest file set changed')
    if family == 'npm':
        return verify_npm(before, after, lookup)
    if family not in ('pip', 'docker'):
        raise Rejected('Unsupported dependency family')
    for path in before:
        if family == 'pip':
            if not re.fullmatch(r'(?:[^/]+/)*requirements(?:-[A-Za-z0-9_-]+)?\.txt', path):
                raise Rejected('Only exact requirements files are supported')
            verify_pip(before[path], after[path])
        else:
            verify_docker(before[path], after[path])


def main():
    """Read exact GitHub revisions for the trusted EasyEPG workflow."""
    import argparse
    import subprocess

    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument('--repository', required=True)
    cli.add_argument('--base', required=True)
    cli.add_argument('--head', required=True)
    args = cli.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', args.repository):
        raise Rejected('Invalid repository identity')
    if not all(re.fullmatch(r'[a-f0-9]{40}', ref) for ref in (args.base, args.head)):
        raise Rejected('Immutable commit references are required')

    def read(ref):
        route = f'repos/{args.repository}/contents/requirements.txt?ref={ref}'
        result = subprocess.run(['gh', 'api', route], check=True, capture_output=True,
                                text=True, timeout=30)
        data = _json_object(result.stdout)
        if data.get('encoding') != 'base64' or data.get('size', 0) > 1024 * 1024:
            raise Rejected('Manifest content cannot be verified')
        return base64.b64decode(data['content']).decode('utf-8')

    verify('pip', {'requirements.txt': read(args.base)}, {'requirements.txt': read(args.head)})
    print('Exact manifest contents contain only verified patch upgrades.')


if __name__ == '__main__':
    try:
        main()
    except (Rejected, RuntimeError, ValueError) as error:
        raise SystemExit(f'Patch verification blocked: {error}') from error
