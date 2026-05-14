/**
 * Writes expo-go-qr.png encoding exp://<LAN_IP>:<PORT>
 * Run while Metro is up (default port 8081). Override: METRO_PORT=8082 node scripts/make-expo-qr.js
 */
const fs = require('fs');
const path = require('path');
const os = require('os');
const QRCode = require('qrcode');

function lanIpv4() {
  const nets = os.networkInterfaces();
  for (const name of Object.keys(nets)) {
    for (const addr of nets[name] || []) {
      if (addr.family === 'IPv4' && !addr.internal) return addr.address;
    }
  }
  return '127.0.0.1';
}

const port = process.env.METRO_PORT || process.env.EXPO_METRO_PORT || '8081';
const ip = process.env.EXPO_LAN_IP || lanIpv4();
const url = `exp://${ip}:${port}`;
const out = path.join(__dirname, '..', 'expo-go-qr.png');

QRCode.toFile(out, url, { width: 420, margin: 2, errorCorrectionLevel: 'M' })
  .then(() => {
    console.log('Wrote', out);
    console.log('Payload:', url);
    console.log('Open Expo Go (SDK 52) on your phone and scan expo-go-qr.png');
  })
  .catch((err) => {
    console.error(err);
    process.exit(1);
  });
