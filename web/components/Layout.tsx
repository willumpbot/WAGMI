import React, { useEffect, useState, useMemo } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/router';
import { C, R, S, G } from '../src/theme';

const NAV_ITEMS = [
  { href: '/', label: 'Dashboard' },
  { href: '/today', label: 'Morning Brief' },
  { href: '/signals', label: 'Live Signals' },
  { href: '/copy-trade', label: 'Trade This' },
  { href: '/portfolio', label: 'Portfolio' },
  { href: '/results', label: 'Track Record' },
  { href: '/performance', label: 'Performance' },
  { href: '/backtest', label: 'Backtest' },
  { href: '/forensics', label: 'Forensics' },
  { href: '/llm-audit', label: 'AI Audit' },
  { href: '/ai-decisions', label: 'Decision Theater' },
  { href: '/strategies', label: 'How It Trades' },
  { href: '/learn', label: 'Understand' },
  { href: '/pricing', label: 'Pricing' },
  { href: '/about', label: 'About' },
];

// Resolve once at module level for the env-based portion; window check happens in useMemo.
const ENV_API_BASE =
  (process.env.NEXT_PUBLIC_API_URL as string | undefined)?.trim() ||
  (process.env.NEXT_PUBLIC_API_BASE_URL as string | undefined)?.trim() ||
  '';

