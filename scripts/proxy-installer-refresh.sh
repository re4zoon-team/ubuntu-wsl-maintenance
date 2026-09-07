#!/usr/bin/env bash
set -Eeuo pipefail

if [[ $(id -u) -eq 0 ]]; then
    echo 'The proxy installer refresh must run as the registered WSL user.' >&2
    exit 1
fi

package=/opt/company-maintenance/current/packages/proxy-installer
[[ -f $package/installer.py && ! -L $package/installer.py ]] || {
    echo "The reviewed proxy installer package is unavailable: $package" >&2
    exit 1
}

exec /usr/bin/python3 "$package/installer.py" refresh
