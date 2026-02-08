'use client';

import React, { useEffect, useState } from 'react';
import { useRouter } from 'next/router';

type LogEntry = {
  ts: string;
  event: string;
  details?: Record<string, any>;
};

type LatestSignal = {
  label: string;
  score: number;
  market: string;
  price: number;
  trend: { sma20: 'Up' | 'Down'; sma50: 'Up' | 'Down'; rsi14: number };
  zones: { deepAccum: number; accum: number; distrib: number; safeDistrib: number };
};

type StrategyCard = {
  id: string;
  name: string;
  status: string;
  lastEvaluated: string;
  latestSignal: LatestSignal | null;
};

type Summary = {
  updatedAt?: number | null;
  regime?: string;
  status?: string;
  errors?: number;
  mostRecentTrade?: {
    strategyId: string;
    name: string;
    market: string;
    action: string;
    price: number;
    ts: string;
  } | null;
};

function resolveApiBase(): string {
  const envVal = (process.env.NEXT_PUBLIC_API_URL as string | undefined) || (process.env.NEXT_PUBLIC_API_BASE_URL as string | undefined);
  if (envVal && envVal.trim().length > 0) return envVal;
  if (typeof window !== 'undefined') {
    const host = window.location.hostname;
    if (host && host !== 'localhost' && host !== '127.0.0.1') {
      return 'https://nunuirl-platform.onrender.com';
    }
  }
  return 'http://localhost:8000';
}

