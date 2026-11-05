import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from _public_fixture import make_sealed_fixture
import public_assets
import public_output

spec = importlib.util.spec_from_file_location('git_transport', Path(__file__).parents[1] / 'deploy.py')
d = importlib.util.module_from_spec(spec); spec.loader.exec_module(d)
SHA = 'b' * 40


def metadata(sha=SHA):
    return {'githubOrg': d.EXPECTED_ORG, 'githubRepo': d.EXPECTED_PROJECT_NAME,
            'githubCommitRef': 'main', 'githubCommitSha': sha}


def project():
    return {'id': d.EXPECTED_PROJECT_ID, 'name': d.EXPECTED_PROJECT_NAME,
            'accountId': d.EXPECTED_TEAM, 'framework': None,
            'targets': {'production': {'meta': metadata()}},
            'link': {'type': 'github', 'org': d.EXPECTED_ORG, 'repo': d.EXPECTED_PROJECT_NAME}}


def deployment(state='READY'):
    return {'id': 'dpl_test', 'projectId': d.EXPECTED_PROJECT_ID,
            'target': 'production', 'meta': metadata(), 'readyState': state}


def alias():
    return {'alias': d.EXPECTED_HOST, 'projectId': d.EXPECTED_PROJECT_ID, 'deploymentId': 'dpl_test'}


