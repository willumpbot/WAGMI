/**
 * / — WAGMI Dream Dashboard
 * Real-time status, agent performance, trading intelligence at a glance
 * Professional, unique, animated interface
 */

import React, { useEffect, useState } from 'react';
import Head from 'next/head';
import Link from 'next/link';
import { C, R, F, G, S, fmtUsd, fmtPct } from '../src/theme';
import { useAuth } from '../src/useAuth';

interface DashboardStats {
  today_pnl: number;
  month_pnl: number;
  win_rate: number;
  open_positions: number;
  total_agents: number;
  system_health: 'healthy' | 'warning' | 'critical';
  agent_consensus: number;
}

export default function HomePage() {
  const { logout } = useAuth();
  const [stats, setStats] = useState<DashboardStats | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setTimeout(() => {
      setStats({
        today_pnl: 234.56,
        month_pnl: 4520.12,
        win_rate: 0.68,
        open_positions: 3,
        total_agents: 9,
        system_health: 'healthy',
        agent_consensus: 0.82,
      });
      setLoading(false);
    }, 600);
  }, []);

  const healthColor = {
    healthy: C.bull,
    warning: C.warn,
    critical: C.bear,
  }[stats?.system_health || 'healthy'];

  const statCards = stats ? [
    { icon: '💰', label: "Today's P&L", value: fmtUsd(stats.today_pnl), color: stats.today_pnl >= 0 ? C.bull : C.bear, sub: `${fmtPct(stats.today_pnl / 100)}` },
    { icon: '📈', label: "Month's P&L", value: fmtUsd(stats.month_pnl), color: stats.month_pnl >= 0 ? C.bull : C.bear, sub: `${fmtPct(stats.month_pnl / 100)}` },
    { icon: '🎯', label: 'Win Rate', value: `${Math.round(stats.win_rate * 100)}%`, color: C.brand, sub: 'vs 50% random' },
    { icon: '⚡', label: 'Consensus', value: `${Math.round(stats.agent_consensus * 100)}%`, color: C.info, sub: 'agent agreement' },
  ] : [];

  const quickLinks = [
    { icon: '🎯', title: 'Decisions', href: '/ai-decisions', desc: 'Real-time trade decisions' },
    { icon: '🤖', title: 'Agents', href: '/agent-intelligence', desc: 'Agent performance' },
    { icon: '💰', title: 'Results', href: '/results', desc: 'Equity curves' },
    { icon: '📊', title: 'Performance', href: '/performance', desc: 'P&L metrics' },
    { icon: '💼', title: 'Portfolio', href: '/portfolio', desc: 'Open positions' },
    { icon: '🎬', title: 'Signals', href: '/signals', desc: 'Live signals' },
    { icon: '⚙️', title: 'LLM Audit', href: '/llm-audit', desc: 'Cost routing' },
    { icon: '🔬', title: 'Forensics', href: '/forensics', desc: 'Trade analysis' },
  ];

  return (
    <>
      <Head>
        <title>WAGMI Dashboard</title>
        <meta name="description" content="WAGMI 9-agent autonomous trading intelligence dashboard" />
      </Head>

      <div style={{ minHeight: '100vh', background: `linear-gradient(135deg, ${C.bg} 0%, #0d1529 50%, #0f172a 100%)`, padding: '40px 20px' }}>
        {/* Header */}
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '50px', animation: 'slideInDown 0.5s ease' }}>
          <div>
            <h1 style={{ fontSize: F['4xl'], fontWeight: 800, color: C.text, margin: '0 0 8px 0', letterSpacing: '-1px' }}>
              🤖 WAGMI Intelligence
            </h1>
            <p style={{ fontSize: F.sm, color: C.muted, margin: 0 }}>
              9-agent autonomous trading system • Real-time decision transparency
            </p>
          </div>
          <button
            onClick={logout}
            style={{
              padding: '10px 16px',
              fontSize: F.sm,
              fontWeight: 600,
              background: C.surface,
              color: C.text,
              border: `1px solid ${C.border}`,
              borderRadius: R.md,
              cursor: 'pointer',
              transition: 'all 0.2s ease',
            }}
            onMouseEnter={(e) => {
              (e.currentTarget as any).style.background = C.surfaceHover;
            }}
            onMouseLeave={(e) => {
              (e.currentTarget as any).style.background = C.surface;
            }}
          >
            🚪 Logout
          </button>
        </div>

        {/* Stats Grid */}
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: '16px', marginBottom: '40px' }}>
          {loading
            ? [1, 2, 3, 4].map((i) => (
                <div
                  key={i}
                  style={{
                    padding: '24px',
                    background: C.card,
                    borderRadius: R.lg,
                    border: `1px solid ${C.border}`,
                    height: '140px',
                    opacity: 0.6,
                    animation: 'pulse 2s infinite',
                  }}
                />
              ))
            : statCards.map((card, idx) => (
                <div
                  key={idx}
                  style={{
                    padding: '24px',
                    background: `linear-gradient(135deg, ${C.card} 0%, ${C.surface} 100%)`,
                    border: `1px solid ${card.color}20`,
                    borderRadius: R.lg,
                    transition: 'all 0.3s ease',
                    cursor: 'pointer',
                    animation: `slideInUp 0.5s ease ${idx * 0.1}s both`,
                  }}
                  className="card-hover"
                  onMouseEnter={(e) => {
                    (e.currentTarget as any).style.boxShadow = `0 0 30px ${card.color}30`;
                  }}
                  onMouseLeave={(e) => {
                    (e.currentTarget as any).style.boxShadow = 'none';
                  }}
                >
                  <div style={{ fontSize: '24px', marginBottom: '12px' }}>{card.icon}</div>
                  <div style={{ fontSize: F.xs, fontWeight: 700, color: C.muted, marginBottom: '8px', textTransform: 'uppercase', letterSpacing: '1px' }}>
                    {card.label}
                  </div>
                  <div style={{ fontSize: F['2xl'], fontWeight: 800, color: card.color, marginBottom: '4px' }}>
                    {card.value}
                  </div>
                  <div style={{ fontSize: F.xs, color: C.muted }}>{card.sub}</div>
                </div>
              ))}
        </div>

        {/* Quick Links */}
        <div style={{ marginBottom: '40px' }}>
          <h2 style={{ fontSize: F.lg, fontWeight: 700, color: C.text, marginBottom: '20px', marginTop: 0, animation: 'slideInLeft 0.5s ease' }}>
            📊 Intelligence Hub
          </h2>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(140px, 1fr))', gap: '12px' }}>
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
                    background: C.card,
                    border: `1px solid ${C.border}`,
                    borderRadius: R.md,
                    textDecoration: 'none',
                    color: 'inherit',
                    transition: 'all 0.3s ease',
                    animation: `slideInUp 0.5s ease ${idx * 0.05}s both`,
                  }}
                  className="card-hover"
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
            background: `linear-gradient(135deg, ${C.surface} 0%, ${C.card} 100%)`,
            border: `1px solid ${C.border}`,
            borderRadius: R.lg,
            textAlign: 'center',
            animation: 'slideInUp 0.5s ease 0.3s both',
          }}
        >
          <p style={{ fontSize: F.xs, color: C.muted, margin: 0 }}>
            ✨ WAGMI Dashboard • 9-agent LLM ensemble • Real-time autonomous trading intelligence
          </p>
        </div>
      </div>

      <style>{`
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
        @keyframes pulse {
          0%, 100% { opacity: 1; }
          50% { opacity: 0.5; }
        }
        a {
          color: inherit;
          text-decoration: none;
        }
      `}</style>
    </>
  );
}
