import React, { useEffect, useState, useRef } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/router';
import { C, R, S, G } from '../src/theme';
import { resolveApiBase } from '../src/api';

// ── Nav structure: grouped with dropdowns ──────────────────────────────────────

type NavItem = { href: string; label: string; desc?: string };
type NavGroup = { label: string; href?: string; items?: NavItem[] };

const NAV_GROUPS: NavGroup[] = [
  {
    label: 'Live Trading',
    items: [
      { href: '/',           label: 'Dashboard',     desc: 'Bot overview & status' },
{ href: '/signals',    label: 'Live Signals',   desc: 'Real-time signal feed' },
      { href: '/copy-trade', label: 'Trade This',     desc: 'Copy the bot\'s trades' },
    ],
  },
  {
    label: 'Portfolio',
    items: [
      { href: '/portfolio',    label: 'Portfolio',     desc: 'Open positions & equity' },
      { href: '/results',      label: 'Track Record',  desc: 'Closed trade history' },
      { href: '/performance',  label: 'Performance',   desc: 'PnL & metrics over time' },
    ],
  },
  {
    label: 'Analysis',
    items: [
      { href: '/backtest',  label: 'Backtest',   desc: 'Strategy simulation' },
      { href: '/forensics', label: 'Forensics',  desc: 'Deep-dive trade autopsy' },
    ],
  },
  {
    label: 'AI Brain',
    items: [
      { href: '/llm-audit',    label: 'AI Audit',          desc: 'LLM usage logs & cost' },
      { href: '/ai-decisions', label: 'Decision Theater',  desc: 'Watch the AI reason' },
      { href: '/strategies',   label: 'How It Trades',     desc: 'Strategy logic explainer' },
    ],
  },
  {
    label: 'Understand',
    href: '/learn',
  },
  {
    label: 'More',
    items: [
      { href: '/pricing', label: 'Pricing', desc: 'Plans & access tiers' },
      { href: '/about',   label: 'About',   desc: 'What is WAGMI?' },
    ],
  },
];

// Flat list for mobile menu
const ALL_NAV_ITEMS: NavItem[] = NAV_GROUPS.flatMap((g) =>
  g.href ? [{ href: g.href, label: g.label }] : (g.items ?? [])
);

