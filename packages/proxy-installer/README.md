# WSL proxy installer

A self-contained **tool installation folder** for the Pillér/NAV proxy setup on Ubuntu 26.04 in WSL2. Copy the entire folder; no files are read from the original development installation. Ubuntu runtime packages are installed through APT if missing, so a clean machine may need network access. This is not an offline Ubuntu/Docker distribution.

## One-command workflows

Run as the intended Linux user, **without prefixing sudo**:

```bash
./install.sh
```

The installer requests sudo for system setup. Normal operation needs no sudo. Installation can restart Docker if its daemon proxy configuration changes; plan around running containers.

```bash
./install.sh --dry-run   # validate payload/prerequisites and show the plan; no changes
./self-test.sh           # isolated installer lifecycle tests; no sudo or network
./uninstall.sh          # restore saved integration settings
```

The default installation location is `~/.local/share/wsl-proxy`. Your existing `proxy` command remains in `~/bin`. Re-running this package on its managed installation is a no-op; uninstall before installing a different package version.

## Documentation

- [Installation and prerequisites](docs/INSTALL.md)
- [Uninstall and recovery](docs/UNINSTALL.md)
- [Using the tool](docs/TOOL.md)
- [Architecture](docs/ARCHITECTURE.md)

The folder includes the controller, Python helpers, regression suite, service/config templates. It contains **no account or application credentials**, private keys, images, old installation logs, or external-folder symlinks.

This package preserves the current HAProxy + Tinyproxy architecture. WPAD/PAC support is not included. Real VPN-off and WSL reboot acceptance remain separate checks; installer self-tests do not prove those network scenarios.

Upstream host/port settings: edit `~/.local/share/wsl-proxy/config/proxy.yaml`; the monitor reloads them on its next check. See the installer package’s `docs/CONFIGURATION.md` for package defaults and validation. Certificates are managed separately; this installer supplies none.
