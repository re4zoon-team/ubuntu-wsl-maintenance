# WSL maintenance

This public repository supplies reviewed scripts and the proxy runtime for company
WSL images. `maintenance.yaml` declares stable task IDs, Python script paths,
root/user execution, and one of four explicit modes: `files`, `once`, `cron`, or `systemd`.

The image's Python maintenance agent reads YAML directly, selects the highest
stable SemVer tag, validates paths and scripts, and applies each task independently.
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
Successful `once` executions are recorded separately in `completed`, keyed by
task ID, task version, and account UID. A repository tag or dependency-package
change does not rerun a completed once task. Bump its task version to run it again,
or use `--force`. Failed executions are retried, and user tasks wait for onboarding.
As with any process launcher, a crash between script success and recording it can
cause a retry; make scripts safe to retry. Cron output follows the host's cron
logging/mail configuration; scripts should log useful results themselves.
The proxy additionally records its successfully activated package version in
`~/.local/share/wsl-proxy/managed-version.yaml` and skips redundant reinstall/restarts.

## Retire a service or cron job remotely

Omitting an item preserves it. To retire jobs, remove their definitions from
`tasks` and add their IDs to the release manifest's removal list:

```yaml
remove:
  tasks: [old-vpn-service, old-cleanup-job]
```

When a developer's updater receives that release:

- Systemd tasks: stop and disable the timer first, then the service; delete both
  generated unit files and reload systemd.
- Cron tasks: delete their managed `/etc/cron.d/company-maintenance-<id>` entry.
  This prevents future invocations; an already-running cron invocation finishes
  normally (or reaches its configured timeout).
- Pending user tasks: cancel them even if onboarding has not happened yet.

This works for both root and developer-user tasks. Repeated removals are safe.
Keep the removal list in subsequent releases so laptops that skip a release
still receive it, and failed removals can retry. Do not declare and remove the
same task in one manifest. To restore a retired task later, remove its removal
entry and add a versioned task definition again.

These IDs identify jobs managed by this updater, not arbitrary services on the
laptop. No task is retired simply by removing its Python source from Git.

Package removal uses `remove.packages` and is rejected while a retained task
depends on it. Removing a task unschedules it; it does not uninstall software or
delete developer data. A failed task reconfiguration restores that task's prior
units/cron entry, while independent successful updates remain applied and retries
skip them. Distributed files and script side effects are not rolled back. Removing
or disabling a task leaves its distributed files and once-completion records intact.

## Run a branch/tag or replay releases

Run these commands inside the WSL instance with the updated agent:

```bash
sudo company-maintenance-update                         # latest stable tag
sudo company-maintenance-update --ref feature/vpn       # one-run branch override
sudo company-maintenance-update --ref v0.7.0 --force    # explicit tag and replay
sudo company-maintenance-update --force                 # replay latest stable
sudo company-maintenance-update --force --all           # all stable tags, oldest first
```

`--ref` accepts a branch or tag, never changes the configured repository or
scheduled channel, and resolves the current commit on every invocation. It is a
real deployment, **not a dry run**: use a disposable WSL instance for experiments.
Preview runs permit component downgrades and same-version edits; normal stable
runs enforce immutable component versions. The next scheduled/default run restores
components declared by the latest stable manifest, even after a failed preview.
Items omitted from that stable manifest are retained under the normal omission
rule; remove preview-only items explicitly. Script side effects cannot be undone.
Preview once-completion records are separate from stable records; use `--force`
to rerun the same task version on the same branch.

`--force` reapplies tasks declared in the selected manifest, including successful
once scripts, and restarts/reinstalls their managed jobs/files. It does not bypass
stable version-content checks. Scripts with their own internal no-op checks may
still skip work. `--force --all` explicitly permits historical component versions
and applies stable tags in numeric SemVer order. It cannot be combined with `--ref`.
All selected manifests are validated before any task is applied. Old tags without
the four-mode format are rejected, not silently skipped; existing pre-feature tags
therefore prevent replay-all until using a repository whose stable history uses
this format. No backward-compatibility interpreter is included.

## Four task modes

Every task needs `id`, its own `version`, `description`, `enabled`, `runAs`
(`root` or `user`), and `mode`. Scripts are Python and run from root-owned,
immutable snapshots with their declared `dependsOn` packages.

File delivery executes no script and installs the specified permissions:

```yaml
- id: company-notice
  version: '1.0.0'
  description: Company developer notice
  enabled: true
  runAs: user
  mode: files
  files:
    - source: files/notice.txt
      target: ~/.config/company/notice.txt
      chmod: '0644'
```

Sources must be regular files under `files/`. User targets start with `~/` and
are owned by the registered developer; root targets are absolute paths (or `~/`
for root's home) and owned by root. Symlinks and traversal are rejected. Only
ordinary four-digit octal permissions are accepted—quote them in YAML.
An update overwrites declared destinations, so use paths intended for managed
content, not personal files. Parent directories are created as the selected user.
The same optional `files` list is supported in all four modes and is applied
before starting the task. Files associated with an already-completed once task
are left alone until its task version changes or force is requested.

Run a script once per task version:

```yaml
- id: initialize-tool
  version: '1.0.0'
  description: Initialize a company tool
  enabled: true
  runAs: user
  mode: once
  script: scripts/initialize-tool.py
  timeoutSeconds: 300
```

Install a real cron job, using five numeric fields (lists, ranges, steps supported):

```yaml
- id: weekly-cleanup
  version: '1.0.0'
  description: Weekly maintenance
  enabled: true
  runAs: root
  mode: cron
  script: scripts/weekly-cleanup.py
  timeoutSeconds: 1800
  cron: '0 4 * * 0'
```

The image includes Ubuntu's cron daemon. Jobs live in
`/etc/cron.d/company-maintenance-<id>`, with the resolved account in the cron user
column. HOME, PATH, and user-systemd connection variables are supplied. Timeout
limits apply to each invocation; schedules should allow enough time to finish.

Install a systemd service and optionally a calendar timer:

```yaml
- id: vpn-connector
  version: '1.0.0'
  description: Company VPN connector
  enabled: true
  runAs: user
  mode: systemd
  serviceType: simple
  script: scripts/vpn-connector.py
  timeoutSeconds: 300
  schedule:
    onBoot: true
```

`serviceType` defaults to `oneshot`; use `simple` for a long-running foreground
process. Optional `schedule.onCalendar` uses systemd calendar syntax and is only
valid for oneshot services. `onBoot: true` enables the service and starts it on
deployment. These are system-level services with `User=` set to root or the
registered developer, so user execution does not depend on an interactive login.

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
never move or reuse a tag. Normal clients reject component downgrades; explicit
preview and replay-all commands are the exceptions described above. A moved
cached tag is rejected. The working manifest is prepared for 0.7.0; no tag is
created by editing it.

This is a privileged deployment channel: protect reviews and tag permissions,
keep credentials out of the repository, and leave destructive tasks disabled
until their behavior is approved.
