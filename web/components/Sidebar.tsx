'use client';

import React, { useEffect, useState, useRef, useCallback } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/router';
import { motion, AnimatePresence } from 'framer-motion';
import { C, R, S, G, Glass, Z, SP } from '../src/theme';
import { resolveApiBase } from '../src/api';

// ── SVG Icons ────────────────────────────────────────────────────────────────

const IconLightning = () => (
  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M13 2L3 14h9l-1 8 10-12h-9l1-8z" />
  </svg>
);

const IconPortfolio = () => (
  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <rect x="3" y="3" width="18" height="18" rx="2" />
    <path d="M3 15h18" />
    <path d="M8 3v18" />
    <path d="M16 3v18" />
    <path d="M3 9h18" />
  </svg>
);

const IconAnalysis = () => (
  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <circle cx="11" cy="11" r="8" />
    <path d="M21 21l-4.35-4.35" />
    <path d="M11 8v6" />
    <path d="M8 11h6" />
  </svg>
);

const IconBrain = () => (
  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M12 2a7 7 0 0 1 7 7c0 2.5-1.3 4.8-3.5 6L12 18l-3.5-3C6.3 13.8 5 11.5 5 9a7 7 0 0 1 7-7z" />
    <circle cx="12" cy="9" r="2" />
    <path d="M12 18v4" />
    <path d="M8 22h8" />
  </svg>
);

const IconMore = () => (
  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <circle cx="5" cy="12" r="1.5" />
    <circle cx="12" cy="12" r="1.5" />
    <circle cx="19" cy="12" r="1.5" />
  </svg>
);

const IconChevronLeft = () => (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M15 18l-6-6 6-6" />
  </svg>
);

const IconChevronRight = () => (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M9 18l6-6-6-6" />
  </svg>
);

const IconChevronDown = () => (
  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M6 9l6 6 6-6" />
  </svg>
);

// ── Types ────────────────────────────────────────────────────────────────────

type NavItem = { href: string; label: string; desc: string };
type NavGroup = {
  label: string;
  icon: React.FC;
  items: NavItem[];
};

// ── Nav Structure ────────────────────────────────────────────────────────────

const NAV_GROUPS: NavGroup[] = [
  {
    label: 'Live Trading',
    icon: IconLightning,
    items: [
      { href: '/', label: 'Dashboard', desc: 'Bot overview & status' },
      { href: '/signals', label: 'Live Signals', desc: 'Real-time signal feed' },
      { href: '/copy-trade', label: 'Trade This', desc: "Copy the bot's trades" },
    ],
  },
  {
    label: 'Portfolio',
    icon: IconPortfolio,
    items: [
      { href: '/portfolio', label: 'Portfolio', desc: 'Open positions & equity' },
      { href: '/results', label: 'Track Record', desc: 'Closed trade history' },
      { href: '/performance', label: 'Performance', desc: 'PnL & metrics over time' },
    ],
  },
  {
    label: 'Analysis',
    icon: IconAnalysis,
    items: [
      { href: '/backtest', label: 'Backtest', desc: 'Strategy simulation' },
      { href: '/forensics', label: 'Forensics', desc: 'Deep-dive trade autopsy' },
    ],
  },
  {
    label: 'AI Brain',
    icon: IconBrain,
    items: [
      { href: '/llm-audit', label: 'AI Audit', desc: 'LLM usage logs & cost' },
      { href: '/ai-decisions', label: 'Decision Theater', desc: 'Watch the AI reason' },
      { href: '/agent-intelligence', label: 'Agent Intel', desc: 'Agent performance' },
      { href: '/strategies', label: 'How It Trades', desc: 'Strategy logic explainer' },
    ],
  },
  {
    label: 'More',
    icon: IconMore,
    items: [
      { href: '/masterclass', label: "Nunu's Masterclass", desc: 'Complete trading course' },
      { href: '/learn', label: 'Understand', desc: 'Learn how it all works' },
      { href: '/about', label: 'About', desc: 'What is WAGMI?' },
    ],
  },
];

// ── Constants ────────────────────────────────────────────────────────────────

const COLLAPSED_WIDTH = 64;
const EXPANDED_WIDTH = 240;
const STORAGE_KEY = 'wagmi-sidebar-collapsed';
const MOBILE_BREAKPOINT = 1024;

