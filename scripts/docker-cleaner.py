#!/usr/bin/python3
"""Disabled by default: prune unused Docker resources older than seven days."""
import os
import subprocess


def main():
    if os.geteuid() != 0:
        raise RuntimeError('Docker cleanup must run as root')
    if subprocess.run(['systemctl', 'is-active', '--quiet', 'docker.service']).returncode:
        print('Docker is not running; nothing to clean.')
        return
    subprocess.run(['docker', 'system', 'prune', '--force', '--filter', 'until=168h'], check=True)


if __name__ == '__main__':
    main()
