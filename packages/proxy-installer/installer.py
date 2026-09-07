#!/usr/bin/python3
"""WSL proxy installer. Run as the intended Linux user, not via sudo."""
import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time

import yaml

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent / 'payload/lib'))
from settings import load_settings

VERSION = 2
UNITS = ['proxy-endpoint.service', 'proxy-direct.service', 'proxy-monitor.service']
ROOT_UNITS = ['haproxy.service', 'tinyproxy.service']
PACKAGES = ['haproxy', 'tinyproxy-bin', 'netcat-openbsd', 'curl', 'iproute2', 'util-linux']
BEGIN = '# >>> wsl-proxy installer >>>'
END = '# <<< wsl-proxy installer <<<'
NO_PROXY = 'localhost,127.0.0.1,::1,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16,.nav.gov.hu'
DOCKER_PROXY = {'httpProxy': 'http://192.168.20.5:18080', 'httpsProxy': 'http://192.168.20.5:18080', 'noProxy': NO_PROXY}


def digest(path):
    if path.is_symlink():
        return {'kind': 'link', 'target': os.readlink(path)}
    if path.is_file():
        return {'kind': 'file', 'sha256': hashlib.sha256(path.read_bytes()).hexdigest(), 'mode': path.stat().st_mode & 0o777}
    if path.exists():
        raise RuntimeError('Expected a file, not a directory: ' + str(path))
    return {'kind': 'absent'}


def remove_shell_block(text):
    pattern = re.escape(BEGIN) + r'\n.*?\n' + re.escape(END) + r'\n?'
    return re.sub(pattern, '', text, flags=re.S)


