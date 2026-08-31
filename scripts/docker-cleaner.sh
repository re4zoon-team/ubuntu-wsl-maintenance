#!/usr/bin/env bash
set -Eeuo pipefail

if [[ $(id -u) -ne 0 ]]; then
    echo 'docker-cleaner must run as root.' >&2
    exit 1
fi
if ! systemctl is-active --quiet docker.service; then
    echo 'Docker is not running; nothing to clean.'
    exit 0
fi

# This task is intentionally disabled in maintenance.json until company policy
# approves deletion of unused containers, networks, images, and build cache.
docker system prune --force --filter 'until=168h'
