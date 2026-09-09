"""Validated upstream settings shared by installation and the controller."""
import re
import sys

import yaml

def load_settings(path):
    with open(path, encoding='utf-8') as stream:
        data = yaml.safe_load(stream)
    if not isinstance(data, dict) or set(data) != {'upstream_host', 'upstream_port'}:
        raise ValueError('Config must contain upstream_host and upstream_port only')
    host, port = data['upstream_host'], data['upstream_port']
    if not isinstance(host, str) or len(host) > 253 or not all(re.fullmatch(r'[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?', label) for label in host.split('.')):
        raise ValueError('upstream_host must be a DNS hostname or IPv4 address')
    if type(port) is not int or not 1 <= port <= 65535:
        raise ValueError('upstream_port must be an integer from 1 to 65535')
    return host, port

if __name__ == '__main__':
    try:
        print(*load_settings(sys.argv[1]))
    except (OSError, ValueError) as exc:
        print('Invalid proxy configuration: ' + str(exc), file=sys.stderr)
        raise SystemExit(1)
