# WSL proxy

Active folder: `~/.local/share/wsl-proxy`. Routine operation is unprivileged.

There is one executable, `proxy`. `~/bin/proxy` links to it. Proxy operations use subcommands:

```bash
proxy status
proxy auto                # automatic routing
proxy on                  # corporate override
proxy off                 # direct override
proxy toggle
proxy check               # probe immediately
proxy stop                # stop monitor only; endpoints stay running
proxy start               # start monitor
proxy test                # isolated regressions
proxy verify on           # live VPN-connected acceptance
proxy verify off          # live VPN-disconnected acceptance
```

The monitor waits five seconds between checks. Routing changes after two successful or three failed probes; network/DNS timeouts can extend detection time. Check `proxy status` for the expected route before running `proxy verify`. It checks services, host HTTP/HTTPS, fresh Zsh, APT updates, Docker image pulls and uncached builds, both approved Docker networks, and complete authenticated OpenCode streaming. It uses this machine's existing registry credentials and CA bundle; it does not change routing.

## Acceptance coverage

`proxy verify on` pulls and builds from both images:

- `registry.suse.com/bci/bci-base:15.7`
- `docker.nexus.secdmz.nav.gov.hu/nav-builder/suse:0.3.0`

Each uncached build checks the Docker-injected proxy environment and makes HTTP and HTTPS requests. The existing CA bundle is mounted read-only during the build and is not copied into the image. Test images are removed afterward; Docker build cache and pulled base images remain. Corporate image checks are skipped when the direct route is selected.

APT checks use the installed proxy configuration and user-owned indices/cache, with administrative hooks disabled. Both all configured repositories and Ubuntu-only repositories are tested. Signature checks stay enabled, and any repository failure fails the overall suite. No root access or system APT state changes are required. Per-check logs, build contexts, and `results.json` are saved in `logs/acceptance/`.

## Files

| Path | Purpose |
|---|---|
| `proxy` | Only executable: controller, command dispatch |
| `lib/operations.py` | Non-executable Python helpers for reload and verification |
| `tests/controller.sh` | Non-executable regression suite, invoked by `proxy test` |
| `systemd/` | Authoritative user service units; installed locations link here |
| `config/tinyproxy-direct.conf` | Direct backend configuration |
| `logs/acceptance/` | New live test logs |

Generated state remains at `~/.cache/.proxy-state{,.pending,.lock}` and HAProxy configuration at `~/.config/haproxy/proxy.cfg`. Edit `config/proxy.yaml` to change the upstream host or port; do not edit generated HAProxy configuration. Certificate trust is managed separately.

## Shells and containers

Zsh loads the stable environment once at startup, with no per-prompt controller call. For an existing shell: `source ~/.cache/.proxy-state`. Existing Bash integration also sources this file.

Host clients use `http://127.0.0.1:18080`; containers/builds use `http://192.168.20.5:18080`. Ordinary `docker run` and Docker builds use the existing Docker client proxy configuration. There is no Docker wrapper or alias. Container HTTPS needs the appropriate CA trust, for example:

```bash
docker run --rm \
  --mount type=bind,src=/etc/ssl/certs/ca-certificates.crt,dst=/tmp/proxy-ca.pem,readonly \
  registry.suse.com/bci/bci-base:15.7 \
  curl --cacert /tmp/proxy-ca.pem --fail https://example.com
```

## Maintenance

Run `proxy test` before applying controller changes. Then restart the monitor with `systemctl --user restart proxy-monitor`. It applies changed rendered configuration on its next check. After editing units, run `systemctl --user daemon-reload`. Direct-backend configuration changes require `systemctl --user restart proxy-direct`, interrupting existing direct connections.

Logs: `journalctl --user -u proxy-endpoint -u proxy-direct -u proxy-monitor`.

Installation is performed by the base image during onboarding. This runtime
package contains no installation or removal tooling. The image removes its
bootstrap after successful setup; contact the image maintainer for repair.


VPN-off and WSL restart acceptance remain pending. The GitHub CLI signing key was updated on 7 September 2026; full system APT update now passes. See [ARCHITECTURE.md](ARCHITECTURE.md) for the design and verification boundary.

Upstream host/port settings: edit `~/.local/share/wsl-proxy/config/proxy.yaml`; the monitor reloads them on its next check. See the installer package’s `docs/CONFIGURATION.md` for package defaults and validation. Certificates are managed separately; this installer supplies none.
