# Proxy runtime

The Python `proxy` command selects a corporate upstream or a direct Tinyproxy route.
Use `proxy status`, `proxy on`, `proxy off`, or `proxy auto`.
The monitor checks every five seconds, switching after two successes or three failures.

Edit `config/proxy.yaml` to change the upstream hostname and port.
Bash and Zsh use the same generated proxy exports. Certificate trust is managed
by the image, not this controller.

HAProxy listens on localhost and the configured Docker bridge, with source restrictions.
The user services are `proxy-endpoint`, `proxy-direct`, and `proxy-monitor`.
`lib/controller.py` owns routing and persistent state.
`lib/operations.py` validates HAProxy configuration and confirms graceful reloads.
Maintenance refresh preserves user configuration and restores the old runtime if restart fails.
Tests and installation tools are not part of the deployed runtime.
