# Uninstall and recovery

From the retained installer folder, as the original Linux user:

```bash
./uninstall.sh
```

It requests sudo only to restore system integrations. It does not remove Ubuntu packages or Docker images.

Uninstall stops/disables the three managed user services, restores saved unit links, launchers, APT/Docker-daemon settings, then restores previous service enablement/activity and lingering. Docker restarts if its daemon proxy drop-in was changed by installation.

For Docker client settings, only the installed proxy configuration is undone when other JSON fields changed later. Newly added registry credentials are preserved. Installer-added shell blocks are removed while preserving unrelated later shell edits. Existing shell integrations that the installer left alone are left alone on uninstall.

Modified managed configuration outside those mergeable cases causes uninstall to stop **before stopping services or overwriting the change**. The error identifies the path. Compare it with the saved backup and restore the expected installed contents before retrying, or manually reconcile the setting. No force-overwrite option is supplied.

If a tool installation existed before this installer, it is restored. Thus uninstall may return to the previous working proxy setup rather than removing all proxy functionality. On a fresh installation, its new integration files are removed.

The removed tool folder (including logs or local edits), previous-file backups, and journal are retained in a timestamped directory beside `~/.local/state/wsl-proxy-installer`. This avoids deleting diagnostic/user data. Removing that historical directory later is optional and is not needed to uninstall.

## Installation failure

The installer attempts rollback if a step fails. Saved files and prior service states are restored; packages installed during bootstrap remain available. If the process was terminated or rollback could not finish, rerun `./uninstall.sh` as the same user. Keep the journal/backups until recovery succeeds.

Do not run a historical `restore-layout` command from earlier development snapshots. The packaged tool does not expose that command; the installer journal is the supported recovery mechanism.

## Remove installer files

Keep this self-contained folder until uninstall is no longer needed. If it must be moved, move it whole. The uninstall journal identifies installed paths independently of the package's location. Do not copy the journal to a different account or machine.
