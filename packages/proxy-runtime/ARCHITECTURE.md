# Proxy routing

Applications use a stable local HAProxy endpoint. The controller routes traffic
through the configured corporate proxy when reachable, otherwise through local
Tinyproxy. Manual on/off modes override automatic detection.

The Python controller reads upstream YAML directly and reads its shell-export state as data.
It serializes updates with a lock and records pending transitions
so interrupted reloads can be retried. HAProxy validates configuration before
a graceful reload. Three user systemd services run the endpoint, direct backend,
and monitor. Maintenance replaces the runtime while preserving user configuration.