class GitTransportTests(unittest.TestCase):
    def test_existing_exact_git_target_is_permitted(self):
        with patch.object(d, 'api', return_value=project()): d._preflight_overwrite_guard()

    def test_override_cannot_bypass_identity(self):
        for key, value in [('id','prj_wrong'),('name','wrong'),('accountId','team_wrong'),('framework','nextjs'),('rootDirectory','other-app')]:
            p=project();p[key]=value
            with self.subTest(key=key), patch.dict(d.os.environ, {'ALLOW_OVERWRITE':'1'}), patch.object(d,'api',return_value=p):
                with self.assertRaises(ValueError): d._preflight_overwrite_guard()

    def test_wrong_team_and_project_rejected_before_api(self):
        for key in ['TEAM','PROJECT']:
            with patch.object(d,key,'wrong'),patch.object(d,'api') as api:
                with self.assertRaises(ValueError):d._preflight_overwrite_guard()
                api.assert_not_called()

    def test_wrong_or_missing_existing_source_rejected(self):
        for key in ['githubOrg','githubRepo','githubCommitRef']:
            p=project();p['targets']['production']['meta'][key]='wrong'
            with self.subTest(key=key),patch.object(d,'api',return_value=p):
                with self.assertRaises(ValueError):d._preflight_overwrite_guard()
        p=project();p['targets']={}
        with patch.object(d,'api',return_value=p):
            with self.assertRaises(ValueError):d._preflight_overwrite_guard()

    def test_wrong_git_link_rejected(self):
        p=project();p['link']['repo']='another-repo'
        with patch.object(d,'api',return_value=p):
            with self.assertRaises(ValueError):d._preflight_overwrite_guard()

    def test_ready_requires_exact_alias(self):
        a=alias();a['deploymentId']='dpl_old'
        with patch.object(d,'api',side_effect=[deployment('BUILDING'),deployment(),a,deployment(),alias()]),patch.object(d.time,'sleep') as sleep:
            d.wait_for_production('dpl_test',SHA)
            self.assertEqual(sleep.call_count,2)

    def test_ready_wrong_commit_fails(self):
        p=deployment();p['meta']['githubCommitSha']='c'*40
        with patch.object(d,'api',return_value=p):
            with self.assertRaises(ValueError):d.wait_for_production('dpl_test',SHA)

    def test_failed_and_canceled_are_failure(self):
        for state in ['ERROR','CANCELED','BLOCKED']:
            with patch.object(d,'api',return_value=deployment(state)):
                with self.assertRaises(ValueError):d.wait_for_production('dpl_test',SHA)

    def test_timeout_is_failure(self):
        with patch.object(d.time,'monotonic',side_effect=[0,2]),patch.object(d,'api') as api:
            with self.assertRaises(ValueError):d.wait_for_production('dpl_test',SHA,timeout=1)
            api.assert_not_called()

    def test_success_payload_contains_only_pinned_git_source(self):
        with patch.object(d,'TOKEN','fixture'),patch.object(d,'committed_snapshot',return_value=SHA),patch.object(d,'_preflight_overwrite_guard'),patch.object(d,'api',return_value={'id':'dpl_test'}) as api,patch.object(d,'wait_for_production') as wait:
            self.assertEqual(d.main(),0)
            api.assert_called_once_with('/v13/deployments',{'name':d.EXPECTED_PROJECT_NAME,'project':d.EXPECTED_PROJECT_ID,'target':'production','gitSource':{'type':'github','org':'tekvisions','repo':d.EXPECTED_PROJECT_NAME,'ref':'main','sha':SHA}})
            wait.assert_called_once_with('dpl_test',SHA)

    def test_stale_local_receipt_never_calls_api(self):
        with patch.object(d,'TOKEN','fixture'),patch.object(d,'committed_snapshot',side_effect=ValueError('stale receipt')),patch.object(d,'api') as api:
            self.assertEqual(d.main(),1);api.assert_not_called()

    def test_creation_error_or_readiness_error_prevents_success(self):
        with patch.object(d,'TOKEN','fixture'),patch.object(d,'committed_snapshot',return_value=SHA),patch.object(d,'_preflight_overwrite_guard'),patch.object(d,'api',return_value={'id':'dpl_test'}),patch.object(d,'wait_for_production',side_effect=ValueError('not ready')):
            self.assertEqual(d.main(),1)

    def test_manifest_output_excludes_private_source_and_config(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);make_sealed_fixture(root)
            (root/'vercel.json').write_text(json.dumps(public_output.EXPECTED_CONFIG))
            (root/'private.json').write_text('private')
            (root/'helper.py').write_text('# tooling')
            self.assertEqual(public_output.build(root),['index.html'])
            self.assertEqual(list((root/'public-output').iterdir()),[root/'public-output/index.html'])
            with self.assertRaises(FileExistsError):public_output.build(root)

    def test_bad_config_and_symlink_fail(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);make_sealed_fixture(root)
            (root/'vercel.json').write_text('{}')
            with self.assertRaises(ValueError):public_output.build(root)
            (root/'vercel.json').write_text(json.dumps(public_output.EXPECTED_CONFIG))
            (root/'index.html').unlink();(root/'index.html').symlink_to(root/'sitemap.xml')
            with self.assertRaises(ValueError):public_output.build(root)

    def test_committed_snapshot_uses_real_head_not_github_sha(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);make_sealed_fixture(root)
            (root/'vercel.json').write_text(json.dumps(public_output.EXPECTED_CONFIG))
            def git(*a):return subprocess.check_output(['git',*a],cwd=root,stderr=subprocess.DEVNULL)
            git('init','-q');git('config','user.email','fixture@example.invalid');git('config','user.name','Fixture')
            git('add','index.html','sitemap.xml','public.assets','url.lifecycle','vercel.json');git('commit','-qm','fixture')
            git('remote','add','origin','https://github.com/tekvisions/'+d.EXPECTED_PROJECT_NAME+'.git')
            sha=git('rev-parse','HEAD').decode().strip();public_assets.seal(root)
            def guarded(*args):
                if args[0]=='ls-remote':return (sha+'\trefs/heads/main\n').encode()
                return git(*args)
            with patch.object(d,'ROOT',folder),patch.object(d,'git',side_effect=guarded),patch.dict(d.os.environ,{'GITHUB_SHA':'a'*40}):
                self.assertEqual(d.committed_snapshot(),sha)
                (root/'index.html').write_text('changed');public_assets.seal(root)
                with self.assertRaises(ValueError):d.committed_snapshot()
            (root/'index.html').write_text('public fixture');public_assets.seal(root)
            def stale(*args):
                if args[0]=='ls-remote':return (('c'*40)+'\trefs/heads/main\n').encode()
                return git(*args)
            with patch.object(d,'ROOT',folder),patch.object(d,'git',side_effect=stale):
                with self.assertRaises(ValueError):d.committed_snapshot()

