# Upstream configuration

Before installation, edit `payload/config/proxy.yaml` inside this package. After installation, edit `~/.local/share/wsl-proxy/config/proxy.yaml` as your normal Linux user:

```yaml
upstream_host: 'fortiproxy.intranet.nav.gov.hu'
upstream_port: 8080
```

Use a DNS hostname or IPv4 address, without a scheme or path, and an integer port from 1 to 65535. Both the installer package-download bootstrap and the controller use this configuration. There are no upstream host defaults in installer code.

Save both values together. The monitor reads the file on each check (a five-second pause between checks). Run `proxy check` to apply it immediately, then `proxy status`. No sudo, reinstall or service restart is needed. Normal detection thresholds still apply. Invalid YAML or invalid values make a check fail before changing routing; the current listener configuration remains intact. Fix the file and the monitor retries.

The installed file is independent of the package copy. Editing the package after installation does not modify the running tool. `PROXY_HOST` and `PROXY_PORT` environment overrides remain available for isolated tests; use the file for persistent service configuration.

The stable local listeners remain `127.0.0.1:18080` and `192.168.20.5:18080`. Those addresses are part of the existing APT/Docker network integration, not corporate upstream hosts. This is one upstream HTTP proxy, not a PAC/WPAD rules engine or a multiple-upstream failover list.

Certificate trust is managed separately. The tool uses the system CA bundle `/etc/ssl/certs/ca-certificates.crt` by default. `PROXY_CA_BUNDLE` can override the path for a command invocation. Verification may read/mount that existing bundle; the installer never supplies or changes it.
