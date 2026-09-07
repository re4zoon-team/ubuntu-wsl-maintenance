# Installation

## Supported target

- Ubuntu **26.04**, WSL2, Linux x86_64. Python 3, PyYAML, and the system CA trust store must already be available. Configure any required corporate trust separately before installation.
- systemd enabled in `/etc/wsl.conf` with `[boot]` / `systemd=true`. If this setting is changed, restart WSL before installation.
- A working user systemd session. Run from a normal terminal as the user who will own the tool, not as root.
- Docker Engine already installed, running, and accessible to that user without sudo.
- Existing Docker gateway **192.168.20.5/24**. The installer checks this and does not reconfigure Docker networks or install Docker.
- Sudo permission for package/bootstrap changes. Installation does not change sudo policy.
- A normal Linux home path without spaces or shell metacharacters.

The extra Docker network `opencode_gitlab_mcp_net` and the local OpenCode installation are needed for this environment's full `proxy verify` checks, not for the proxy service itself. OpenCode is expected at `/home/linuxbrew/.linuxbrew/bin/opencode`, with an existing authenticated account. Private-registry credentials must already be configured by the user. The installer does not copy or create them.

## Install

```bash
cd /home/sat/proxy-installer
./install.sh --dry-run
./install.sh
```

Only the final line is required once prerequisites are met. The package is relocatable: run `./install.sh` from wherever the complete folder was copied.

The installer:

1. Checks payload hashes, OS, user systemd, Docker access/network layout, and conflicting system proxy services.
2. Saves prior user-service state and all settings it will replace under `~/.local/state/wsl-proxy-installer/` (mode 0700).
3. Masks package-supplied root HAProxy/Tinyproxy services so only the user services own the endpoints.
4. Installs missing runtime packages through APT: HAProxy, Tinyproxy, netcat, curl, iproute2, util-linux. If the configured upstream is reachable, package bootstrap uses it directly. No root-level monitor is installed.
5. Stages the bundled payload, runs its controller regressions, and saves any pre-existing tool folder before replacing it.
6. Installs user-service links, the `proxy` launcher and shell startup blocks where no existing integration is present.
7. Merges only `proxies.default` into Docker's client JSON, preserving authentication and unrelated keys and file permissions.
8. Installs static APT and Docker-daemon proxy settings, enables user lingering, starts the user services, and selects automatic mode.
9. Restarts Docker only if the daemon proxy drop-in changed. Conflicting bind addresses or failed service startup trigger restoration of saved settings.

## Files and trust

Active tool: `~/.local/share/wsl-proxy/`. Command: `~/bin/proxy`. Generated state: `~/.cache/.proxy-state{,.pending,.lock}`. Generated HAProxy configuration: `~/.config/haproxy/proxy.cfg`. Installed user units link into the active tool's `systemd/` folder.

System integrations are `/etc/apt/apt.conf.d/90-tinyproxy` and `/etc/systemd/system/docker.service.d/90-tinyproxy.conf`.

The installer does not bundle certificates or alter trust stores. Existing trust remains managed separately. `checksums.yaml` checks package code and documentation; the editable `payload/config/proxy.yaml` is validated separately and excluded from hashes.

## Validate

Open a new shell, or run `source ~/.cache/.proxy-state`, then:

```bash
proxy status
proxy test
proxy verify on
```

Disconnect VPN, wait for `proxy status` to report `route: off`, then run `proxy verify off`. Reconnect and repeat `proxy verify on`. Finally restart WSL at a convenient time and repeat the applicable command.

The monitor pauses five seconds between checks and requires two successes or three failures. Probe duration adds to that interval. `pending: none` and active services are expected after a settled transition.

APT verification uses user-owned indices/cache and does not need sudo. Docker pulls/builds use the two documented public/company images. Full verification additionally exercises fresh Zsh, both approved container networks, and authenticated OpenCode streaming. Missing validation tools/networks or repository signing-key failures produce a real failure rather than a false success.

## Limits

Installing/reinstalling replaces the application folder and restarts proxy services, so active tunnels can be interrupted. Ordinary route reloads remain graceful. Packages downloaded by APT remain installed after uninstall. Do not modify the saved installation journal or move its backups. A killed installer can be recovered with `./uninstall.sh`; inspect errors if the journal reports an incomplete installation.
