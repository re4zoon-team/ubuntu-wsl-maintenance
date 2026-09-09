#!/usr/bin/env bash
set -Eeuo pipefail

if [[ $(id -u) -eq 0 ]]; then
    echo 'The proxy installer refresh must run as the registered WSL user.' >&2
    exit 1
fi

package=/opt/company-maintenance/current/packages/proxy-runtime
[[ -f $package/proxy && ! -L $package/proxy ]] || {
    echo "The reviewed proxy installer package is unavailable: $package" >&2
    exit 1
}

onboarding_marker=${XDG_STATE_HOME:-"$HOME/.local/state"}/company-dev-image/onboarding.done
proxy_manifest=$HOME/.local/state/wsl-proxy-installer/manifest.json
if [[ -e $onboarding_marker && ! -f $proxy_manifest ]]; then
    echo 'Required proxy installation is missing after developer onboarding completed.' >&2
    echo 'Contact the image maintainer to restore the required proxy installation.' >&2
    exit 1
fi

exec /usr/bin/python3 "$package/refresh.py"
