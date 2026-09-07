"""Lifecycle tests use temporary files and mocked service/package commands; no sudo or network."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import shutil
import time
from unittest.mock import patch
import sys
import tempfile
import unittest

import yaml

sys.dont_write_bytecode=True

PACKAGE=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('installer',PACKAGE/'installer.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)


class FakeCommands:
    def __init__(self, fail_once=None):
        self.states={}
        self.calls=[]
        self.fail_once=fail_once

    def __call__(self,args,check=True,**kwargs):
        args=[str(a) for a in args];self.calls.append(args)
        out='';code=0
        if self.fail_once and self.fail_once in ' '.join(args):
            self.fail_once=None
            if check:raise subprocess.CalledProcessError(1,args)
            return subprocess.CompletedProcess(args,1,'','injected failure')
        if args[0]=='loginctl':out='yes\n'
        if args[0]=='systemctl':
            user='--user' in args
            i=2 if user else 1
            action=args[i]
            for unit in args[i+1:]:
                state=self.states.setdefault((user,unit),{'enabled':'disabled','active':False})
                if action=='is-enabled':out=state['enabled']+'\n'
                elif action=='is-active':out=('active' if state['active'] else 'inactive')+'\n';code=0 if state['active'] else 3
                elif action=='enable':state['enabled']='enabled'
                elif action=='disable':state['enabled']='disabled'
                elif action in ['start','restart']:state['active']=True
                elif action=='stop':state['active']=False
                elif action=='mask':state['enabled']='masked'
                elif action=='unmask':state['enabled']='disabled'
            # is-active with multiple units succeeds only if all were started.
        return subprocess.CompletedProcess(args,code,out,'')


class Lifecycle(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.base=Path(self.temp.name)
        self.home=self.base/'home/tester';self.home.mkdir(parents=True)
        self.system=self.base/'system';self.system.mkdir()
        self.fake=FakeCommands()
        self.inst=module.Installer(PACKAGE,self.home,self.system,self.fake)
        (self.home/'.docker').mkdir()
        self.docker=self.home/'.docker/config.json'
        self.original={'auths':{'example.invalid':{'auth':'fixture-only'}},'other':'keep'}
        self.docker.write_text(json.dumps(self.original))
        self.docker.chmod(0o640)
        (self.home/'.bashrc').write_text('# original shell\n')

    def tearDown(self):self.temp.cleanup()

    def test_fresh_install_uninstall_preserves_credentials_and_shell_additions(self):
        self.inst.install(packages=False,checked=True)
        self.assertTrue((self.home/'bin/proxy').is_symlink())
        self.assertEqual(json.loads(self.docker.read_text())['auths'],self.original['auths'])
        self.assertEqual(self.docker.stat().st_mode&0o777,0o640)
        data=json.loads(self.docker.read_text());data['auths']['later.invalid']={'auth':'later-fixture'}
        self.docker.write_text(json.dumps(data))
        shell=self.home/'.bashrc';shell.write_text(shell.read_text()+'export LATER=1\n')
        self.inst.uninstall()
        data=json.loads(self.docker.read_text())
        self.assertNotIn('proxies',data)
        self.assertIn('later.invalid',data['auths'])
        self.assertEqual(shell.read_text(),'# original shell\n\nexport LATER=1\n')
        self.assertFalse(self.inst.root.exists())
        self.assertFalse((self.home/'bin/proxy').is_symlink())

    def test_existing_tool_and_symlink_restore(self):
        self.inst.root.mkdir(parents=True)
        (self.inst.root/'proxy').write_text('old controller')
        (self.home/'bin').mkdir()
        os.symlink(self.inst.root/'proxy',self.home/'bin/proxy')
        self.inst.install(packages=False,checked=True)
        self.inst.uninstall()
        self.assertEqual((self.home/'bin/proxy').read_text(),'old controller')

    def test_failure_rolls_back_before_returning(self):
        self.fake.fail_once='is-active proxy-endpoint.service proxy-direct.service proxy-monitor.service'
        with self.assertRaises(subprocess.CalledProcessError):self.inst.install(packages=False,checked=True)
        self.assertEqual(json.loads(self.docker.read_text()),self.original)
        self.assertEqual((self.home/'.bashrc').read_text(),'# original shell\n')
        self.assertFalse(self.inst.root.exists())

    def test_uninstall_conflict_does_not_stop_services(self):
        self.inst.install(packages=False,checked=True)
        apt=self.system/'etc/apt/apt.conf.d/90-tinyproxy'
        apt.write_text('later administrator change')
        n=len(self.fake.calls)
        with self.assertRaises(RuntimeError):self.inst.uninstall()
        self.assertEqual(len(self.fake.calls),n)

    def test_reinstall_is_idempotent(self):
        self.inst.install(packages=False,checked=True)
        before=self.inst.manifest_path.read_bytes()
        self.inst.install(packages=False,checked=True)
        self.assertEqual(self.inst.manifest_path.read_bytes(),before)

    def test_existing_certificates_are_untouched(self):
        cert=self.system/'usr/local/share/ca-certificates/company/existing.crt'
        cert.parent.mkdir(parents=True);cert.write_text('existing trust fixture')
        bundle=self.home/'existing-ca-bundle.pem'
        bundle.write_text('existing bundle fixture')
        self.inst.install(packages=False,checked=True)
        self.assertEqual(cert.read_text(),'existing trust fixture')
        self.assertEqual(bundle.read_text(),'existing bundle fixture')
        self.assertFalse(any('update-ca-certificates' in call for call in self.fake.calls))
        self.inst.uninstall()
        self.assertEqual(cert.read_text(),'existing trust fixture')
        self.assertEqual(bundle.read_text(),'existing bundle fixture')

    def test_config_validation(self):
        config=self.base/'settings.yaml'
        for value in [{'upstream_host':'proxy.new.example','upstream_port':3128},
                      {'upstream_host':'192.0.2.10','upstream_port':8080}]:
            config.write_text(yaml.safe_dump(value))
            self.assertEqual(module.load_settings(config),(value['upstream_host'],value['upstream_port']))
        for host,port in [('bad host',8080),('a..b',8080),('-bad.example',8080),('https://proxy',8080),('proxy',True),('proxy',0),('proxy',65536)]:
            config.write_text(yaml.safe_dump({'upstream_host':host,'upstream_port':port}))
            with self.assertRaises(ValueError):module.load_settings(config)

    def test_runtime_rereads_settings_and_rejects_invalid_edits(self):
        tool=self.base/'tool';shutil.copytree(PACKAGE/'payload',tool)
        config=tool/'config/proxy.yaml'
        service=self.base/'systemctl-mock'
        service.write_text('#!/bin/sh\nprintf \"4242\\n\"\n')
        service.chmod(0o700)
        env=dict(os.environ,HOME=str(self.home),PROXY_STATE=str(self.base/'state'),
                 PROXY_HAPROXY_CONFIG=str(self.base/'haproxy.cfg'),PROXY_SYSTEMCTL=str(service),
                 PROXY_LISTENER_WAKEUP='/bin/true',PROXY_NC='/bin/true')
        env.pop('PROXY_HOST',None);env.pop('PROXY_PORT',None)
        def run(action):
            return subprocess.run([str(tool/'proxy'),action],env=env,capture_output=True,text=True)
        # Set canonical state using the controller, then render without service interaction.
        result=run('on')
        self.assertEqual(result.returncode,0,result.stderr)
        config.write_text(yaml.safe_dump({'upstream_host':'new.proxy.example','upstream_port':3128}))
        result=run('check')
        self.assertEqual(result.returncode,0,result.stderr)
        rendered=(self.base/'haproxy.cfg').read_text()
        self.assertIn('server corporate new.proxy.example:3128 ',rendered)
        config.write_text(': broken')
        self.assertNotEqual(run('check').returncode,0)
        self.assertEqual((self.base/'haproxy.cfg').read_text(),rendered)

    def test_bootstrap_uses_editable_package_settings(self):
        tool=self.base/'package';shutil.copytree(PACKAGE,tool)
        (tool/'payload/config/proxy.yaml').write_text(yaml.safe_dump({'upstream_host':'new.proxy.example','upstream_port':3128}))
        installer=module.Installer(tool,self.home,self.system,self.fake)
        installer.verify_package()  # User-editable settings are deliberately outside code hashes.
        with patch.object(module.socket,'create_connection') as connect:
            installer.install(packages=True,checked=True)
            connect.assert_called_once_with(('new.proxy.example',3128),timeout=2)
        apt=[call for call in self.fake.calls if 'apt-get' in call]
        self.assertTrue(apt)
        self.assertTrue(all('Acquire::https::Proxy=http://new.proxy.example:3128' in call for call in apt))

    def test_install_regenerates_state_and_uninstall_restores_it(self):
        state=self.home/'.cache/.proxy-state'
        state.parent.mkdir(parents=True)
        state.write_text('previous state exports')
        self.inst.install(packages=False,checked=True)
        # The mocked controller writes nothing: old state must already be gone.
        self.assertFalse(state.exists())
        self.inst.uninstall()
        self.assertEqual(state.read_text(),'previous state exports')

    def test_package_checksums(self):self.inst.verify_package()

    def test_install_requests_sudo_authentication(self):
        self.inst.fake_system=False
        self.inst.request_privilege()
        self.assertEqual(self.fake.calls[-1], ['sudo', '-v'])

    def test_refresh_preserves_settings_and_restarts_services(self):
        self.inst.install(packages=False,checked=True)
        config=self.inst.root/'config/proxy.yaml'
        config.write_text(yaml.safe_dump({'upstream_host':'custom.proxy.example','upstream_port':3128}))
        self.inst.refresh(checked=True)
        self.assertEqual(module.load_settings(config),('custom.proxy.example',3128))
        for unit in module.UNITS:
            self.assertTrue(self.fake.states[(True,unit)]['active'])

    def test_incomplete_journal_allows_recovery_without_after_hash(self):
        self.inst.install(packages=False,checked=True)
        self.inst.manifest['status']='installing'
        for item in self.inst.manifest['files']:item.pop('after',None)
        self.inst.save()
        recovery=module.Installer(PACKAGE,self.home,self.system,self.fake)
        recovery.uninstall()
        self.assertEqual(json.loads(self.docker.read_text()),self.original)
        self.assertFalse(recovery.root.exists())


if __name__=='__main__':unittest.main(verbosity=2)
