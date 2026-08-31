# Security policy

This repository is a privileged deployment channel. Do not add credentials,
private keys, VPN secrets, kubeconfigs, registry tokens, or developer data.

Root tasks must be narrowly scoped, idempotent, time-bounded, and safe when run
more than once. User tasks must not assume a particular username or home path.
Use `$HOME` and XDG directories supplied by the generated systemd service.

If a release is faulty, fix it with a higher SemVer tag. Never rewrite or delete
an existing tag as a rollback mechanism. For urgent containment, disable the task
in a new release and publish that release immediately.
