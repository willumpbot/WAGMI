'use client';

import React, { useEffect, useState, useRef, useCallback } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/router';
import { C, Z } from '../src/theme';
import { resolveApiBase } from '../src/api';

// ── SVG Icons ─────────────────────────────────────────────────────────────────

const IconGrid = () => (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <rect x="3" y="3" width="7" height="7" /><rect x="14" y="3" width="7" height="7" />
    <rect x="3" y="14" width="7" height="7" /><rect x="14" y="14" width="7" height="7" />
  </svg>
);

const IconBarChart = () => (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <line x1="18" y1="20" x2="18" y2="10" /><line x1="12" y1="20" x2="12" y2="4" />
    <line x1="6" y1="20" x2="6" y2="14" /><line x1="2" y1="20" x2="22" y2="20" />
  </svg>
);

const IconSearch = () => (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <circle cx="11" cy="11" r="8" /><line x1="21" y1="21" x2="16.65" y2="16.65" />
  </svg>
);

const IconCpu = () => (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <rect x="4" y="4" width="16" height="16" rx="2" />
    <rect x="9" y="9" width="6" height="6" />
    <line x1="9" y1="1" x2="9" y2="4" /><line x1="15" y1="1" x2="15" y2="4" />
    <line x1="9" y1="20" x2="9" y2="23" /><line x1="15" y1="20" x2="15" y2="23" />
    <line x1="20" y1="9" x2="23" y2="9" /><line x1="20" y1="14" x2="23" y2="14" />
    <line x1="1" y1="9" x2="4" y2="9" /><line x1="1" y1="14" x2="4" y2="14" />
  </svg>
);

const IconZap = () => (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2" />
  </svg>
);

const IconBook = () => (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20" />
    <path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z" />
  </svg>
);

const IconMenu = () => (
  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <line x1="3" y1="12" x2="21" y2="12" /><line x1="3" y1="6" x2="21" y2="6" /><line x1="3" y1="18" x2="21" y2="18" />
  </svg>
);

const IconX = () => (
  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <line x1="18" y1="6" x2="6" y2="18" /><line x1="6" y1="6" x2="18" y2="18" />
  </svg>
);

const IconChevronLeft = () => (
  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <polyline points="15 18 9 12 15 6" />
  </svg>
);

const IconChevronRight = () => (
  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <polyline points="9 18 15 12 9 6" />
  </svg>
);

// ── Types ─────────────────────────────────────────────────────────────────────

type NavItem = { href: string; label: string; icon?: React.FC };
type NavGroup = {
  label: string;
  icon: React.FC;
  items: NavItem[];
};

// ── Nav Structure ─────────────────────────────────────────────────────────────

const NAV_GROUPS: NavGroup[] = [
  {
    label: 'Trading',
    icon: IconZap,
    items: [
      { href: '/dashboard', label: 'Dashboard' },
      { href: '/signals', label: 'Live Signals' },
      { href: '/copy-trade', label: 'Copy Trade' },
    ],
  },
  {
    label: 'Performance',
    icon: IconBarChart,
    items: [
      { href: '/portfolio', label: 'Portfolio' },
      { href: '/results', label: 'Track Record' },
      { href: '/performance', label: 'Performance' },
    ],
  },
  {
    label: 'Analysis',
    icon: IconSearch,
    items: [
      { href: '/backtest', label: 'Backtest' },
      { href: '/forensics', label: 'Forensics' },
    ],
  },
  {
    label: 'AI Brain',
    icon: IconCpu,
    items: [
      { href: '/reasoning', label: 'Agent Reasoning' },
      { href: '/counterfactuals', label: 'Counterfactuals' },
      { href: '/llm-audit', label: 'AI Audit' },
      { href: '/ai-decisions', label: 'Decisions' },
      { href: '/agent-intelligence', label: 'Agents' },
      { href: '/strategies', label: 'Strategies' },
    ],
  },
  {
    label: 'Learn',
    icon: IconBook,
    items: [
      { href: '/learn', label: 'Course' },
      { href: '/masterclass', label: 'Masterclass' },
    ],
  },
];

const COLLAPSED_WIDTH = 56;
const EXPANDED_WIDTH = 220;
const STORAGE_KEY = 'wagmi-sidebar-collapsed';
const MOBILE_BREAKPOINT = 1024;

