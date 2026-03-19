import React, { useEffect, useState, useMemo } from 'react';
import Head from 'next/head';
import Layout from '../components/Layout';
import { C, R, S, F, fmtUsd, fmtPct, timeAgo } from '../src/theme';
import { apiFetch } from '../src/api';
import type { Strategy, TradeHistoryResponse, TradeRecord } from '../src/types';

// ─── Types ────────────────────────────────────────────────────────────────────

type StrategiesResponse = Strategy[];

// ─── Helpers ──────────────────────────────────────────────────────────────────

function pnlColor(v: number | null | undefined): string {
  if (v == null) return C.muted;
  if (v > 0) return C.bull;
  if (v < 0) return C.bear;
  return C.muted;
}

function sideColor(side?: string): string {
  if (!side) return C.muted;
  return side.toUpperCase() === 'BUY' || side.toUpperCase() === 'LONG' ? C.bull : C.bear;
}

function Badge({ label, color, bg }: { label: string; color: string; bg: string }) {
  return (
    <span style={{
      display: 'inline-flex', alignItems: 'center', padding: '2px 8px',
      borderRadius: R.pill, background: bg, color, fontSize: F.xs, fontWeight: 700,
    }}>{label}</span>
  );
}

// ─── Daily PnL Waterfall ──────────────────────────────────────────────────────

function DailyWaterfall({ trades }: { trades: TradeRecord[] }) {
  const today = new Date();
  const todayTrades = trades.filter((t) => {
    // We don't have a closed_at timestamp in TradeRecord, so use the last N trades as proxy
    return t.pnl != null;
  }).slice(0, 20); // last 20 trades as "recent"

  if (!todayTrades.length) {
    return <div style={{ color: C.muted, fontSize: F.sm, padding: 20 }}>No recent trade data.</div>;
  }

  const width = 700;
  const height = 120;
  const pad = { t: 10, r: 20, b: 24, l: 64 };
  const W = width - pad.l - pad.r;
  const H = height - pad.t - pad.b;

  const pnls = todayTrades.map((t) => t.pnl ?? 0);
  const maxAbs = Math.max(1, ...pnls.map(Math.abs));
  const barW = W / pnls.length;

  return (
    <svg width="100%" viewBox={`0 0 ${width} ${height}`} style={{ display: 'block' }}>
      <line x1={pad.l} y1={pad.t + H / 2} x2={pad.l + W} y2={pad.t + H / 2} stroke={C.border} strokeWidth={1} />
      <text x={pad.l - 4} y={pad.t + H / 2 + 4} fill={C.muted} fontSize={9} textAnchor="end">$0</text>
      {pnls.map((pnl, i) => {
        const barH = (Math.abs(pnl) / maxAbs) * (H / 2 - 2);
        const barX = pad.l + i * barW + 1;
        const barY = pnl >= 0 ? pad.t + H / 2 - barH : pad.t + H / 2;
        return (
          <g key={i}>
            <rect x={barX} y={barY} width={barW - 2} height={Math.max(2, barH)}
              fill={pnl >= 0 ? C.bull : C.bear} rx={2} opacity={0.85} />
          </g>
        );
      })}
      <text x={pad.l + W / 2} y={height - 4} fill={C.muted} fontSize={9} textAnchor="middle">Last {pnls.length} closed trades (newest right)</text>
    </svg>
  );
}

// ─── Exposure Gauge ───────────────────────────────────────────────────────────

function ExposureGauge({ used, total }: { used: number; total: number }) {
  const pct = total > 0 ? Math.min(100, (used / total) * 100) : 0;
  const color = pct > 80 ? C.bear : pct > 50 ? C.warn : C.bull;
  return (
    <div style={{ padding: '16px 0' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 6 }}>
        <span style={{ fontSize: F.sm, color: C.textSub }}>Portfolio Exposure</span>
        <span style={{ fontSize: F.sm, fontWeight: 700, color }}>{pct.toFixed(1)}%</span>
      </div>
      <div style={{ height: 8, background: C.surface, borderRadius: R.pill, overflow: 'hidden' }}>
        <div style={{ width: `${pct}%`, height: '100%', background: color, borderRadius: R.pill, transition: 'width 0.4s' }} />
      </div>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 4 }}>
        <span style={{ fontSize: F.xs, color: C.muted }}>{fmtUsd(used)} deployed</span>
        <span style={{ fontSize: F.xs, color: C.muted }}>{fmtUsd(total)} total</span>
      </div>
    </div>
  );
}

