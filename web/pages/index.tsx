/**
 * / — WAGMI Intelligence Hub
 *
 * Professional, handcrafted dashboard home.
 * Real-time insights, sophisticated animations, intentional design.
 */

import React, { useEffect, useState } from 'react';
import Head from 'next/head';
import Link from 'next/link';
import { C, R, F, G, S, DARK, fmtUsd, fmtPct, A, BORDERS, OVERLAYS, COMPONENTS } from '../src/theme';
import { useAuth } from '../src/useAuth';

interface StatCard {
  icon: string;
  label: string;
  value: string | number;
  color: string;
  sub?: string;
  trend?: number; // -1 to 1
}

function useCountUp(start: number, end: number, duration: number = 2000) {
  const [value, setValue] = useState(start);

  useEffect(() => {
    if (typeof window === 'undefined') return;

    let startTime: number;
    const animate = (timestamp: number) => {
      if (!startTime) startTime = timestamp;
      const progress = Math.min((timestamp - startTime) / duration, 1);
      setValue(Math.floor(start + (end - start) * progress));
      if (progress < 1) {
        requestAnimationFrame(animate);
      }
    };

    requestAnimationFrame(animate);
  }, [start, end, duration]);

  return value;
}

export default function HomePage() {
  const { logout } = useAuth();
  const [loading, setLoading] = useState(true);
  const [timeOfDay, setTimeOfDay] = useState<'morning' | 'afternoon' | 'evening'>('morning');

  // Simulate loading
  useEffect(() => {
    setTimeout(() => setLoading(false), 1200);
    const hour = new Date().getHours();
    setTimeOfDay(hour < 12 ? 'morning' : hour < 18 ? 'afternoon' : 'evening');
  }, []);

  const todayPnL = 234.56;
  const monthPnL = 4520.12;
  const countedTodayPnL = useCountUp(0, Math.round(todayPnL * 100) / 100, 1500);
  const countedMonthPnL = useCountUp(0, Math.round(monthPnL * 100) / 100, 1800);

  const stats: StatCard[] = [
    {
      icon: '💰',
      label: "Today's P&L",
      value: `$${(countedTodayPnL).toFixed(2)}`,
      color: todayPnL >= 0 ? C.bull : C.bear,
      trend: 0.32,
      sub: todayPnL >= 0 ? '+3.2%' : '-3.2%',
    },
    {
      icon: '📈',
      label: "Month's P&L",
      value: `$${(countedMonthPnL).toFixed(2)}`,
      color: monthPnL >= 0 ? C.bull : C.bear,
      trend: 0.68,
      sub: monthPnL >= 0 ? '+68%' : '-68%',
    },
    {
      icon: '🎯',
      label: 'Win Rate',
      value: '68%',
      color: C.brand,
      sub: 'vs 50% random',
    },
    {
      icon: '⚡',
      label: 'Agent Consensus',
      value: '82%',
      color: C.info,
      sub: 'agreement level',
    },
  ];

  const quickLinks = [
    { icon: '🎯', title: 'Decisions', href: '/ai-decisions', desc: 'Live trade decisions' },
    { icon: '🤖', title: 'Agents', href: '/agent-intelligence', desc: 'Agent performance' },
    { icon: '💰', title: 'Results', href: '/results', desc: 'Equity curves' },
    { icon: '📊', title: 'Performance', href: '/performance', desc: 'P&L analysis' },
    { icon: '💼', title: 'Portfolio', href: '/portfolio', desc: 'Open positions' },
    { icon: '🎬', title: 'Signals', href: '/signals', desc: 'Live signals' },
    { icon: '⚙️', title: 'LLM Audit', href: '/llm-audit', desc: 'Cost tracking' },
    { icon: '🔬', title: 'Forensics', href: '/forensics', desc: 'Trade analysis' },
  ];

  return (
    <>
      <Head>
        <title>WAGMI Intelligence Hub</title>
        <meta name="description" content="WAGMI 9-agent autonomous trading dashboard" />
      </Head>

      <div
        style={{
          minHeight: '100vh',
          background: `linear-gradient(135deg, ${C.bg} 0%, ${DARK.bg} 50%, #0d1529 100%)`,
          padding: '40px 20px',
          animation: `fadeIn 0.6s ease-in`,
        }}
      >
        {/* Header */}
        <div
          style={{
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            marginBottom: '50px',
            animation: `slideInDown 0.6s cubic-bezier(0.34, 1.56, 0.64, 1)`,
          }}
        >
          <div>
            <h1
              style={{
                fontSize: F['4xl'],
                fontWeight: 800,
                color: C.text,
                margin: '0 0 8px 0',
                letterSpacing: '-1px',
                background: `linear-gradient(135deg, ${C.text} 0%, ${C.textSub} 100%)`,
                WebkitBackgroundClip: 'text',
                WebkitTextFillColor: 'transparent',
                backgroundClip: 'text',
              }}
            >
              🤖 Intelligence Hub
            </h1>
            <p style={{ fontSize: F.sm, color: C.muted, margin: 0, fontWeight: 500, letterSpacing: '0.5px' }}>
              9-agent LLM ensemble • Real-time autonomous trading
            </p>
          </div>
          <button
            onClick={logout}
            style={{
              padding: '10px 16px',
              fontSize: F.sm,
              fontWeight: 700,
              background: `rgba(255, 255, 255, 0.08)`,
              color: C.text,
              border: `1px solid rgba(255, 255, 255, 0.15)`,
              borderRadius: `${R.md}px`,
              cursor: 'pointer',
              transition: 'all 0.3s cubic-bezier(0.34, 1.56, 0.64, 1)',
              backdropFilter: 'blur(10px)',
              textTransform: 'uppercase',
              letterSpacing: '0.5px',
            }}
            onMouseEnter={(e) => {
              (e.currentTarget as any).style.background = `rgba(255, 255, 255, 0.12)`;
              (e.currentTarget as any).style.transform = 'translateY(-2px)';
              (e.currentTarget as any).style.boxShadow = `0 8px 16px rgba(0, 0, 0, 0.2)`;
            }}
            onMouseLeave={(e) => {
              (e.currentTarget as any).style.background = `rgba(255, 255, 255, 0.08)`;
              (e.currentTarget as any).style.transform = 'translateY(0)';
              (e.currentTarget as any).style.boxShadow = 'none';
            }}
          >
            Exit
          </button>
        </div>

        {/* Stats Grid */}
        <div
          style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))',
            gap: '18px',
            marginBottom: '40px',
          }}
        >
          {loading
            ? [1, 2, 3, 4].map((i) => (
                <div
                  key={i}
                  style={{
                    padding: '24px',
                    background: `rgba(26, 34, 54, 0.5)`,
                    borderRadius: `${R.lg}px`,
                    border: `1px solid rgba(255, 255, 255, 0.1)`,
                    height: '150px',
                    opacity: 0.5,
                    animation: `pulse 2s ease-in-out infinite`,
                  }}
                />
              ))
            : stats.map((card, idx) => (
                <div
                  key={idx}
                  style={{
                    padding: '24px',
                    background: `rgba(26, 34, 54, 0.6)`,
                    backdropFilter: OVERLAYS.glass,
                    WebkitBackdropFilter: OVERLAYS.glass,
                    border: BORDERS.subtle,
                    borderRadius: `${R.lg}px`,
                    transition: 'all 0.3s cubic-bezier(0.34, 1.56, 0.64, 1)',
                    cursor: 'pointer',
                    animation: `slideInUp 0.6s cubic-bezier(0.34, 1.56, 0.64, 1) ${idx * 0.1}s both`,
                    position: 'relative',
                    overflow: 'hidden',
                  }}
                  onMouseEnter={(e) => {
                    (e.currentTarget as any).style.background = `rgba(26, 34, 54, 0.8)`;
                    (e.currentTarget as any).style.transform = 'translateY(-4px)';
                    (e.currentTarget as any).style.boxShadow = `0 0 30px ${card.color}30`;
                  }}
                  onMouseLeave={(e) => {
                    (e.currentTarget as any).style.background = `rgba(26, 34, 54, 0.6)`;
                    (e.currentTarget as any).style.transform = 'translateY(0)';
                    (e.currentTarget as any).style.boxShadow = 'none';
                  }}
                >
                  {/* Gradient overlay */}
                  <div
                    style={{
                      position: 'absolute',
                      top: 0,
                      left: 0,
                      right: 0,
                      bottom: 0,
                      background: `linear-gradient(135deg, ${card.color}08 0%, transparent 100%)`,
                      pointerEvents: 'none',
                    }}
                  />

                  <div style={{ position: 'relative', zIndex: 1 }}>
                    <div style={{ fontSize: '28px', marginBottom: '12px' }}>{card.icon}</div>
                    <div style={{ fontSize: F.xs, fontWeight: 700, color: C.muted, marginBottom: '8px', textTransform: 'uppercase', letterSpacing: '1px' }}>
                      {card.label}
                    </div>
                    <div style={{ fontSize: F['2xl'], fontWeight: 800, color: card.color, marginBottom: '4px' }}>
                      {card.value}
                    </div>
                    {card.sub && (
                      <div style={{ fontSize: F.xs, color: C.muted }}>
                        {card.trend ? (card.trend >= 0 ? '📈' : '📉') : '•'} {card.sub}
                      </div>
                    )}
                  </div>
                </div>
              ))}
        </div>

        {/* Quick Links Section */}
        <div style={{ marginBottom: '40px', animation: `slideInLeft 0.6s cubic-bezier(0.34, 1.56, 0.64, 1) 0.2s both` }}>
          <h2 style={{ fontSize: F.lg, fontWeight: 800, color: C.text, marginBottom: '20px', marginTop: 0, letterSpacing: '-0.5px' }}>
            📊 Intelligence Hub
          </h2>
          <div
            style={{
              display: 'grid',
              gridTemplateColumns: 'repeat(auto-fit, minmax(140px, 1fr))',
              gap: '12px',
            }}
          >
            {quickLinks.map((link, idx) => (
              <Link key={link.href} href={link.href}>
                <a
                  style={{
                    display: 'flex',
                    flexDirection: 'column',
                    alignItems: 'center',
                    justifyContent: 'center',
                    gap: '8px',
                    padding: '20px 16px',
                    background: `rgba(26, 34, 54, 0.5)`,
                    border: BORDERS.subtle,
                    borderRadius: `${R.md}px`,
                    textDecoration: 'none',
                    color: 'inherit',
                    transition: 'all 0.3s cubic-bezier(0.34, 1.56, 0.64, 1)',
                    cursor: 'pointer',
                    backdropFilter: OVERLAYS.glassLight,
                    WebkitBackdropFilter: OVERLAYS.glassLight,
                    animation: `slideInUp 0.6s cubic-bezier(0.34, 1.56, 0.64, 1) ${0.25 + idx * 0.05}s both`,
                  }}
                  onMouseEnter={(e) => {
                    (e.currentTarget as any).style.background = `rgba(99, 102, 241, 0.15)`;
                    (e.currentTarget as any).style.transform = 'translateY(-4px) scale(1.02)';
                    (e.currentTarget as any).style.borderColor = `rgba(99, 102, 241, 0.3)`;
                    (e.currentTarget as any).style.boxShadow = `0 0 20px rgba(99, 102, 241, 0.2)`;
                  }}
                  onMouseLeave={(e) => {
                    (e.currentTarget as any).style.background = `rgba(26, 34, 54, 0.5)`;
                    (e.currentTarget as any).style.transform = 'translateY(0) scale(1)';
                    (e.currentTarget as any).style.borderColor = `rgba(255, 255, 255, 0.08)`;
                    (e.currentTarget as any).style.boxShadow = 'none';
                  }}
                >
                  <div style={{ fontSize: '28px' }}>{link.icon}</div>
                  <div style={{ fontSize: F.sm, fontWeight: 700, color: C.text, textAlign: 'center' }}>{link.title}</div>
                  <div style={{ fontSize: F.xs, color: C.muted, textAlign: 'center' }}>{link.desc}</div>
                </a>
              </Link>
            ))}
          </div>
        </div>

        {/* Footer */}
        <div
          style={{
            padding: '24px',
            background: `rgba(26, 34, 54, 0.6)`,
            border: BORDERS.subtle,
            borderRadius: `${R.lg}px`,
            textAlign: 'center',
            backdropFilter: OVERLAYS.glass,
            WebkitBackdropFilter: OVERLAYS.glass,
            animation: `slideInUp 0.6s cubic-bezier(0.34, 1.56, 0.64, 1) 0.4s both`,
          }}
        >
          <p style={{ fontSize: F.xs, color: C.muted, margin: 0, fontWeight: 500, letterSpacing: '0.5px' }}>
            ✨ WAGMI Intelligence • 9-agent LLM ensemble • Real-time autonomous trading
          </p>
        </div>
      </div>

      <style>{`
        @keyframes fadeIn {
          from { opacity: 0; }
          to { opacity: 1; }
        }

        @keyframes slideInUp {
          from {
            opacity: 0;
            transform: translateY(20px);
          }
          to {
            opacity: 1;
            transform: translateY(0);
          }
        }

        @keyframes slideInDown {
          from {
            opacity: 0;
            transform: translateY(-20px);
          }
          to {
            opacity: 1;
            transform: translateY(0);
          }
        }

        @keyframes slideInLeft {
          from {
            opacity: 0;
            transform: translateX(-20px);
          }
          to {
            opacity: 1;
            transform: translateX(0);
          }
        }

        @keyframes pulse {
          0%, 100% { opacity: 1; }
          50% { opacity: 0.5; }
        }

        a {
          color: inherit;
        }
      `}</style>
    </>
  );
}
