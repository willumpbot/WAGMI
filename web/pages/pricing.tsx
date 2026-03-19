import React, { useState } from 'react';
import Head from 'next/head';
import Link from 'next/link';
import Layout from '../components/Layout';
import { C, R, S, F, fmtUsd } from '../src/theme';

// ─── Tier Config ──────────────────────────────────────────────────────────────

type Tier = {
  name: string;
  monthly: number | null;
  annual: number | null;
  tagline: string;
  features: { label: string; included: boolean; note?: string }[];
  cta: string;
  ctaHref: string;
  highlighted: boolean;
  badge?: string;
};

const TIERS: Tier[] = [
  {
    name: 'Observer',
    monthly: 0,
    annual: 0,
    tagline: 'See how the bot thinks. No commitment.',
    features: [
      { label: 'Live signals (delayed 15 min)', included: true },
      { label: 'Public AI audit trail', included: true, note: 'Every decision, logged' },
      { label: 'Analytics dashboard', included: true },
      { label: 'Performance track record', included: true },
      { label: 'Learning course (Sections 1–3)', included: true },
      { label: 'Real-time signals', included: false },
      { label: 'Telegram alerts', included: false },
      { label: 'Morning brief', included: false },
      { label: 'Full course access', included: false },
      { label: 'Auto-execution', included: false },
    ],
    cta: 'Get Started Free',
    ctaHref: '/',
    highlighted: false,
  },
  {
    name: 'Pro',
    monthly: 29,
    annual: 232,
    tagline: 'Everything you need to follow the bot profitably.',
    badge: 'Most Popular',
    features: [
      { label: 'Real-time signals (no delay)', included: true },
      { label: 'Full AI audit trail', included: true },
      { label: 'Analytics dashboard', included: true },
      { label: 'Telegram alerts — instant', included: true, note: 'Signal, TP hit, close' },
      { label: 'Daily morning brief', included: true },
      { label: 'Full course (all 8 sections)', included: true },
      { label: 'Risk calculator + tools', included: true },
      { label: 'Discord community access', included: true },
      { label: 'Copy-trade setup guide', included: true },
      { label: 'Auto-execution', included: false },
    ],
    cta: 'Start 7-Day Free Trial',
    ctaHref: '/copy-trade',
    highlighted: true,
  },
  {
    name: 'Elite',
    monthly: 97,
    annual: 776,
    tagline: 'Automated execution with custom risk parameters.',
    features: [
      { label: 'Everything in Pro', included: true },
      { label: 'Auto-execution on Hyperliquid', included: true, note: 'API key required' },
      { label: 'Custom risk parameters', included: true, note: 'Your sizing, your limits' },
      { label: 'Multi-symbol expansion', included: true, note: 'Beyond BTC/SOL/HYPE' },
      { label: 'API access', included: true },
      { label: 'Priority support', included: true },
      { label: 'Dedicated onboarding call', included: true },
      { label: 'Custom alert thresholds', included: true },
      { label: 'Performance reporting', included: true },
      { label: 'Early access to new agents', included: true },
    ],
    cta: 'Talk to Us',
    ctaHref: '/about',
    highlighted: false,
  },
];

// ─── Returns Calculator ───────────────────────────────────────────────────────

