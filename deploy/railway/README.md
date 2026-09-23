# Bilshenz on Railway + Vercel (leave DigitalOcean)
#
# IMPORTANT
# - Trading MUST run on Railway (always-on). Never on Vercel serverless.
# - Primary UI today is Expo APK (EAS), NOT Next.js.
# - Vercel is optional Phase-2 for Expo web only.
#
# Railway services (create 2 services from same repo):
#   1) bilshenz-bridge  — Dockerfile path: Dockerfile
#   2) bilshenz-desk    — Dockerfile path: deploy/railway/Dockerfile.desk
#
# Attach a shared volume mounted at /data on BOTH services (or at least bridge).

## Service A — Python Binance bridge (trading engine)

Root Directory: (repo root)
Dockerfile: Dockerfile
Start: (from Dockerfile CMD)
Health: GET /health on $PORT

Required env:
  BILSHENZ_ENV=production
  HOST=0.0.0.0
  PORT=${{PORT}}
  BRIDGE_TOKEN=<long-random>
  SESSION_ENC_KEY=<long-random>
  BINANCE_SESSION_FILE=/data/binance-session.json
  SCANNER_RISK_CONFIG_PATH=/data/scanner-risk.json
  LOG_DIR=/data/logs
  SCANNER_EXEC=1
  FORWARD_DRY_RUN=0
  BINANCE_TESTNET=0
  BINANCE_PAPER=0
  # Optional server-held keys (or connect via app login):
  # BINANCE_API_KEY=
  # BINANCE_API_SECRET=
  SCANNER_INVALIDATION_PCT=6.5
  SCANNER_RESCUE_BUFFER_PCT=1.0

Public networking: enable HTTPS domain, e.g. https://bridge-xxxx.up.railway.app
(Prefer keeping bridge PRIVATE and only expose desk — see below.)

## Service B — Node desk-api (public API)

Root Directory: (repo root)
Dockerfile: deploy/railway/Dockerfile.desk
Health: GET /health on $PORT

Required env:
  BILSHENZ_ENV=production
  DESK_API_PORT=${{PORT}}
  DESK_API_KEY=<long-random>
  PRODUCTION_MODE=1
  BINANCE_API_URL=http://${{bilshenz-bridge.RAILWAY_PRIVATE_DOMAIN}}:8766
  # Or Railway private DNS name Railway injects — set after bridge is up:
  # BINANCE_API_URL=http://bilshenz-bridge.railway.internal:8766
  AUTH_JWT_SECRET=<long-random>
  AUTH_DATA_DIR=/data/auth
  CORS_ORIGINS=https://YOUR-VERCEL-APP.vercel.app,http://localhost:8081
  STRATEGY_FREEZE=1

Public networking: https://api-xxxx.up.railway.app  ← Expo / Vercel points here

## Volume

Mount name: bilshenz-data
Mount path: /data
Attach to: bridge (required) and desk (for auth JSON until Postgres)

## Expo / EAS (not Vercel)

In eas.json production env (or EAS secrets):
  EXPO_PUBLIC_DESK_API_URL=https://api-xxxx.up.railway.app
  EXPO_PUBLIC_BINANCE_API_URL=https://api-xxxx.up.railway.app/v1/binance
  EXPO_PUBLIC_DESK_API_KEY=<same as DESK_API_KEY>
  EXPO_PUBLIC_AUTH_REQUIRED=1
  EXPO_PUBLIC_BROKER_MODE=binance

Rebuild APK after URL change.

## Vercel (optional web only)

Only after `npx expo export --platform web` works:
  EXPO_PUBLIC_DESK_API_URL=https://api-xxxx.up.railway.app
  EXPO_PUBLIC_BINANCE_API_URL=https://api-xxxx.up.railway.app/v1/binance
Never put BINANCE_API_SECRET / DATABASE_URL / BRIDGE_TOKEN in Vercel public env
except DESK_API_KEY if you still use the machine key (prefer user JWT only).

## Cutover checklist

1. Create Railway project + volume + two services
2. Set env vars (no DO IP)
3. Deploy bridge, confirm /health
4. Deploy desk with BINANCE_API_URL → private bridge
5. Point Expo EAS env at desk HTTPS URL; rebuild APK
6. Stop DO systemd units when Railway is stable
7. (Later) Postgres for auth; remove client-held Binance keys

## What NOT to do

- Do not put the Python scanner on Vercel
- Do not use scale-to-zero on the bridge service
- Do not keep http://157.245.33.42 in production builds
