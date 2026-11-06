# Move Bilshenz to Oracle Cloud

The bot installs with trading off and does not start itself. Stay on testnet until you
order mainnet.

## 1. Create the server (Oracle console)

| Setting | Value |
|---|---|
| Region | **Germany Central (Frankfurt)**. Binance blocks some regions, including the US |
| Image | Canonical Ubuntu 24.04 (match the image to the shape) |
| Shape | `VM.Standard.A1.Flex`, 2 OCPU, 12 GB. Avoid `E2.1.Micro`: 1 GB is too small |
| Public IP | **Reserved**, so the phone app survives a rebuild |
| SSH | Your public key. The login user is `ubuntu`, not `root` |

Then add ingress rules to the subnet's security list for TCP **8766** and **8791**.
Limit SSH (22) to your own IP if it is stable.

**Keep the server from being reclaimed:** Oracle can reclaim idle Always Free instances, and
this bot uses little CPU. Moving the account to Pay As You Go avoids that, and Always Free
usage stays free. Check Oracle's current terms, because third-party sources disagree on the
thresholds.

## 2. Build and upload (your PC)

```powershell
python deploy/oracle/make_bundle.py
scp deploy/oracle/dist/bilshenz-oracle-*.tar.gz deploy/oracle/install-oracle.sh ubuntu@NEW_IP:~/
```

The bundle comes from your working tree, so it includes fixes that are not committed yet.

## 3. Install (Oracle server)

```bash
sudo bash ~/install-oracle.sh ~/bilshenz-oracle-*.tar.gz
```

This installs everything and runs all test suites. It stops if any test fails.

## 4. Copy settings and state from the old server

Run on the old server, then copy the archive across. It contains secrets, so delete it afterwards.

```bash
sudo tar -czf ~/bilshenz-state.tgz /etc/bilshenz.env /var/lib/bilshenz
```

On Oracle:

```bash
sudo tar -xzf ~/bilshenz-state.tgz -C /
sudo chmod 600 /etc/bilshenz.env
sudo sed -i 's/^SCANNER_EXEC=.*/SCANNER_EXEC=0/' /etc/bilshenz.env
rm ~/bilshenz-state.tgz
```

Add `REST_BAN_FILE` and `TRADE_HISTORY_CACHE_FILE` from `bilshenz.env.template` if they are missing.

## 5. Check, then start with trading off

```bash
sudo bash /opt/bilshenz/deploy/oracle/preflight.sh
sudo systemctl start bilshenz-binance-api bilshenz-desk-api
sudo bash /opt/bilshenz/deploy/ubuntu/healthcheck.sh
```

Watch the log for a few minutes: `sudo tail -f /var/log/bilshenz/binance-api.log`

## 6. Point the phone app at the new IP

```powershell
python deploy/oracle/retarget_app.py NEW_IP
python deploy/oracle/retarget_app.py NEW_IP --apply
```

Then rebuild the APK. The old app keeps talking to the old server until you install the new one.

## 7. Cut over

**Never run both servers with trading on.** Two bots on one API key double-trade the account.

1. On the old server, confirm no open positions, closing any from the app.
2. Stop it for good:
   `sudo systemctl stop bilshenz-binance-api bilshenz-desk-api && sudo systemctl disable bilshenz-binance-api bilshenz-desk-api`
3. Check the Binance testnet site shows no positions or open orders.
4. On Oracle:
   `sudo bash /opt/bilshenz/deploy/oracle/arm-trading.sh on --old-server-stopped --book-flat`

If the API key has an IP allow-list, add the new IP first.

**Turn trading off:** `sudo bash /opt/bilshenz/deploy/oracle/arm-trading.sh off`
This blocks new entries. Open pairs still need managing or closing from the app.

**Watchdog:** a timer checks the bridge every 30 seconds and restarts it only if it is hung
(three failed checks, at most three restarts an hour). It never starts a service you stopped.
Actions are logged to `/var/log/bilshenz/watchdog.log`.

**Roll back:** turn trading off on Oracle, stop its services, then re-enable and start the old
server. Keep the old server for a week before deleting it.

## 8. First 48 hours

```bash
cd /var/log/bilshenz
grep -c 'scanner SHORT ' binance-api.log    # trades are flowing again
grep -c 'EXEC_TP_REJECTED' binance-api.log  # above 0 means resting take-profits are refused
grep -c '418 IP ban' binance-api.log        # should stay at 0
grep 'reason=SHORT_TP' binance-api.log | tail
grep -c 'CIRCUIT_OPEN' binance-api.log      # new entries paused by repeated failures
grep -c 'EXEC_UNKNOWN' binance-api.log      # order outcomes that needed reconciling
grep -c 'RECONCILE_QTY' binance-api.log     # bot size corrected from the exchange
grep -c 'DUPLICATE_WORKER' binance-api.log  # a second bridge was refused
cat watchdog.log                            # every watchdog action
```

Judge P&L from Binance income records only, and allow days rather than hours: normal daily
swings are large.
