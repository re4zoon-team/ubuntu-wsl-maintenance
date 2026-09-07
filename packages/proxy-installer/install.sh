#!/usr/bin/env bash
set -euo pipefail
package_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
if [[ ! -x /usr/bin/python3 ]]; then
  printf '%s\n' 'Ubuntu Python 3 is required. Install python3 before running this installer.' >&2
  exit 1
fi
exec /usr/bin/python3 "$package_dir/installer.py" install "$@"
