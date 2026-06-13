# Binance Futures install (BSV3.2)

1. Create Binance Futures **testnet** API key: https://testnet.binancefuture.com
2. Whitelist your VPS/home IP on the API key.
3. Start the Python bridge:

```powershell
cd binance_trading_system\python
$env:BINANCE_API_KEY = "..."
$env:BINANCE_API_SECRET = "..."
$env:BINANCE_TESTNET = "1"
.\start-api.ps1
```

4. Start desk-api with `BINANCE_API_URL=http://127.0.0.1:8766`.
5. Set `EXPO_PUBLIC_BROKER_MODE=binance` in the Expo app.

See `docs/BINANCE_DEPLOYMENT.md` for full guide.
