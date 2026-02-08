import React, { useEffect, useState, useRef } from 'react';

type Strategy = {
  id: string;
  name?: string;
  lastHeartbeat?: string | null;
  lastTradeAt?: string | null;
  openPosition?: any;
  pnl?: number | null;
};

function resolveApiBase(): string {
  const envVal = process.env.NEXT_PUBLIC_API_URL as string | undefined;
  if (envVal && envVal.trim().length > 0) return envVal;
  if (typeof window !== 'undefined') {
    const host = window.location.hostname;
    // In production on Render, default to the live API if env is missing
    if (host && host !== 'localhost' && host !== '127.0.0.1') {
      return 'https://nunuirl-platform.onrender.com';
    }
  }
  // Local dev fallback
  return 'http://localhost:8000';
}

export default function StrategyList() {
  const [strategies, setStrategies] = useState<Strategy[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [cursor, setCursor] = useState<string | null>(null);
  const [autoRefresh, setAutoRefresh] = useState(true);
  const [lastStatus, setLastStatus] = useState<number | null>(null);
  const [rawPreview, setRawPreview] = useState<string | null>(null);
  const [itemCount, setItemCount] = useState<number>(0);
  const backoff = useRef(1000);
  const isMounted = useRef(true);

  // Determine API base at runtime to avoid "localhost" fallback in production when env isn't baked in
  const apiBase = resolveApiBase();

  const fetchWithTimeout = async (url: string, options: RequestInit = {}, timeoutMs = 10000) => {
    const controller = new AbortController();
    const id = setTimeout(() => controller.abort(), timeoutMs);
    try {
      const res = await fetch(url, { ...options, signal: controller.signal });
      return res;
    } finally {
      clearTimeout(id);
    }
  };

  const fetchStrategies = async (useCursor = false) => {
    try {
      setError(null);
      const url = new URL(`${apiBase}/v1/strategies`);
      if (useCursor && cursor) url.searchParams.set('cursor', cursor);
      const res = await fetchWithTimeout(url.toString());
      setLastStatus(res.status);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const text = await res.text();
      setRawPreview(text ? text.slice(0, 500) : null);
      let data: any;
      try { data = text ? JSON.parse(text) : {}; } catch (e) {
        throw new Error('Invalid JSON from API');
      }
      // support { items: [...], next_cursor } or plain array
      const items = Array.isArray(data) ? data : data.items || [];
      const next = data.next_cursor || null;
      if (!isMounted.current) return;
      setStrategies(items as Strategy[]);
      setItemCount((items as any[]).length || 0);
      setCursor(next);
      setLoading(false);
      backoff.current = 1000;
    } catch (err: any) {
      if (!isMounted.current) return;
      setError(err.message || String(err));
      setLoading(false);
      backoff.current = Math.min(30000, backoff.current * 2);
      // schedule a retry after backoff
      setTimeout(() => fetchStrategies(useCursor), backoff.current);
    }
  };

  useEffect(() => {
    isMounted.current = true;
    fetchStrategies();
    const iv = setInterval(() => { if (autoRefresh) fetchStrategies(); }, 10000);
    return () => {
      isMounted.current = false;
      clearInterval(iv);
    };
  }, [autoRefresh]);

  const isOnline = (s: Strategy) => {
    const tsStr = (s as any).lastHeartbeat || (s as any).last_seen || s.lastHeartbeat;
    if (!tsStr) return false;
    const ts = Date.parse(tsStr);
    if (isNaN(ts)) return false;
    return (Date.now() - ts) / 1000 <= 120;
  };

  const getPnl = (s: Strategy) => {
    return (s as any).pnl_realized ?? (s as any).pnl ?? (s as any).realizedPnL ?? null;
  };

  return (
    <main style={{ padding: 20 }}>
      <h1>Strategies</h1>
      <div style={{ fontSize: 12, color: '#666', marginBottom: 8 }}>API: {apiBase}</div>
      <div style={{ marginBottom: 8 }}>
        <label>
          <input type="checkbox" checked={autoRefresh} onChange={(e)=>setAutoRefresh(e.target.checked)} /> Auto-refresh
        </label>
        <button style={{ marginLeft: 8 }} onClick={() => { setLoading(true); fetchStrategies(); }}>Refresh now</button>
      </div>
      {error && (
        <div style={{ background: '#fee', padding: 10, borderRadius: 6, marginBottom: 12 }}>
          <strong>Error:</strong> {error} <button onClick={() => { setError(null); setLoading(true); fetchStrategies(); }}>Retry</button>
        </div>
      )}
      <details style={{ marginBottom: 12 }}>
        <summary>Debug</summary>
        <div style={{ fontSize: 12, color: '#444' }}>
          <div>Status: {lastStatus ?? '—'}</div>
          <div>Items: {itemCount}</div>
          <pre style={{ whiteSpace: 'pre-wrap', background: '#f7f7f7', padding: 8, borderRadius: 6 }}>{rawPreview ?? '—'}</pre>
        </div>
      </details>
      {loading && <p>Loading…</p>}
      {!loading && strategies.length === 0 && <p>No strategies found.</p>}
      <ul style={{ listStyle: 'none', padding: 0 }}>
        {strategies.map((s) => (
          <li key={s.id} style={{ marginBottom: 12, padding: 10, border: '1px solid #eee', borderRadius: 6 }}>
            <a href={`/strategies/${encodeURIComponent(s.id)}`}>
              <strong>{s.name || s.id}</strong>
            </a>
            <div style={{ marginTop: 6 }}>
              <span style={{ padding: '4px 8px', borderRadius: 6, background: isOnline(s) ? '#4caf50' : '#ddd', color: isOnline(s) ? '#fff' : '#333' }}>
                {isOnline(s) ? 'online' : 'offline'}
              </span>
              <span style={{ marginLeft: 12 }}>lastHeartbeat: {(s as any).lastHeartbeat || (s as any).last_seen || '—'}</span>
              <span style={{ marginLeft: 12 }}>lastTrade: {(s as any).lastTradeAt || (s as any).last_trade_ts || '—'}</span>
              <span style={{ marginLeft: 12 }}>
                <strong>PnL:</strong> {getPnl(s) ?? '—'}
              </span>
            </div>
            <div style={{ marginTop: 8 }}>
              {((s as any).open_position) ? (
                <div style={{ background: '#fafafa', padding: 8, borderRadius: 6 }}>
                  <div>Open: {(s as any).open_position.side} {(s as any).open_position.size}</div>
                  <div>Avg entry: {(s as any).open_position.avg_entry}</div>
                </div>
              ) : (
                <div style={{ color: '#666' }}>No open position</div>
              )}
            </div>
          </li>
        ))}
      </ul>
      <div style={{ marginTop: 12 }}>
        {cursor ? (
          <button onClick={() => fetchStrategies(true)}>Next page</button>
        ) : null}
      </div>
    </main>
  );
}
