#!/usr/bin/env python3
"""Deploy the freshly verified, committed snapshot through the existing Git target.

Creation is never retried. Success requires READY plus the production alias.
"""
import hashlib, json, os, sys, urllib.request, urllib.error
import re, subprocess
from pathlib import Path
from public_assets import collect_public_files
import http.client, socket, ssl, time
from urllib.parse import urlsplit

ROOT = os.path.dirname(os.path.abspath(__file__))
TOKEN = os.environ.get("VERCEL_TOKEN", "").strip()
TEAM = os.environ.get("VERCEL_TEAM_ID", "team_L6hpqgg8pEHznOzrnU66JuoW").strip()
PROJECT = os.environ.get("VERCEL_PROJECT", "eval-index").strip()
EXPECTED_PROJECT_ID = "prj_DPmR5Ill2tG5LRSnDDq2BB6hQcQf"
EXPECTED_PROJECT_NAME = "eval-index"


def req(url, data=None, headers=None, method=None):
    # File uploads are content-addressed and safe to repeat. Deployment creation
    # is not: after an uncertain response, inspect native state before retrying.
    parsed = urlsplit(url)
    effective_method = method or ("POST" if data is not None else "GET")
    safe_retry = effective_method == "GET" or (
        effective_method == "POST" and parsed.hostname == "api.vercel.com"
        and parsed.path == "/v2/files"
    )
    attempts = 4 if safe_retry else 1
    for attempt in range(attempts):
        r = urllib.request.Request(url, data=data, headers=headers or {}, method=method)
        try:
            with urllib.request.urlopen(r, timeout=60) as resp:
                return resp.status, resp.read()
        except urllib.error.HTTPError as e:
            body = e.read()
            if e.code not in (429, 500, 502, 503, 504) or attempt == attempts - 1:
                return e.code, body
            retry_after = e.headers.get("Retry-After", "")
            delay = min(60, max(1, int(retry_after))) if retry_after.isdigit() else 2 ** attempt
        except (urllib.error.URLError, TimeoutError, ConnectionError, http.client.RemoteDisconnected) as e:
            reason = e.reason if isinstance(e, urllib.error.URLError) else e
            transient = isinstance(reason, (TimeoutError, ConnectionError, socket.timeout, http.client.RemoteDisconnected))
            if isinstance(reason, ssl.SSLError) or not transient or attempt == attempts - 1:
                raise
            delay = 2 ** attempt
        time.sleep(delay)



EXPECTED_TEAM = "team_L6hpqgg8pEHznOzrnU66JuoW"
EXPECTED_ORG = "tekvisions"
EXPECTED_REF = "main"
EXPECTED_HOST = 'eval.kymatalabs.com'


def refuse(message):
    raise ValueError('REFUSING: ' + message)


def api(path, payload=None):
    st, body = req('https://api.vercel.com' + path + '?teamId=' + TEAM,
                   data=None if payload is None else json.dumps(payload).encode(),
                   headers={'Authorization': 'Bearer ' + TOKEN, 'Content-Type': 'application/json'},
                   method='GET' if payload is None else 'POST')
    if st >= 400:
        refuse('Vercel request failed (HTTP ' + str(st) + '); do not repeat creation blindly')
    value = json.loads(body)
    if not isinstance(value, dict): refuse('invalid API response')
    return value


def git(*args):
    return subprocess.check_output(['git', *args], cwd=ROOT, timeout=60)


def committed_snapshot():
    files = collect_public_files(ROOT)  # Fresh existing offline receipt and lifecycle.
    receipt = json.loads((Path(ROOT) / 'public.build').read_text())
    # Do not use GITHUB_SHA: this workflow can create and push a newer commit.
    sha = git('rev-parse', 'HEAD').decode().strip()
    if not re.fullmatch(r'[0-9a-f]{40}', sha): refuse('invalid HEAD')
    remote = git('remote', 'get-url', 'origin').decode().strip()
    expected = EXPECTED_ORG + '/' + EXPECTED_PROJECT_NAME
    if remote not in ('https://github.com/' + expected, 'https://github.com/' + expected + '.git',
                      'git@github.com:' + expected + '.git'):
        refuse('unexpected Git origin')
    for name, digest in receipt['sha256'].items():
        # Missing/untracked inputs, modified sources and uncommitted outputs all fail.
        content = git('show', sha + ':' + name)
        if hashlib.sha256(content).hexdigest() != digest:
            refuse('sealed file differs from committed snapshot: ' + name)
    from git_public_snapshot import verify_committed_publication
    verify_committed_publication(ROOT, sha, receipt)
    from public_output import EXPECTED_CONFIG
    if json.loads((Path(ROOT) / 'vercel.json').read_text()) != EXPECTED_CONFIG:
        refuse('Git build must use the closed public output configuration')
    # Configuration must be tracked even when an edited manifest omits it.
    if git('show', sha + ':vercel.json') != (Path(ROOT) / 'vercel.json').read_bytes():
        refuse('uncommitted Vercel configuration')
    remote_head = git('ls-remote', '--exit-code', 'origin', 'refs/heads/' + EXPECTED_REF).decode().split()
    if remote_head != [sha, 'refs/heads/' + EXPECTED_REF]:
        refuse('HEAD is not the current pushed main; rebuild from latest main')
    return sha


