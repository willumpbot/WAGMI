'use client';

import React, { useEffect, useState } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/router';
import { C, F, R, Z, alpha } from '../src/theme';
import EquityTicker from './EquityTicker';

/**
 * TopNav — Hyperliquid-style horizontal nav.
 * Replaces the old sidebar at top-level. Single row, fixed height,
 * left-justified primary tabs, right-aligned account / status.
 *
 * Design: per audits/2026-04-29/05_ui_reshape_hyperliquid_style.md §3
 *   Trade  Portfolio  Vaults  Leaderboard  Bot  Learn
 *
 * Each item maps to an existing page so nothing breaks during transition.
 * As pages are restructured (Phase 3+), the hrefs update; the labels stay.
 */

type NavItem = {
  label: string;
  href: string;
  /** Routes that should make this tab appear "active". The first href is the canonical. */
  activeMatch?: (path: string) => boolean;
};

const NAV_ITEMS: NavItem[] = [
  {
    label: 'Trade',
    href: '/signals',
    activeMatch: (p) => p === '/' || p.startsWith('/signals') || p.startsWith('/trade'),
  },
  {
    label: 'Portfolio',
    href: '/portfolio',
    activeMatch: (p) =>
      p.startsWith('/portfolio') ||
      p.startsWith('/dashboard') ||
      p.startsWith('/results') ||
      p.startsWith('/performance') ||
      p.startsWith('/forensics') ||
      p.startsWith('/counterfactuals'),
  },
  {
    label: 'Vaults',
    href: '/vaults',
    activeMatch: (p) => p.startsWith('/vaults'),
  },
  {
    label: 'Leaderboard',
    href: '/leaderboard',
    activeMatch: (p) => p.startsWith('/leaderboard'),
  },
  {
    label: 'Co-Pilot',
    href: '/live',
    activeMatch: (p) =>
      p.startsWith('/live') ||
      p.startsWith('/ai-decisions') ||
      p.startsWith('/bot') ||
      p.startsWith('/agent-intelligence') ||
      p.startsWith('/llm-audit') ||
      p.startsWith('/reasoning') ||
      p.startsWith('/strategies') ||
      p.startsWith('/backtest') ||
      p.startsWith('/copy-trade'),
  },
  {
    label: 'Learn',
    href: '/learn',
    activeMatch: (p) =>
      p.startsWith('/learn') || p.startsWith('/masterclass') || p.startsWith('/thesis'),
  },
];

const NAV_HEIGHT = 52;
const MOBILE_BREAKPOINT = 768;

export default function TopNav() {
  const router = useRouter();
  const [isMobile, setIsMobile] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);

  useEffect(() => {
    const onResize = () => setIsMobile(window.innerWidth < MOBILE_BREAKPOINT);
    onResize();
    window.addEventListener('resize', onResize);
    return () => window.removeEventListener('resize', onResize);
  }, []);

  // Close mobile menu on route change
  useEffect(() => {
    const handler = () => setMenuOpen(false);
    router.events.on('routeChangeStart', handler);
    return () => router.events.off('routeChangeStart', handler);
  }, [router.events]);

  const path = router.asPath || '/';
  const isActive = (item: NavItem) =>
    item.activeMatch ? item.activeMatch(path) : path.startsWith(item.href);

  return (
    <>
      <nav
        role="navigation"
        aria-label="Primary"
        style={{
          position: 'sticky',
          top: 0,
          zIndex: Z.sidebar,
          height: NAV_HEIGHT,
          background: '#050508',
          borderBottom: `1px solid ${C.border}`,
          display: 'flex',
          alignItems: 'center',
          padding: '0 16px',
          gap: 16,
        }}
      >
        {/* Logo */}
        <Link
          href="/"
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 8,
            textDecoration: 'none',
            paddingRight: 8,
            borderRight: `1px solid ${C.border}`,
            marginRight: 8,
            height: '100%',
          }}
        >
          <span
            style={{
              width: 24,
              height: 24,
              borderRadius: R.xs,
              border: `1px solid ${C.brand}`,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              fontSize: 11,
              fontWeight: 800,
              color: C.brand,
              fontFamily: 'JetBrains Mono, monospace',
            }}
          >
            W
          </span>
          {!isMobile && (
            <span style={{ fontSize: F.md, fontWeight: 700, color: C.text, letterSpacing: -0.3 }}>
              WAGMI
            </span>
          )}
        </Link>

        {/* Primary nav (desktop) */}
        {!isMobile && (
          <div style={{ display: 'flex', alignItems: 'center', height: '100%', flex: 1 }}>
            {NAV_ITEMS.map((item) => {
              const active = isActive(item);
              return (
                <Link
                  key={item.label}
                  href={item.href}
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    height: '100%',
                    padding: '0 14px',
                    fontSize: F.md,
                    fontWeight: 500,
                    color: active ? C.text : C.textSub,
                    textDecoration: 'none',
                    borderBottom: `2px solid ${active ? C.brand : 'transparent'}`,
                    transition: 'color 120ms ease-out, border-color 120ms ease-out',
                    marginBottom: -1, // align border with nav border
                  }}
                  onMouseEnter={(e) => {
                    if (!active) (e.currentTarget as HTMLAnchorElement).style.color = C.text;
                  }}
                  onMouseLeave={(e) => {
                    if (!active) (e.currentTarget as HTMLAnchorElement).style.color = C.textSub;
                  }}
                >
                  {item.label}
                </Link>
              );
            })}
          </div>
        )}

        {/* Mobile menu button */}
        {isMobile && (
          <button
            onClick={() => setMenuOpen((v) => !v)}
            aria-label="Toggle menu"
            style={{
              marginLeft: 'auto',
              background: 'transparent',
              border: `1px solid ${C.border}`,
              borderRadius: R.sm,
              color: C.text,
              padding: '6px 10px',
              fontSize: F.sm,
              cursor: 'pointer',
            }}
          >
            {menuOpen ? '✕' : '☰'}
          </button>
        )}

        {/* Right-side: equity ticker */}
        {!isMobile && (
          <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
            <EquityTicker compact />
          </div>
        )}
      </nav>

      {/* Mobile menu drawer */}
      {isMobile && menuOpen && (
        <div
          style={{
            position: 'sticky',
            top: NAV_HEIGHT,
            zIndex: Z.sidebar - 1,
            background: '#0a0a0f',
            borderBottom: `1px solid ${C.border}`,
            padding: '8px 0',
          }}
        >
          {NAV_ITEMS.map((item) => {
            const active = isActive(item);
            return (
              <Link
                key={item.label}
                href={item.href}
                style={{
                  display: 'block',
                  padding: '12px 16px',
                  fontSize: F.md,
                  fontWeight: 500,
                  color: active ? C.brand : C.text,
                  textDecoration: 'none',
                  borderLeft: `2px solid ${active ? C.brand : 'transparent'}`,
                }}
              >
                {item.label}
              </Link>
            );
          })}
          <div style={{ padding: '12px 16px', borderTop: `1px solid ${C.border}`, marginTop: 4 }}>
            <EquityTicker compact />
          </div>
        </div>
      )}
    </>
  );
}
