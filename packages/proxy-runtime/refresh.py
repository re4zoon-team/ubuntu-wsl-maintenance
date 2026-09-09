#!/usr/bin/python3
"""Refresh only the installed proxy runtime; never perform system installation."""
import ast
import argparse
import json
import os
import re
from pathlib import Path
import shutil
import subprocess
import sys
import yaml

sys.dont_write_bytecode = True
UNITS = ['proxy-endpoint.service', 'proxy-direct.service', 'proxy-monitor.service']

class Runtime:
    def __init__(self, package):
        self.package = Path(package).resolve()
        self.home = Path.home().resolve()
        self.root = self.home / '.local/share/wsl-proxy'
        self.manifest_path = self.home / '.local/state/wsl-proxy-installer/manifest.json'

    def run(self, args, check=True, **kwargs):
        return subprocess.run([str(a) for a in args], check=check, text=True, **kwargs)

    def ctl(self, *args, check=True):
        return self.run(['systemctl', '--user', *args], check=check, capture_output=True)

    def refresh(self, version):
        """Atomically refresh an existing user installation without sudo."""
        if not re.fullmatch(r'(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)', version):
            raise ValueError('Proxy package version must be stable SemVer')
        if os.geteuid() == 0:
            raise RuntimeError('Run refresh as the developer account, not as root')
        if not self.manifest_path.exists():
            print('Proxy is not installed for this user yet; refresh deferred until onboarding.')
            return
        saved = json.loads(self.manifest_path.read_text())
        if saved.get('status') != 'installed' or saved.get('home') != str(self.home) or saved.get('root') != str(self.root):
            raise RuntimeError('Installation journal is incomplete or belongs to a different user/path')
        if not self.root.is_dir() or self.root.is_symlink():
            raise RuntimeError('Installed proxy tree is missing or unsafe: ' + str(self.root))
        marker = self.root / 'managed-version.yaml'
        if marker.exists():
            installed = yaml.safe_load(marker.read_text())['version']
            if tuple(map(int, version.split('.'))) < tuple(map(int, installed.split('.'))):
                raise RuntimeError('Proxy runtime downgrade rejected')
            if installed == version:
                print('Proxy runtime ' + version + ' is already installed; no restart needed.')
                return

        stage = self.root.with_name('.wsl-proxy-refresh-' + str(os.getpid()))
        previous = self.root.with_name('.wsl-proxy-previous-' + str(os.getpid()))
        if stage.exists() or previous.exists():
            raise RuntimeError('Proxy refresh staging path already exists')
        try:
            shutil.copytree(self.package, stage, ignore=shutil.ignore_patterns('tests', '__pycache__', '*.md', 'refresh.py'))
            installed_config = self.root/'config/proxy.yaml'
            if installed_config.is_file() and not installed_config.is_symlink():
                shutil.copy2(installed_config, stage/'config/proxy.yaml')
            load_settings(stage/'config/proxy.yaml')
            for path in (stage/'systemd').glob('*.service'):
                path.write_text(path.read_text().replace('@HOME@', str(self.home)))
            (stage/'proxy').chmod(0o700)
            for path in (stage/'systemd').glob('*'):
                path.chmod(0o644)
            for path in [stage/'proxy', *(stage/'lib').glob('*.py')]:
                ast.parse(path.read_text(), filename=str(path))
            (stage/'managed-version.yaml').write_text(yaml.safe_dump(dict(version=version)))
        except BaseException:
            if stage.exists():
                shutil.rmtree(stage)
            raise

        self.ctl('stop', *UNITS, check=False)
        try:
            self.root.rename(previous)
            stage.rename(self.root)
            self.ctl('daemon-reload')
            self.ctl('restart', *UNITS)
            self.run([self.root/'proxy', 'check'])
            self.ctl('is-active', *UNITS)
        except BaseException:
            if previous.exists():
                if self.root.exists():
                    shutil.rmtree(self.root)
                previous.rename(self.root)
            self.ctl('daemon-reload', check=False)
            self.ctl('restart', *UNITS, check=False)
            raise
        finally:
            if stage.exists():
                shutil.rmtree(stage)
        shutil.rmtree(previous)
        print('Refreshed the installed proxy package without changing user configuration or system integration.')


if __name__ == '__main__':
    package = Path(__file__).resolve().parent
    sys.path.insert(0, str(package / 'lib'))
    from settings import load_settings
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--version', required=True)
    Runtime(package).refresh(parser.parse_args().version)
