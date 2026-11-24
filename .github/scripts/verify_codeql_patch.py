"""Read and verify only the existing CodeQL pins at immutable PR revisions."""
import argparse
import base64
import re
import subprocess

import patch_policy


REPOSITORY = 'Railsimulatornet/docker.new-easyepg'
WORKFLOW = '.github/workflows/codeql.yml'
SHA = r'[a-f0-9]{40}'


def api(route):
    result = subprocess.run(['gh', 'api', route], check=True, capture_output=True,
                            text=True, timeout=30)
    return patch_policy._json_object(result.stdout)


def release_commit(tag, get=api):
    if not re.fullmatch(r'v[0-9]+\.[0-9]+\.[0-9]+', tag):
        raise patch_policy.Rejected('An exact CodeQL release tag is required')
    obj = get('repos/github/codeql-action/git/ref/tags/' + tag).get('object')
    for _ in range(3):
        if not isinstance(obj, dict) or not re.fullmatch(SHA, str(obj.get('sha', ''))):
            raise patch_policy.Rejected('Invalid official CodeQL tag object')
        if obj.get('type') == 'commit':
            return obj['sha']
        if obj.get('type') != 'tag':
            break
        obj = get('repos/github/codeql-action/git/tags/' + obj['sha']).get('object')
    raise patch_policy.Rejected('Cannot resolve the official CodeQL release commit')


def verify_workflow(before, after, body, lookup):
    """Keep both existing analyses aligned; accept no other workflow edits."""
    action_sets = []
    for text in (before, after):
        pins = []
        for line in text.split('\n'):
            if 'github/codeql-action/' not in line:
                continue
            match = patch_policy.CODEQL.fullmatch(line.removesuffix('\r'))
            if not match:
                raise patch_policy.Rejected('Unrecognized CodeQL action reference')
            pins.append((match['action'], match['ref']))
        actions = [action for action, _ in pins]
        if (actions.count('init') != 1 or actions.count('analyze') != 1
                or actions.count('upload-sarif') > 1
                or len({ref for _, ref in pins}) != 1):
            raise patch_policy.Rejected('Existing CodeQL analysis pins must remain aligned')
        action_sets.append(actions)
    if action_sets[0] != action_sets[1]:
        raise patch_policy.Rejected('CodeQL action set changed')
    cache = {}

    def cached_lookup(tag):
        if tag not in cache:
            cache[tag] = lookup(tag)
        return cache[tag]

    patch_policy.verify_codeql({WORKFLOW: before}, {WORKFLOW: after}, body, cached_lookup)


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument('--repository', required=True)
    cli.add_argument('--base', required=True)
    cli.add_argument('--head', required=True)
    cli.add_argument('--pull-request', type=int, required=True)
    args = cli.parse_args()
    if (args.repository != REPOSITORY or args.pull_request < 1
            or not all(re.fullmatch(SHA, value) for value in (args.base, args.head))):
        raise patch_policy.Rejected('Invalid immutable repository or PR identity')
    pr = api(f'repos/{REPOSITORY}/pulls/{args.pull_request}')
    if (pr.get('state') != 'open' or pr.get('draft') is not False
            or pr.get('user', {}).get('login') != 'dependabot[bot]'
            or pr.get('base', {}).get('ref') != 'master'
            or pr.get('base', {}).get('sha') != args.base
            or pr.get('head', {}).get('sha') != args.head
            or pr.get('head', {}).get('repo', {}).get('full_name') != REPOSITORY
            or not pr.get('head', {}).get('ref', '').startswith('dependabot/')):
        raise patch_policy.Rejected('The current PR identity differs from the verified candidate')

    def read(ref):
        data = api(f'repos/{REPOSITORY}/contents/{WORKFLOW}?ref={ref}')
        if data.get('encoding') != 'base64' or data.get('size', 0) > 1024 * 1024:
            raise patch_policy.Rejected('Workflow content cannot be verified')
        return base64.b64decode(data['content']).decode('utf-8')

    verify_workflow(read(args.base), read(args.head), pr.get('body') or '', release_commit)
    print('Existing CodeQL pins match a verified stable patch release pair.')


if __name__ == '__main__':
    try:
        main()
    except (patch_policy.Rejected, subprocess.SubprocessError, ValueError, KeyError) as error:
        raise SystemExit(f'CodeQL patch verification blocked: {error}') from error
