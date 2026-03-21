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
    <div style={{ minHeight: '100vh', background: C.bg, fontFamily: "'Inter', system-ui, -apple-system, sans-serif", position: 'relative', overflow: 'hidden' }}>
      {/* ── Global Animated Nebula Background ──────── */}
      <div
        aria-hidden="true"
        style={{
          position: 'fixed',
          inset: 0,
          zIndex: 0,
          pointerEvents: 'none',
        }}
      >
        {/* Primary gradient mesh — breathing nebula */}
        <div className="nebula-mesh" style={{ position: 'absolute', inset: 0 }} />
        {/* Fine dot grid for texture/grain */}
        <div className="nebula-grid" style={{ position: 'absolute', inset: 0, opacity: 0.4 }} />
        {/* Subtle vignette for focus */}
        <div style={{
          position: 'absolute',
          inset: 0,
          background: 'radial-gradient(ellipse at 50% 50%, transparent 40%, rgba(0,0,0,0.35) 100%)',
        }} />
      </div>

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
          position: 'relative',
          zIndex: 1,
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

      {/* Global styles */}
      <style>{`
        /* ── Nebula Background Animation ──────────────── */
        @keyframes nebulaDrift {
          0%   { background-position: 0% 50%, 100% 0%, 50% 100%, 30% 70%; }
          25%  { background-position: 100% 30%, 0% 80%, 70% 20%, 60% 40%; }
          50%  { background-position: 50% 100%, 80% 20%, 20% 60%, 90% 10%; }
          75%  { background-position: 20% 60%, 60% 100%, 90% 40%, 10% 80%; }
          100% { background-position: 0% 50%, 100% 0%, 50% 100%, 30% 70%; }
        }
        .nebula-mesh {
          background:
            radial-gradient(ellipse 80% 60% at 20% 40%, rgba(99,102,241,0.07) 0%, transparent 70%),
            radial-gradient(ellipse 60% 80% at 80% 20%, rgba(168,85,247,0.05) 0%, transparent 70%),
            radial-gradient(ellipse 70% 50% at 50% 85%, rgba(6,182,212,0.04) 0%, transparent 70%),
            radial-gradient(ellipse 50% 70% at 70% 60%, rgba(236,72,153,0.025) 0%, transparent 70%);
          background-size: 200% 200%, 200% 200%, 200% 200%, 200% 200%;
          animation: nebulaDrift 35s ease-in-out infinite;
        }
        .nebula-grid {
          background-image:
            radial-gradient(circle, rgba(99,102,241,0.12) 1px, transparent 1px);
          background-size: 32px 32px;
        }

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
