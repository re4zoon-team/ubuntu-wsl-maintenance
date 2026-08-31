#!/usr/bin/env bash
set -Eeuo pipefail

state_root=${XDG_STATE_HOME:-"$HOME/.local/state"}/company-maintenance
install -d -m 0700 "$state_root"
report="$state_root/health-report.txt"
temporary=$(mktemp)
trap 'rm -f "$temporary"' EXIT

{
    printf 'generated_at=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    printf 'user=%s\n' "$(id -un)"
    printf 'kernel=%s\n' "$(uname -r)"
    if [[ -r /etc/company-dev-image/image-release ]]; then
        sed 's/^/image_/' /etc/company-dev-image/image-release
    fi
    for command in java mvn node npm python uv docker kubectl k9s; do
        if command -v "$command" >/dev/null 2>&1; then
            version=$($command --version 2>&1 | head -n 1 || true)
            printf '%s=%s\n' "$command" "$version"
        else
            printf '%s=missing\n' "$command"
        fi
    done
} > "$temporary"

install -m 0600 "$temporary" "$report"
echo "Health report updated: $report"
