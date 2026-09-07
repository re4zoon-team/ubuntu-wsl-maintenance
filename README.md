# Ubuntu WSL maintenance releases

This public repository is the reviewed maintenance channel for deployed company
Ubuntu WSL instances. The base image checks it on every WSL boot and every 24
hours. It selects the highest stable `vMAJOR.MINOR.PATCH` tag, validates
`maintenance.yaml` and every referenced Bash script, and generates systemd units
that run explicitly as either `root` or the registered WSL user.

## Trust boundary

A newer tag can deploy code to every connected WSL instance and tasks may run as
root. Treat release permission as production infrastructure access:

- require pull requests and at least two reviewers on `main`
- restrict tag creation and deletion to a small maintainer group
- never move or reuse a published SemVer tag
- run secret scanning and shell/static analysis in CI
- test releases in a disposable WSL instance before tagging
- keep destructive tasks disabled until their behavior is approved

The repository is public so clients need no credentials. Public visibility does
not make the channel safe by itself; GitHub organization security and release
governance are part of the control boundary.

## Manifest

`maintenance.yaml` is the task and package registry. Each task declares:

- a stable lowercase `id`
- whether it is enabled
- `runAs`: `root` or `user`
- a relative Bash script below `scripts/`
- an execution timeout
- `onBoot`, an optional systemd `onCalendar`, or both

Raw cron files, arbitrary unit files, symlinks, commands outside `scripts/`, and
pre-release tags are not ingested.

The `packages` section permits reviewed, symlink-free file trees below
`packages/` to travel with the same immutable SemVer release. The bundled
`proxy-installer` package is refreshed once per boot and daily as the registered
WSL user. Refreshing preserves the developer's selected upstream proxy settings
and performs an atomic rollback if the updated controller fails its checks. If
onboarding has not installed the proxy yet, the refresh exits successfully and
defers to onboarding.

## Publish a release

1. Update scripts and the manifest through a reviewed pull request.
2. Set `version` in `maintenance.yaml` to the next SemVer value.
3. Validate locally:

   ```bash
   python3 -c "import yaml; yaml.safe_load(open('maintenance.yaml'))"
   bash -n scripts/*.sh
   ```

4. Merge the reviewed commit and create an immutable matching tag:

   ```bash
   git tag -a v0.3.0 -m "WSL maintenance v0.3.0"
   git push origin v0.3.0
   ```

Deployed clients never downgrade and never refetch a version they have already
installed. Publish a new tag for every change.

## VPN connector example

Add the connector below `scripts/`, make it idempotent and non-interactive, then
register it in the manifest. Use `runAs: root` only for the small privileged
portion. Keep credentials outside this repository and fetch them at runtime from
an approved secret or identity system.
