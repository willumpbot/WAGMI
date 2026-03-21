'use client';

import React, { useEffect, useState } from 'react';
import { useRouter } from 'next/router';
import { C, R, G, S } from '../src/theme';
import Sidebar from './Sidebar';

const COLLAPSED_WIDTH = 64;
const EXPANDED_WIDTH = 240;
const STORAGE_KEY = 'wagmi-sidebar-collapsed';
const MOBILE_BREAKPOINT = 1024;

export default function Layout({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const [sidebarWidth, setSidebarWidth] = useState(COLLAPSED_WIDTH);
  const [isMobile, setIsMobile] = useState(false);

  // Read sidebar width from CSS custom property set by Sidebar component
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

    // Listen for sidebar toggle events
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
    <div style={{ minHeight: '100vh', background: C.bg, fontFamily: "'Inter', system-ui, -apple-system, sans-serif" }}>
      {/* Skip-to-content */}
      <a href="#main-content" className="skip-to-content">Skip to content</a>

      {/* Sidebar navigation */}
      <Sidebar />

      {/* ── Page content ────────────────────────────── */}
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
        <main id="main-content" role="main" style={{ maxWidth: 1280, margin: '0 auto', padding: '28px 20px 60px', width: '100%', flex: 1 }}>
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
            <p style={{ margin: 0, fontSize: 10, color: C.faint }}>&copy; 2026 WAGMI</p>
          </div>
        </footer>
      </div>

      {/* Global styles for live-dot animation */}
      <style>{`
        @keyframes livePulse {
          0%, 100% { opacity: 1; }
          50% { opacity: 0.4; }
        }
        .live-dot {
          animation: livePulse 2s ease-in-out infinite;
        }
        .skip-to-content {
          position: absolute;
          left: -9999px;
          top: auto;
          width: 1px;
          height: 1px;
          overflow: hidden;
        }
        .skip-to-content:focus {
          position: fixed;
          top: 8px;
          left: 8px;
          width: auto;
          height: auto;
          padding: 8px 16px;
          background: ${C.surface};
          color: ${C.text};
          z-index: 9999;
          border-radius: 6px;
          border: 1px solid ${C.brand};
          font-size: 13px;
        }
      `}</style>
    </div>
  );
}