// ─── Position Card ────────────────────────────────────────────────────────────

function PositionCard({ strategy }: { strategy: Strategy }) {
  const pos = strategy.open_position;
  if (!pos) return null;

  const unrealPnl = pos.unrealized_pnl ?? null;
  const unrealPct = pos.unrealized_pnl_pct ?? null;
  const side = pos.side ?? 'LONG';
  const entry = pos.avg_entry ?? null;
  const size = pos.size ?? null;

  return (
    <div style={{
      background: C.card, border: `1px solid ${C.border}`, borderRadius: R.lg,
      padding: '18px 20px', boxShadow: S.sm,
    }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <span style={{ fontSize: F.lg, fontWeight: 800, color: C.text }}>{strategy.id}</span>
          {strategy.name && <span style={{ fontSize: F.sm, color: C.muted }}>{strategy.name}</span>}
          <Badge
            label={side.toUpperCase()}
            color={sideColor(side)}
            bg={side.toUpperCase() === 'BUY' || side.toUpperCase() === 'LONG' ? 'rgba(22,163,74,0.15)' : 'rgba(220,38,38,0.15)'}
          />
        </div>
        <div style={{ textAlign: 'right' }}>
          <div style={{ fontSize: F.xl, fontWeight: 700, color: pnlColor(unrealPnl) }}>
            {unrealPnl != null ? fmtUsd(unrealPnl) : '—'}
          </div>
          {unrealPct != null && (
            <div style={{ fontSize: F.sm, color: pnlColor(unrealPct) }}>{fmtPct(unrealPct * 100)}</div>
          )}
        </div>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 10 }}>
        <div style={{ background: C.surface, borderRadius: R.sm, padding: '8px 12px' }}>
          <div style={{ fontSize: F.xs, color: C.muted, marginBottom: 2 }}>Entry</div>
          <div style={{ fontSize: F.base, fontWeight: 600, color: C.text }}>{entry != null ? fmtUsd(entry) : '—'}</div>
        </div>
        <div style={{ background: C.surface, borderRadius: R.sm, padding: '8px 12px' }}>
          <div style={{ fontSize: F.xs, color: C.muted, marginBottom: 2 }}>Size</div>
          <div style={{ fontSize: F.base, fontWeight: 600, color: C.text }}>{size != null ? fmtUsd(size) : '—'}</div>
        </div>
        <div style={{ background: C.surface, borderRadius: R.sm, padding: '8px 12px' }}>
          <div style={{ fontSize: F.xs, color: C.muted, marginBottom: 2 }}>Last Update</div>
          <div style={{ fontSize: F.base, fontWeight: 600, color: C.text }}>{timeAgo(pos.updated_at)}</div>
        </div>
      </div>
    </div>
  );
}

// ─── Main Page ────────────────────────────────────────────────────────────────

