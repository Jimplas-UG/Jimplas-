# Cursor / agents — hard rule

**Never** run `mstsc`, `rdp-*.ps1`, `move-to-vps-only.ps1`, or FreeRDP against `104.194.140.203`.

Use only:
- `GODMODE-SSH-DEPLOY.ps1` (user runs locally with `$env:VPS_PW`)
- `CONSOLE-PASTE-INSTALL.ps1` (user pastes in hosting web console)

RDP scripts are renamed to `*.ps1.disabled`.