class Installer:
    def __init__(self, package, home=None, system=Path('/'), runner=None):
        self.package = Path(package).resolve()
        self.home = Path(home or Path.home()).resolve()
        self.system = Path(system).resolve()
        self.root = self.home / '.local/share/wsl-proxy'
        self.state = self.home / '.local/state/wsl-proxy-installer'
        self.manifest_path = self.state / 'manifest.json'
        self.runner = runner or subprocess.run
        self.fake_system = self.system != Path('/')
        self.manifest = None
        self.upstream_host, self.upstream_port = load_settings(self.package/'payload/config/proxy.yaml')

    def run(self, args, check=True, **kwargs):
        return self.runner([str(a) for a in args], check=check, text=True, **kwargs)

    def ctl(self, *args, user=True, check=True):
        cmd = ['systemctl'] + (['--user'] if user else []) + list(args)
        if not user and not self.fake_system and args[0] not in ['is-enabled','is-active','show']:
            cmd = ['sudo', '-n'] + cmd
        return self.run(cmd, check=check, capture_output=True)

    def request_privilege(self):
        if not self.fake_system:
            print('Administrator access is required for the managed system integrations.')
            self.run(['sudo', '-v'])

    def service_state(self, name, user=True):
        enabled = self.ctl('is-enabled', name, user=user, check=False).stdout.strip()
        active = self.ctl('is-active', name, user=user, check=False).stdout.strip() == 'active'
        return {'enabled': enabled, 'active': active}

    def save(self):
        self.state.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.state.chmod(0o700)
        tmp = self.manifest_path.with_suffix('.tmp')
        tmp.write_text(json.dumps(self.manifest, indent=2) + '\n')
        tmp.chmod(0o600)
        os.replace(tmp, self.manifest_path)

    def snapshot(self, path, privileged=False, kind='file'):
        path = Path(path)
        item = {'path': str(path), 'privileged': privileged, 'before': digest(path), 'kind': kind}
        if path.is_file() and not path.is_symlink():
            saved = self.state / 'files' / str(len(self.manifest['files']))
            saved.parent.mkdir(exist_ok=True, mode=0o700)
            shutil.copy2(path, saved)
            item['backup'] = str(saved)
        self.manifest['files'].append(item)
        self.save()
        return item

    def write(self, path, data=None, mode=0o644, target=None, privileged=False):
        path = Path(path)
        if privileged and not self.fake_system:
            self.run(['sudo', '-n', 'mkdir', '-p', str(path.parent)])
            if target is not None:
                raise RuntimeError('Privileged symlinks are not supported')
            with tempfile.NamedTemporaryFile(dir=self.state, delete=False) as f:
                f.write(data)
                temporary = Path(f.name)
            try:
                self.run(['sudo', '-n', 'install', '-o', 'root', '-g', 'root', '-m', format(mode, 'o'), str(temporary), str(path) + '.wsl-proxy-new'])
                self.run(['sudo', '-n', 'mv', '-fT', str(path) + '.wsl-proxy-new', str(path)])
            finally:
                temporary.unlink()
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_name(path.name + '.wsl-proxy-new')
            if temporary.exists() or temporary.is_symlink():
                raise RuntimeError('Temporary destination already exists: ' + str(temporary))
            if target is not None:
                os.symlink(str(target), temporary)
            else:
                temporary.write_bytes(data)
                temporary.chmod(mode)
            os.replace(temporary, path)

    def install_file(self, path, data=None, mode=0o644, target=None, privileged=False, kind='file'):
        item = self.snapshot(path, privileged, kind)
        self.write(path, data, mode, target, privileged)
        item['after'] = digest(Path(path))
        self.save()

    def restore_file(self, item):
        path = Path(item['path'])
        before = item['before']
        if before['kind'] == 'absent':
            if item['privileged'] and not self.fake_system:
                self.run(['sudo', '-n', 'rm', '-f', '--', path])
            elif path.exists() or path.is_symlink():
                path.unlink()
        elif before['kind'] == 'link':
            if item['privileged']:
                raise RuntimeError('Refusing unexpected privileged symlink backup')
            self.write(path, target=before['target'])
        else:
            self.write(path, Path(item['backup']).read_bytes(), before['mode'], privileged=item['privileged'])

    def verify_package(self):
        manifest = yaml.safe_load((self.package / 'checksums.yaml').read_text())
        if not isinstance(manifest, dict) or not manifest:
            raise RuntimeError('Package checksum manifest is invalid')
        for name, expected in manifest.items():
            path = self.package / name
            if Path(name).is_absolute() or '..' in Path(name).parts or not path.is_file():
                raise RuntimeError('Invalid package member: ' + name)
            if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
                raise RuntimeError('Package checksum mismatch: ' + name)

    def preflight(self):
        if os.geteuid() == 0:
            raise RuntimeError('Run ./install.sh as the intended user, without sudo')
        self.verify_package()
        if not re.fullmatch(r'/[A-Za-z0-9_./-]+', str(self.home)):
            raise RuntimeError('This installer requires a normal Linux home path without spaces or shell metacharacters')
        release = (self.system / 'etc/os-release').read_text()
        if 'ID=ubuntu' not in release or 'VERSION_ID="26.04"' not in release:
            raise RuntimeError('Supported target: Ubuntu 26.04 in WSL2')
        if not (self.system / 'run/systemd/system').is_dir():
            raise RuntimeError('Enable systemd in /etc/wsl.conf and restart WSL before installing')
        if self.ctl('show-environment', check=False).returncode:
            raise RuntimeError('The user systemd manager is unavailable; open a normal WSL login first')
        for unit in ROOT_UNITS:
            if self.service_state(unit, False)['active']:
                raise RuntimeError('An existing system proxy service is active: ' + unit)
            override = self.system / 'etc/systemd/system' / unit
            if override.exists() and not override.is_symlink():
                raise RuntimeError('Existing custom system service requires manual review: ' + str(override))
            if override.is_symlink() and os.readlink(override)!='/dev/null':
                raise RuntimeError('Existing custom system service link requires manual review: '+str(override))
        if self.run(['docker', 'info'], check=False, capture_output=True).returncode:
            raise RuntimeError('Docker Engine must already be running and accessible to this user')
        addresses = self.run(['ip', '-4', '-o', 'addr', 'show'], capture_output=True).stdout
        if not re.search(r'\binet 192\.168\.20\.5/24\b', addresses):
            raise RuntimeError('Expected Docker gateway 192.168.20.5/24 is missing; this package targets that existing network layout')
        if self.root.is_symlink():
            raise RuntimeError('Installation root must not be a symlink')
        for path in [self.system/'etc/apt/apt.conf.d/90-tinyproxy', self.system/'etc/systemd/system/docker.service.d/90-tinyproxy.conf', self.home/'.docker/config.json']:
            if path.is_symlink():
                raise RuntimeError('Configuration symlink requires manual review: ' + str(path))
        docker = self.home / '.docker/config.json'
        if docker.exists():
            data = json.loads(docker.read_text())
            if not isinstance(data, dict) or not isinstance(data.get('proxies', {}), dict):
                raise RuntimeError('Unsupported Docker configuration structure')

    def plan(self):
        print('Target:', self.root)
        print('User:', self.home.name)
        print('Upstream:', str(self.upstream_host)+':'+str(self.upstream_port))
        print('Install bundled tool, shell startup blocks, and three user services.')
        print('Configure static APT/Docker proxies; merge only Docker proxies.default; enable user lingering.')
        print('Install missing Ubuntu packages:', ', '.join(PACKAGES))
        print('Restart proxy services. Restart Docker only if its daemon proxy drop-in changes.')
        print('Backups and uninstall journal:', self.state)
        print('Existing files are saved; credentials are never included in the package or printed.')

    def install(self, packages=True, checked=False):
        if not checked:
            self.preflight()
        if self.manifest_path.exists():
            saved = json.loads(self.manifest_path.read_text())
            if saved['status'] == 'installed':
                print('Already managed by this installer. Run proxy status; uninstall before installing another package version.')
                return
            raise RuntimeError('A previous installation journal exists; run uninstall first or inspect ' + str(self.state))
        self.request_privilege()
        self.state.mkdir(parents=True, mode=0o700, exist_ok=True)
        self.state.chmod(0o700)
        self.manifest = {'version': VERSION, 'status': 'installing', 'home': str(self.home), 'root': str(self.root), 'files': [],
                         'services': {u:self.service_state(u) for u in UNITS},
                         'root_services': {u:self.service_state(u,False) for u in ROOT_UNITS},
                         'tree_moved': False, 'tree_installed': False, 'docker_changed': False,
                         'linger_before': self.run(['loginctl','show-user',str(os.getuid()),'-p','Linger','--value'],check=False,capture_output=True).stdout.strip() == 'yes'}
        self.save()
        try:
            for unit in ROOT_UNITS:
                if self.manifest['root_services'][unit]['enabled'] not in ['masked','masked-runtime']:
                    self.ctl('mask', unit, user=False)
            if packages:
                missing = []
                for package in PACKAGES:
                    p = self.run(['dpkg-query','-W','-f=${db:Status-Status}',package],check=False,capture_output=True)
                    if p.returncode or p.stdout.strip() != 'installed': missing.append(package)
                if missing:
                    bootstrap=[]
                    try:
                        with socket.create_connection((self.upstream_host,self.upstream_port),timeout=2):pass
                        url=f'http://{self.upstream_host}:{self.upstream_port}'
                        bootstrap=['-o','Acquire::http::Proxy='+url,'-o','Acquire::https::Proxy='+url]
                    except OSError:pass
                    self.run(['sudo','-n','apt-get',*bootstrap,'update'])
                    self.run(['sudo','-n','apt-get',*bootstrap,'install','-y','--no-install-recommends',*missing])
            self.run(['sudo','-n','loginctl','enable-linger',str(os.getuid())]) if not self.fake_system else None
            stage = self.root.with_name('.wsl-proxy-install-' + str(os.getpid()))
            if stage.exists(): raise RuntimeError('Staging directory already exists: ' + str(stage))
            stage.parent.mkdir(parents=True,exist_ok=True)
            shutil.copytree(self.package/'payload',stage)
            for p in stage.rglob('*'):
                if p.is_file() and p.suffix not in ('.pem',):
                    try: text = p.read_text()
                    except UnicodeDecodeError: continue
                    p.write_text(text.replace('@HOME@', str(self.home)))
            (stage/'proxy').chmod(0o700)
            for p in (stage/'systemd').glob('*'): p.chmod(0o644)
            (stage/'logs').mkdir(exist_ok=True,mode=0o700)
            self.run([stage/'proxy','test'])
            self.ctl('stop',*UNITS,check=False)
            if self.root.exists():
                self.manifest['tree_moved'] = True
                self.save()
                self.root.rename(self.state/'previous-tool')
            self.manifest['tree_installed'] = True
            self.save()
            stage.rename(self.root)
            for unit in UNITS:
                self.install_file(self.home/'.config/systemd/user'/unit,target=self.root/'systemd'/unit)
            self.install_file(self.home/'bin/proxy',target=self.root/'proxy')
            for name in ['.bashrc','.zshrc']:
                path = self.home/name
                text = path.read_text() if path.exists() else ''
                # Existing integrations already reference canonical state; leave them intact.
                if '.proxy-state' not in text and BEGIN not in text:
                    block = '\n'+BEGIN+'\nexport PATH="$HOME/bin:$PATH"\nif [ -r "$HOME/.cache/.proxy-state" ]; then\n  . "$HOME/.cache/.proxy-state"\nfi\n'+END+'\n'
                    self.install_file(path,(text+block).encode(),path.stat().st_mode&0o777 if path.exists() else 0o644,kind='shell')
            docker = self.home/'.docker/config.json'
            data = json.loads(docker.read_text()) if docker.exists() else {}
            self.manifest['docker_proxy_before'] = copy.deepcopy(data.get('proxies',{}).get('default'))
            self.manifest['docker_had_proxies'] = 'proxies' in data
            self.manifest['docker_had_default'] = 'default' in data.get('proxies',{})
            self.save()
            data.setdefault('proxies',{})['default'] = DOCKER_PROXY
            self.install_file(docker,(json.dumps(data,indent=2)+'\n').encode(),docker.stat().st_mode&0o777 if docker.exists() else 0o600,kind='docker')
            apt = self.system/'etc/apt/apt.conf.d/90-tinyproxy'
            self.install_file(apt,b'Acquire::http::Proxy "http://127.0.0.1:18080";\nAcquire::https::Proxy "http://127.0.0.1:18080";\n',privileged=True)
            dropin = self.system/'etc/systemd/system/docker.service.d/90-tinyproxy.conf'
            contents = ('[Service]\nEnvironment="HTTP_PROXY=http://127.0.0.1:18080"\nEnvironment="HTTPS_PROXY=http://127.0.0.1:18080"\nEnvironment="NO_PROXY='+NO_PROXY+'"\n').encode()
            self.manifest['docker_changed'] = not dropin.is_file() or dropin.read_bytes()!=contents
            self.save()
            self.install_file(dropin,contents,privileged=True)
            generated = [self.home/'.cache/.proxy-state',self.home/'.cache/.proxy-state.pending',self.home/'.config/haproxy/proxy.cfg']
            items = [self.snapshot(p,kind='generated') for p in generated]
            for state_file in generated[:2]:
                state_file.unlink(missing_ok=True)
            self.ctl('daemon-reload')
            self.ctl('enable',*UNITS)
            self.ctl('start','proxy-direct.service','proxy-endpoint.service')
            self.run([self.root/'proxy','auto'])
            self.run([self.root/'proxy','check'])
            self.run([self.root/'proxy','check'])
            self.ctl('start','proxy-monitor.service')
            for item in items: item['after']=digest(Path(item['path']))
            self.save()
            self.ctl('daemon-reload',user=False)
            if self.manifest['docker_changed']: self.ctl('restart','docker.service',user=False)
            self.ctl('is-active',*UNITS)
            self.run(['/usr/sbin/haproxy','-c','-f',self.home/'.config/haproxy/proxy.cfg'])
            self.manifest['status']='installed'
            self.save()
            print('Installed. Open a new shell, then run proxy status and proxy verify on|off.')
        except BaseException:
            print('Installation failed; restoring saved settings.',file=sys.stderr)
            self.uninstall(rollback=True)
            raise

    def refresh(self, checked=False):
        """Atomically refresh an existing user installation without sudo."""
        if os.geteuid() == 0 and not self.fake_system:
            raise RuntimeError('Run refresh as the developer account, not as root')
        if not checked:
            self.verify_package()
        if not self.manifest_path.exists():
            print('Proxy is not installed for this user yet; refresh deferred until onboarding.')
            return
        saved = json.loads(self.manifest_path.read_text())
        if saved.get('status') != 'installed' or saved.get('home') != str(self.home) or saved.get('root') != str(self.root):
            raise RuntimeError('Installation journal is incomplete or belongs to a different user/path')
        if not self.root.is_dir() or self.root.is_symlink():
            raise RuntimeError('Installed proxy tree is missing or unsafe: ' + str(self.root))

        stage = self.root.with_name('.wsl-proxy-refresh-' + str(os.getpid()))
        previous = self.root.with_name('.wsl-proxy-previous-' + str(os.getpid()))
        if stage.exists() or previous.exists():
            raise RuntimeError('Proxy refresh staging path already exists')
        shutil.copytree(self.package/'payload', stage)
        installed_config = self.root/'config/proxy.yaml'
        if installed_config.is_file() and not installed_config.is_symlink():
            shutil.copy2(installed_config, stage/'config/proxy.yaml')
        load_settings(stage/'config/proxy.yaml')
        for path in stage.rglob('*'):
            if path.is_file() and path.suffix not in ('.pem',):
                try: text = path.read_text()
                except UnicodeDecodeError: continue
                path.write_text(text.replace('@HOME@', str(self.home)))
        (stage/'proxy').chmod(0o700)
        for path in (stage/'systemd').glob('*'):
            path.chmod(0o644)
        (stage/'logs').mkdir(exist_ok=True, mode=0o700)
        self.run([stage/'proxy', 'test'])

        self.ctl('stop', *UNITS, check=False)
        try:
            self.root.rename(previous)
            stage.rename(self.root)
            self.ctl('daemon-reload')
            self.ctl('restart', *UNITS)
            self.run([self.root/'proxy', 'check'])
            self.ctl('is-active', *UNITS)
        except BaseException:
            if self.root.exists():
                shutil.rmtree(self.root)
            if previous.exists():
                previous.rename(self.root)
            self.ctl('daemon-reload', check=False)
            self.ctl('restart', *UNITS, check=False)
            raise
        finally:
            if stage.exists():
                shutil.rmtree(stage)
        shutil.rmtree(previous)
        print('Refreshed the installed proxy package without changing user configuration or system integration.')

    def uninstall(self, rollback=False):
        if self.manifest is None:
            if not self.manifest_path.exists():
                print('No managed installation found. Nothing changed.')
                return
            self.manifest=json.loads(self.manifest_path.read_text())
        if self.manifest['home']!=str(self.home) or self.manifest['root']!=str(self.root):
            raise RuntimeError('Installation journal belongs to a different user/path')
        rollback = rollback or self.manifest['status']=='installing'
        files=self.manifest['files']
        # Refuse conflicting changes before stopping anything. Docker auth changes and shell additions are merged below.
        if not rollback:
            for item in files:
                path=Path(item['path'])
                if item['kind']=='docker':
                    current=json.loads(path.read_text()) if path.exists() else {}
                    if current.get('proxies',{}).get('default')!=DOCKER_PROXY:
                        raise RuntimeError('Docker proxy settings changed since install; resolve before uninstalling: '+str(path))
                elif item['kind'] not in ['shell','generated'] and digest(path)!=item.get('after'):
                    raise RuntimeError('Managed file changed since install; saved backup retained: '+str(path))
        self.ctl('stop',*UNITS,check=False)
        self.ctl('disable',*UNITS,check=False)
        if self.manifest['tree_installed'] and self.root.exists():
            archive=self.state/('removed-tool-'+str(time.time_ns()))
            self.root.rename(archive)
        self.manifest['tree_installed']=False
        self.save()
        if self.manifest['tree_moved'] and (self.state/'previous-tool').exists():
            (self.state/'previous-tool').rename(self.root)
        self.manifest['tree_moved']=False
        self.save()
        for item in reversed(files):
            path=Path(item['path'])
            if not rollback and item['kind']=='shell' and digest(path)!=item.get('after'):
                text=path.read_text() if path.exists() else ''
                self.write(path,remove_shell_block(text).encode(),path.stat().st_mode&0o777 if path.exists() else 0o644)
            elif not rollback and item['kind']=='docker' and digest(path)!=item.get('after'):
                data=json.loads(path.read_text())
                if self.manifest['docker_had_default']:
                    data['proxies']['default']=self.manifest['docker_proxy_before']
                else:
                    data['proxies'].pop('default',None)
                    if not data['proxies'] and not self.manifest['docker_had_proxies']:data.pop('proxies')
                self.write(path,(json.dumps(data,indent=2)+'\n').encode(),path.stat().st_mode&0o777)
            else:self.restore_file(item)
        self.ctl('daemon-reload')
        for unit,previous in self.manifest['services'].items():
            if previous['enabled'] in ['enabled','enabled-runtime']:self.ctl('enable',unit,check=False)
            if previous['active']:self.ctl('start',unit)
        for unit,previous in self.manifest['root_services'].items():
            if previous['enabled'] not in ['masked','masked-runtime']:self.ctl('unmask',unit,user=False,check=False)
            if previous['enabled'] in ['enabled','enabled-runtime']:self.ctl('enable',unit,user=False,check=False)
            elif previous['enabled'] not in ['masked','masked-runtime']:self.ctl('disable',unit,user=False,check=False)
        if not self.manifest['linger_before'] and not self.fake_system:
            self.run(['sudo','-n','loginctl','disable-linger',str(os.getuid())])
        self.ctl('daemon-reload',user=False)
        if self.manifest['docker_changed']:self.ctl('restart','docker.service',user=False)
        self.manifest['status']='rolled-back' if rollback else 'uninstalled'
        self.save()
        history=self.state.with_name('wsl-proxy-installer-history-'+str(time.time_ns()))
        self.state.rename(history)
        print('Saved settings restored. Packages retained. Backups/logs preserved at:',history)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['install','uninstall','check','refresh'])
    parser.add_argument('--dry-run',action='store_true')
    args=parser.parse_args()
    installer=Installer(Path(__file__).resolve().parent)
    if args.action == 'refresh':
        installer.refresh()
        return
    if args.action in ['install','check']:
        installer.preflight()
        installer.plan()
        if args.action=='check' or args.dry_run:return
    if args.action=='uninstall' and args.dry_run:
        print('Would restore the saved installation journal at',installer.state)
        return
    if os.geteuid()==0:raise RuntimeError('Run as the intended Linux user, without sudo')
    if args.action=='uninstall' and not installer.manifest_path.exists():
        installer.uninstall();return
    subprocess.run(['sudo','-v'],check=True)
    if args.action=='install':installer.install(checked=True)
    else:installer.uninstall()


if __name__=='__main__':
    try:main()
    except (RuntimeError,subprocess.CalledProcessError,OSError,ValueError) as exc:
        print('ERROR:',exc,file=sys.stderr)
        raise SystemExit(1)
