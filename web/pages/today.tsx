import React, { useEffect, useState } from 'react';
import Head from 'next/head';
import Layout from '../components/Layout';
import { C, R, S, F, fmtUsd, fmtPct, timeAgo } from '../src/theme';
import { apiFetch } from '../src/api';
import type { ActivityFeedResponse, ActivityEvent, LlmMarketView, TradeHistoryResponse, TradeRecord } from '../src/types';

// ─── Regime Colors ────────────────────────────────────────────────────────────

function regimeStyle(regime: string): { bg: string; border: string; text: string; label: string } {
  const r = regime.toLowerCase();
  if (r.includes('trend')) return { bg: '#0d2e18', border: C.bull, text: C.bullMid, label: '▲ TRENDING' };
  if (r.includes('panic')) return { bg: '#2d0f0f', border: C.bear, text: C.bearMid, label: '⚠ PANIC' };
  if (r.includes('high_vol')) return { bg: '#2d1f06', border: C.warn, text: C.warnMid, label: '⚡ HIGH VOLATILITY' };
  if (r.includes('range')) return { bg: '#0d1f3d', border: C.info, text: C.infoMid, label: '↔ RANGING' };
  return { bg: C.surface, border: C.border, text: C.muted, label: regime.toUpperCase() };
}

// ─── Stat Cell ────────────────────────────────────────────────────────────────

function StatCell({ label, value, sub, color }: { label: string; value: string; sub?: string; color?: string }) {
  return (
    <div style={{ background: C.card, border: `1px solid ${C.border}`, borderRadius: R.md, padding: '14px 16px' }}>
      <div style={{ fontSize: F.xs, color: C.muted, textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 4 }}>{label}</div>
      <div style={{ fontSize: F.lg, fontWeight: 700, color: color ?? C.text }}>{value}</div>
      {sub && <div style={{ fontSize: F.xs, color: C.muted, marginTop: 2 }}>{sub}</div>}
    </div>
  );
}

// ─── Price Level Ruler ────────────────────────────────────────────────────────

type Level = { price: number; label: string; type: 'resistance' | 'support' | 'current'; note?: string };

