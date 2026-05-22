# Push deploy folder to GitHub (required for VPS git clone)

The VPS clone failed because **`deploy/` was never on GitHub** — only `backend` and `mt5_trading_system` were pushed.

## One-time fix (on your PC)

```powershell
cd c:\Users\Amoskole\bsv3
git add deploy/ backend/production/
git status
git commit -m "Add Windows VPS deploy scripts and production safety layer"
git push origin main
```

Verify:

```powershell
git ls-tree -r --name-only origin/main deploy/windows/production-setup.ps1
```

Should print the file path.

## VPS install after push

```powershell
powershell -NoExit -ExecutionPolicy Bypass
```

Then:

```powershell
iwr -UseBasicParsing https://raw.githubusercontent.com/Jimplas-UG/Jimplas-/main/deploy/windows/vps-clone-install.ps1 -OutFile C:\opt\vps-clone-install.ps1
powershell -ExecutionPolicy Bypass -File C:\opt\vps-clone-install.ps1
```

Or clone manually:

```powershell
git clone --depth 1 https://github.com/Jimplas-UG/Jimplas-.git C:\opt\bilshenz
cd C:\opt\bilshenz\deploy\windows
.\production-setup.ps1
```
