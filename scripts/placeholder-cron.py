"""Harmless cron demonstration: replace a small per-user last-run record."""
from datetime import datetime, timezone
import os
from pathlib import Path
import yaml


def main():
    if os.geteuid() == 0:
        raise SystemExit('Run the placeholder cron task as the registered developer')
    directory = Path.home() / '.local/state/company-maintenance'
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / 'placeholder-last-run.yaml'
    temporary = target.with_suffix('.tmp')
    temporary.write_text(yaml.safe_dump(dict(task='placeholder-cron', uid=os.geteuid(),
                                            ranAt=datetime.now(timezone.utc).isoformat())))
    temporary.chmod(0o600)
    temporary.replace(target)


if __name__ == '__main__':
    main()