function ReturnsCalc({ returnPct }: { returnPct: number }) {
  const [capital, setCapital] = useState(10000);
  const projected = capital * (returnPct / 100);
  return (
    <div style={{ background: C.card, border: `1px solid ${C.border}`, borderRadius: R.xl, padding: '24px 28px', maxWidth: 480, marginLeft: 'auto', marginRight: 'auto' }}>
      <div style={{ fontSize: F.sm, fontWeight: 700, color: C.text, marginBottom: 16 }}>What could this mean for you?</div>
      <div style={{ marginBottom: 14 }}>
        <label style={{ fontSize: F.xs, color: C.muted, display: 'block', marginBottom: 6 }}>Your trading capital</label>
        <input
          type="range" min={1000} max={100000} step={1000} value={capital}
          onChange={(e) => setCapital(Number(e.target.value))}
          style={{ width: '100%', accentColor: C.brand }}
        />
        <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 4 }}>
          <span style={{ fontSize: F.xs, color: C.muted }}>$1,000</span>
          <span style={{ fontSize: F.base, fontWeight: 700, color: C.text }}>{fmtUsd(capital, 0)}</span>
          <span style={{ fontSize: F.xs, color: C.muted }}>$100,000</span>
        </div>
      </div>
      <div style={{ background: C.surface, borderRadius: R.md, padding: '14px 16px', textAlign: 'center' }}>
        <div style={{ fontSize: F.xs, color: C.muted, marginBottom: 4 }}>Projected return at {returnPct.toFixed(1)}% (30-day backtest rate)</div>
        <div style={{ fontSize: F['2xl'], fontWeight: 800, color: C.bull }}>{fmtUsd(projected)}</div>
        <div style={{ fontSize: F.xs, color: C.muted, marginTop: 4 }}>Past performance does not predict future results</div>
      </div>
    </div>
  );
}

// ─── Feature Comparison ───────────────────────────────────────────────────────

const ALL_FEATURES = [
  { category: 'Signals', rows: [
    { feature: 'Live signals', observer: 'Delayed 15m', pro: 'Real-time', elite: 'Real-time' },
    { feature: 'Signal reasoning', observer: '✓', pro: '✓', elite: '✓' },
    { feature: 'AI confidence score', observer: '✓', pro: '✓', elite: '✓' },
    { feature: 'Symbols covered', observer: 'BTC, SOL, HYPE', pro: 'BTC, SOL, HYPE', elite: 'Unlimited' },
  ]},
  { category: 'Alerts', rows: [
    { feature: 'Telegram signal alerts', observer: '—', pro: '✓', elite: '✓' },
    { feature: 'Telegram TP/close alerts', observer: '—', pro: '✓', elite: '✓' },
    { feature: 'Morning brief (06:00 UTC)', observer: '—', pro: '✓', elite: '✓' },
    { feature: 'Custom thresholds', observer: '—', pro: '—', elite: '✓' },
  ]},
  { category: 'Analytics', rows: [
    { feature: 'Track record & forensics', observer: '✓', pro: '✓', elite: '✓' },
    { feature: 'AI audit trail', observer: '✓', pro: '✓', elite: '✓' },
    { feature: 'Performance metrics (Sharpe etc.)', observer: '✓', pro: '✓', elite: '✓' },
    { feature: 'Portfolio page', observer: '✓', pro: '✓', elite: '✓' },
  ]},
  { category: 'Execution', rows: [
    { feature: 'Manual copy trade guide', observer: '✓', pro: '✓', elite: '✓' },
    { feature: 'Auto-execution (API)', observer: '—', pro: '—', elite: '✓' },
    { feature: 'Custom risk parameters', observer: '—', pro: '—', elite: '✓' },
    { feature: 'API access', observer: '—', pro: '—', elite: '✓' },
  ]},
  { category: 'Learning', rows: [
    { feature: 'Course (Sections 1–3)', observer: '✓', pro: '✓', elite: '✓' },
    { feature: 'Full course (8 sections)', observer: '—', pro: '✓', elite: '✓' },
    { feature: 'Interactive calculators', observer: 'Basic', pro: '✓', elite: '✓' },
  ]},
  { category: 'Support', rows: [
    { feature: 'Discord community', observer: 'Read-only', pro: '✓', elite: '✓' },
    { feature: 'Priority support', observer: '—', pro: '—', elite: '✓' },
    { feature: 'Onboarding call', observer: '—', pro: '—', elite: '✓' },
  ]},
];

