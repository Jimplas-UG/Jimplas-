# Fix: "can't find the computer" on \\tsclient\windows

That path only works if **drive sharing** is enabled in Remote Desktop.

## Option A — No shared folder (easiest)

On the **VPS**, Administrator PowerShell — paste **entire** file:

`vps-install-no-copy.ps1`

Or run line by line:

```powershell
Set-ExecutionPolicy Bypass -Scope Process -Force
git clone https://github.com/Jimplas-UG/Jimplas-.git C:\opt\bilshenz
cd C:\opt\bilshenz
# Then paste contents of vps-install-no-copy.ps1
```

Downloads everything from GitHub — **no \\tsclient\**.

## Option B — Fix drive sharing

Before connecting RDP:

1. Open **Remote Desktop Connection** (mstsc)
2. Click **Show Options** → **Local Resources** → **More...**
3. Under **Local devices and resources**, check **Drives**
4. Expand Drives → check **C:** or the folder `bsv3`
5. Connect to `104.194.140.203`

On VPS, find the share:

```powershell
Get-ChildItem \\tsclient\
Get-ChildItem \\tsclient\C\Users\Amoskole\bsv3\deploy\windows\
```

Copy zip from the path that exists:

```powershell
Copy-Item "\\tsclient\C\Users\Amoskole\bsv3\deploy\windows\bilshenz-vps-bundle.zip" C:\opt\
```

## After install (VPS only)

1. Install **Exness MT5** on the VPS (not your home PC)
2. Log in → **XAUUSD** in Market Watch
3. `Invoke-RestMethod http://127.0.0.1:8765/api/status`
4. `FORWARD_DRY_RUN=0` when ready