export default function StrategyDetail() {
  const router = useRouter();
  const { id } = router.query;
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [card, setCard] = useState<StrategyCard | null>(null);
  const [summary, setSummary] = useState<Summary | null>(null);
  const apiBase = resolveApiBase();

  // Safe number formatter to avoid .toFixed on undefined/null
  const fmt = (v: any, digits = 2) => {
    const n = typeof v === 'number' ? v : Number.isFinite(Number(v)) ? Number(v) : NaN;
    return Number.isFinite(n) ? n.toFixed(digits) : '—';
  };

  useEffect(() => {
    if (!id) return;

    const fetchLogs = async () => {
      try {
        setError(null);
        const res = await fetch(`${apiBase}/v1/strategies/${id}/logs`, { cache: 'no-store' });
        if (res.ok) {
          const data = await res.json();
          // Handle both array response and { value: [], Count: N } response
          const items = Array.isArray(data) ? data : data?.value || [];
          setLogs(items);
        } else {
          console.warn('Logs fetch failed:', res.status);
          setError(`Failed to load logs (HTTP ${res.status})`);
        }
        setLoading(false);
      } catch (e: any) {
        console.error('Logs fetch error:', e);
        setError(e?.message || 'Failed to load logs');
        setLoading(false);
      }
    };

    const fetchCard = async () => {
      try {
        const res = await fetch(`${apiBase}/v1/strategies/${id}`, { cache: 'no-store' });
        if (res.ok) {
          const data = await res.json();
          setCard(data);
        }
      } catch (e) {
        console.warn('Strategy card fetch failed', e);
      }
    };

    const fetchSummary = async () => {
      try {
        const res = await fetch(`${apiBase}/v1/summary`, { cache: 'no-store' });
        if (res.ok) {
          setSummary(await res.json());
        }
      } catch (e) {}
    };

    fetchLogs();
    fetchCard();
    fetchSummary();
    const interval = setInterval(() => { fetchLogs(); fetchCard(); fetchSummary(); }, 30000); // Poll every 30s for real-time logs
    return () => clearInterval(interval);
  }, [id, apiBase]);

  const formatTime = (isoString: string) => {
    try {
      return new Date(isoString).toLocaleString();
    } catch {
      return isoString;
    }
  };

  if (loading) {
    return <div style={{ padding: 20 }}>Loading strategy logs...</div>;
  }

  return (
    <div style={{ padding: '0 20px', maxWidth: 1200, margin: '0 auto' }}>
      <div style={{ marginBottom: 24 }}>
        <button
          onClick={() => router.push('/')}
          style={{
            padding: '8px 16px',
            border: '1px solid #ddd',
            borderRadius: 6,
            background: '#f9f9f9',
            cursor: 'pointer',
            fontSize: 14,
            marginBottom: 12,
          }}
        >
          ← Back to Home
        </button>
        <h1 style={{ margin: 0, marginBottom: 8 }}>{card?.name || `Strategy ${id}`}</h1>
        <div style={{ display: 'flex', gap: 12, alignItems: 'center', marginBottom: 8 }}>
          <span style={{ fontSize: 14, color: '#666' }}>Status: {card?.status || 'Waiting'}</span>
          <span style={{ fontSize: 12, color: '#999' }}>Last evaluated: {card?.lastEvaluated ? new Date(card.lastEvaluated).toLocaleTimeString() : '—'}</span>
        </div>

        {/* At-a-glance row */}
        <div style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))',
          gap: 8,
          background: '#fafafa',
          border: '1px solid #eee',
          borderRadius: 8,
          padding: 12,
          marginBottom: 12,
          fontSize: 13,
        }}>
          <div>
            <div style={{ color: '#999' }}>Label • Score</div>
            <div><strong>{card?.latestSignal ? `${card.latestSignal.label} • ${card.latestSignal.score}/100` : 'Waiting for first evaluation'}</strong></div>
          </div>
          <div>
            <div style={{ color: '#999' }}>Market • Price</div>
            <div><strong>{card?.latestSignal ? `${card.latestSignal.market} • $${fmt(card.latestSignal.price, 2)}` : '—'}</strong></div>
          </div>
          <div>
            <div style={{ color: '#999' }}>Trend</div>
            <div><strong>{card?.latestSignal ? `SMA20 ${card.latestSignal.trend.sma20} • SMA50 ${card.latestSignal.trend.sma50} • RSI ${fmt(card.latestSignal.trend.rsi14, 1)}` : '—'}</strong></div>
          </div>
          <div>
            <div style={{ color: '#999' }}>Zones</div>
            <div><strong>{card?.latestSignal && card.latestSignal.zones ? `${fmt(card.latestSignal.zones.deepAccum, 2)} | ${fmt(card.latestSignal.zones.accum, 2)} | ${fmt(card.latestSignal.zones.distrib, 2)} | ${fmt(card.latestSignal.zones.safeDistrib, 2)}` : '—'}</strong></div>
          </div>
        </div>

        {/* Recent Trade */}
        {summary?.mostRecentTrade && summary.mostRecentTrade.strategyId === (card?.id || id) && (
          <div style={{ border: '1px solid #ddd', borderRadius: 8, padding: 12, background: '#fff', marginBottom: 12 }}>
            <div style={{ fontSize: 13, color: '#666', marginBottom: 6 }}>Recent Trade</div>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <div>
                <div style={{ fontWeight: 600 }}>
                  {summary.mostRecentTrade.action} • {summary.mostRecentTrade.market} • ${fmt(summary.mostRecentTrade.price, 2)}
                </div>
                <div style={{ fontSize: 12, color: '#999' }}>{new Date(summary.mostRecentTrade.ts).toLocaleString()}</div>
              </div>
              <a href={`/strategies/${id}`} style={{ fontSize: 13 }}>View more</a>
            </div>
          </div>
        )}

        <div style={{ fontSize: 14, color: '#666' }}>Execution logs (last 50 entries)</div>
        {error && (
          <div style={{ fontSize: 13, color: '#f44336', marginTop: 8 }}>
            {error}
          </div>
        )}
      </div>

      {logs.length === 0 && !error && (
        <div style={{ fontSize: 14, color: '#999', padding: 16, background: '#f9f9f9', borderRadius: 8 }}>
          No logs yet — strategy is waiting for first evaluation.
        </div>
      )}

      {logs.length > 0 && (
        <div style={{ border: '1px solid #ddd', borderRadius: 8, overflow: 'hidden' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
            <thead style={{ background: '#f5f5f5' }}>
              <tr>
                <th style={{ textAlign: 'left', padding: 12, borderBottom: '1px solid #ddd' }}>Time</th>
                <th style={{ textAlign: 'left', padding: 12, borderBottom: '1px solid #ddd' }}>Event</th>
                <th style={{ textAlign: 'left', padding: 12, borderBottom: '1px solid #ddd' }}>Details</th>
              </tr>
            </thead>
            <tbody>
              {logs.map((log, idx) => (
                <tr key={idx} style={{ background: idx % 2 === 0 ? '#fff' : '#fafafa' }}>
                  <td style={{ padding: 12, borderBottom: '1px solid #eee', whiteSpace: 'nowrap' }}>
                    {formatTime(log.ts)}
                  </td>
                  <td style={{ padding: 12, borderBottom: '1px solid #eee', fontWeight: 600 }}>{log.event}</td>
                  <td style={{ padding: 12, borderBottom: '1px solid #eee', fontSize: 12, color: '#666' }}>
                    {log.details ? (
                      <pre style={{ margin: 0, whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>
                        {JSON.stringify(log.details, null, 2)}
                      </pre>
                    ) : (
                      '—'
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Footer disclaimer */}
      <div
        style={{
          fontSize: 11,
          color: '#999',
          padding: '16px 0',
          borderTop: '1px solid #eee',
          textAlign: 'center',
          marginTop: 24,
        }}
      >
        <div style={{ marginBottom: 6 }}>
          <strong>How to read:</strong> Score ranges 0–100. Higher means stronger alignment of trend (SMA20/50), volatility (ATR), RSI, and volume.
        </div>
        <div style={{ marginBottom: 6 }}>
          <strong>Zones:</strong> Prices relative to SMA20 ± k·ATR define Accumulation/Distribution bands; k varies by asset risk.
        </div>
        <div>
          <strong>Disclaimer:</strong> Informational only. Verify on-chain. Never DM-first. $MICO is independent and unaffiliated with Microsoft.
        </div>
      </div>
    </div>
  );
}
