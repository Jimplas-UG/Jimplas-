const TOKEN = (process.env.TELEGRAM_BOT_TOKEN ?? '').trim();
const CHAT = (process.env.TELEGRAM_CHAT_ID ?? '').trim();

export async function notifyTelegram(text: string): Promise<void> {
  if (!TOKEN || !CHAT) return;
  try {
    const url = `https://api.telegram.org/bot${TOKEN}/sendMessage`;
    await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ chat_id: CHAT, text: text.slice(0, 4000) }),
      signal: AbortSignal.timeout(12_000),
    });
  } catch {
    /* non-fatal */
  }
}