def matching_source(meta, sha=None):
    return (meta.get('githubOrg') == EXPECTED_ORG
            and meta.get('githubRepo') == EXPECTED_PROJECT_NAME
            and meta.get('githubCommitRef') == EXPECTED_REF
            and (sha is None or meta.get('githubCommitSha') == sha))


def _preflight_overwrite_guard():
    # No ALLOW_OVERWRITE route. All identities are mandatory and fail closed.
    if TEAM != EXPECTED_TEAM or PROJECT not in (EXPECTED_PROJECT_NAME, EXPECTED_PROJECT_ID):
        refuse('configured target differs from the verified team/project')
    project = api('/v9/projects/' + EXPECTED_PROJECT_ID)
    if (project.get('id') != EXPECTED_PROJECT_ID or project.get('name') != EXPECTED_PROJECT_NAME
            or project.get('accountId') != EXPECTED_TEAM or project.get('framework') is not None
            or project.get('rootDirectory') not in (None, '')):
        refuse('existing project identity/framework mismatch')
    production = (project.get('targets') or {}).get('production') or {}
    if not matching_source(production.get('meta') or {}):
        refuse('existing production is not this repository main')
    link = project.get('link')
    if link and (link.get('type') != 'github' or link.get('org') != EXPECTED_ORG
                 or link.get('repo') != EXPECTED_PROJECT_NAME):
        refuse('project Git link differs from expected source')


def wait_for_production(deployment_id, sha, timeout=900):
    if not re.fullmatch(r'dpl_[A-Za-z0-9]+', deployment_id): refuse('missing deployment identity')
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        d = api('/v13/deployments/' + deployment_id)
        if (d.get('id') != deployment_id or (d.get('projectId') or (d.get('project') or {}).get('id')) != EXPECTED_PROJECT_ID
                or d.get('target') != 'production' or not matching_source(d.get('meta') or {}, sha)):
            refuse('deployment identity/source mismatch')
        if d.get('readyState') in ('ERROR', 'CANCELED', 'BLOCKED') or d.get('aliasError'):
            refuse('deployment failed or alias assignment failed: ' + deployment_id)
        if d.get('readyState') == 'READY':
            alias = api('/v4/aliases/' + EXPECTED_HOST)
            if (alias.get('alias') == EXPECTED_HOST and alias.get('projectId') == EXPECTED_PROJECT_ID
                    and alias.get('deploymentId') == deployment_id):
                return d
        time.sleep(10)
    refuse('readiness/alias not verified before timeout; inspect ' + deployment_id + ' before any retry')


def main():
    if not TOKEN:
        print('VERCEL_TOKEN not set', file=sys.stderr)
        return 1
    try:
        sha = committed_snapshot()
        _preflight_overwrite_guard()
        # Configuration stays in version-controlled vercel.json. No files, settings
        # overrides, overwrite escape hatch, or stale deploymentId redeploy.
        d = api('/v13/deployments', {
            'name': EXPECTED_PROJECT_NAME, 'project': EXPECTED_PROJECT_ID, 'target': 'production',
            'gitSource': {'type': 'github', 'org': EXPECTED_ORG, 'repo': EXPECTED_PROJECT_NAME,
                          'ref': EXPECTED_REF, 'sha': sha}})
        deployment_id = d.get('id', '')
        print('Created deployment ' + deployment_id + ' for ' + sha + '; waiting for production alias', flush=True)
        wait_for_production(deployment_id, sha)
        print('Verified READY production https://' + EXPECTED_HOST + ' at ' + sha)
        return 0  # Workflow may now invoke IndexNow.
    except (ValueError, OSError, subprocess.SubprocessError) as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
