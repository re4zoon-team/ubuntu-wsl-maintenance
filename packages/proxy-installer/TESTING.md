# Package validation

- Installer lifecycle/configuration suite includes refresh, certificate non-mutation, package bootstrap using edited settings, runtime upstream changes, invalid-setting rejection, uninstall and failure recovery. These use temporary files and mocked system/package commands.
- Controller suite: 152 isolated regression checks.
- The original Ubuntu-work installation remains unchanged; this revised package targets the company Ubuntu 26.04 image.
- No certificates or TLS helper assets are distributed. Package code is checksummed; editable upstream configuration is validated separately.

Run `./self-test.sh` for installer/configuration tests and `./payload/proxy test` for controller regressions. Live VPN-off, WSL restart and full application acceptance must still be checked after installation using the documented `proxy verify on|off` workflow. Isolated tests do not prove those network scenarios.