// ── Regime Colors ────────────────────────────────────────────────────────────

const regimeColors: Record<string, { bg: string; border: string; text: string; dot: string }> = {
  trend:           { bg: 'rgba(22,101,52,.25)',  border: 'rgba(74,222,128,.2)',  text: '#4ade80', dot: '#16a34a' },
  range:           { bg: 'rgba(30,58,95,.25)',   border: 'rgba(147,197,253,.2)', text: '#93c5fd', dot: '#2563eb' },
  panic:           { bg: 'rgba(127,29,29,.25)',  border: 'rgba(252,165,165,.2)', text: '#fca5a5', dot: '#dc2626' },
  high_volatility: { bg: 'rgba(120,53,15,.25)',  border: 'rgba(251,191,36,.2)',  text: '#fbbf24', dot: '#d97706' },
  low_liquidity:   { bg: 'rgba(55,65,81,.2)',    border: 'rgba(156,163,175,.15)', text: '#9ca3af', dot: '#6b7280' },
};

// ── Component ────────────────────────────────────────────────────────────────

export default function Sidebar(): JSX.Element {
  const router = useRouter();
  const [collapsed, setCollapsed] = useState(true);
  const [isMobile, setIsMobile] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);
  const [expandedGroups, setExpandedGroups] = useState<Set<string>>(new Set());
  const [hoveredGroup, setHoveredGroup] = useState<string | null>(null);
  const hoverTimeout = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [regime, setRegime] = useState<string | null>(null);
  const [botLive, setBotLive] = useState(false);

  const apiBase = resolveApiBase();

  // Load persisted collapsed state
  useEffect(() => {
    try {
      const stored = localStorage.getItem(STORAGE_KEY);
      if (stored !== null) {
        setCollapsed(stored === 'true');
      }
    } catch { /* noop */ }
  }, []);

  // Persist collapsed state
  const toggleCollapsed = useCallback(() => {
    setCollapsed((prev) => {
      const next = !prev;
      try { localStorage.setItem(STORAGE_KEY, String(next)); } catch { /* noop */ }
      // Dispatch storage event so Layout can react
      window.dispatchEvent(new Event('sidebar-toggle'));
      return next;
    });
  }, []);

  // Responsive check
  useEffect(() => {
    const check = () => setIsMobile(window.innerWidth < MOBILE_BREAKPOINT);
    check();
    window.addEventListener('resize', check);
    return () => window.removeEventListener('resize', check);
  }, []);

  // Close mobile drawer on route change
  useEffect(() => {
    setMobileOpen(false);
  }, [router.pathname]);

  // Fetch regime + live status
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
      } catch { /* silent */ }
    };
    fetchStatus();
    const iv = setInterval(fetchStatus, 30000);
    return () => clearInterval(iv);
  }, [apiBase]);

  // Auto-expand the group that contains the active route
  useEffect(() => {
    const activeGroup = NAV_GROUPS.find((g) =>
      g.items.some((item) =>
        item.href === '/' ? router.pathname === '/' : router.pathname.startsWith(item.href)
      )
    );
    if (activeGroup) {
      setExpandedGroups((prev) => new Set(prev).add(activeGroup.label));
    }
  }, [router.pathname]);

  const isItemActive = (href: string) =>
    href === '/' ? router.pathname === '/' : router.pathname.startsWith(href);

  const isGroupActive = (group: NavGroup) =>
    group.items.some((item) => isItemActive(item.href));

  const toggleGroup = (label: string) => {
    setExpandedGroups((prev) => {
      const next = new Set(prev);
      if (next.has(label)) next.delete(label);
      else next.add(label);
      return next;
    });
  };

  const rc = regime
    ? regimeColors[regime.toLowerCase()] || { bg: 'rgba(30,41,59,.3)', border: 'rgba(100,116,139,.2)', text: '#94a3b8', dot: '#64748b' }
    : null;

  const sidebarWidth = collapsed ? COLLAPSED_WIDTH : EXPANDED_WIDTH;

  // Expose current width for Layout to read
  useEffect(() => {
    document.documentElement.style.setProperty('--sidebar-width', `${isMobile ? 0 : sidebarWidth}px`);
  }, [sidebarWidth, isMobile]);

  const openHover = (label: string) => {
    if (hoverTimeout.current) clearTimeout(hoverTimeout.current);
    setHoveredGroup(label);
  };

  const closeHover = () => {
    hoverTimeout.current = setTimeout(() => setHoveredGroup(null), 150);
  };

  const keepHover = () => {
    if (hoverTimeout.current) clearTimeout(hoverTimeout.current);
  };

  // ── Render helpers ─────────────────────────────────────────────────────────

  const renderNavItem = (item: NavItem, showDesc: boolean) => {
    const active = isItemActive(item.href);
    return (
      <Link
        key={item.href}
        href={item.href}
        onClick={() => { if (isMobile) setMobileOpen(false); }}
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 10,
          padding: '8px 12px',
          borderRadius: R.md,
          textDecoration: 'none',
          background: active ? G.brandSubtle : 'transparent',
          borderLeft: '3px solid transparent',
          marginBottom: 2,
          position: 'relative',
          transition: 'background 0.15s ease',
        }}
        className="sidebar-nav-item"
      >
        {active && (
          <div style={{
            position: 'absolute',
            left: 0,
            top: '15%',
            bottom: '15%',
            width: 2,
            borderRadius: 1,
            background: C.brand,
            boxShadow: '0 0 8px rgba(99,102,241,0.3)',
          }} />
        )}
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{
            fontSize: 13,
            fontWeight: active ? 700 : 500,
            color: active ? C.text : C.textSub,
            lineHeight: 1.3,
            whiteSpace: 'nowrap',
            overflow: 'hidden',
            textOverflow: 'ellipsis',
          }}>
            {item.label}
          </div>
          {showDesc && item.desc && (
            <div style={{ fontSize: 11, color: C.muted, lineHeight: 1.3, marginTop: 1 }}>
              {item.desc}
            </div>
          )}
        </div>
      </Link>
    );
  };

  const renderSidebarContent = (isExpanded: boolean) => (
    <>
      {/* Logo */}
      <div style={{ padding: isExpanded ? '16px 16px 12px' : '16px 0 12px', display: 'flex', alignItems: 'center', justifyContent: isExpanded ? 'flex-start' : 'center', gap: 10, flexShrink: 0 }}>
        <Link href="/" style={{ display: 'flex', alignItems: 'center', gap: 10, textDecoration: 'none' }}>
          <span style={{
            width: 32,
            height: 32,
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
          }}>
            W
          </span>
          {isExpanded && (
            <motion.span
              initial={{ opacity: 0, x: -8 }}
              animate={{ opacity: 1, x: 0 }}
              exit={{ opacity: 0, x: -8 }}
              transition={{ duration: 0.15, ease: [0.25, 0.1, 0.25, 1] as const }}
              style={{ fontSize: 16, fontWeight: 800, color: C.text, letterSpacing: -0.5 }}
            >
              WAGMI
            </motion.span>
          )}
        </Link>
      </div>

      {/* Nav groups */}
      <div style={{ flex: 1, overflowY: 'auto', overflowX: 'hidden', padding: isExpanded ? '0 8px' : '0 4px' }}>
        {NAV_GROUPS.map((group) => {
          const GroupIcon = group.icon;
          const groupActive = isGroupActive(group);
          const groupExpanded = expandedGroups.has(group.label);

          if (!isExpanded) {
            // Collapsed: icon rail with floating panel on hover
            return (
              <div
                key={group.label}
                style={{ position: 'relative', marginBottom: 4 }}
                onMouseEnter={() => openHover(group.label)}
                onMouseLeave={closeHover}
              >
                {NAV_GROUPS.indexOf(group) > 0 && (
                  <div style={{
                    height: 1,
                    margin: '4px 8px 8px',
                    background: 'linear-gradient(90deg, transparent, rgba(255,255,255,0.06) 30%, rgba(255,255,255,0.06) 70%, transparent)',
                  }} />
                )}
                <div
                  style={{
                    position: 'relative',
                    width: 48,
                    height: 44,
                    margin: '0 auto',
                    borderRadius: R.md,
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    color: groupActive ? C.brand : C.muted,
                    background: groupActive ? C.brandGlow : 'transparent',
                    cursor: 'pointer',
                    transition: 'all 0.15s ease',
                    borderLeft: '3px solid transparent',
                  }}
                  className="sidebar-icon-btn"
                >
                  {groupActive && (
                    <div style={{
                      position: 'absolute',
                      left: 0,
                      top: '20%',
                      bottom: '20%',
                      width: 2,
                      borderRadius: 1,
                      background: C.brand,
                      boxShadow: '0 0 8px rgba(99,102,241,0.3)',
                    }} />
                  )}
                  <GroupIcon />
                </div>

                {/* Floating panel */}
                <AnimatePresence>
                  {hoveredGroup === group.label && (
                    <motion.div
                      initial={{ opacity: 0, x: -8, scale: 0.95 }}
                      animate={{ opacity: 1, x: 0, scale: 1 }}
                      exit={{ opacity: 0, x: -8, scale: 0.95 }}
                      transition={{ duration: 0.15, ease: [0.25, 0.1, 0.25, 1] as const }}
                      onMouseEnter={keepHover}
                      onMouseLeave={closeHover}
                      style={{
                        position: 'absolute',
                        left: COLLAPSED_WIDTH - 8,
                        top: 0,
                        minWidth: 200,
                        ...Glass.elevated,
                        borderRadius: R.lg,
                        padding: 6,
                        zIndex: Z.tooltip,
                      }}
                    >
                      <div style={{ fontSize: 10, fontWeight: 700, color: C.muted, textTransform: 'uppercase', letterSpacing: 1, padding: '6px 12px 4px', }}>
                        {group.label}
                      </div>
                      {group.items.map((item) => renderNavItem(item, true))}
                    </motion.div>
                  )}
                </AnimatePresence>
              </div>
            );
          }

          // Expanded: collapsible groups
          return (
            <div key={group.label} style={{ marginBottom: 4, position: 'relative' }}>
              {/* Gradient section divider */}
              {NAV_GROUPS.indexOf(group) > 0 && (
                <div style={{
                  height: 1,
                  margin: '4px 12px 8px',
                  background: 'linear-gradient(90deg, transparent, rgba(255,255,255,0.06) 20%, rgba(255,255,255,0.06) 80%, transparent)',
                }} />
              )}
              <button
                onClick={() => toggleGroup(group.label)}
                style={{
                  width: '100%',
                  display: 'flex',
                  alignItems: 'center',
                  gap: 10,
                  padding: '8px 12px',
                  borderRadius: R.md,
                  border: 'none',
                  background: groupActive ? C.brandGlow : 'transparent',
                  color: groupActive ? C.text : C.muted,
                  cursor: 'pointer',
                  fontSize: 11,
                  fontWeight: 700,
                  textTransform: 'uppercase',
                  letterSpacing: 0.8,
                  transition: 'all 0.15s ease',
                }}
                className="sidebar-group-btn"
              >
                <span style={{ color: groupActive ? C.brand : C.muted, display: 'flex', flexShrink: 0 }}>
                  <GroupIcon />
                </span>
                <motion.span
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1 }}
                  transition={{ duration: 0.15, ease: [0.25, 0.1, 0.25, 1] as const }}
                  style={{ flex: 1, textAlign: 'left' }}
                >
                  {group.label}
                </motion.span>
                <motion.span
                  animate={{ rotate: groupExpanded ? 180 : 0 }}
                  transition={{ duration: 0.15, ease: [0.25, 0.1, 0.25, 1] as const }}
                  style={{ display: 'flex', opacity: 0.5 }}
                >
                  <IconChevronDown />
                </motion.span>
              </button>

              <AnimatePresence initial={false}>
                {groupExpanded && (
                  <motion.div
                    initial={{ height: 0, opacity: 0 }}
                    animate={{ height: 'auto', opacity: 1 }}
                    exit={{ height: 0, opacity: 0 }}
                    transition={{ duration: 0.2, ease: [0.25, 0.1, 0.25, 1] }}
                    style={{ overflow: 'hidden', paddingLeft: 8 }}
                  >
                    {group.items.map((item) => renderNavItem(item, true))}
                  </motion.div>
                )}
              </AnimatePresence>
            </div>
          );
        })}
      </div>

      {/* Bottom section: regime + live + toggle */}
      <div style={{ flexShrink: 0, padding: isExpanded ? '8px 12px 12px' : '8px 4px 12px', position: 'relative' }}>
        {/* Gradient divider */}
        <div style={{
          position: 'absolute',
          top: 0,
          left: 0,
          right: 0,
          height: 1,
          background: 'linear-gradient(90deg, transparent, rgba(255,255,255,0.06) 20%, rgba(255,255,255,0.06) 80%, transparent)',
        }} />
        {/* Regime badge */}
        {rc && regime && (
          <div style={{ display: 'flex', justifyContent: isExpanded ? 'flex-start' : 'center', marginBottom: 8, padding: isExpanded ? '0 4px' : 0 }}>
            <span style={{
              fontSize: isExpanded ? 10.5 : 0,
              fontWeight: 700,
              padding: isExpanded ? '3px 10px' : '4px',
              borderRadius: R.pill,
              background: rc.bg,
              color: rc.text,
              border: `1px solid ${rc.border}`,
              boxShadow: `0 0 12px ${rc.dot}25`,
              letterSpacing: 0.8,
              textTransform: 'uppercase',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              gap: 5,
              minWidth: isExpanded ? undefined : 32,
              minHeight: isExpanded ? undefined : 24,
            }}>
              <span style={{ width: 6, height: 6, borderRadius: '50%', background: rc.dot, flexShrink: 0 }} />
              {isExpanded && regime.replace('_', ' ')}
            </span>
          </div>
        )}

        {/* Live indicator */}
        <div style={{ display: 'flex', justifyContent: isExpanded ? 'flex-start' : 'center', marginBottom: 8, padding: isExpanded ? '0 4px' : 0 }}>
          <div style={{
            display: 'flex',
            alignItems: 'center',
            gap: 5,
            padding: isExpanded ? '3px 10px' : '4px',
            borderRadius: R.pill,
            background: botLive ? 'rgba(22,163,74,.1)' : 'rgba(100,116,139,.1)',
            border: `1px solid ${botLive ? 'rgba(22,163,74,.2)' : 'rgba(100,116,139,.15)'}`,
            minWidth: isExpanded ? undefined : 32,
            minHeight: isExpanded ? undefined : 24,
            justifyContent: 'center',
          }}>
            <span
              className={botLive ? 'live-dot' : ''}
              style={{
                width: 6,
                height: 6,
                borderRadius: '50%',
                background: botLive ? '#4ade80' : C.muted,
                flexShrink: 0,
              }}
            />
            {isExpanded && (
              <span style={{ fontSize: 10.5, color: botLive ? '#4ade80' : C.muted, fontWeight: 700, letterSpacing: 0.6 }}>
                {botLive ? 'LIVE' : 'OFFLINE'}
              </span>
            )}
          </div>
        </div>

        {/* Collapse toggle */}
        {!isMobile && (
          <button
            onClick={toggleCollapsed}
            style={{
              width: '100%',
              height: 36,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              gap: 6,
              borderRadius: R.md,
              border: `1px solid ${C.border}`,
              background: C.surfaceHover,
              color: C.muted,
              cursor: 'pointer',
              fontSize: 12,
              transition: 'all 0.15s ease',
            }}
            className="sidebar-toggle-btn"
            aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
          >
            {collapsed ? <IconChevronRight /> : (
              <>
                <IconChevronLeft />
                <span>Collapse</span>
              </>
            )}
          </button>
        )}
      </div>
    </>
  );

  // ── Mobile overlay ─────────────────────────────────────────────────────────

  if (isMobile) {
    return (
      <>
        {/* Mobile top bar */}
        <div style={{
          position: 'fixed',
          top: 0,
          left: 0,
          right: 0,
          height: 52,
          zIndex: Z.sidebar,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          padding: '0 16px',
          ...Glass.nav,
          borderBottom: `1px solid ${C.border}`,
        }}>
          <Link href="/" style={{ display: 'flex', alignItems: 'center', gap: 8, textDecoration: 'none' }}>
            <span style={{
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
            }}>
              W
            </span>
            <span style={{ fontSize: 15, fontWeight: 800, color: C.text, letterSpacing: -0.5 }}>WAGMI</span>
          </Link>

          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            {/* Live indicator in mobile bar */}
            <div style={{
              display: 'flex',
              alignItems: 'center',
              gap: 4,
              padding: '3px 8px',
              borderRadius: R.pill,
              background: botLive ? 'rgba(22,163,74,.1)' : 'rgba(100,116,139,.1)',
              border: `1px solid ${botLive ? 'rgba(22,163,74,.2)' : 'rgba(100,116,139,.15)'}`,
            }}>
              <span className={botLive ? 'live-dot' : ''} style={{ width: 5, height: 5, borderRadius: '50%', background: botLive ? '#4ade80' : C.muted }} />
              <span style={{ fontSize: 10, color: botLive ? '#4ade80' : C.muted, fontWeight: 700 }}>{botLive ? 'LIVE' : 'OFF'}</span>
            </div>

            <button
              onClick={() => setMobileOpen((v) => !v)}
              style={{
                background: 'none',
                border: 'none',
                color: C.text,
                fontSize: 22,
                padding: '4px 6px',
                cursor: 'pointer',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
              }}
              aria-label={mobileOpen ? 'Close menu' : 'Open menu'}
            >
              {mobileOpen ? '\u2715' : '\u2630'}
            </button>
          </div>
        </div>

        {/* Mobile drawer overlay */}
        <AnimatePresence>
          {mobileOpen && (
            <>
              {/* Backdrop */}
              <motion.div
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                exit={{ opacity: 0 }}
                transition={{ duration: 0.15, ease: [0.25, 0.1, 0.25, 1] as const }}
                onClick={() => setMobileOpen(false)}
                style={{
                  position: 'fixed',
                  inset: 0,
                  background: 'rgba(0,0,0,0.6)',
                  zIndex: Z.sidebar + 1,
                }}
              />
              {/* Drawer */}
              <motion.aside
                initial={{ x: '-100%' }}
                animate={{ x: 0 }}
                exit={{ x: '-100%' }}
                transition={{ duration: 0.25, ease: [0.25, 0.1, 0.25, 1] }}
                style={{
                  position: 'fixed',
                  top: 0,
                  left: 0,
                  bottom: 0,
                  width: '100%',
                  maxWidth: 320,
                  zIndex: Z.sidebar + 2,
                  ...Glass.nav,
                  display: 'flex',
                  flexDirection: 'column',
                  overflowY: 'auto',
                }}
              >
                {renderSidebarContent(true)}
              </motion.aside>
            </>
          )}
        </AnimatePresence>
      </>
    );
  }

  // ── Desktop sidebar ────────────────────────────────────────────────────────

  return (
    <>
      <motion.aside
        animate={{ width: sidebarWidth }}
        transition={{ duration: 0.2, ease: [0.25, 0.1, 0.25, 1] }}
        style={{
          position: 'fixed',
          top: 0,
          left: 0,
          height: '100vh',
          zIndex: Z.sidebar,
          ...Glass.nav,
          borderRight: `1px solid ${C.border}`,
          display: 'flex',
          flexDirection: 'column',
          overflow: 'visible',
        }}
      >
        {/* Noise texture overlay */}
        <div style={{
          position: 'absolute',
          inset: 0,
          opacity: 0.03,
          backgroundImage: `url("data:image/svg+xml,%3Csvg viewBox='0 0 256 256' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='4' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)'/%3E%3C/svg%3E")`,
          backgroundSize: '128px 128px',
          pointerEvents: 'none',
          borderRadius: 'inherit',
        }} />

        <div style={{ position: 'relative', zIndex: 1, display: 'flex', flexDirection: 'column', height: '100%' }}>
          {renderSidebarContent(!collapsed)}
        </div>
      </motion.aside>

      {/* Hover styles */}
      <style>{`
        .sidebar-nav-item:hover {
          background: rgba(255,255,255,0.05) !important;
          text-shadow: 0 0 8px rgba(99,102,241,0.2);
        }
        .sidebar-icon-btn:hover {
          background: rgba(255,255,255,0.04) !important;
          color: ${C.text} !important;
          text-shadow: 0 0 8px rgba(99,102,241,0.3);
        }
        .sidebar-group-btn:hover {
          background: rgba(255,255,255,0.04) !important;
          color: ${C.text} !important;
          text-shadow: 0 0 8px rgba(99,102,241,0.3);
        }
        .sidebar-toggle-btn:hover {
          background: ${C.border} !important;
          color: ${C.text} !important;
        }
      `}</style>
    </>
  );
}