export default function Layout({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const [regime, setRegime] = useState<string | null>(null);
  const [botLive, setBotLive] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);
  const [activeDropdown, setActiveDropdown] = useState<string | null>(null);
  const dropdownTimeout = useRef<ReturnType<typeof setTimeout> | null>(null);

  const apiBase = resolveApiBase();

  useEffect(() => {
    const fetchStatus = async () => {
      try {
        const res = await fetch(`${apiBase}/v1/summary`, { cache: 'no-store' }).catch(() => null);
        if (res?.ok) {
          const data = await res.json();
          setRegime(data?.regime || null);
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

  // Close dropdown when route changes
  useEffect(() => {
    setActiveDropdown(null);
    setMenuOpen(false);
  }, [router.pathname]);

  const regimeColors: Record<string, { bg: string; border: string; text: string; dot: string }> = {
    trend:          { bg: 'rgba(22,101,52,.25)',   border: 'rgba(74,222,128,.2)',  text: '#4ade80', dot: '#16a34a' },
    range:          { bg: 'rgba(30,58,95,.25)',    border: 'rgba(147,197,253,.2)', text: '#93c5fd', dot: '#2563eb' },
    panic:          { bg: 'rgba(127,29,29,.25)',   border: 'rgba(252,165,165,.2)', text: '#fca5a5', dot: '#dc2626' },
    high_volatility:{ bg: 'rgba(120,53,15,.25)',  border: 'rgba(251,191,36,.2)',  text: '#fbbf24', dot: '#d97706' },
    low_liquidity:  { bg: 'rgba(55,65,81,.2)',    border: 'rgba(156,163,175,.15)',text: '#9ca3af', dot: '#6b7280' },
  };
  const rc = regime
    ? regimeColors[regime.toLowerCase()] || { bg: 'rgba(30,41,59,.3)', border: 'rgba(100,116,139,.2)', text: '#94a3b8', dot: '#64748b' }
    : null;

  // Check if any item in a group is active
  const isGroupActive = (group: NavGroup) => {
    if (group.href) {
      return group.href === '/' ? router.pathname === '/' : router.pathname.startsWith(group.href);
    }
    return group.items?.some((item) =>
      item.href === '/' ? router.pathname === '/' : router.pathname.startsWith(item.href)
    ) ?? false;
  };

  const isItemActive = (href: string) =>
    href === '/' ? router.pathname === '/' : router.pathname.startsWith(href);

  const openDropdown = (label: string) => {
    if (dropdownTimeout.current) clearTimeout(dropdownTimeout.current);
    setActiveDropdown(label);
  };

  const closeDropdown = () => {
    dropdownTimeout.current = setTimeout(() => setActiveDropdown(null), 120);
  };

  const keepDropdown = () => {
    if (dropdownTimeout.current) clearTimeout(dropdownTimeout.current);
  };

  return (
    <div style={{ minHeight: '100vh', background: C.bg, fontFamily: "'Inter', system-ui, -apple-system, sans-serif" }}>
      {/* Skip-to-content */}
      <a href="#main-content" className="skip-to-content">Skip to content</a>

      {/* ── Top nav ─────────────────────────────────── */}
      <nav
        aria-label="Main navigation"
        style={{
          position: 'sticky',
          top: 0,
          zIndex: 200,
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
            height: 52,
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
              marginRight: 24,
              textDecoration: 'none',
              flexShrink: 0,
            }}
          >
            <span
              style={{
                width: 28,
                height: 28,
                borderRadius: R.md,
                background: G.brand,
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                fontSize: 13,
                fontWeight: 900,
                color: '#fff',
                boxShadow: `${S.glow}, 0 2px 8px rgba(99,102,241,.4)`,
                flexShrink: 0,
                letterSpacing: -0.5,
              }}
            >
              W
            </span>
            <span style={{ fontSize: 15, fontWeight: 800, color: C.text, letterSpacing: -0.5, lineHeight: 1 }}>
              WAGMI
            </span>
          </Link>

          {/* Desktop grouped nav */}
          <div
            style={{ display: 'flex', gap: 2, flex: 1, alignItems: 'center', height: '100%' }}
            className="desktop-nav"
          >
            {NAV_GROUPS.map((group) => {
              const active = isGroupActive(group);
              const isOpen = activeDropdown === group.label;

              // Single-link group (no dropdown)
              if (group.href) {
                return (
                  <Link
                    key={group.label}
                    href={group.href}
                    style={{
                      fontSize: 13,
                      fontWeight: active ? 600 : 400,
                      color: active ? C.text : C.muted,
                      textDecoration: 'none',
                      padding: '5px 11px',
                      borderRadius: R.sm,
                      background: active ? G.brandSubtle : 'transparent',
                      border: active ? `1px solid rgba(99,102,241,.25)` : '1px solid transparent',
                      transition: 'background 0.15s ease, color 0.15s ease',
                      whiteSpace: 'nowrap',
                    }}
                    className="nav-link"
                  >
                    {group.label}
                  </Link>
                );
              }

              // Group with dropdown
              return (
                <div
                  key={group.label}
                  style={{ position: 'relative', height: '100%', display: 'flex', alignItems: 'center' }}
                  onMouseEnter={() => openDropdown(group.label)}
                  onMouseLeave={closeDropdown}
                >
                  <button
                    style={{
                      fontSize: 13,
                      fontWeight: active ? 600 : 400,
                      color: active ? C.text : C.muted,
                      background: active ? G.brandSubtle : isOpen ? C.surfaceHover : 'transparent',
                      border: active ? `1px solid rgba(99,102,241,.25)` : '1px solid transparent',
                      borderRadius: R.sm,
                      padding: '5px 11px',
                      cursor: 'pointer',
                      display: 'flex',
                      alignItems: 'center',
                      gap: 4,
                      whiteSpace: 'nowrap',
                      transition: 'background 0.15s ease, color 0.15s ease',
                    }}
                    className="nav-link"
                    aria-haspopup="true"
                    aria-expanded={isOpen}
                  >
                    {group.label}
                    <span
                      style={{
                        fontSize: 9,
                        opacity: 0.6,
                        transition: 'transform 0.15s',
                        transform: isOpen ? 'rotate(180deg)' : 'rotate(0deg)',
                        display: 'inline-block',
                      }}
                    >
                      ▼
                    </span>
                  </button>

                  {/* Dropdown panel */}
                  {isOpen && (
                    <div
                      onMouseEnter={keepDropdown}
                      onMouseLeave={closeDropdown}
                      style={{
                        position: 'absolute',
                        top: '100%',
                        left: 0,
                        minWidth: 200,
                        background: C.surface,
                        border: `1px solid ${C.borderBright}`,
                        borderRadius: R.lg,
                        boxShadow: '0 8px 32px rgba(0,0,0,.4)',
                        padding: '6px',
                        zIndex: 300,
                        animation: 'dropIn 0.1s ease',
                      }}
                    >
                      {group.items?.map((item) => {
                        const itemActive = isItemActive(item.href);
                        return (
                          <Link
                            key={item.href}
                            href={item.href}
                            style={{
                              display: 'block',
                              padding: '9px 12px',
                              borderRadius: R.md,
                              textDecoration: 'none',
                              background: itemActive ? G.brandSubtle : 'transparent',
                              border: `1px solid ${itemActive ? 'rgba(99,102,241,.2)' : 'transparent'}`,
                              transition: 'background 0.1s',
                              marginBottom: 2,
                            }}
                            className="dropdown-item"
                          >
                            <div
                              style={{
                                fontSize: 13,
                                fontWeight: itemActive ? 700 : 500,
                                color: itemActive ? C.text : C.textSub,
                                marginBottom: item.desc ? 2 : 0,
                              }}
                            >
                              {item.label}
                            </div>
                            {item.desc && (
                              <div style={{ fontSize: 11, color: C.muted, lineHeight: 1.4 }}>
                                {item.desc}
                              </div>
                            )}
                          </Link>
                        );
                      })}
                    </div>
                  )}
                </div>
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
            <div
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 5,
                padding: '3px 10px',
                borderRadius: R.pill,
                background: botLive ? 'rgba(22,163,74,.1)' : 'rgba(100,116,139,.1)',
                border: `1px solid ${botLive ? 'rgba(22,163,74,.2)' : 'rgba(100,116,139,.15)'}`,
              }}
            >
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
            {/* Group headers + items */}
            {NAV_GROUPS.map((group) => (
              <div key={group.label} style={{ marginBottom: 12 }}>
                {group.items ? (
                  <>
                    <div style={{ fontSize: 10, fontWeight: 700, color: C.muted, textTransform: 'uppercase', letterSpacing: 1, padding: '8px 0 4px' }}>
                      {group.label}
                    </div>
                    {group.items.map((item) => {
                      const itemActive = isItemActive(item.href);
                      return (
                        <Link
                          key={item.href}
                          href={item.href}
                          onClick={() => setMenuOpen(false)}
                          aria-current={itemActive ? 'page' : undefined}
                          style={{
                            display: 'block',
                            fontSize: 14,
                            fontWeight: itemActive ? 600 : 400,
                            color: itemActive ? C.text : C.muted,
                            padding: '8px 10px',
                            borderRadius: R.sm,
                            background: itemActive ? G.brandSubtle : 'transparent',
                            textDecoration: 'none',
                            marginBottom: 2,
                          }}
                        >
                          {item.label}
                        </Link>
                      );
                    })}
                  </>
                ) : (
                  <Link
                    href={group.href!}
                    onClick={() => setMenuOpen(false)}
                    style={{
                      display: 'block',
                      fontSize: 14,
                      fontWeight: isGroupActive(group) ? 600 : 400,
                      color: isGroupActive(group) ? C.text : C.muted,
                      padding: '10px 0',
                      borderBottom: `1px solid ${C.border}`,
                      textDecoration: 'none',
                    }}
                  >
                    {group.label}
                  </Link>
                )}
              </div>
            ))}
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
            Crypto carries significant risk. Historical results don&apos;t predict future performance.
          </p>
          <p style={{ margin: 0, fontSize: 10, color: C.faint }}>© 2026 WAGMI</p>
        </div>
      </footer>

      {/* Responsive + interactive styles */}
      <style>{`
        @keyframes dropIn {
          from { opacity: 0; transform: translateY(-6px); }
          to   { opacity: 1; transform: translateY(0); }
        }
        @media (max-width: 900px) {
          .desktop-nav { display: none !important; }
          .hamburger { display: flex !important; }
        }
        .nav-link:hover {
          background: ${C.surfaceHover} !important;
          color: ${C.textSub} !important;
          border-color: ${C.border} !important;
        }
        .dropdown-item:hover {
          background: ${C.surfaceHover} !important;
        }
        .hamburger:hover { background: ${C.surfaceHover} !important; border-radius: 6px; }
        #mobile-nav a:hover { color: ${C.text} !important; }
      `}</style>
    </div>
  );
}
