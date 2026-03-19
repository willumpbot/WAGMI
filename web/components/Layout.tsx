import React, { useEffect, useState, useRef } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/router';
import { C, R, S, timeAgo } from '../src/theme';

const NAV_ITEMS = [
  { href: '/', label: 'Dashboard' },
  { href: '/signals', label: '🔴 Signals' },
  { href: '/copy-trade', label: 'Copy Trade' },
  { href: '/portfolio', label: 'Portfolio' },
  { href: '/results', label: 'Results' },
  { href: '/performance', label: 'Performance' },
  { href: '/backtest', label: 'Backtest' },
  { href: '/forensics', label: 'Forensics' },
  { href: '/llm-audit', label: 'LLM Audit' },
  { href: '/strategies', label: 'Strategies' },
  { href: '/learn', label: 'Learn' },
];

function resolveApiBase(): string {
  const envVal =
    (process.env.NEXT_PUBLIC_API_URL as string | undefined) ||
    (process.env.NEXT_PUBLIC_API_BASE_URL as string | undefined);
  if (envVal && envVal.trim().length > 0) return envVal;
  if (typeof window !== 'undefined') {
    const host = window.location.hostname;
    if (host && host !== 'localhost' && host !== '127.0.0.1') {
      return 'https://nunuirl-platform.onrender.com';
    }
  }
  return 'http://localhost:8000';
}

