import React, { useEffect, useState, useRef } from 'react';
import Head from 'next/head';
import Link from 'next/link';
import { C, fmtUsd, fmtPct } from '../src/theme';
import { apiFetch } from '../src/api';
import type { TradeHistoryResponse, TradeRecord, EquityCurveResponse, LlmMarketView } from '../src/types';

// ─── Types ────────────────────────────────────────────────────────────────────

type SummaryStats = {
  totalPnl: number | null;
  winRate: number | null;
  sharpe: number | null;
  maxDrawdown: number | null;
  totalTrades: number;
};

// ─── Stat Card ────────────────────────────────────────────────────────────────

function StatCard({
  label,
  value,
  color,
  sub,
}: {
  label: string;
  value: string;
  color?: string;
  sub?: string;
}) {
  return (
    <div
      style={{
        flex: '1 1 160px',
        padding: '20px 24px',
        background: 'rgba(13,13,20,0.8)',
        border: '1px solid rgba(255,255,255,0.06)',
        borderRadius: 12,
        minWidth: 140,
      }}
    >
      <div style={{ fontSize: 11, fontWeight: 600, color: C.muted, textTransform: 'uppercase', letterSpacing: 1, marginBottom: 8 }}>
        {label}
      </div>
      <div
        style={{
          fontSize: 26,
          fontWeight: 700,
          color: color || C.text,
          fontFamily: 'JetBrains Mono, monospace',
          letterSpacing: -0.5,
          lineHeight: 1.1,
        }}
      >
        {value}
      </div>
      {sub && (
        <div style={{ fontSize: 12, color: C.muted, marginTop: 4 }}>{sub}</div>
      )}
    </div>
  );
}

// ─── Mini Equity Curve SVG ────────────────────────────────────────────────────

function EquityCurveMini({ points }: { points: Array<{ equity: number }> }) {
  if (!points || points.length < 2) return null;
  const values = points.map((p) => p.equity);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = max - min || 1;
  const w = 800;
  const h = 120;
  const pad = 4;
  const pts = values.map((v, i) => {
    const x = pad + (i / (values.length - 1)) * (w - pad * 2);
    const y = pad + ((max - v) / range) * (h - pad * 2);
    return `${x},${y}`;
  });
  const pathD = 'M' + pts.join(' L');
  const fillD = pathD + ` L${w - pad},${h - pad} L${pad},${h - pad} Z`;
  const isPositive = values[values.length - 1] >= values[0];
  const lineColor = isPositive ? C.bull : C.bear;

  return (
    <svg viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="none" style={{ width: '100%', height: '100%' }}>
      <defs>
        <linearGradient id="ecGrad" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={lineColor} stopOpacity="0.2" />
          <stop offset="100%" stopColor={lineColor} stopOpacity="0" />
        </linearGradient>
      </defs>
      <path d={fillD} fill="url(#ecGrad)" />
      <path d={pathD} fill="none" stroke={lineColor} strokeWidth="2" strokeLinejoin="round" />
    </svg>
  );
}

// ─── Recent Trade Row ─────────────────────────────────────────────────────────