class CommittedPublicationRegressionTests(unittest.TestCase):
    def setUp(self):
        import git_public_snapshot
        self.snapshot = git_public_snapshot
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        make_sealed_fixture(self.root)
        (self.root / 'vercel.json').write_text(json.dumps(public_output.EXPECTED_CONFIG))
        rules = json.loads((self.root / 'public.assets').read_text())
        rules['legacy_source_paths'] = ['p/removed-entity/index.html']
        (self.root / 'public.assets').write_text(json.dumps(rules))
        self.legacy = self.root / 'p/removed-entity/index.html'
        self.legacy.parent.mkdir(parents=True)
        self.legacy.write_text('previously tracked legacy route')
        (self.root / 'helper.py').write_text('# private build input\n')
        self.git('init', '-q')
        self.git('config', 'user.email', 'fixture@example.invalid')
        self.git('config', 'user.name', 'Fixture')
        self.git('add', '--', 'index.html', 'sitemap.xml', 'public.assets', 'url.lifecycle',
                 'vercel.json', 'helper.py', 'p/removed-entity/index.html')
        self.git('commit', '-qm', 'baseline')
        self.git('remote', 'add', 'origin', 'https://github.com/tekvisions/' + d.EXPECTED_PROJECT_NAME + '.git')
        public_assets.seal(self.root)

    def git(self, *args):
        return subprocess.check_output(['git', *args], cwd=self.root, stderr=subprocess.DEVNULL)

    def verify(self):
        return self.snapshot.verify_committed_publication(self.root, self.git('rev-parse', 'HEAD').decode().strip(),
                                                          json.loads((self.root / 'public.build').read_text()))

    def guarded_git(self, *args):
        if args[0] == 'ls-remote':
            return self.git('rev-parse', 'HEAD').strip() + b'\trefs/heads/main\n'
        return self.git(*args)

    def test_exact_omitted_legacy_reproducer_fails_before_api(self):
        self.legacy.unlink()
        public_assets.seal(self.root)
        self.assertEqual(public_assets.collect_public_files(self.root), ['index.html'])
        self.git('add', '--', *public_assets.collect_public_files(self.root))
        self.assertIn(' D p/removed-entity/index.html', self.git('status', '--short').decode())
        # Demonstrate that the committed checkout really would emit an extra page.
        with self.snapshot.committed_tree(self.root, 'HEAD') as checkout:
            actual = public_output.build(checkout)
            self.assertEqual(actual, ['index.html', 'p/removed-entity/index.html'])
        with self.assertRaisesRegex(ValueError, 'publication set differs'):
            self.verify()
        with patch.object(d, 'ROOT', str(self.root)), patch.object(d, 'TOKEN', 'fixture'), patch.object(d, 'git', side_effect=self.guarded_git), patch.object(d, 'api') as api:
            self.assertEqual(d.main(), 1)
            api.assert_not_called()

    def test_staged_but_uncommitted_deletion_fails(self):
        self.legacy.unlink(); public_assets.seal(self.root)
        self.snapshot.stage_public_snapshot(self.root)
        self.assertIn('D  p/removed-entity/index.html', self.git('status', '--short').decode())
        with self.assertRaisesRegex(ValueError, 'publication set differs'): self.verify()

    def test_explicitly_committed_public_deletion_passes(self):
        self.legacy.unlink(); public_assets.seal(self.root)
        staged = self.snapshot.stage_public_snapshot(self.root)
        self.assertEqual(staged, ['index.html', 'p/removed-entity/index.html'])
        self.assertEqual(self.git('diff', '--cached', '--name-only').decode().splitlines(), ['p/removed-entity/index.html'])
        self.git('commit', '-qm', 'reviewed removal')
        self.verify()
        with patch.object(d, 'ROOT', str(self.root)), patch.object(d, 'git', side_effect=self.guarded_git):
            self.assertEqual(d.committed_snapshot(), self.git('rev-parse', 'HEAD').decode().strip())
        with self.snapshot.committed_tree(self.root, 'HEAD') as checkout:
            self.assertEqual(public_output.build(checkout), ['index.html'])

    def test_deleted_private_build_input_fails_and_is_never_staged(self):
        (self.root / 'helper.py').unlink(); public_assets.seal(self.root)
        self.snapshot.stage_public_snapshot(self.root)
        self.assertEqual(self.git('diff', '--cached', '--name-only'), b'')
        with self.assertRaisesRegex(ValueError, 'full input fingerprint differs'): self.verify()

    def test_private_modifications_additions_and_deletions_are_not_auto_staged(self):
        (self.root / 'helper.py').write_text('# modified private source\n')
        (self.root / 'account.json').write_text('private synthetic data')
        self.legacy.unlink(); public_assets.seal(self.root)
        self.snapshot.stage_public_snapshot(self.root)
        self.assertEqual(self.git('diff', '--cached', '--name-only').decode().splitlines(), ['p/removed-entity/index.html'])
        self.assertNotIn('public.build', self.git('diff', '--cached', '--name-only').decode())

    def test_export_ignore_cannot_hide_extra_committed_route(self):
        (self.root / '.gitattributes').write_text('p/removed-entity/index.html export-ignore\n')
        self.git('add', '--', '.gitattributes'); self.git('commit', '-qm', 'archive exclusion')
        self.legacy.unlink(); public_assets.seal(self.root)
        with self.assertRaisesRegex(ValueError, 'publication set differs'): self.verify()

    def test_uncommitted_tracked_symlink_replacement_fails_closed(self):
        target = self.root / 'private-link'
        target.symlink_to('helper.py')
        self.git('add', '--', 'private-link'); self.git('commit', '-qm', 'unsupported link')
        public_assets.seal(self.root)
        with self.assertRaisesRegex(ValueError, 'Unsupported committed tree path or mode'): self.verify()


if __name__ == '__main__':unittest.main()
