# WSL maintenance

This public repository supplies reviewed scripts and the proxy runtime for company
WSL images. `maintenance.yaml` declares stable task IDs, Python script paths,
root/user execution, timeouts, and boot/calendar schedules.

The image's Python maintenance agent reads YAML directly, selects the highest
stable SemVer tag, validates paths and scripts, and generates systemd services.
It retains the current/previous release and any older release still referenced by
an independently installed component. No repository authentication is needed.

## Individual versions

The repository tag is a delivery index, not the version of every component.
Every task and package has its own required SemVer `version`. Bump only the items
you change; changing code, settings, or schedules without bumping that item's
version is rejected. Component downgrades are rejected too.

Tasks declare package IDs in `dependsOn`. A package change updates only dependent
tasks. Each task runs from an immutable snapshot containing its script and exact
declared package versions. An unrelated repository release does not restart its
services. Scheduled jobs still run on their normal schedules.

For example, bump `packages[id=proxy-runtime].version` to deploy a controller
change, without changing the Docker cleaner version. Bump the cleaner's own
version when its script or schedule changes. Keep it disabled unless cleanup is approved.

`/var/lib/company-maintenance/components.yaml` records configured task versions,
available package versions, and immutable version/content hashes. It does not
claim a scheduled job succeeded; execution status remains in systemd/journald.
The proxy additionally records its successfully activated package version in
`~/.local/share/wsl-proxy/managed-version.yaml` and skips redundant reinstall/restarts.

Omitting an item preserves it. Explicitly remove a managed job with:

```yaml
remove:
  tasks: [docker-cleaner]
```

Package removal uses `remove.packages` and is rejected while a retained task
depends on it. Removing a task unschedules it; it does not uninstall software or
delete developer data. A failed task reconfiguration restores that task's prior
units, while independent successful updates remain applied and retries skip them.

## Contents

- `scripts/proxy-refresh.py`: refresh the required proxy for the registered user.
- `scripts/docker-cleaner.py`: seven-day Docker cleanup, **disabled by default**.
- `packages/proxy-runtime`: Python controller, configuration, service units, and refresh code.
- `tests`: isolated repository-only checks, never installed in the image.

Proxy updates preserve upstream settings and restore the previous runtime after a
failed activation. Before onboarding they defer; a missing installation after
onboarding is an error. Bash and Zsh consume generated proxy exports, not Python code.

## Validate

Run `python3 -B -m unittest discover -s tests -v` with system Python and PyYAML.
Test VPN transitions, Docker connectivity, and WSL restart in a disposable image
before approving a release.

## Releases

Maintenance tasks must be Python files. The agent rejects Bash task paths and
executes tasks with Ubuntu's system Python.

Release only when explicitly approved. Use a new matching stable SemVer tag;
never move or reuse a tag. Clients do not downgrade or refetch installed versions.

This is a privileged deployment channel: protect reviews and tag permissions,
keep credentials out of the repository, and leave destructive tasks disabled
until their behavior is approved.
