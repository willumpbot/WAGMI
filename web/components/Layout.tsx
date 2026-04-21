'use client';

import React, { useEffect, useState } from 'react';
import { C, R, Z } from '../src/theme';
import Sidebar from './Sidebar';
import EquityTicker from './EquityTicker';

const COLLAPSED_WIDTH = 64;
const EXPANDED_WIDTH = 240;
const STORAGE_KEY = 'wagmi-sidebar-collapsed';
const MOBILE_BREAKPOINT = 1024;

export default function Layout({ children }: { children: React.ReactNode }) {
  const [sidebarWidth, setSidebarWidth] = useState(COLLAPSED_WIDTH);
  const [isMobile, setIsMobile] = useState(false);

  useEffect(() => {
    const readWidth = () => {
      const mobile = window.innerWidth < MOBILE_BREAKPOINT;
      setIsMobile(mobile);
      if (mobile) {
        setSidebarWidth(0);
        return;
      }
      try {
        const stored = localStorage.getItem(STORAGE_KEY);
        setSidebarWidth(stored === 'true' ? COLLAPSED_WIDTH : EXPANDED_WIDTH);
      } catch {
        setSidebarWidth(COLLAPSED_WIDTH);
      }
    };

    readWidth();
    const handleToggle = () => readWidth();
    window.addEventListener('sidebar-toggle', handleToggle);
    window.addEventListener('resize', handleToggle);
    window.addEventListener('storage', handleToggle);

    return () => {
      window.removeEventListener('sidebar-toggle', handleToggle);
      window.removeEventListener('resize', handleToggle);
      window.removeEventListener('storage', handleToggle);
    };
  }, []);

  return (
    <div
      style={{
        minHeight: '100vh',
        background: C.bg,
        fontFamily: "'Inter', system-ui, -apple-system, sans-serif",
        position: 'relative',
      }}
    >
      {/* Skip-to-content */}
      <a href="#main-content" className="skip-to-content">
        Skip to content
      </a>

      {/* Sidebar */}
      <Sidebar />

      {/* Page content */}
      <div
        style={{
          marginLeft: sidebarWidth,
          transition: 'margin-left 0.2s cubic-bezier(0.25, 0.1, 0.25, 1)',
          minHeight: '100vh',
          display: 'flex',
          flexDirection: 'column',
          paddingTop: isMobile ? 52 : 0,
        }}
      >
        {/* Sticky top header — persistent live equity ticker across every page */}
        <header
          style={{
            position: 'sticky',
            top: isMobile ? 52 : 0,
            zIndex: Z.sidebar - 10,
            padding: isMobile ? '8px 12px' : '12px 20px',
            background: 'linear-gradient(180deg, rgba(5,5,8,0.85) 0%, rgba(5,5,8,0.55) 100%)',
            backdropFilter: 'blur(10px)',
            WebkitBackdropFilter: 'blur(10px)',
            borderBottom: `1px solid ${C.border}`,
            display: 'flex',
            justifyContent: 'flex-end',
            alignItems: 'center',
          }}
        >
          <div style={{ maxWidth: 1280, margin: '0', display: 'flex', justifyContent: 'flex-end', width: '100%' }}>
            <EquityTicker compact={isMobile} />
          </div>
        </header>

        <main
          id="main-content"
          role="main"
          className="wagmi-main"
          style={{
            maxWidth: 1280,
            margin: '0 auto',
            padding: isMobile ? '16px 12px 48px' : '24px 20px 60px',
            width: '100%',
            flex: 1,
            overflowX: 'hidden',
          }}
        >
          {children}
        </main>

        {/* Footer */}
        <footer
          style={{
            borderTop: `1px solid ${C.border}`,
            background: C.surface,
            padding: '20px',
          }}
        >
          <div
            style={{
              maxWidth: 1280,
              margin: '0 auto',
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'center',
              gap: 8,
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <span
                style={{
                  width: 20,
                  height: 20,
                  borderRadius: R.xs,
                  border: `1px solid ${C.brand}`,
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  fontSize: 10,
                  fontWeight: 800,
                  color: C.brand,
                  flexShrink: 0,
                  fontFamily: 'JetBrains Mono, monospace',
                }}
              >
                W
              </span>
              <span
                style={{
                  fontSize: 12,
                  fontWeight: 700,
                  color: C.textSub,
                  letterSpacing: -0.3,
                }}
              >
                WAGMI
              </span>
            </div>
            <p
              style={{
                margin: 0,
                fontSize: 11,
                color: C.muted,
                textAlign: 'center',
                lineHeight: 1.7,
                maxWidth: 560,
              }}
            >
              AI-driven market analysis for informational purposes only. Not financial advice — you are
              responsible for your own trading decisions. Crypto carries significant risk. Historical
              results don&apos;t predict future performance.
            </p>
            <p style={{ margin: 0, fontSize: 10, color: C.faint }}>
              &copy; 2026 WAGMI
            </p>
          </div>
        </footer>
      </div>
    </div>
  );
}