export default function PortfolioPage() {
  const [strategies, setStrategies] = useState<Strategy[]>([]);
  const [recentTrades, setRecentTrades] = useState<TradeRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [lastUpdate, setLastUpdate] = useState<Date | null>(null);

  const fetchData = async () => {
    const [stratRes, tradeRes] = await Promise.all([
      apiFetch<StrategiesResponse>('/v1/strategies'),
      apiFetch<TradeHistoryResponse>('/v1/trades/history?limit=30'),
    ]);
    setStrategies(Array.isArray(stratRes) ? stratRes : []);
    setRecentTrades(tradeRes?.trades ?? []);
    setLastUpdate(new Date());
    setLoading(false);
  };

  useEffect(() => {
    fetchData();
    const id = setInterval(fetchData, 20_000);
    return () => clearInterval(id);
  }, []);

  // Derived portfolio stats
  const openPositions = useMemo(
    () => strategies.filter((s) => s.open_position != null),
    [strategies],
  );

  const totalUnrealPnl = useMemo(
    () => openPositions.reduce((a, s) => a + (s.open_position?.unrealized_pnl ?? 0), 0),
    [openPositions],
  );

  const totalExposure = useMemo(
    () => openPositions.reduce((a, s) => a + (s.open_position?.size ?? 0), 0),
    [openPositions],
  );

  const totalRealizedPnl = useMemo(
    () => strategies.reduce((a, s) => a + (s.pnl_realized ?? 0), 0),
    [strategies],
  );

  // Concentration risk: are there multiple positions on the same side?
  const concentrationWarning = useMemo(() => {
    if (openPositions.length < 2) return null;
    const sides = openPositions.map((s) => s.open_position?.side?.toUpperCase() ?? 'LONG');
    const longCount = sides.filter((s) => s === 'BUY' || s === 'LONG').length;
    const shortCount = sides.filter((s) => s === 'SELL' || s === 'SHORT').length;
    if (longCount >= 2) return `${longCount} long positions open — concentration risk`;
    if (shortCount >= 2) return `${shortCount} short positions open — concentration risk`;
    return null;
  }, [openPositions]);

  const recentClosedPnl = useMemo(
    () => recentTrades.slice(0, 10).reduce((a, t) => a + (t.pnl ?? 0), 0),
    [recentTrades],
  );

  return (
    <Layout>
      <Head>
        <title>Portfolio — WAGMI</title>
        <meta name="description" content="Live portfolio view: open positions, exposure, unrealized P&L, and recent trade waterfall." />
      </Head>

      <div style={{ maxWidth: 900, margin: '0 auto', padding: '32px 20px' }}>
        {/* Header */}
        <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', marginBottom: 28, flexWrap: 'wrap', gap: 12 }}>
          <div>
            <h1 style={{ margin: 0, fontSize: F['3xl'], fontWeight: 800, color: C.text }}>Portfolio</h1>
            <p style={{ margin: '6px 0 0', color: C.muted, fontSize: F.base }}>
              Live positions across all strategies · refreshes every 20s
            </p>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            {lastUpdate && (
              <span style={{ fontSize: F.xs, color: C.muted }}>Updated {timeAgo(lastUpdate.toISOString())}</span>
            )}
            <button
              onClick={fetchData}
              style={{
                padding: '6px 14px', fontSize: F.sm, fontWeight: 600,
                background: C.brand, color: '#fff', border: 'none', borderRadius: R.sm,
                cursor: 'pointer',
              }}
            >Refresh</button>
          </div>
        </div>

        {loading ? (
          <div style={{ color: C.muted, padding: 40, textAlign: 'center', fontSize: F.base }}>Loading portfolio data…</div>
        ) : (
          <>
            {/* ── Summary KPIs ── */}
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(200px, 1fr))', gap: 16, marginBottom: 28 }}>
              <div style={{ background: C.card, border: `1px solid ${C.border}`, borderRadius: R.lg, padding: '16px 20px', boxShadow: S.sm }}>
                <div style={{ fontSize: F.sm, color: C.muted, marginBottom: 4 }}>UNREALIZED P&L</div>
                <div style={{ fontSize: F['2xl'], fontWeight: 700, color: pnlColor(totalUnrealPnl) }}>{fmtUsd(totalUnrealPnl)}</div>
                <div style={{ fontSize: F.xs, color: C.muted }}>{openPositions.length} open position{openPositions.length !== 1 ? 's' : ''}</div>
              </div>
              <div style={{ background: C.card, border: `1px solid ${C.border}`, borderRadius: R.lg, padding: '16px 20px', boxShadow: S.sm }}>
                <div style={{ fontSize: F.sm, color: C.muted, marginBottom: 4 }}>REALIZED P&L</div>
                <div style={{ fontSize: F['2xl'], fontWeight: 700, color: pnlColor(totalRealizedPnl) }}>{fmtUsd(totalRealizedPnl)}</div>
                <div style={{ fontSize: F.xs, color: C.muted }}>All-time closed trades</div>
              </div>
              <div style={{ background: C.card, border: `1px solid ${C.border}`, borderRadius: R.lg, padding: '16px 20px', boxShadow: S.sm }}>
                <div style={{ fontSize: F.sm, color: C.muted, marginBottom: 4 }}>RECENT 10 TRADES</div>
                <div style={{ fontSize: F['2xl'], fontWeight: 700, color: pnlColor(recentClosedPnl) }}>{fmtUsd(recentClosedPnl)}</div>
                <div style={{ fontSize: F.xs, color: C.muted }}>Last 10 closed</div>
              </div>
              <div style={{ background: C.card, border: `1px solid ${C.border}`, borderRadius: R.lg, padding: '16px 20px', boxShadow: S.sm }}>
                <div style={{ fontSize: F.sm, color: C.muted, marginBottom: 4 }}>ACTIVE STRATEGIES</div>
                <div style={{ fontSize: F['2xl'], fontWeight: 700, color: C.text }}>{strategies.length}</div>
                <div style={{ fontSize: F.xs, color: C.muted }}>
                  {strategies.filter((s) => s.lastHeartbeat && (Date.now() - new Date(s.lastHeartbeat).getTime()) < 300_000).length} live
                </div>
              </div>
            </div>

            {/* ── Exposure gauge ── */}
            {totalExposure > 0 && (
              <div style={{ background: C.card, border: `1px solid ${C.border}`, borderRadius: R.lg, padding: '4px 20px 16px', marginBottom: 24, boxShadow: S.sm }}>
                <ExposureGauge used={totalExposure} total={50000} />
              </div>
            )}

            {/* ── Concentration warning ── */}
            {concentrationWarning && (
              <div style={{
                background: 'rgba(217,119,6,0.12)', border: `1px solid ${C.warn}`,
                borderRadius: R.md, padding: '10px 16px', marginBottom: 20,
                display: 'flex', alignItems: 'center', gap: 10,
              }}>
                <span style={{ fontSize: F.lg }}>⚠</span>
                <span style={{ fontSize: F.sm, color: C.warnMid, fontWeight: 600 }}>{concentrationWarning}</span>
              </div>
            )}

            {/* ── Open Positions ── */}
            <div style={{ marginBottom: 32 }}>
              <h2 style={{ margin: '0 0 14px', fontSize: F.lg, fontWeight: 700, color: C.text, borderBottom: `1px solid ${C.border}`, paddingBottom: 10 }}>
                Open Positions ({openPositions.length})
              </h2>
              {openPositions.length === 0 ? (
                <div style={{
                  background: C.card, border: `1px solid ${C.border}`, borderRadius: R.lg,
                  padding: 32, textAlign: 'center',
                }}>
                  <div style={{ fontSize: 36, marginBottom: 8 }}>💤</div>
                  <div style={{ fontSize: F.base, color: C.muted }}>No open positions right now.</div>
                  <div style={{ fontSize: F.sm, color: C.faint, marginTop: 4 }}>The bot is watching the market but hasn't entered any trades.</div>
                </div>
              ) : (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
                  {openPositions.map((s) => <PositionCard key={s.id} strategy={s} />)}
                </div>
              )}
            </div>

            {/* ── All Strategies Status ── */}
            <div style={{ marginBottom: 32 }}>
              <h2 style={{ margin: '0 0 14px', fontSize: F.lg, fontWeight: 700, color: C.text, borderBottom: `1px solid ${C.border}`, paddingBottom: 10 }}>
                All Strategies ({strategies.length})
              </h2>
              <div style={{ background: C.card, border: `1px solid ${C.border}`, borderRadius: R.lg, overflow: 'hidden' }}>
                <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: F.sm }}>
                  <thead>
                    <tr style={{ background: C.surface }}>
                      {['Strategy', 'Status', 'Realized P&L', 'Open Position', 'Last Seen'].map((h) => (
                        <th key={h} style={{ padding: '10px 16px', textAlign: 'left', color: C.muted, fontWeight: 600, fontSize: F.xs, textTransform: 'uppercase', letterSpacing: '0.04em', borderBottom: `1px solid ${C.border}` }}>{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {strategies.map((s, i) => {
                      const isLive = s.lastHeartbeat && (Date.now() - new Date(s.lastHeartbeat).getTime()) < 300_000;
                      return (
                        <tr key={s.id} style={{ borderBottom: i < strategies.length - 1 ? `1px solid ${C.border}` : 'none' }}>
                          <td style={{ padding: '12px 16px', color: C.text, fontWeight: 600 }}>{s.id}</td>
                          <td style={{ padding: '12px 16px' }}>
                            <Badge
                              label={isLive ? '● LIVE' : 'OFFLINE'}
                              color={isLive ? C.bull : C.muted}
                              bg={isLive ? 'rgba(22,163,74,0.12)' : C.surface}
                            />
                          </td>
                          <td style={{ padding: '12px 16px', color: pnlColor(s.pnl_realized), fontWeight: 600 }}>
                            {s.pnl_realized != null ? fmtUsd(s.pnl_realized) : '—'}
                          </td>
                          <td style={{ padding: '12px 16px' }}>
                            {s.open_position ? (
                              <span style={{ color: pnlColor(s.open_position.unrealized_pnl), fontWeight: 600 }}>
                                {s.open_position.side?.toUpperCase()} {s.open_position.unrealized_pnl != null ? fmtUsd(s.open_position.unrealized_pnl) : ''}
                              </span>
                            ) : (
                              <span style={{ color: C.faint }}>—</span>
                            )}
                          </td>
                          <td style={{ padding: '12px 16px', color: C.muted }}>{timeAgo(s.lastHeartbeat)}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </div>

            {/* ── Recent Trades Waterfall ── */}
            {recentTrades.length > 0 && (
              <div style={{ marginBottom: 32 }}>
                <h2 style={{ margin: '0 0 14px', fontSize: F.lg, fontWeight: 700, color: C.text, borderBottom: `1px solid ${C.border}`, paddingBottom: 10 }}>
                  Recent Closed Trades
                </h2>
                <div style={{ background: C.card, border: `1px solid ${C.border}`, borderRadius: R.lg, padding: 20, overflowX: 'auto' }}>
                  <DailyWaterfall trades={[...recentTrades].reverse()} />
                  <div style={{ marginTop: 16, overflowX: 'auto' }}>
                    <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: F.sm, minWidth: 600 }}>
                      <thead>
                        <tr>
                          {['Symbol', 'Side', 'Strategy', 'P&L', 'Outcome', 'Close Reason', 'R:R'].map((h) => (
                            <th key={h} style={{ padding: '6px 12px', textAlign: 'left', color: C.muted, fontWeight: 600, fontSize: F.xs, borderBottom: `1px solid ${C.border}` }}>{h}</th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        {recentTrades.slice(0, 15).map((t, i) => (
                          <tr key={i} style={{
                            borderBottom: `1px solid ${C.border}`,
                            background: t.outcome === 'WIN' ? 'rgba(22,163,74,0.06)' : t.outcome === 'LOSS' ? 'rgba(220,38,38,0.06)' : 'transparent',
                          }}>
                            <td style={{ padding: '8px 12px', fontWeight: 700, color: C.text }}>{t.symbol}</td>
                            <td style={{ padding: '8px 12px', color: sideColor(t.side) }}>{t.side}</td>
                            <td style={{ padding: '8px 12px', color: C.muted, fontSize: F.xs }}>{t.strategy}</td>
                            <td style={{ padding: '8px 12px', fontWeight: 600, color: pnlColor(t.pnl) }}>{t.pnl != null ? fmtUsd(t.pnl) : '—'}</td>
                            <td style={{ padding: '8px 12px' }}>
                              <Badge label={t.outcome} color={t.outcome === 'WIN' ? C.bull : C.bear} bg={t.outcome === 'WIN' ? 'rgba(22,163,74,0.12)' : 'rgba(220,38,38,0.12)'} />
                            </td>
                            <td style={{ padding: '8px 12px', color: C.muted, fontSize: F.xs }}>{t.close_reason || '—'}</td>
                            <td style={{ padding: '8px 12px', color: t.rr_achieved != null && t.rr_achieved >= 1 ? C.bull : C.bear }}>
                              {t.rr_achieved != null ? `${t.rr_achieved.toFixed(2)}R` : '—'}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              </div>
            )}
          </>
        )}
      </div>
    </Layout>
  );
}