const REGIME_COLORS: Record<string, { bg: string; text: string; dot: string }> = {
  trend: { bg: 'rgba(0,204,136,0.12)', text: '#00cc88', dot: '#00cc88' },
  range: { bg: 'rgba(68,136,255,0.12)', text: '#4488ff', dot: '#4488ff' },
  panic: { bg: 'rgba(255,68,102,0.12)', text: '#ff4466', dot: '#ff4466' },
  high_volatility: { bg: 'rgba(255,170,0,0.12)', text: '#ffaa00', dot: '#ffaa00' },
  low_liquidity: { bg: 'rgba(107,107,123,0.12)', text: '#a0a0b8', dot: '#6b6b7b' },
};

// ── Component ─────────────────────────────────────────────────────────────────

export default function Sidebar(): JSX.Element {
  const router = useRouter();
  const [collapsed, setCollapsed] = useState(true);
  const [isMobile, setIsMobile] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);
  const [expandedGroups, setExpandedGroups] = useState<Set<string>>(new Set(['Trading']));
  const [regime, setRegime] = useState<string | null>(null);
  const [botLive, setBotLive] = useState(false);
  const apiBase = resolveApiBase();

  // Load persisted collapsed state
  useEffect(() => {
    try {
      const stored = localStorage.getItem(STORAGE_KEY);
      if (stored !== null) setCollapsed(stored === 'true');
    } catch { /* noop */ }
  }, []);

  const toggleCollapsed = useCallback(() => {
    setCollapsed((prev) => {
      const next = !prev;
      try { localStorage.setItem(STORAGE_KEY, String(next)); } catch { /* noop */ }
      window.dispatchEvent(new Event('sidebar-toggle'));
      return next;
    });
  }, []);

  // Responsive
  useEffect(() => {
    const check = () => setIsMobile(window.innerWidth < MOBILE_BREAKPOINT);
    check();
    window.addEventListener('resize', check);
    return () => window.removeEventListener('resize', check);
  }, []);

  useEffect(() => { setMobileOpen(false); }, [router.pathname]);

  // Fetch bot status
  useEffect(() => {
    const fetchStatus = async () => {
      try {
        const res = await fetch(`${apiBase}/v1/summary`, { cache: 'no-store' }).catch(() => null);
        if (res?.ok) {
          const data = await res.json();
          setRegime(data?.regime || null);
          if (data?.updatedAt) {
            const age = (Date.now() - new Date(data.updatedAt).getTime()) / 1000;
            setBotLive(age < 180);
          }
        }
      } catch { /* silent */ }
    };
    fetchStatus();
    const iv = setInterval(fetchStatus, 30_000);
    return () => clearInterval(iv);
  }, [apiBase]);

  const toggleGroup = (label: string) => {
    setExpandedGroups((prev) => {
      const next = new Set(prev);
      if (next.has(label)) next.delete(label);
      else next.add(label);
      return next;
    });
  };

  const isActive = (href: string) => {
    if (href === '/dashboard') return router.pathname === '/dashboard' || router.pathname === '/';
    return router.pathname === href || router.pathname.startsWith(href + '/');
  };

  const regimeStyle = regime && REGIME_COLORS[regime] ? REGIME_COLORS[regime] : null;

  // ── Mobile hamburger ──────────────────────────────────────────────────────

  if (isMobile) {
    return (
      <>
        {/* Top bar */}
        <div
          style={{
            position: 'fixed',
            top: 0,
            left: 0,
            right: 0,
            height: 52,
            background: C.surface,
            borderBottom: `1px solid ${C.border}`,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            padding: '0 16px',
            zIndex: Z.sidebar,
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <span style={{ width: 22, height: 22, borderRadius: 4, border: `1px solid ${C.brand}`, display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 10, fontWeight: 800, color: C.brand, fontFamily: 'JetBrains Mono, monospace' }}>W</span>
            <span style={{ fontSize: 13, fontWeight: 700, color: C.text }}>WAGMI</span>
          </div>
          <button
            onClick={() => setMobileOpen((v) => !v)}
            style={{ background: 'none', border: `1px solid ${C.border}`, borderRadius: 6, padding: '5px 7px', color: C.textSub, cursor: 'pointer', display: 'flex', alignItems: 'center' }}
          >
            {mobileOpen ? <IconX /> : <IconMenu />}
          </button>
        </div>

        {/* Mobile drawer overlay */}
        {mobileOpen && (
          <div
            style={{
              position: 'fixed',
              inset: 0,
              zIndex: Z.sidebar - 1,
              background: 'rgba(5,5,8,0.85)',
            }}
            onClick={() => setMobileOpen(false)}
          />
        )}

        {/* Mobile drawer */}
        <div
          style={{
            position: 'fixed',
            top: 52,
            left: 0,
            bottom: 0,
            width: 240,
            background: C.surface,
            borderRight: `1px solid ${C.border}`,
            zIndex: Z.sidebar,
            overflowY: 'auto',
            transform: mobileOpen ? 'translateX(0)' : 'translateX(-100%)',
            transition: 'transform 0.2s ease',
            padding: '16px 0',
          }}
        >
          <SidebarContent
            collapsed={false}
            groups={NAV_GROUPS}
            expandedGroups={expandedGroups}
            onToggleGroup={toggleGroup}
            isActive={isActive}
            botLive={botLive}
            regime={regime}
            regimeStyle={regimeStyle}
          />
        </div>
      </>
    );
  }

  // ── Desktop sidebar ───────────────────────────────────────────────────────

  const width = collapsed ? COLLAPSED_WIDTH : EXPANDED_WIDTH;

  return (
    <div
      style={{
        position: 'fixed',
        top: 0,
        left: 0,
        bottom: 0,
        width,
        background: C.surface,
        borderRight: `1px solid ${C.border}`,
        zIndex: Z.sidebar,
        transition: 'width 0.2s cubic-bezier(0.25, 0.1, 0.25, 1)',
        display: 'flex',
        flexDirection: 'column',
        overflow: 'hidden',
      }}
    >
      {/* Logo */}
      <div
        style={{
          height: 52,
          display: 'flex',
          alignItems: 'center',
          padding: collapsed ? '0 16px' : '0 16px',
          borderBottom: `1px solid ${C.border}`,
          flexShrink: 0,
          gap: 10,
          overflow: 'hidden',
        }}
      >
        <div style={{ flexShrink: 0, width: 22, height: 22, borderRadius: 4, border: `1px solid ${C.brand}`, display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 10, fontWeight: 800, color: C.brand, fontFamily: 'JetBrains Mono, monospace' }}>W</div>
        {!collapsed && (
          <span style={{ fontSize: 13, fontWeight: 700, color: C.text, whiteSpace: 'nowrap', overflow: 'hidden' }}>WAGMI</span>
        )}
        <div style={{ flex: 1 }} />
        {!collapsed && (
          <button
            onClick={toggleCollapsed}
            style={{ background: 'none', border: 'none', color: C.muted, cursor: 'pointer', padding: 4, display: 'flex', alignItems: 'center', borderRadius: 4, flexShrink: 0 }}
            title="Collapse sidebar"
          >
            <IconChevronLeft />
          </button>
        )}
      </div>

      {/* Nav content */}
      <div style={{ flex: 1, overflowY: 'auto', overflowX: 'hidden', padding: '12px 0' }}>
        <SidebarContent
          collapsed={collapsed}
          groups={NAV_GROUPS}
          expandedGroups={expandedGroups}
          onToggleGroup={toggleGroup}
          isActive={isActive}
          botLive={botLive}
          regime={regime}
          regimeStyle={regimeStyle}
        />
      </div>

      {/* Bottom: live status + expand toggle */}
      <div
        style={{
          borderTop: `1px solid ${C.border}`,
          padding: '10px 8px',
          flexShrink: 0,
        }}
      >
        {/* Live status */}
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 8,
            padding: '6px 8px',
            borderRadius: 6,
            overflow: 'hidden',
          }}
        >
          <div
            className={botLive ? 'live-dot' : undefined}
            style={{
              width: 7,
              height: 7,
              borderRadius: '50%',
              background: botLive ? C.bull : C.faint,
              flexShrink: 0,
            }}
          />
          {!collapsed && (
            <span style={{ fontSize: 11, fontWeight: 600, color: botLive ? C.bull : C.muted, whiteSpace: 'nowrap' }}>
              {botLive ? 'LIVE' : 'OFFLINE'}
            </span>
          )}
          {!collapsed && regime && regimeStyle && (
            <span
              style={{
                marginLeft: 'auto',
                fontSize: 10,
                fontWeight: 700,
                padding: '2px 7px',
                borderRadius: 999,
                background: regimeStyle.bg,
                color: regimeStyle.text,
                whiteSpace: 'nowrap',
              }}
            >
              {regime.replace(/_/g, ' ').toUpperCase()}
            </span>
          )}
        </div>

        {/* Expand button when collapsed */}
        {collapsed && (
          <button
            onClick={toggleCollapsed}
            style={{
              width: '100%',
              padding: '6px 0',
              background: 'none',
              border: 'none',
              color: C.muted,
              cursor: 'pointer',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              borderRadius: 6,
            }}
            title="Expand sidebar"
          >
            <IconChevronRight />
          </button>
        )}
      </div>
    </div>
  );
}