export default function Layout({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const [regime, setRegime] = useState<string | null>(null);
  const [botLive, setBotLive] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);

  // Resolved once on first render (window is available client-side only).
  const apiBase = useMemo(() => {
    if (ENV_API_BASE) return ENV_API_BASE;
    if (typeof window !== 'undefined') {
      const host = window.location.hostname;
      if (host && host !== 'localhost' && host !== '127.0.0.1') {
        return 'https://nunuirl-platform.onrender.com';
      }
    }
    return 'http://localhost:8000';
  }, []);

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

  const regimeColors: Record<string, { bg: string; border: string; text: string; dot: string }> = {
    trend:          { bg: 'rgba(22,101,52,.25)',   border: 'rgba(74,222,128,.2)',  text: '#4ade80', dot: '#16a34a' },
    range:          { bg: 'rgba(30,58,95,.25)',    border: 'rgba(147,197,253,.2)', text: '#93c5fd', dot: '#2563eb' },
    panic:          { bg: 'rgba(127,29,29,.25)',   border: 'rgba(252,165,165,.2)', text: '#fca5a5', dot: '#dc2626' },
    high_volatility:{ bg: 'rgba(120,53,15,.25)',  border: 'rgba(251,191,36,.2)',  text: '#fbbf24', dot: '#d97706' },
    low_liquidity:  { bg: 'rgba(55,65,81,.2)',    border: 'rgba(156,163,175,.15)',text: '#9ca3af', dot: '#6b7280' },
  };
  const rc = regime ? regimeColors[regime.toLowerCase()] || { bg: 'rgba(30,41,59,.3)', border: 'rgba(100,116,139,.2)', text: '#94a3b8', dot: '#64748b' } : null;

  return (
    <div style={{ minHeight: '100vh', background: C.bg, fontFamily: "'Inter', system-ui, -apple-system, sans-serif" }}>
      {/* Skip-to-content for keyboard users */}
      <a href="#main-content" className="skip-to-content">Skip to content</a>

      {/* ── Top nav ─────────────────────────────────── */}
      <nav
        aria-label="Main navigation"
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
              gap: 9,
              marginRight: 28,
              textDecoration: 'none',
              flexShrink: 0,
            }}
          >
            <span
              style={{
                width: 30,
                height: 30,
                borderRadius: R.md,
                background: G.brand,
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                fontSize: 14,
                fontWeight: 900,
                color: '#fff',
                boxShadow: `${S.glow}, 0 2px 8px rgba(99,102,241,.4)`,
                flexShrink: 0,
                letterSpacing: -0.5,
              }}
            >
              W
            </span>
            <span style={{ fontSize: 16, fontWeight: 800, color: C.text, letterSpacing: -0.5, lineHeight: 1 }}>
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
                  aria-current={isActive ? 'page' : undefined}
                  style={{
                    fontSize: 12.5,
                    fontWeight: isActive ? 600 : 400,
                    color: isActive ? C.text : C.muted,
                    textDecoration: 'none',
                    padding: '5px 10px',
                    borderRadius: R.sm,
                    background: isActive ? G.brandSubtle : 'transparent',
                    transition: 'background 0.15s ease, color 0.15s ease',
                    whiteSpace: 'nowrap',
                    border: isActive ? `1px solid rgba(99,102,241,.25)` : '1px solid transparent',
                    position: 'relative',
                  }}
                >
                  {item.label}
                </Link>
              );
            })}
          </div>

          {/* Right side: regime + live indicator */}
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginLeft: 'auto', flexShrink: 0 }}>
            {rc && regime && (
              <span
                style={{
                  fontSize: 10.5,
                  fontWeight: 700,
                  padding: '3px 10px',
                  borderRadius: R.pill,
                  background: rc.bg,
                  color: rc.text,
                  border: `1px solid ${rc.border}`,
                  letterSpacing: 0.8,
                  textTransform: 'uppercase',
                  display: 'flex',
                  alignItems: 'center',
                  gap: 5,
                }}
              >
                <span style={{ width: 5, height: 5, borderRadius: '50%', background: rc.dot, flexShrink: 0 }} />
                {regime.replace('_', ' ')}
              </span>
            )}

            {/* Live pulse */}
            <div style={{ display: 'flex', alignItems: 'center', gap: 5, padding: '3px 10px', borderRadius: R.pill, background: botLive ? 'rgba(22,163,74,.1)' : 'rgba(100,116,139,.1)', border: `1px solid ${botLive ? 'rgba(22,163,74,.2)' : 'rgba(100,116,139,.15)'}` }}>
              <span
                className={botLive ? 'live-dot' : ''}
                style={{
                  width: 6,
                  height: 6,
                  borderRadius: '50%',
                  background: botLive ? '#4ade80' : C.muted,
                  display: 'inline-block',
                  flexShrink: 0,
                }}
              />
              <span style={{ fontSize: 10.5, color: botLive ? '#4ade80' : C.muted, fontWeight: 700, letterSpacing: 0.6 }}>
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
              aria-label={menuOpen ? 'Close menu' : 'Open menu'}
              aria-expanded={menuOpen}
              aria-controls="mobile-nav"
            >
              {menuOpen ? '✕' : '☰'}
            </button>
          </div>
        </div>

        {/* Mobile dropdown */}
        {menuOpen && (
          <div
            id="mobile-nav"
            className="slide-down"
            style={{
              background: C.surface,
              borderTop: `1px solid ${C.border}`,
              padding: '8px 20px 20px',
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
                  aria-current={isActive ? 'page' : undefined}
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
      <main id="main-content" role="main" style={{ maxWidth: 1280, margin: '0 auto', padding: '28px 20px 60px' }}>
        {children}
      </main>

      {/* ── Footer ──────────────────────────────────── */}
      <footer
        style={{
          borderTop: `1px solid ${C.border}`,
          background: C.surface,
          padding: '20px 20px',
        }}
      >
        <div style={{ maxWidth: 1280, margin: '0 auto', display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 8 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <span style={{ width: 18, height: 18, borderRadius: R.xs, background: G.brand, display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 9, fontWeight: 900, color: '#fff', flexShrink: 0 }}>W</span>
            <span style={{ fontSize: 12, fontWeight: 700, color: C.textSub, letterSpacing: -0.3 }}>WAGMI</span>
          </div>
          <p style={{ margin: 0, fontSize: 11, color: C.muted, textAlign: 'center', lineHeight: 1.7, maxWidth: 560 }}>
            AI-driven market analysis for informational purposes only. Not financial advice — you are responsible for your own trading decisions.
            Crypto carries significant risk. Historical results don't predict future performance.
          </p>
          <p style={{ margin: 0, fontSize: 10, color: C.faint }}>© 2026 WAGMI</p>
        </div>
      </footer>

      {/* Responsive + interactive styles */}
      <style>{`
        @media (max-width: 900px) {
          .desktop-nav { display: none !important; }
          .hamburger { display: flex !important; }
        }
        .desktop-nav a:hover {
          background: ${C.surfaceHover} !important;
          color: ${C.textSub} !important;
          border-color: ${C.border} !important;
        }
        .hamburger:hover { background: ${C.surfaceHover} !important; border-radius: 6px; }
        #mobile-nav a:hover { color: ${C.text} !important; }
      `}</style>
    </div>
  );
}