export default function Layout({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const [regime, setRegime] = useState<string | null>(null);
  const [botLive, setBotLive] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);
  const apiBase = resolveApiBase();

  useEffect(() => {
    const fetchStatus = async () => {
      try {
        const res = await fetch(`${apiBase}/v1/summary`, { cache: 'no-store' }).catch(() => null);
        if (res?.ok) {
          const data = await res.json();
          setRegime(data?.regime || null);
          // Consider live if updated within 3 minutes
          const updatedAt = data?.updatedAt;
          if (updatedAt) {
            const age = (Date.now() - new Date(updatedAt).getTime()) / 1000;
            setBotLive(age < 180);
          }
        }
      } catch {
        // silent
      }
    };
    fetchStatus();
    const iv = setInterval(fetchStatus, 30000);
    return () => clearInterval(iv);
  }, [apiBase]);

  const regimeColors: Record<string, { bg: string; text: string }> = {
    trend: { bg: '#166534', text: '#86efac' },
    range: { bg: '#1e3a5f', text: '#93c5fd' },
    panic: { bg: '#7f1d1d', text: '#fca5a5' },
    high_volatility: { bg: '#78350f', text: '#fbbf24' },
    low_liquidity: { bg: '#374151', text: '#9ca3af' },
  };
  const rc = regime ? regimeColors[regime.toLowerCase()] || { bg: '#1e293b', text: '#94a3b8' } : null;

  return (
    <div style={{ minHeight: '100vh', background: C.bg, fontFamily: "'Inter', system-ui, -apple-system, sans-serif" }}>
      {/* ── Top nav ─────────────────────────────────── */}
      <nav
        style={{
          position: 'sticky',
          top: 0,
          zIndex: 100,
          background: C.surface,
          borderBottom: `1px solid ${C.border}`,
          boxShadow: S.md,
        }}
      >
        <div
          style={{
            maxWidth: 1280,
            margin: '0 auto',
            padding: '0 20px',
            height: 56,
            display: 'flex',
            alignItems: 'center',
            gap: 0,
          }}
        >
          {/* Logo */}
          <Link
            href="/"
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 8,
              marginRight: 32,
              textDecoration: 'none',
            }}
          >
            <span
              style={{
                width: 28,
                height: 28,
                borderRadius: R.sm,
                background: C.brand,
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                fontSize: 14,
                fontWeight: 800,
                color: '#fff',
                boxShadow: S.glow,
                flexShrink: 0,
              }}
            >
              W
            </span>
            <span style={{ fontSize: 17, fontWeight: 800, color: C.text, letterSpacing: -0.3 }}>
              WAGMI
            </span>
          </Link>

          {/* Desktop nav links */}
          <div
            style={{
              display: 'flex',
              gap: 2,
              flex: 1,
            }}
            className="desktop-nav"
          >
            {NAV_ITEMS.map((item) => {
              const isActive =
                item.href === '/'
                  ? router.pathname === '/'
                  : router.pathname.startsWith(item.href);
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  style={{
                    fontSize: 13,
                    fontWeight: isActive ? 600 : 400,
                    color: isActive ? C.text : C.muted,
                    textDecoration: 'none',
                    padding: '6px 12px',
                    borderRadius: R.sm,
                    background: isActive ? C.surfaceHover : 'transparent',
                    transition: 'all 0.15s ease',
                    whiteSpace: 'nowrap',
                  }}
                >
                  {item.label}
                </Link>
              );
            })}
          </div>

          {/* Right side: regime + live indicator */}
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginLeft: 'auto' }}>
            {rc && regime && (
              <span
                style={{
                  fontSize: 11,
                  fontWeight: 600,
                  padding: '3px 10px',
                  borderRadius: R.pill,
                  background: rc.bg,
                  color: rc.text,
                  letterSpacing: 0.5,
                  textTransform: 'uppercase',
                }}
              >
                {regime}
              </span>
            )}

            {/* Live pulse */}
            <div style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
              <span
                style={{
                  width: 7,
                  height: 7,
                  borderRadius: '50%',
                  background: botLive ? C.bull : C.muted,
                  boxShadow: botLive ? `0 0 6px ${C.bull}` : 'none',
                  display: 'inline-block',
                  flexShrink: 0,
                }}
              />
              <span style={{ fontSize: 11, color: botLive ? C.bull : C.muted, fontWeight: 600 }}>
                {botLive ? 'LIVE' : 'OFFLINE'}
              </span>
            </div>

            {/* Hamburger (mobile) */}
            <button
              onClick={() => setMenuOpen((v) => !v)}
              style={{
                display: 'none',
                background: 'none',
                border: 'none',
                color: C.text,
                fontSize: 20,
                padding: '4px 6px',
                cursor: 'pointer',
              }}
              className="hamburger"
              aria-label="Open menu"
            >
              {menuOpen ? '✕' : '☰'}
            </button>
          </div>
        </div>

        {/* Mobile dropdown */}
        {menuOpen && (
          <div
            style={{
              background: C.surface,
              borderTop: `1px solid ${C.border}`,
              padding: '8px 20px 16px',
            }}
          >
            {NAV_ITEMS.map((item) => {
              const isActive =
                item.href === '/'
                  ? router.pathname === '/'
                  : router.pathname.startsWith(item.href);
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  onClick={() => setMenuOpen(false)}
                  style={{
                    display: 'block',
                    fontSize: 15,
                    fontWeight: isActive ? 600 : 400,
                    color: isActive ? C.text : C.muted,
                    padding: '10px 0',
                    borderBottom: `1px solid ${C.border}`,
                    textDecoration: 'none',
                  }}
                >
                  {item.label}
                </Link>
              );
            })}
          </div>
        )}
      </nav>

      {/* ── Page content ────────────────────────────── */}
      <main style={{ maxWidth: 1280, margin: '0 auto', padding: '28px 20px 60px' }}>
        {children}
      </main>

      {/* ── Footer ──────────────────────────────────── */}
      <footer
        style={{
          borderTop: `1px solid ${C.border}`,
          background: C.surface,
          padding: '16px 20px',
          textAlign: 'center',
          fontSize: 11,
          color: C.muted,
          lineHeight: 1.7,
        }}
      >
        <strong style={{ color: C.textSub }}>WAGMI</strong> — AI-powered crypto trading intelligence.{' '}
        <strong>Not financial advice.</strong> All signals are for informational purposes only.
        Past performance does not guarantee future results. Always use a stop loss.
      </footer>

      {/* Responsive styles via style tag */}
      <style>{`
        @media (max-width: 768px) {
          .desktop-nav { display: none !important; }
          .hamburger { display: block !important; }
        }
      `}</style>
    </div>
  );
}