function TradeRow({ trade, index }: { trade: TradeRecord; index: number }) {
  const isWin = trade.outcome === 'WIN' || (trade.pnl ?? 0) > 0;
  const pnl = trade.pnl ?? 0;

  return (
    <div
      className={`fade-in-${Math.min(index + 1, 4)}`}
      style={{
        display: 'grid',
        gridTemplateColumns: '80px 56px 1fr 80px 70px',
        gap: 8,
        padding: '10px 16px',
        borderBottom: '1px solid rgba(255,255,255,0.04)',
        alignItems: 'center',
      }}
    >
      <div style={{ fontSize: 13, fontWeight: 600, color: C.text, fontFamily: 'JetBrains Mono, monospace' }}>
        {trade.symbol}
      </div>
      <div>
        <span
          style={{
            fontSize: 11,
            fontWeight: 700,
            padding: '2px 7px',
            borderRadius: 999,
            background: trade.side === 'BUY' ? C.bullLight : C.bearLight,
            color: trade.side === 'BUY' ? C.bull : C.bear,
          }}
        >
          {trade.side}
        </span>
      </div>
      <div style={{ fontSize: 12, color: C.muted, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
        {trade.strategy}
      </div>
      <div
        style={{
          fontSize: 13,
          fontWeight: 700,
          color: isWin ? C.bull : C.bear,
          textAlign: 'right',
          fontFamily: 'JetBrains Mono, monospace',
        }}
      >
        {fmtUsd(pnl)}
      </div>
      <div
        style={{
          fontSize: 11,
          fontWeight: 700,
          padding: '2px 7px',
          borderRadius: 999,
          background: isWin ? C.bullLight : C.bearLight,
          color: isWin ? C.bull : C.bear,
          textAlign: 'center',
        }}
      >
        {trade.outcome}
      </div>
    </div>
  );
}

// ─── Feature Card ─────────────────────────────────────────────────────────────

function FeatureCard({
  icon,
  title,
  desc,
}: {
  icon: string;
  title: string;
  desc: string;
}) {
  return (
    <div
      className="card-hover"
      style={{
        padding: '24px',
        background: '#0d0d14',
        border: '1px solid rgba(255,255,255,0.06)',
        borderRadius: 12,
        flex: '1 1 220px',
        minWidth: 200,
      }}
    >
      <div style={{ fontSize: 24, marginBottom: 14 }}>{icon}</div>
      <div style={{ fontSize: 15, fontWeight: 700, color: C.text, marginBottom: 8 }}>{title}</div>
      <div style={{ fontSize: 13, color: C.muted, lineHeight: 1.7 }}>{desc}</div>
    </div>
  );
}

// ─── Page ─────────────────────────────────────────────────────────────────────

export default function LandingPage() {
  const [stats, setStats] = useState<SummaryStats>({ totalPnl: null, winRate: null, sharpe: null, maxDrawdown: null, totalTrades: 0 });
  const [equityPoints, setEquityPoints] = useState<Array<{ equity: number; ts: string }>>([]);
  const [trades, setTrades] = useState<TradeRecord[]>([]);
  const [marketView, setMarketView] = useState<LlmMarketView | null>(null);
  const [loading, setLoading] = useState(true);
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);

  useEffect(() => {
    async function load() {
      const [tradeRes, equityRes, marketRes] = await Promise.all([
        apiFetch<TradeHistoryResponse>('/v1/trades/history?limit=50'),
        apiFetch<EquityCurveResponse>('/v1/trades/equity-curve?run=latest'),
        apiFetch<LlmMarketView>('/v1/llm/market-view'),
      ]);

      // Compute stats from trades
      if (tradeRes?.trades && tradeRes.trades.length > 0) {
        const ts = tradeRes.trades;
        const wins = ts.filter((t) => t.outcome === 'WIN' || (t.pnl ?? 0) > 0);
        const totalPnl = ts.reduce((a, b) => a + (b.pnl ?? 0), 0);
        const winRate = (wins.length / ts.length) * 100;

        // Sharpe from equity curve
        let sharpe: number | null = null;
        if (equityRes?.points && equityRes.points.length > 5) {
          const pts = equityRes.points;
          const returns = pts.slice(1).map((p, i) => (p.equity - pts[i].equity) / pts[i].equity);
          const mean = returns.reduce((a, b) => a + b, 0) / returns.length;
          const variance = returns.reduce((a, b) => a + (b - mean) ** 2, 0) / returns.length;
          const std = Math.sqrt(variance);
          if (std > 0) sharpe = (mean / std) * Math.sqrt(365);
        }

        // Max drawdown from equity curve
        let maxDrawdown: number | null = null;
        if (equityRes?.points) {
          const pts = equityRes.points;
          let peak = pts[0]?.equity ?? 0;
          let maxDD = 0;
          for (const p of pts) {
            if (p.equity > peak) peak = p.equity;
            const dd = peak > 0 ? ((peak - p.equity) / peak) * 100 : 0;
            if (dd > maxDD) maxDD = dd;
          }
          maxDrawdown = maxDD;
        }

        setStats({ totalPnl, winRate, sharpe, maxDrawdown, totalTrades: ts.length });
        setTrades(ts.slice(0, 6));
      }

      if (equityRes?.points) setEquityPoints(equityRes.points);
      if (marketRes) setMarketView(marketRes);
      setLoading(false);
    }

    load();
    const iv = setInterval(load, 30_000);
    return () => clearInterval(iv);
  }, []);

  const biasColor = marketView?.overall_bias === 'bullish' ? C.bull
    : marketView?.overall_bias === 'bearish' ? C.bear
    : C.warn;

  return (
    <>
      <Head>
        <title>CrazyOnSol — AI-Powered Perpetual Trading</title>
        <meta name="description" content="A quant engine that trades BTC, ETH, SOL, and HYPE on Hyperliquid perpetual futures." />
      </Head>

      <div style={{ background: C.bg, minHeight: '100vh', color: C.text, fontFamily: "'Inter', system-ui, sans-serif" }}>

        {/* ── Sticky Nav ─────────────────────────────────────────────────── */}
        <nav
          style={{
            position: 'sticky',
            top: 0,
            zIndex: 100,
            background: 'rgba(5,5,8,0.92)',
            borderBottom: '1px solid rgba(255,255,255,0.06)',
            backdropFilter: 'blur(12px)',
            WebkitBackdropFilter: 'blur(12px)',
          }}
        >
          <div
            style={{
              maxWidth: 1200,
              margin: '0 auto',
              padding: '0 24px',
              height: 60,
              display: 'flex',
              alignItems: 'center',
              gap: 32,
            }}
          >
            {/* Logo */}
            <Link href="/" style={{ display: 'flex', alignItems: 'center', gap: 10, textDecoration: 'none' }}>
              <div
                style={{
                  width: 28,
                  height: 28,
                  borderRadius: 6,
                  border: `1.5px solid ${C.brand}`,
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  fontSize: 13,
                  fontWeight: 800,
                  color: C.brand,
                  fontFamily: 'JetBrains Mono, monospace',
                  background: C.brandMuted,
                  flexShrink: 0,
                }}
              >
                C
              </div>
              <span style={{ fontSize: 15, fontWeight: 700, color: C.text, letterSpacing: -0.3 }}>
                CrazyOnSol
              </span>
            </Link>

            {/* Desktop nav links */}
            <div style={{ display: 'flex', alignItems: 'center', gap: 2, marginLeft: 8 }} className="desktop-nav">
              {['Performance', 'Brain', 'Learn'].map((label) => {
                const href = label === 'Performance' ? '/performance' : label === 'Brain' ? '/agent-intelligence' : '/learn';
                return (
                  <Link
                    key={label}
                    href={href}
                    style={{
                      padding: '6px 12px',
                      fontSize: 13,
                      fontWeight: 500,
                      color: C.muted,
                      borderRadius: 6,
                      textDecoration: 'none',
                      transition: 'color 0.15s ease',
                    }}
                    onMouseEnter={(e) => ((e.target as HTMLAnchorElement).style.color = C.text)}
                    onMouseLeave={(e) => ((e.target as HTMLAnchorElement).style.color = C.muted)}
                  >
                    {label}
                  </Link>
                );
              })}
            </div>

            <div style={{ flex: 1 }} />

            {/* Live dot */}
            <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
              <div
                className="live-dot"
                style={{
                  width: 7,
                  height: 7,
                  borderRadius: '50%',
                  background: C.bull,
                }}
              />
              <span style={{ fontSize: 11, fontWeight: 600, color: C.bull }}>LIVE</span>
            </div>

            {/* CTA */}
            <Link
              href="/dashboard"
              style={{
                padding: '8px 18px',
                background: C.brand,
                color: '#050508',
                borderRadius: 8,
                fontSize: 13,
                fontWeight: 700,
                textDecoration: 'none',
                transition: 'opacity 0.15s ease',
                flexShrink: 0,
              }}
              onMouseEnter={(e) => ((e.currentTarget as HTMLAnchorElement).style.opacity = '0.85')}
              onMouseLeave={(e) => ((e.currentTarget as HTMLAnchorElement).style.opacity = '1')}
            >
              Dashboard →
            </Link>
          </div>
        </nav>

        {/* ── Hero ───────────────────────────────────────────────────────── */}
        <section
          style={{
            maxWidth: 1200,
            margin: '0 auto',
            padding: '80px 24px 60px',
          }}
        >
          <div style={{ maxWidth: 680 }}>
            {/* Live badge */}
            <div
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: 8,
                padding: '5px 12px',
                background: 'rgba(0,204,136,0.08)',
                border: '1px solid rgba(0,204,136,0.2)',
                borderRadius: 999,
                marginBottom: 28,
              }}
            >
              <div
                className="live-dot"
                style={{ width: 6, height: 6, borderRadius: '50%', background: C.bull }}
              />
              <span style={{ fontSize: 12, fontWeight: 600, color: C.bull }}>
                Trading live on Hyperliquid
              </span>
            </div>

            <h1
              style={{
                fontSize: 'clamp(36px, 6vw, 62px)',
                fontWeight: 800,
                lineHeight: 1.08,
                letterSpacing: -1.5,
                color: C.text,
                margin: '0 0 20px',
              }}
            >
              AI-powered perpetual
              <br />
              <span style={{ color: C.brand }}>trading.</span>
            </h1>

            <p
              style={{
                fontSize: 17,
                lineHeight: 1.7,
                color: C.textSub,
                margin: '0 0 36px',
                maxWidth: 560,
              }}
            >
              A quant engine that trades BTC, ETH, SOL, and HYPE on Hyperliquid
              perpetual futures. Multi-strategy signals filtered through a{' '}
              <strong style={{ color: C.text, fontWeight: 600 }}>9-agent AI brain.</strong>
            </p>

            <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap' }}>
              <Link
                href="/dashboard"
                style={{
                  padding: '12px 28px',
                  background: C.brand,
                  color: '#050508',
                  borderRadius: 8,
                  fontSize: 14,
                  fontWeight: 700,
                  textDecoration: 'none',
                  display: 'inline-flex',
                  alignItems: 'center',
                  gap: 6,
                }}
                onMouseEnter={(e) => ((e.currentTarget as HTMLAnchorElement).style.opacity = '0.85')}
                onMouseLeave={(e) => ((e.currentTarget as HTMLAnchorElement).style.opacity = '1')}
              >
                View Dashboard
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><path d="M5 12h14M12 5l7 7-7 7" /></svg>
              </Link>
              <Link
                href="/learn"
                style={{
                  padding: '12px 28px',
                  background: 'transparent',
                  color: C.textSub,
                  border: '1px solid rgba(255,255,255,0.1)',
                  borderRadius: 8,
                  fontSize: 14,
                  fontWeight: 600,
                  textDecoration: 'none',
                }}
                onMouseEnter={(e) => { (e.currentTarget as HTMLAnchorElement).style.borderColor = 'rgba(255,255,255,0.2)'; (e.currentTarget as HTMLAnchorElement).style.color = C.text; }}
                onMouseLeave={(e) => { (e.currentTarget as HTMLAnchorElement).style.borderColor = 'rgba(255,255,255,0.1)'; (e.currentTarget as HTMLAnchorElement).style.color = C.textSub; }}
              >
                Learn More
              </Link>
            </div>
          </div>
        </section>

        {/* ── Stats Row ──────────────────────────────────────────────────── */}
        <section style={{ maxWidth: 1200, margin: '0 auto', padding: '0 24px 48px' }}>
          <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap' }}>
            <StatCard
              label="Total P&L"
              value={loading ? '—' : fmtUsd(stats.totalPnl)}
              color={(stats.totalPnl ?? 0) >= 0 ? C.bull : C.bear}
              sub={`${stats.totalTrades} trades`}
            />
            <StatCard
              label="Win Rate"
              value={loading ? '—' : fmtPct(stats.winRate)}
              color={(stats.winRate ?? 0) >= 50 ? C.bull : C.bear}
            />
            <StatCard
              label="Sharpe Ratio"
              value={loading || stats.sharpe == null ? '—' : stats.sharpe.toFixed(2)}
              color={C.info}
            />
            <StatCard
              label="Max Drawdown"
              value={loading || stats.maxDrawdown == null ? '—' : `-${stats.maxDrawdown.toFixed(1)}%`}
              color={C.bear}
            />
          </div>
        </section>

        {/* ── Equity Curve ───────────────────────────────────────────────── */}
        <section style={{ maxWidth: 1200, margin: '0 auto', padding: '0 24px 48px' }}>
          <div
            style={{
              background: '#0d0d14',
              border: '1px solid rgba(255,255,255,0.06)',
              borderRadius: 12,
              overflow: 'hidden',
            }}
          >
            <div
              style={{
                padding: '16px 20px',
                borderBottom: '1px solid rgba(255,255,255,0.04)',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
              }}
            >
              <div>
                <div style={{ fontSize: 14, fontWeight: 700, color: C.text }}>Equity Curve</div>
                <div style={{ fontSize: 12, color: C.muted, marginTop: 2 }}>Portfolio value over time</div>
              </div>
              {equityPoints.length > 0 && (
                <div
                  style={{
                    fontSize: 13,
                    fontWeight: 700,
                    color: (equityPoints[equityPoints.length - 1]?.equity ?? 0) >= (equityPoints[0]?.equity ?? 0) ? C.bull : C.bear,
                    fontFamily: 'JetBrains Mono, monospace',
                  }}
                >
                  {fmtUsd(equityPoints[equityPoints.length - 1]?.equity)}
                </div>
              )}
            </div>
            <div style={{ height: 200, padding: '12px 0' }}>
              {equityPoints.length > 1 ? (
                <EquityCurveMini points={equityPoints} />
              ) : (
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100%', color: C.muted, fontSize: 13 }}>
                  {loading ? 'Loading...' : 'No equity data yet'}
                </div>
              )}
            </div>
          </div>
        </section>

        {/* ── Recent Trades + AI Brain ────────────────────────────────────── */}
        <section style={{ maxWidth: 1200, margin: '0 auto', padding: '0 24px 56px' }}>
          <div style={{ display: 'grid', gridTemplateColumns: 'minmax(0,1.5fr) minmax(0,1fr)', gap: 16 }}>

            {/* Recent Trades */}
            <div
              style={{
                background: '#0d0d14',
                border: '1px solid rgba(255,255,255,0.06)',
                borderRadius: 12,
                overflow: 'hidden',
              }}
            >
              <div style={{ padding: '16px 20px', borderBottom: '1px solid rgba(255,255,255,0.04)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <div style={{ fontSize: 14, fontWeight: 700, color: C.text }}>Recent Trades</div>
                <Link href="/results" style={{ fontSize: 12, color: C.brand, textDecoration: 'none', fontWeight: 600 }}>
                  View all →
                </Link>
              </div>
              {/* Table header */}
              <div
                style={{
                  display: 'grid',
                  gridTemplateColumns: '80px 56px 1fr 80px 70px',
                  gap: 8,
                  padding: '8px 16px',
                  borderBottom: '1px solid rgba(255,255,255,0.04)',
                }}
              >
                {['Symbol', 'Side', 'Strategy', 'P&L', 'Result'].map((h) => (
                  <div key={h} style={{ fontSize: 10, fontWeight: 700, color: C.muted, textTransform: 'uppercase', letterSpacing: 0.8 }}>{h}</div>
                ))}
              </div>
              {loading ? (
                <div style={{ padding: '20px 16px', color: C.muted, fontSize: 13 }}>Loading...</div>
              ) : trades.length === 0 ? (
                <div style={{ padding: '24px 16px', color: C.muted, fontSize: 13, textAlign: 'center' }}>No trade history yet</div>
              ) : (
                trades.map((t, i) => <TradeRow key={i} trade={t} index={i} />)
              )}
            </div>

            {/* AI Brain Status */}
            <div
              style={{
                background: '#0d0d14',
                border: '1px solid rgba(255,255,255,0.06)',
                borderRadius: 12,
                overflow: 'hidden',
              }}
            >
              <div style={{ padding: '16px 20px', borderBottom: '1px solid rgba(255,255,255,0.04)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <div style={{ fontSize: 14, fontWeight: 700, color: C.text }}>AI Brain</div>
                <Link href="/agent-intelligence" style={{ fontSize: 12, color: C.brand, textDecoration: 'none', fontWeight: 600 }}>
                  Details →
                </Link>
              </div>

              <div style={{ padding: '20px' }}>
                {loading || !marketView ? (
                  <div style={{ color: C.muted, fontSize: 13 }}>Loading brain status...</div>
                ) : !marketView.has_data ? (
                  <div style={{ color: C.muted, fontSize: 13 }}>Brain data will appear once the bot runs.</div>
                ) : (
                  <>
                    {/* Regime */}
                    <div style={{ marginBottom: 20 }}>
                      <div style={{ fontSize: 11, fontWeight: 700, color: C.muted, textTransform: 'uppercase', letterSpacing: 1, marginBottom: 8 }}>
                        Market Regime
                      </div>
                      <div
                        style={{
                          display: 'inline-flex',
                          alignItems: 'center',
                          gap: 8,
                          padding: '6px 12px',
                          borderRadius: 8,
                          background: 'rgba(0,204,136,0.08)',
                          border: '1px solid rgba(0,204,136,0.15)',
                        }}
                      >
                        <div style={{ width: 8, height: 8, borderRadius: '50%', background: C.bull }} />
                        <span style={{ fontSize: 13, fontWeight: 700, color: C.bull, textTransform: 'capitalize' }}>
                          {marketView.regime?.replace(/_/g, ' ') || 'Unknown'}
                        </span>
                      </div>
                    </div>

                    {/* Bias */}
                    <div style={{ marginBottom: 20 }}>
                      <div style={{ fontSize: 11, fontWeight: 700, color: C.muted, textTransform: 'uppercase', letterSpacing: 1, marginBottom: 8 }}>
                        Market Bias
                      </div>
                      <div
                        style={{
                          display: 'inline-flex',
                          alignItems: 'center',
                          gap: 6,
                          padding: '4px 10px',
                          borderRadius: 999,
                          background: `${biasColor}15`,
                          border: `1px solid ${biasColor}30`,
                        }}
                      >
                        <span style={{ fontSize: 12, fontWeight: 700, color: biasColor, textTransform: 'capitalize' }}>
                          {marketView.overall_bias || 'Neutral'}
                        </span>
                      </div>
                    </div>

                    {/* Decision counts */}
                    <div style={{ marginBottom: 20 }}>
                      <div style={{ fontSize: 11, fontWeight: 700, color: C.muted, textTransform: 'uppercase', letterSpacing: 1, marginBottom: 8 }}>
                        Recent Decisions
                      </div>
                      <div style={{ display: 'flex', gap: 8 }}>
                        {[
                          { label: 'Proceed', value: marketView.decision_counts?.proceed ?? 0, color: C.bull },
                          { label: 'Skip', value: marketView.decision_counts?.flat ?? 0, color: C.muted },
                          { label: 'Flip', value: marketView.decision_counts?.flip ?? 0, color: C.warn },
                        ].map((d) => (
                          <div key={d.label} style={{ flex: 1, textAlign: 'center', padding: '8px 4px', background: 'rgba(255,255,255,0.03)', borderRadius: 8 }}>
                            <div style={{ fontSize: 18, fontWeight: 800, color: d.color, fontFamily: 'JetBrains Mono, monospace' }}>
                              {d.value}
                            </div>
                            <div style={{ fontSize: 10, color: C.muted, marginTop: 2, fontWeight: 600 }}>{d.label}</div>
                          </div>
                        ))}
                      </div>
                    </div>

                    {/* Confidence */}
                    {marketView.avg_confidence != null && (
                      <div>
                        <div style={{ fontSize: 11, fontWeight: 700, color: C.muted, textTransform: 'uppercase', letterSpacing: 1, marginBottom: 8 }}>
                          Avg Confidence
                        </div>
                        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                          <div
                            style={{
                              flex: 1,
                              height: 4,
                              background: 'rgba(255,255,255,0.06)',
                              borderRadius: 999,
                              overflow: 'hidden',
                            }}
                          >
                            <div
                              style={{
                                height: '100%',
                                width: `${(marketView.avg_confidence * 100).toFixed(0)}%`,
                                background: C.brand,
                                borderRadius: 999,
                                transition: 'width 0.5s ease',
                              }}
                            />
                          </div>
                          <span style={{ fontSize: 13, fontWeight: 700, color: C.text, fontFamily: 'JetBrains Mono, monospace', flexShrink: 0 }}>
                            {(marketView.avg_confidence * 100).toFixed(0)}%
                          </span>
                        </div>
                      </div>
                    )}
                  </>
                )}
              </div>
            </div>
          </div>
        </section>

        {/* ── How It Works ───────────────────────────────────────────────── */}
        <section
          style={{
            maxWidth: 1200,
            margin: '0 auto',
            padding: '0 24px 64px',
          }}
        >
          <div style={{ marginBottom: 32 }}>
            <h2 style={{ fontSize: 28, fontWeight: 800, color: C.text, margin: '0 0 8px', letterSpacing: -0.5 }}>
              How It Works
            </h2>
            <p style={{ fontSize: 14, color: C.muted, margin: 0 }}>
              Three stages from raw market data to executed trade.
            </p>
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: 16 }}>
            {[
              {
                step: '01',
                title: 'Signal Generation',
                desc: 'Four independent strategies scan BTC, ETH, SOL, and HYPE simultaneously using regime analysis, Monte Carlo zones, multi-timeframe quality scoring, and confidence models.',
                color: C.info,
              },
              {
                step: '02',
                title: 'AI Brain Analysis',
                desc: 'A 9-agent specialist pipeline — Regime, Trade, Risk, Critic, Learning, Exit, Scout, Overseer, and Quant — deliberates on every signal before any position opens.',
                color: C.brand,
              },
              {
                step: '03',
                title: 'Execution',
                desc: 'Positions are sized using Kelly Criterion, protected by circuit breakers, and managed through a state machine with progressive trailing stops and dynamic TP targets.',
                color: C.purple,
              },
            ].map((item) => (
              <div
                key={item.step}
                className="card-hover"
                style={{
                  padding: '24px',
                  background: '#0d0d14',
                  border: '1px solid rgba(255,255,255,0.06)',
                  borderRadius: 12,
                  position: 'relative',
                  overflow: 'hidden',
                }}
              >
                <div
                  style={{
                    fontSize: 48,
                    fontWeight: 900,
                    color: `${item.color}10`,
                    position: 'absolute',
                    top: 12,
                    right: 16,
                    fontFamily: 'JetBrains Mono, monospace',
                    lineHeight: 1,
                    letterSpacing: -2,
                    userSelect: 'none',
                  }}
                >
                  {item.step}
                </div>
                <div
                  style={{
                    fontSize: 11,
                    fontWeight: 700,
                    color: item.color,
                    textTransform: 'uppercase',
                    letterSpacing: 1.2,
                    marginBottom: 10,
                  }}
                >
                  Step {item.step}
                </div>
                <div style={{ fontSize: 16, fontWeight: 700, color: C.text, marginBottom: 10 }}>
                  {item.title}
                </div>
                <div style={{ fontSize: 13, color: C.muted, lineHeight: 1.7 }}>
                  {item.desc}
                </div>
              </div>
            ))}
          </div>
        </section>

        {/* ── Feature Cards ──────────────────────────────────────────────── */}
        <section
          style={{
            maxWidth: 1200,
            margin: '0 auto',
            padding: '0 24px 72px',
          }}
        >
          <div style={{ marginBottom: 32 }}>
            <h2 style={{ fontSize: 28, fontWeight: 800, color: C.text, margin: '0 0 8px', letterSpacing: -0.5 }}>
              Built for edge, not noise.
            </h2>
          </div>

          <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap' }}>
            <FeatureCard
              icon="🧠"
              title="9-Agent AI Brain"
              desc="Every trade decision passes through a deliberation pipeline of specialist AI agents — regime analysis, thesis formation, risk assessment, critic review, and learning from outcomes."
            />
            <FeatureCard
              icon="📊"
              title="Multi-Strategy Ensemble"
              desc="Four independent strategies vote on every signal. Weighted-veto mode requires consensus with minimum agreement thresholds to block low-conviction trades."
            />
            <FeatureCard
              icon="🛡️"
              title="Risk-First Design"
              desc="Six-stage signal gate, circuit breakers, Kelly-based position sizing, progressive trailing stops, and daily drawdown caps. Risk management is non-negotiable."
            />
            <FeatureCard
              icon="📱"
              title="Telegram Copilot"
              desc="Real-time trade alerts, AI brain summaries, and position updates delivered to Telegram. Full transparency on every decision the bot makes."
            />
          </div>
        </section>

        {/* ── Footer ─────────────────────────────────────────────────────── */}
        <footer
          style={{
            borderTop: '1px solid rgba(255,255,255,0.06)',
            padding: '32px 24px',
          }}
        >
          <div
            style={{
              maxWidth: 1200,
              margin: '0 auto',
              display: 'flex',
              alignItems: 'flex-start',
              justifyContent: 'space-between',
              gap: 32,
              flexWrap: 'wrap',
            }}
          >
            <div>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 12 }}>
                <div style={{ width: 22, height: 22, borderRadius: 4, border: `1px solid ${C.brand}`, display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 11, fontWeight: 800, color: C.brand, fontFamily: 'JetBrains Mono, monospace', background: C.brandMuted }}>C</div>
                <span style={{ fontSize: 13, fontWeight: 700, color: C.text }}>CrazyOnSol</span>
              </div>
              <p style={{ fontSize: 12, color: C.muted, lineHeight: 1.7, maxWidth: 380, margin: 0 }}>
                AI-driven market analysis for informational purposes only. Not financial advice.
                Crypto trading carries significant risk. Historical results do not predict future performance.
              </p>
            </div>

            <div style={{ display: 'flex', gap: 32, flexWrap: 'wrap' }}>
              <div>
                <div style={{ fontSize: 11, fontWeight: 700, color: C.muted, textTransform: 'uppercase', letterSpacing: 1, marginBottom: 12 }}>System</div>
                {[
                  { href: '/dashboard', label: 'Dashboard' },
                  { href: '/performance', label: 'Performance' },
                  { href: '/agent-intelligence', label: 'AI Brain' },
                  { href: '/backtest', label: 'Backtest' },
                ].map((link) => (
                  <Link key={link.href} href={link.href} style={{ display: 'block', fontSize: 13, color: C.muted, marginBottom: 6, textDecoration: 'none' }}
                    onMouseEnter={(e) => ((e.target as HTMLAnchorElement).style.color = C.text)}
                    onMouseLeave={(e) => ((e.target as HTMLAnchorElement).style.color = C.muted)}
                  >
                    {link.label}
                  </Link>
                ))}
              </div>
              <div>
                <div style={{ fontSize: 11, fontWeight: 700, color: C.muted, textTransform: 'uppercase', letterSpacing: 1, marginBottom: 12 }}>Learn</div>
                {[
                  { href: '/learn', label: 'Course' },
                  { href: '/masterclass', label: 'Masterclass' },
                  { href: '/forensics', label: 'Forensics' },
                ].map((link) => (
                  <Link key={link.href} href={link.href} style={{ display: 'block', fontSize: 13, color: C.muted, marginBottom: 6, textDecoration: 'none' }}
                    onMouseEnter={(e) => ((e.target as HTMLAnchorElement).style.color = C.text)}
                    onMouseLeave={(e) => ((e.target as HTMLAnchorElement).style.color = C.muted)}
                  >
                    {link.label}
                  </Link>
                ))}
              </div>
            </div>
          </div>

          <div
            style={{
              maxWidth: 1200,
              margin: '20px auto 0',
              paddingTop: 20,
              borderTop: '1px solid rgba(255,255,255,0.04)',
              fontSize: 11,
              color: C.faint,
            }}
          >
            &copy; 2026 CrazyOnSol · crazyonsol.online
          </div>
        </footer>

        <style>{`
          @media (max-width: 768px) {
            .desktop-nav { display: none !important; }
          }
          @media (max-width: 640px) {
            section { padding-left: 16px !important; padding-right: 16px !important; }
          }
        `}</style>
      </div>
    </>
  );
}

// No sidebar layout for landing page
LandingPage.noLayout = true;