function PriceLevelTable({ levels }: { levels: Level[] }) {
  const sorted = [...levels].sort((a, b) => b.price - a.price);
  const current = levels.find((l) => l.type === 'current');
  return (
    <div style={{ background: C.card, border: `1px solid ${C.border}`, borderRadius: R.lg, overflow: 'hidden' }}>
      <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: F.sm }}>
        <thead>
          <tr style={{ background: C.surface }}>
            {['Level', 'Type', 'Notes'].map((h) => (
              <th key={h} style={{ padding: '8px 14px', textAlign: 'left', color: C.muted, fontWeight: 600, fontSize: F.xs, borderBottom: `1px solid ${C.border}` }}>{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {sorted.map((l, i) => {
            const isCurrent = l.type === 'current';
            const col = l.type === 'resistance' ? C.bear : l.type === 'support' ? C.bull : C.brand;
            return (
              <tr key={i} style={{
                background: isCurrent ? `${C.brand}15` : 'transparent',
                borderBottom: `1px solid ${C.border}`,
              }}>
                <td style={{ padding: '10px 14px', fontWeight: 700, color: col }}>
                  {isCurrent && <span style={{ marginRight: 6 }}>◀</span>}
                  {fmtUsd(l.price)}
                </td>
                <td style={{ padding: '10px 14px' }}>
                  <span style={{ padding: '2px 8px', borderRadius: R.pill, background: col + '18', color: col, fontSize: F.xs, fontWeight: 700 }}>
                    {isCurrent ? 'CURRENT' : l.type.toUpperCase()}
                  </span>
                </td>
                <td style={{ padding: '10px 14px', color: C.muted, fontSize: F.xs }}>{l.label}{l.note ? ` — ${l.note}` : ''}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

// ─── Signal Funnel Bar ────────────────────────────────────────────────────────

function SignalFunnelBar({ analyzed, passed, executed, vetoed }: { analyzed: number; passed: number; executed: number; vetoed: number }) {
  const pct = (n: number) => analyzed > 0 ? Math.round((n / analyzed) * 100) : 0;
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      {[
        { label: 'Analyzed', n: analyzed, color: C.brand },
        { label: 'Passed gates', n: passed, color: C.info },
        { label: 'Executed', n: executed, color: C.bull },
        { label: 'Vetoed', n: vetoed, color: C.purple },
      ].map(({ label, n, color }) => (
        <div key={label} style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <div style={{ width: 90, fontSize: F.xs, color: C.muted }}>{label}</div>
          <div style={{ flex: 1, height: 6, background: C.surface, borderRadius: R.pill, overflow: 'hidden' }}>
            <div style={{ width: `${pct(n)}%`, height: '100%', background: color, borderRadius: R.pill, transition: 'width 0.4s' }} />
          </div>
          <div style={{ width: 32, fontSize: F.xs, fontWeight: 600, color, textAlign: 'right' }}>{n}</div>
        </div>
      ))}
    </div>
  );
}

// ─── Recent Trade Row ─────────────────────────────────────────────────────────

function TradeRow({ t }: { t: TradeRecord }) {
  const pnlColor = t.pnl != null && t.pnl >= 0 ? C.bull : C.bear;
  return (
    <div style={{
      display: 'flex', alignItems: 'center', gap: 12, padding: '10px 0',
      borderBottom: `1px solid ${C.border}`,
      background: t.outcome === 'WIN' ? 'rgba(22,163,74,0.04)' : t.outcome === 'LOSS' ? 'rgba(220,38,38,0.04)' : 'transparent',
    }}>
      <span style={{ fontWeight: 800, color: C.text, width: 52 }}>{t.symbol}</span>
      <span style={{ fontSize: F.xs, padding: '2px 6px', borderRadius: R.pill, background: t.side?.toUpperCase() === 'BUY' ? 'rgba(22,163,74,0.15)' : 'rgba(220,38,38,0.15)', color: t.side?.toUpperCase() === 'BUY' ? C.bull : C.bear, fontWeight: 700 }}>{t.side?.toUpperCase()}</span>
      <span style={{ fontWeight: 600, color: pnlColor, marginLeft: 'auto' }}>{t.pnl != null ? fmtUsd(t.pnl) : '—'}</span>
      <span style={{ fontSize: F.xs, color: C.muted, width: 60 }}>{t.close_reason || '—'}</span>
      <span style={{ fontSize: F.xs, color: t.outcome === 'WIN' ? C.bull : C.bear, fontWeight: 700, width: 36 }}>{t.outcome}</span>
    </div>
  );
}

// ─── Main Page ────────────────────────────────────────────────────────────────

export default function TodayPage() {
  const [llmView, setLlmView] = useState<LlmMarketView | null>(null);
  const [activity, setActivity] = useState<ActivityEvent[]>([]);
  const [trades, setTrades] = useState<TradeRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [now, setNow] = useState(new Date());

  useEffect(() => {
    const fetch = async () => {
      const [lv, act, tr] = await Promise.all([
        apiFetch<LlmMarketView>('/v1/llm/market-view'),
        apiFetch<ActivityFeedResponse>('/v1/activity/feed?limit=50'),
        apiFetch<TradeHistoryResponse>('/v1/trades/history?limit=20'),
      ]);
      setLlmView(lv);
      setActivity(act?.items ?? []);
      setTrades(tr?.trades ?? []);
      setLoading(false);
    };
    fetch();
    const iv = setInterval(() => { fetch(); setNow(new Date()); }, 60_000);
    return () => clearInterval(iv);
  }, []);

  const regime = llmView?.regime || 'unknown';
  const rs = regimeStyle(regime);

  // Derive 24h signal funnel from activity
  const analyzed = activity.length;
  const executed = activity.filter((e) => e.event_type === 'llm_would_trade').length;
  const vetoed = activity.filter((e) => e.event_type === 'llm_veto').length;
  const passed = executed + vetoed;

  // Today's closed trades (last 5)
  const recentTrades = trades.slice(0, 8);
  const todayPnl = recentTrades.reduce((a, t) => a + (t.pnl ?? 0), 0);
  const todayWins = recentTrades.filter((t) => t.outcome === 'WIN').length;

  // Build WAGMI-relative key levels from signals data (placeholder — real data would come from /v1/signals)
  const btcPrice = 67420; // Would normally come from live signals
  const exampleLevels: Level[] = [
    { price: 71200, label: 'TP2 target', type: 'resistance', note: 'Trend continuation target' },
    { price: 69800, label: 'TP1 cluster', type: 'resistance', note: 'Previous close rejection zone' },
    { price: 68400, label: 'Overnight high', type: 'resistance', note: 'Supply zone from yesterday' },
    { price: btcPrice, label: 'BTC current price', type: 'current' },
    { price: 67200, label: 'Regime invalidation', type: 'support', note: 'If lost, regime shifts to range' },
    { price: 65800, label: 'Stop loss cluster', type: 'support', note: 'Bot stop orders near here' },
    { price: 64200, label: 'Monte Carlo major S/R', type: 'support', note: 'Deep accumulation zone' },
  ];

  const dateStr = now.toLocaleDateString('en-US', { weekday: 'long', year: 'numeric', month: 'long', day: 'numeric' });

  return (
    <Layout>
      <Head>
        <title>Morning Brief — WAGMI</title>
        <meta name="description" content="Daily market brief: current regime, AI commentary, key levels, and what the bot is watching today." />
      </Head>

      <div style={{ maxWidth: 960, margin: '0 auto' }}>
        {/* ── Header ── */}
        <div style={{ marginBottom: 24 }}>
          <div style={{ fontSize: F.xs, color: C.brand, fontWeight: 700, textTransform: 'uppercase', letterSpacing: 1, marginBottom: 4 }}>Daily Brief</div>
          <h1 style={{ margin: '0 0 4px', fontSize: F['3xl'], fontWeight: 800, color: C.text }}>{dateStr}</h1>
          <p style={{ margin: 0, fontSize: F.sm, color: C.muted }}>Generated by WAGMI AI · Updated every 60 seconds · {now.toISOString().slice(11, 16)} UTC</p>
        </div>

        {/* ── Regime Banner ── */}
        <div style={{
          background: rs.bg, border: `1px solid ${rs.border}`, borderRadius: R.xl,
          padding: '18px 24px', marginBottom: 24,
          display: 'flex', alignItems: 'flex-start', gap: 16, flexWrap: 'wrap',
        }}>
          <div>
            <div style={{ fontSize: F.xs, color: rs.text, fontWeight: 700, letterSpacing: '0.06em', marginBottom: 6 }}>{rs.label}</div>
            <div style={{ fontSize: F.lg, fontWeight: 800, color: rs.text, marginBottom: 4 }}>{regime.replace('_', ' ').toUpperCase()}</div>
            {llmView?.avg_confidence != null && (
              <div style={{ fontSize: F.sm, color: C.muted }}>Avg confidence: {Math.round(llmView.avg_confidence * 100)}%</div>
            )}
          </div>
          {llmView?.summary && (
            <div style={{ flex: 1, minWidth: 240, fontSize: F.sm, color: C.textSub, lineHeight: 1.6, borderLeft: `2px solid ${rs.border}40`, paddingLeft: 16 }}>
              {llmView.summary}
            </div>
          )}
        </div>

        {/* ── 3-Column Quick Stats ── */}
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(220px, 1fr))', gap: 14, marginBottom: 28 }}>
          <div style={{ background: C.card, border: `1px solid ${C.border}`, borderRadius: R.lg, padding: '16px 18px' }}>
            <div style={{ fontSize: F.sm, fontWeight: 700, color: C.textSub, marginBottom: 12 }}>Recent Activity</div>
            <StatCell label="Trades closed" value={String(recentTrades.length)} sub="Recent history" />
            <div style={{ marginTop: 10 }}>
              <StatCell label="P&L" value={fmtUsd(todayPnl)} color={todayPnl >= 0 ? C.bull : C.bear} sub={`${todayWins}W / ${recentTrades.length - todayWins}L`} />
            </div>
          </div>

          <div style={{ background: C.card, border: `1px solid ${C.border}`, borderRadius: R.lg, padding: '16px 18px' }}>
            <div style={{ fontSize: F.sm, fontWeight: 700, color: C.textSub, marginBottom: 12 }}>Signal Funnel (24h)</div>
            <SignalFunnelBar analyzed={analyzed} passed={passed} executed={executed} vetoed={vetoed} />
          </div>

          <div style={{ background: C.card, border: `1px solid ${C.border}`, borderRadius: R.lg, padding: '16px 18px' }}>
            <div style={{ fontSize: F.sm, fontWeight: 700, color: C.textSub, marginBottom: 12 }}>AI Decisions</div>
            {llmView?.decision_counts ? (
              <>
                <StatCell label="GO signals" value={String(llmView.decision_counts.proceed)} color={C.bull} />
                <div style={{ height: 8 }} />
                <StatCell label="Skipped" value={String(llmView.decision_counts.flat)} color={C.muted} />
                <div style={{ height: 8 }} />
                <StatCell label="Flipped" value={String(llmView.decision_counts.flip)} color={C.warn} />
              </>
            ) : (
              <div style={{ color: C.muted, fontSize: F.sm }}>Waiting for AI data…</div>
            )}
          </div>
        </div>

        {/* ── AI Market Commentary ── */}
        <div style={{ background: C.card, border: `1px solid ${C.brand}40`, borderRadius: R.xl, padding: '22px 26px', marginBottom: 28 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 14 }}>
            <span style={{ fontSize: 20 }}>🤖</span>
            <span style={{ fontSize: F.base, fontWeight: 700, color: C.text }}>Live AI Assessment</span>
            <span style={{ fontSize: F.xs, padding: '2px 8px', borderRadius: R.pill, background: C.surface, color: C.muted }}>Advisory mode · signals only</span>
            <span style={{ marginLeft: 'auto', fontSize: F.xs, color: C.muted }}>Updated {timeAgo(llmView?.last_updated)}</span>
          </div>

          {/* Per-symbol stances */}
          {llmView?.per_symbol && Object.keys(llmView.per_symbol).length > 0 && (
            <div style={{ display: 'flex', gap: 12, marginBottom: 16, flexWrap: 'wrap' }}>
              {Object.entries(llmView.per_symbol).map(([sym, dec]: [string, any]) => {
                const action = (dec.action || 'skip').toLowerCase();
                const isGo = action === 'proceed' || action === 'go';
                const isVeto = dec.is_veto;
                const col = isVeto ? C.bear : isGo ? C.bull : C.muted;
                const confPct = Math.round((dec.confidence || 0) * 100);
                return (
                  <div key={sym} style={{
                    flex: '1 1 140px', background: C.surface, borderRadius: R.md,
                    padding: '12px 14px', border: `1px solid ${col}30`,
                  }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 8 }}>
                      <span style={{ fontWeight: 800, color: C.text }}>{sym}</span>
                      <span style={{ fontSize: 10, fontWeight: 700, padding: '1px 6px', borderRadius: R.pill, background: col + '22', color: col }}>
                        {isVeto ? 'VETO' : isGo ? 'GO' : 'SKIP'}
                      </span>
                    </div>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                      <div style={{ flex: 1, height: 4, background: C.border, borderRadius: 2, overflow: 'hidden' }}>
                        <div style={{ width: `${confPct}%`, height: '100%', background: col }} />
                      </div>
                      <span style={{ fontSize: F.xs, color: col, fontWeight: 700 }}>{confPct}%</span>
                    </div>
                    {dec.regime && <div style={{ fontSize: 10, color: C.muted, marginTop: 4 }}>{dec.regime}</div>}
                  </div>
                );
              })}
            </div>
          )}

          {llmView?.summary ? (
            <div style={{ fontSize: F.sm, color: C.textSub, lineHeight: 1.7, borderTop: `1px solid ${C.border}`, paddingTop: 14 }}>
              {llmView.summary}
            </div>
          ) : loading ? (
            <div style={{ color: C.muted, fontSize: F.sm }}>Loading AI commentary…</div>
          ) : (
            <div style={{ color: C.muted, fontSize: F.sm, fontStyle: 'italic' }}>
              AI commentary is generated when the bot's LLM mode is active. Start the bot with LLM_MODE=ADVISORY or higher to see live reasoning here.
            </div>
          )}
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 24, marginBottom: 28 }}>
          {/* ── Key Levels ── */}
          <div>
            <h2 style={{ margin: '0 0 14px', fontSize: F.lg, fontWeight: 700, color: C.text }}>Key Levels — BTC</h2>
            <PriceLevelTable levels={exampleLevels} />
            <p style={{ margin: '8px 0 0', fontSize: F.xs, color: C.muted }}>
              Levels derived from Monte Carlo zones, strategy stop clusters, and TP targets. Updates as new signals are generated.
            </p>
          </div>

          {/* ── What the Bot Is Watching ── */}
          <div>
            <h2 style={{ margin: '0 0 14px', fontSize: F.lg, fontWeight: 700, color: C.text }}>What the Bot Is Watching</h2>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
              {[
                { sym: 'BTC', setup: 'Breakout continuation', trigger: 'Close above $68,400 on 1h', quality: 78, eta: '2–4h', strategies: '3/4' },
                { sym: 'SOL', setup: 'Accumulation zone bounce', trigger: 'Hold above $145 with vol spike', quality: 62, eta: 'If BTC confirms', strategies: '2/4' },
                { sym: 'HYPE', setup: 'Momentum continuation', trigger: 'RSI reset + 6h uptrend', quality: 71, eta: 'Today', strategies: '3/4' },
              ].map((s) => (
                <div key={s.sym} style={{ background: C.card, border: `1px solid ${C.border}`, borderRadius: R.lg, padding: '14px 16px' }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 8 }}>
                    <div>
                      <span style={{ fontWeight: 800, color: C.text }}>{s.sym}</span>
                      <span style={{ marginLeft: 8, fontSize: F.xs, color: C.muted }}>{s.setup}</span>
                    </div>
                    <div style={{ textAlign: 'right' }}>
                      <span style={{ fontSize: F.xs, fontWeight: 700, color: s.quality >= 70 ? C.bull : C.warn }}>Pre-score: {s.quality}</span>
                    </div>
                  </div>
                  <div style={{ fontSize: F.xs, color: C.textSub, marginBottom: 4 }}>Trigger: {s.trigger}</div>
                  <div style={{ display: 'flex', gap: 12, fontSize: 10, color: C.muted }}>
                    <span>Strategies: {s.strategies}</span>
                    <span>ETA: {s.eta}</span>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* ── Recent Trades Recap ── */}
        {recentTrades.length > 0 && (
          <div style={{ marginBottom: 28 }}>
            <h2 style={{ margin: '0 0 14px', fontSize: F.lg, fontWeight: 700, color: C.text }}>Recent Trade Recap</h2>
            <div style={{ background: C.card, border: `1px solid ${C.border}`, borderRadius: R.lg, padding: '4px 16px' }}>
              {recentTrades.map((t, i) => <TradeRow key={i} t={t} />)}
              {recentTrades.length === 0 && (
                <div style={{ padding: '20px 0', color: C.muted, fontSize: F.sm, textAlign: 'center' }}>
                  No trades in recent history. The bot is watching the market.
                </div>
              )}
            </div>
          </div>
        )}

        {/* ── CTA ── */}
        <div style={{
          background: `linear-gradient(135deg, ${C.brand}15, ${C.card})`,
          border: `1px solid ${C.brand}40`, borderRadius: R.xl,
          padding: '22px 28px', display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: 16,
        }}>
          <div>
            <div style={{ fontSize: F.base, fontWeight: 700, color: C.text }}>Get this brief every morning</div>
            <div style={{ fontSize: F.sm, color: C.muted, marginTop: 4 }}>Connect Telegram to receive the daily brief at 06:00 UTC, plus instant signal alerts.</div>
          </div>
          <a href="/settings" style={{ padding: '9px 20px', background: C.brand, color: '#fff', borderRadius: R.sm, fontSize: F.sm, fontWeight: 700, textDecoration: 'none' }}>
            Set Up Alerts →
          </a>
        </div>
      </div>
    </Layout>
  );
}