function FeatureTable({ annual }: { annual: boolean }) {
  const [expanded, setExpanded] = useState(false);
  const showCategories = expanded ? ALL_FEATURES : ALL_FEATURES.slice(0, 3);
  return (
    <div>
      <div style={{ overflowX: 'auto' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: F.sm, minWidth: 560 }}>
          <thead>
            <tr style={{ background: C.surface }}>
              <th style={{ padding: '10px 16px', textAlign: 'left', color: C.muted, fontWeight: 600, fontSize: F.xs, borderBottom: `1px solid ${C.border}` }}>Feature</th>
              {['Observer', 'Pro', 'Elite'].map((t) => (
                <th key={t} style={{ padding: '10px 16px', textAlign: 'center', color: t === 'Pro' ? C.brand : C.muted, fontWeight: 700, fontSize: F.xs, borderBottom: `1px solid ${C.border}` }}>{t}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {showCategories.map((cat) => (
              <React.Fragment key={cat.category}>
                <tr>
                  <td colSpan={4} style={{ padding: '10px 16px 4px', fontSize: F.xs, fontWeight: 700, color: C.brand, textTransform: 'uppercase', letterSpacing: '0.05em', background: `${C.brand}08` }}>{cat.category}</td>
                </tr>
                {cat.rows.map((row) => (
                  <tr key={row.feature} style={{ borderBottom: `1px solid ${C.border}` }}>
                    <td style={{ padding: '9px 16px', color: C.textSub }}>{row.feature}</td>
                    {[row.observer, row.pro, row.elite].map((v, i) => (
                      <td key={i} style={{ padding: '9px 16px', textAlign: 'center', color: v === '✓' ? C.bull : v === '—' ? C.faint : C.muted, fontWeight: v === '✓' ? 700 : 400 }}>{v}</td>
                    ))}
                  </tr>
                ))}
              </React.Fragment>
            ))}
          </tbody>
        </table>
      </div>
      {!expanded && (
        <button onClick={() => setExpanded(true)} style={{ width: '100%', padding: '12px', background: C.card, border: `1px solid ${C.border}`, borderTop: 'none', borderRadius: `0 0 ${R.lg}px ${R.lg}px`, cursor: 'pointer', color: C.brand, fontSize: F.sm, fontWeight: 600 }}>
          Show all features ↓
        </button>
      )}
    </div>
  );
}

// ─── FAQ ──────────────────────────────────────────────────────────────────────

function PFAQ({ q, a }: { q: string; a: string }) {
  const [open, setOpen] = useState(false);
  return (
    <div style={{ border: `1px solid ${C.border}`, borderRadius: R.md, marginBottom: 8 }}>
      <button onClick={() => setOpen((v) => !v)} style={{ width: '100%', display: 'flex', justifyContent: 'space-between', padding: '13px 16px', background: C.card, border: 'none', cursor: 'pointer', textAlign: 'left', gap: 8 }}>
        <span style={{ fontSize: F.sm, fontWeight: 600, color: C.text }}>{q}</span>
        <span style={{ color: C.muted, flexShrink: 0, transition: 'transform 0.15s', transform: open ? 'rotate(45deg)' : 'none', display: 'inline-block' }}>+</span>
      </button>
      {open && <div style={{ padding: '0 16px 14px', fontSize: F.sm, color: C.textSub, lineHeight: 1.7, background: C.card, borderTop: `1px solid ${C.border}` }}>{a}</div>}
    </div>
  );
}

// ─── Main Page ────────────────────────────────────────────────────────────────

export default function PricingPage() {
  const [annual, setAnnual] = useState(false);
  const returnPct = 11.34; // from backtest results

  return (
    <Layout>
      <Head>
        <title>Pricing — WAGMI</title>
        <meta name="description" content="Start free. Upgrade when you're ready to automate. Three clear tiers with honest feature differentiation." />
      </Head>

      <div style={{ maxWidth: 1000, margin: '0 auto', padding: '40px 20px' }}>

        {/* ── Header ── */}
        <div style={{ textAlign: 'center', marginBottom: 40 }}>
          <h1 style={{ margin: '0 0 12px', fontSize: F['3xl'], fontWeight: 900, color: C.text, letterSpacing: -0.5 }}>Pick your edge.</h1>
          <p style={{ margin: '0 0 24px', fontSize: F.base, color: C.muted }}>Start free. Upgrade when you're ready to automate.</p>

          {/* Annual toggle */}
          <div style={{ display: 'inline-flex', alignItems: 'center', gap: 10, background: C.card, border: `1px solid ${C.border}`, borderRadius: R.pill, padding: '4px 8px' }}>
            <button onClick={() => setAnnual(false)} style={{ padding: '5px 16px', borderRadius: R.pill, border: 'none', cursor: 'pointer', background: !annual ? C.brand : 'transparent', color: !annual ? '#fff' : C.muted, fontSize: F.sm, fontWeight: 600 }}>Monthly</button>
            <button onClick={() => setAnnual(true)} style={{ padding: '5px 16px', borderRadius: R.pill, border: 'none', cursor: 'pointer', background: annual ? C.brand : 'transparent', color: annual ? '#fff' : C.muted, fontSize: F.sm, fontWeight: 600 }}>
              Annual <span style={{ fontSize: F.xs, color: annual ? '#c7d2fe' : C.bull, marginLeft: 4 }}>Save 33%</span>
            </button>
          </div>
        </div>

        {/* ── Tier Cards ── */}
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 16, marginBottom: 48, alignItems: 'start' }}>
          {TIERS.map((tier) => {
            const price = annual && tier.annual != null ? tier.annual / 12 : tier.monthly;
            return (
              <div key={tier.name} style={{
                background: C.card, border: `1px solid ${tier.highlighted ? C.brand : C.border}`,
                borderRadius: R.xl, padding: '28px 24px', position: 'relative',
                boxShadow: tier.highlighted ? S.glow : S.sm,
                transform: tier.highlighted ? 'translateY(-6px)' : 'none',
              }}>
                {tier.badge && (
                  <div style={{ position: 'absolute', top: -12, left: '50%', transform: 'translateX(-50%)', padding: '3px 14px', borderRadius: R.pill, background: C.brand, color: '#fff', fontSize: F.xs, fontWeight: 700, whiteSpace: 'nowrap' }}>{tier.badge}</div>
                )}
                <div style={{ fontSize: F.lg, fontWeight: 800, color: C.text, marginBottom: 4 }}>{tier.name}</div>
                <div style={{ fontSize: F.sm, color: C.muted, marginBottom: 16, lineHeight: 1.4 }}>{tier.tagline}</div>
                <div style={{ marginBottom: 20 }}>
                  <span style={{ fontSize: 36, fontWeight: 900, color: tier.highlighted ? C.brand : C.text }}>
                    {price === 0 ? 'Free' : `$${price?.toFixed(0)}`}
                  </span>
                  {price !== null && price > 0 && (
                    <span style={{ fontSize: F.sm, color: C.muted }}>/month{annual ? ' · billed annually' : ''}</span>
                  )}
                </div>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 8, marginBottom: 24 }}>
                  {tier.features.map((f) => (
                    <div key={f.label} style={{ display: 'flex', gap: 8, alignItems: 'flex-start' }}>
                      <span style={{ color: f.included ? C.bull : C.faint, flexShrink: 0, fontWeight: 700, marginTop: 1 }}>{f.included ? '✓' : '—'}</span>
                      <span style={{ fontSize: F.xs, color: f.included ? C.textSub : C.faint, lineHeight: 1.4 }}>
                        {f.label}{f.note && <span style={{ color: C.muted }}> ({f.note})</span>}
                      </span>
                    </div>
                  ))}
                </div>
                <Link href={tier.ctaHref} style={{
                  display: 'block', textAlign: 'center', padding: '11px 0',
                  background: tier.highlighted ? C.brand : C.surface,
                  color: tier.highlighted ? '#fff' : C.textSub,
                  border: `1px solid ${tier.highlighted ? C.brand : C.border}`,
                  borderRadius: R.md, fontSize: F.sm, fontWeight: 700, textDecoration: 'none',
                }}>{tier.cta}</Link>
              </div>
            );
          })}
        </div>

        {/* ── Returns Calculator ── */}
        <div style={{ marginBottom: 52 }}>
          <ReturnsCalc returnPct={returnPct} />
        </div>

        {/* ── Feature Table ── */}
        <div style={{ marginBottom: 52 }}>
          <h2 style={{ margin: '0 0 20px', fontSize: F.xl, fontWeight: 700, color: C.text, textAlign: 'center' }}>Full feature comparison</h2>
          <div style={{ background: C.card, border: `1px solid ${C.border}`, borderRadius: R.lg, overflow: 'hidden' }}>
            <FeatureTable annual={annual} />
          </div>
        </div>

        {/* ── Social Proof ── */}
        <div style={{ background: `${C.brand}10`, border: `1px solid ${C.brand}30`, borderRadius: R.xl, padding: '24px 28px', marginBottom: 48, textAlign: 'center' }}>
          <div style={{ fontSize: F.xl, fontWeight: 700, color: C.text, marginBottom: 8 }}>7-day money back guarantee</div>
          <div style={{ fontSize: F.sm, color: C.muted }}>Try Pro or Elite for 7 days. If it's not for you, we'll refund without questions.</div>
        </div>

        {/* ── FAQ ── */}
        <div style={{ marginBottom: 40 }}>
          <h2 style={{ margin: '0 0 20px', fontSize: F.xl, fontWeight: 700, color: C.text, textAlign: 'center' }}>Pricing FAQ</h2>
          <PFAQ q="Is there a free trial?" a="Yes — Pro has a 7-day free trial, no credit card required. Observer is free forever with no time limit." />
          <PFAQ q="Can I cancel anytime?" a="Yes. Monthly plans cancel immediately. Annual plans get a prorated refund in the first 30 days." />
          <PFAQ q="What is auto-execution?" a="Elite tier connects to your Hyperliquid API key and places trades automatically when the bot fires a signal. You set the capital allocation and risk parameters; the bot handles execution." />
          <PFAQ q="Do I need my own Hyperliquid account?" a="Yes for Pro and Elite. For Observer and learning purposes, you can follow signals manually on any exchange that lists BTC/SOL/HYPE perps." />
          <PFAQ q="What if I want to scale up my position size?" a="The bot sizes positions at 1.5% risk per trade based on the capital amount you set in Settings. You can adjust this under Elite's custom risk parameters." />
          <PFAQ q="Is there a difference between the AI signals on Pro vs Elite?" a="No — the AI analysis is identical across all tiers. The difference is delivery speed (delayed vs real-time) and execution mode (manual vs auto)." />
        </div>

        {/* ── Final CTA ── */}
        <div style={{ textAlign: 'center', paddingBottom: 20 }}>
          <div style={{ fontSize: F.sm, color: C.muted, marginBottom: 20 }}>
            Still evaluating? Start with the free track record. No account required.
          </div>
          <div style={{ display: 'flex', gap: 12, justifyContent: 'center', flexWrap: 'wrap' }}>
            <Link href="/results" style={{ padding: '10px 22px', border: `1px solid ${C.border}`, color: C.textSub, borderRadius: R.md, fontSize: F.sm, fontWeight: 600, textDecoration: 'none' }}>
              See the Track Record →
            </Link>
            <Link href="/copy-trade" style={{ padding: '10px 22px', background: C.brand, color: '#fff', borderRadius: R.md, fontSize: F.sm, fontWeight: 700, textDecoration: 'none', boxShadow: S.glow }}>
              Start Free →
            </Link>
          </div>
        </div>
      </div>
    </Layout>
  );
}
