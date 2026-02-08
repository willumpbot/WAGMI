'use client';

import React, { useEffect, useState } from 'react';
import { useRouter } from 'next/router';

type MostRecentTrade = {
  strategyId: string;
  name: string;
  market: string;
  action: string;
  price: number;
  ts: string;
};

type Summary = {
  updatedAt?: string;
  regime?: string;
  status?: string;
  errors?: number;
  mostRecentTrade?: MostRecentTrade | null;
};

type LatestSignal = {
  label: string;
  score: number;
  market: string;
  ts: string;
};

type Strategy = {
  id: string;
  name: string;
  markets: string[];
  status: string;
  lastEvaluated?: string;
  latestSignal?: LatestSignal | null;
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

export default function Home() {
  const [summary, setSummary] = useState<Summary>({});
  const [strategies, setStrategies] = useState<Strategy[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const router = useRouter();
  const apiBase = resolveApiBase();

  useEffect(() => {
    const fetchData = async () => {
      try {
        setError(null);
        const [summaryRes, strategiesRes] = await Promise.all([
          fetch(`${apiBase}/v1/summary`, { cache: 'no-store' }),
          fetch(`${apiBase}/v1/strategies`, { cache: 'no-store' }),
        ]);

        if (summaryRes.ok) {
          const summaryData = await summaryRes.json();
          setSummary(summaryData || {});
        } else {
          console.warn('Summary fetch failed:', summaryRes.status);
        }

        if (strategiesRes.ok) {
          const strategiesData = await strategiesRes.json();
          // Handle both array response and { items: [] } response
          const items = Array.isArray(strategiesData) ? strategiesData : strategiesData?.items || [];
          setStrategies(items);
        } else {
          console.warn('Strategies fetch failed:', strategiesRes.status);
        }

        setLoading(false);
      } catch (e: any) {
        console.error('Home fetch error:', e);
        setError(e?.message || 'Failed to load data');
        setLoading(false);
      }
    };

    fetchData();
    const interval = setInterval(fetchData, 30000); // Poll every 30s
    return () => clearInterval(interval);
  }, [apiBase]);

  const formatTime = (isoString?: string) => {
    if (!isoString) return '—';
    try {
      return new Date(isoString).toLocaleTimeString();
    } catch {
      return '—';
    }
  };

  const getStatusBadge = (status: string) => {
    const colors: Record<string, string> = {
      Active: '#4caf50',
      Waiting: '#ff9800',
      Paused: '#9e9e9e',
      Error: '#f44336',
      live: '#4caf50',
    };
    return colors[status] || '#9e9e9e';
  };

  if (loading) {
    return <div style={{ padding: 20 }}>Loading Mico's World...</div>;
  }

  const status = summary?.status || (error ? 'degraded' : 'ok');
  const regime = summary?.regime || 'Neutral';

  return (
    <div style={{ padding: '0 20px', maxWidth: 1200, margin: '0 auto' }}>
      {/* Hero/Meta */}
      <div style={{ marginBottom: 24 }}>
        <h1 style={{ margin: 0, marginBottom: 8 }}>Mico's World</h1>
        <div style={{ display: 'flex', gap: 16, fontSize: 14, color: '#666', alignItems: 'center' }}>
          <span>Updated: {formatTime(summary?.updatedAt)}</span>
          <span>Regime: {regime}</span>
          {status === 'degraded' && (
            <span
              style={{
                padding: '2px 8px',
                borderRadius: 4,
                background: '#ff9800',
                color: '#fff',
                fontSize: 12,
                fontWeight: 600,
              }}
            >
              Degraded (retrying)
            </span>
          )}
          {error && (
            <span style={{ fontSize: 12, color: '#f44336' }}>Error: {error}</span>
          )}
        </div>
        {/* Quick link to server-rendered table */}
        <div style={{ marginTop: 8, fontSize: 13 }}>
          <a href={`${apiBase}/view`} target="_blank" rel="noreferrer">Open server-rendered signals table (/view)</a>
        </div>
      </div>

      {/* How to read */}
      <div
        style={{
          background: '#f9f9f9',
          border: '1px solid #ddd',
          borderRadius: 8,
          padding: 16,
          marginBottom: 24,
          fontSize: 13,
        }}
      >
        <div style={{ marginBottom: 8 }}>
          <strong>How to read:</strong>
        </div>
        <div style={{ marginBottom: 6 }}>
          <strong>Score:</strong> 0–100 shows alignment of trend (SMA20/50), volatility (ATR), RSI, volume.
        </div>
        <div style={{ marginBottom: 6 }}>
          <strong>Zones:</strong> SMA20 ± k·ATR define Accumulation/Distribution bands; k varies by asset risk.
        </div>
        <div style={{ fontSize: 11, color: '#999', marginTop: 8 }}>
          <strong>Disclaimer:</strong> Informational only. Verify on-chain. Never DM-first. $MICO is independent and
          unaffiliated with Microsoft.
        </div>
      </div>

      {/* Most Recent Trade */}
      {summary?.mostRecentTrade && (
        <div style={{ marginBottom: 32 }}>
          <h2 style={{ fontSize: 18, marginBottom: 12 }}>Most Recent Trade</h2>
          <div
            style={{
              border: '1px solid #ddd',
              borderRadius: 8,
              padding: 16,
              backgroundColor: '#fafafa',
            }}
          >
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <div>
                <div style={{ fontSize: 16, fontWeight: 600, marginBottom: 4 }}>
                  {summary.mostRecentTrade.name} • {summary.mostRecentTrade.market}
                </div>
                <div style={{ fontSize: 14, color: '#666', marginBottom: 4 }}>
                  {summary.mostRecentTrade.action} @ ${summary.mostRecentTrade.price?.toFixed(4) || '—'}
                </div>
                <div style={{ fontSize: 12, color: '#999' }}>{formatTime(summary.mostRecentTrade.ts)}</div>
              </div>
              <button
                onClick={() => router.push(`/strategies/${summary.mostRecentTrade!.strategyId}`)}
                style={{
                  padding: '8px 16px',
                  border: '1px solid #444',
                  borderRadius: 6,
                  background: '#111',
                  color: '#eee',
                  cursor: 'pointer',
                  fontSize: 13,
                }}
              >
                View logs
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Strategies */}
      <div style={{ marginBottom: 32 }}>
        <h2 style={{ fontSize: 18, marginBottom: 12 }}>Strategies</h2>

        {strategies.length === 0 && <p style={{ color: '#666' }}>Strategies loading…</p>}

        <div
          style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fill, minmax(320px, 1fr))',
            gap: 16,
          }}
        >
          {strategies.map((strat) => (
            <div
              key={strat.id}
              style={{
                border: '1px solid #ddd',
                borderRadius: 8,
                padding: 16,
                backgroundColor: '#fafafa',
              }}
            >
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
                <div style={{ fontSize: 16, fontWeight: 600 }}>{strat.name}</div>
                <div
                  style={{
                    padding: '4px 8px',
                    borderRadius: 4,
                    background: getStatusBadge(strat.status),
                    color: '#fff',
                    fontSize: 11,
                    fontWeight: 600,
                  }}
                >
                  {strat.status}
                </div>
              </div>

              <div style={{ fontSize: 13, color: '#666', marginBottom: 8 }}>
                Markets: {strat.markets.join(', ') || 'None'}
              </div>

              <div style={{ fontSize: 13, color: '#666', marginBottom: 12 }}>
                Last evaluated: {formatTime(strat.lastEvaluated)}
              </div>

              {strat.latestSignal ? (
                <div
                  style={{
                    fontSize: 13,
                    padding: 8,
                    background: '#fff',
                    border: '1px solid #ddd',
                    borderRadius: 4,
                    marginBottom: 12,
                  }}
                >
                  <strong>Latest signal:</strong> {strat.latestSignal.label} • {strat.latestSignal.score}/100 (
                  {strat.latestSignal.market})
                </div>
              ) : (
                <div
                  style={{
                    fontSize: 13,
                    padding: 8,
                    background: '#fff',
                    border: '1px solid #ddd',
                    borderRadius: 4,
                    marginBottom: 12,
                    color: '#999',
                  }}
                >
                  No signal yet — waiting for first evaluation
                </div>
              )}

              <button
                onClick={() => router.push(`/strategies/${strat.id}`)}
                style={{
                  width: '100%',
                  padding: '8px 16px',
                  border: '1px solid #444',
                  borderRadius: 6,
                  background: '#111',
                  color: '#eee',
                  cursor: 'pointer',
                  fontSize: 13,
                }}
              >
                View logs
              </button>
            </div>
          ))}
        </div>
      </div>

      {/* Footer disclaimer */}
      <div
        style={{
          fontSize: 11,
          color: '#999',
          padding: '16px 0',
          borderTop: '1px solid #eee',
          textAlign: 'center',
        }}
      >
        <strong>Disclaimer:</strong> Informational only. Verify on-chain. Never DM-first. $MICO is independent and
        unaffiliated with Microsoft.
      </div>
    </div>
  );
}