// ── SidebarContent ────────────────────────────────────────────────────────────

function SidebarContent({
  collapsed,
  groups,
  expandedGroups,
  onToggleGroup,
  isActive,
  botLive,
  regime,
  regimeStyle,
}: {
  collapsed: boolean;
  groups: NavGroup[];
  expandedGroups: Set<string>;
  onToggleGroup: (label: string) => void;
  isActive: (href: string) => boolean;
  botLive: boolean;
  regime: string | null;
  regimeStyle: { bg: string; text: string; dot: string } | null;
}) {
  if (collapsed) {
    // Collapsed: show group icon buttons (clicking first item in group)
    return (
      <div style={{ display: 'flex', flexDirection: 'column', gap: 4, padding: '4px 8px' }}>
        {groups.map((group) => {
          const firstHref = group.items[0]?.href;
          const active = group.items.some((i) => isActive(i.href));
          return (
            <Link
              key={group.label}
              href={firstHref || '/dashboard'}
              title={group.label}
              style={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                width: 36,
                height: 36,
                borderRadius: 8,
                color: active ? C.brand : C.muted,
                background: active ? 'rgba(0,204,136,0.08)' : 'transparent',
                border: active ? '1px solid rgba(0,204,136,0.15)' : '1px solid transparent',
                transition: 'all 0.15s ease',
                textDecoration: 'none',
                margin: '0 auto',
              }}
            >
              <group.icon />
            </Link>
          );
        })}
      </div>
    );
  }

  return (
    <div>
      {groups.map((group) => {
        const isExpanded = expandedGroups.has(group.label);
        const hasActive = group.items.some((i) => isActive(i.href));

        return (
          <div key={group.label} style={{ marginBottom: 2 }}>
            {/* Group header */}
            <button
              onClick={() => onToggleGroup(group.label)}
              style={{
                width: '100%',
                display: 'flex',
                alignItems: 'center',
                gap: 8,
                padding: '6px 16px',
                background: 'none',
                border: 'none',
                cursor: 'pointer',
                textAlign: 'left',
                color: hasActive ? C.textSub : C.muted,
              }}
            >
              <span style={{ color: hasActive ? C.brand : 'inherit', flexShrink: 0 }}>
                <group.icon />
              </span>
              <span style={{ fontSize: 11, fontWeight: 700, letterSpacing: 0.5, textTransform: 'uppercase', flex: 1 }}>
                {group.label}
              </span>
              <svg
                width="10"
                height="10"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2.5"
                style={{ transform: isExpanded ? 'rotate(180deg)' : 'rotate(0deg)', transition: 'transform 0.2s ease', flexShrink: 0 }}
              >
                <polyline points="6 9 12 15 18 9" />
              </svg>
            </button>

            {/* Group items */}
            {isExpanded && (
              <div style={{ paddingBottom: 4 }}>
                {group.items.map((item) => {
                  const active = isActive(item.href);
                  return (
                    <Link
                      key={item.href}
                      href={item.href}
                      style={{
                        display: 'block',
                        padding: '7px 16px 7px 40px',
                        fontSize: 13,
                        fontWeight: active ? 600 : 400,
                        color: active ? C.text : C.muted,
                        background: active ? 'rgba(0,204,136,0.06)' : 'transparent',
                        borderLeft: active ? `2px solid ${C.brand}` : '2px solid transparent',
                        textDecoration: 'none',
                        transition: 'all 0.12s ease',
                        letterSpacing: -0.1,
                      }}
                      onMouseEnter={(e) => {
                        if (!active) {
                          (e.currentTarget as HTMLAnchorElement).style.color = C.textSub;
                          (e.currentTarget as HTMLAnchorElement).style.background = 'rgba(255,255,255,0.02)';
                        }
                      }}
                      onMouseLeave={(e) => {
                        if (!active) {
                          (e.currentTarget as HTMLAnchorElement).style.color = C.muted;
                          (e.currentTarget as HTMLAnchorElement).style.background = 'transparent';
                        }
                      }}
                    >
                      {item.label}
                    </Link>
                  );
                })}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
