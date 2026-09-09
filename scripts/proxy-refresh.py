#!/usr/bin/python3
"""Refresh the required proxy as the registered developer account."""
import os
from pathlib import Path
import subprocess
import yaml


def main():
    if os.geteuid() == 0:
        raise RuntimeError('Proxy refresh must run as the registered WSL user')
    package = Path(__file__).resolve().parents[1] / 'packages/proxy-runtime'
    if not (package / 'proxy').is_file() or (package / 'proxy').is_symlink():
        raise RuntimeError('The proxy runtime package is missing or unsafe')
    state = Path(os.environ.get('XDG_STATE_HOME', Path.home() / '.local/state'))
    if (state / 'company-dev-image/onboarding.done').exists() and not (Path.home() / '.local/state/wsl-proxy-installer/manifest.json').is_file():
        raise RuntimeError('Required proxy installation is missing after onboarding; contact the image maintainer')
    manifest = yaml.safe_load((package.parents[1] / 'maintenance.yaml').read_text())
    version = next(item['version'] for item in manifest['packages'] if item['id'] == 'proxy-runtime')
    subprocess.run(['/usr/bin/python3', '-B', str(package / 'refresh.py'), '--version', version], check=True)


if __name__ == '__main__':
    main()
