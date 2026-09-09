"""Install the maintenance demo shortcut and its icon on the Windows desktop."""
import base64
import os
from pathlib import Path
import re
import subprocess


def main():
    if os.geteuid() == 0:
        raise SystemExit('Run the desktop shortcut task as the registered developer')
    icon = Path.home() / '.local/share/company-dev/maintenance.ico'
    if not icon.is_file():
        raise SystemExit('The maintenance icon has not been distributed')
    root = subprocess.check_output(['/usr/bin/wslpath', '-w', '/'], text=True).strip()
    distro = root.split('\\')[3]
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]*', distro):
        raise SystemExit('Unexpected WSL distribution name')
    windows_icon = subprocess.check_output(['/usr/bin/wslpath', '-w', str(icon)], text=True).strip()
    # Background systemd tasks do not inherit an interactive shell's WSL_INTEROP.
    environment = dict(os.environ, WSL_INTEROP='/run/WSL/1_interop')
    powershell = Path('/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe')
    script = f"""
$ErrorActionPreference = 'Stop'
$source = '{windows_icon.replace("'", "''")}'
$assets = Join-Path $env:LOCALAPPDATA 'Company\\DevImage\\assets'
New-Item -ItemType Directory -Force $assets | Out-Null
$icon = Join-Path $assets 'company-maintenance.ico'
Copy-Item -LiteralPath $source -Destination $icon -Force
$path = Join-Path ([Environment]::GetFolderPath('Desktop')) 'Company Dev - Maintenance.lnk'
$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($path)
$shortcut.TargetPath = Join-Path $env:SystemRoot 'System32\\wsl.exe'
$shortcut.Arguments = '-d {distro} --cd ~ --exec /usr/bin/xclock -digital -update 1 -title Company-Maintenance'
$shortcut.WorkingDirectory = [Environment]::GetFolderPath('UserProfile')
$shortcut.Description = 'Company maintenance demo, delivered through the updater'
$shortcut.IconLocation = "$icon,0"
$shortcut.Save()
Write-Output "Installed $path"
"""
    encoded = base64.b64encode(script.encode('utf-16le')).decode('ascii')
    subprocess.run([str(powershell), '-NoProfile', '-NonInteractive', '-EncodedCommand', encoded],
                   env=environment, check=True, timeout=60)


if __name__ == '__main__':
    main()
