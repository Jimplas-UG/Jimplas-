export async function fetchWithRetry(
  url: string,
  opts?: RequestInit & { retries?: number; baseMs?: number }
): Promise<Response> {
  const retries = opts?.retries ?? 5;
  const baseMs = opts?.baseMs ?? 1000;
  let lastErr: unknown;
  for (let i = 0; i <= retries; i++) {
    try {
      const res = await fetch(url, {
        ...opts,
        signal: AbortSignal.timeout(20_000),
      });
      if (res.ok || res.status < 500) return res;
      lastErr = new Error(`HTTP ${res.status}`);
    } catch (e) {
      lastErr = e;
    }
    if (i < retries) {
      const delay = Math.min(baseMs * 2 ** i, 120_000);
      await new Promise((r) => setTimeout(r, delay));
    }
  }
  throw lastErr instanceof Error ? lastErr : new Error(String(lastErr));
}
