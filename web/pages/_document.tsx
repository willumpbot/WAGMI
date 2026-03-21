import { Html, Head, Main, NextScript } from 'next/document';

export default function Document() {
  return (
    <Html lang="en">
      <Head>
        {/* Viewport is set via next/head in _app or per-page; charset is auto-injected by Next.js */}
        {/* Inter font from Google Fonts */}
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="anonymous" />
        <link
          href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;500&display=swap"
          rel="stylesheet"
        />
        {/* Favicon */}
        <link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'><rect width='32' height='32' rx='6' fill='%236366f1'/><text x='50%25' y='55%25' dominant-baseline='middle' text-anchor='middle' fill='white' font-size='18' font-family='system-ui' font-weight='bold'>W</text></svg>" />
        {/* Primary meta */}
        <meta name="description" content="WAGMI — AI-powered crypto trading bot with real-time signals, LLM decision analysis, copy-trade intelligence, and backtested proof." />
        {/* Open Graph */}
        <meta property="og:title" content="WAGMI — AI-Powered Crypto Trading Bot" />
        <meta property="og:description" content="Real-time signals, LLM brain analysis, copy-trade intelligence, and backtested proof." />
        <meta property="og:type" content="website" />
        <meta property="og:site_name" content="WAGMI" />
        <meta property="og:url" content="https://wagmi.trade" />
        <meta property="og:image" content="https://wagmi.trade/og-image.png" />
        {/* Twitter Card */}
        <meta name="twitter:card" content="summary_large_image" />
        <meta name="twitter:title" content="WAGMI — AI-Powered Crypto Trading Bot" />
        <meta name="twitter:description" content="Real-time signals, LLM brain analysis, copy-trade intelligence, and backtested proof." />
        <meta name="twitter:image" content="https://wagmi.trade/og-image.png" />
        {/* Robots / indexing */}
        <meta name="robots" content="index, follow" />
        {/* Theme */}
        <meta name="theme-color" content="#0a0f1e" />
        {/* Global styles */}
        <style>{`
          *, *::before, *::after { box-sizing: border-box; }
          html {
            font-family: 'Inter', system-ui, -apple-system, sans-serif;
            scroll-behavior: smooth;
          }
          body { margin: 0; padding: 0; background: var(--color-bg); color: var(--color-text); }
          a { color: inherit; text-decoration: none; }
          button { font-family: inherit; cursor: pointer; }
          code, pre { font-family: 'JetBrains Mono', 'Fira Code', monospace; }

          /* ── CSS custom properties (design system tokens) ─────────── */
          :root {
            /* Brand */
            --color-brand: #6366f1;
            --color-brand-dark: #4f46e5;
            --color-brand-glow: rgba(99,102,241,0.15);

            /* Semantic */
            --color-bull: #16a34a;
            --color-bear: #dc2626;
            --color-warn: #d97706;
            --color-info: #2563eb;

            /* Dark surfaces */
            --color-bg: #0a0f1e;
            --color-surface: #111827;
            --color-surface-hover: #1e293b;
            --color-card: #1a2236;
            --color-border: #2d3748;
            --color-border-bright: #4a5568;

            /* Text */
            --color-text: #f1f5f9;
            --color-text-sub: #cbd5e1;
            --color-muted: #64748b;

            /* Radii */
            --radius-sm: 6px;
            --radius-md: 10px;
            --radius-lg: 16px;
            --radius-pill: 9999px;
          }

          /* Skip-to-content link (hidden until focused) */
          .skip-to-content {
            position: absolute;
            top: -100%;
            left: 12px;
            z-index: 9999;
            padding: 8px 16px;
            background: var(--color-brand);
            color: #fff;
            font-size: 14px;
            font-weight: 600;
            border-radius: 0 0 var(--radius-sm) var(--radius-sm);
            text-decoration: none;
            transition: top 0.15s ease;
          }
          .skip-to-content:focus { top: 0; outline: none; }

          /* Focus-visible — luminous ring */
          :focus-visible {
            outline: none;
            box-shadow: 0 0 0 2px rgba(99,102,241,0.5), 0 0 12px rgba(99,102,241,0.15);
          }
          /* Suppress focus ring for mouse/touch interactions */
          :focus:not(:focus-visible) { outline: none; }

          /* Skeleton shimmer animation (upgraded from pulse) */
          @keyframes shimmer {
            0% { background-position: -200% 0; }
            100% { background-position: 200% 0; }
          }
          .skeleton {
            background: linear-gradient(
              90deg,
              var(--color-surface-hover) 25%,
              var(--color-card) 50%,
              var(--color-surface-hover) 75%
            );
            background-size: 200% 100%;
            border-radius: var(--radius-sm);
            animation: shimmer 1.5s ease-in-out infinite;
          }

          /* Glass noise texture overlay */
          .glass-noise {
            position: relative;
          }
          .glass-noise::before {
            content: '';
            position: absolute;
            inset: 0;
            background: url("data:image/svg+xml,%3Csvg viewBox='0 0 256 256' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='4' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)' opacity='0.04'/%3E%3C/svg%3E") repeat;
            opacity: 0.03;
            pointer-events: none;
            border-radius: inherit;
            z-index: 0;
          }
          .glass-noise > * { position: relative; z-index: 1; }

          /* Glass surface utility */
          .glass-card {
            background: rgba(26,34,54,0.55);
            backdrop-filter: blur(16px) saturate(1.4);
            -webkit-backdrop-filter: blur(16px) saturate(1.4);
            border: 1px solid rgba(255,255,255,0.06);
            box-shadow: 0 8px 32px rgba(0,0,0,0.25), inset 0 1px 0 rgba(255,255,255,0.04);
          }
          .glass-elevated {
            background: rgba(26,34,54,0.7);
            backdrop-filter: blur(24px) saturate(1.6);
            -webkit-backdrop-filter: blur(24px) saturate(1.6);
            border: 1px solid rgba(255,255,255,0.08);
            box-shadow: 0 8px 32px rgba(0,0,0,0.3);
          }

          /* PnL glow effects */
          .glow-bull { box-shadow: 0 0 20px rgba(22,163,74,0.15), 0 4px 12px rgba(0,0,0,0.2); }
          .glow-bear { box-shadow: 0 0 20px rgba(220,38,38,0.15), 0 4px 12px rgba(0,0,0,0.2); }
          .glow-brand { box-shadow: 0 0 24px rgba(99,102,241,0.2), 0 4px 12px rgba(0,0,0,0.2); }

          /* Gradient mesh background */
          .bg-mesh {
            background:
              radial-gradient(ellipse at 20% 50%, rgba(99,102,241,0.08) 0%, transparent 50%),
              radial-gradient(ellipse at 80% 20%, rgba(168,85,247,0.05) 0%, transparent 50%),
              radial-gradient(ellipse at 50% 80%, rgba(6,182,212,0.04) 0%, transparent 50%),
              var(--color-bg);
          }

          /* ── Futuristic Aurora Background ──────────────────── */
          @keyframes auroraShift {
            0%   { background-position: 0% 50%, 100% 50%, 50% 100%; }
            25%  { background-position: 100% 50%, 0% 100%, 50% 0%; }
            50%  { background-position: 50% 100%, 50% 0%, 100% 50%; }
            75%  { background-position: 0% 100%, 100% 0%, 0% 50%; }
            100% { background-position: 0% 50%, 100% 50%, 50% 100%; }
          }
          .bg-aurora {
            background:
              radial-gradient(ellipse at 20% 50%, rgba(99,102,241,0.1) 0%, transparent 50%),
              radial-gradient(ellipse at 80% 20%, rgba(168,85,247,0.07) 0%, transparent 50%),
              radial-gradient(ellipse at 50% 80%, rgba(6,182,212,0.06) 0%, transparent 50%),
              var(--color-bg);
            background-size: 200% 200%, 200% 200%, 200% 200%;
            animation: auroraShift 20s ease-in-out infinite;
          }

          /* ── Floating Orb Glow ─────────────────────────────── */
          @keyframes orbFloat {
            0%, 100% { transform: translate(0, 0) scale(1); opacity: 0.4; }
            25%  { transform: translate(30px, -20px) scale(1.1); opacity: 0.6; }
            50%  { transform: translate(-15px, 15px) scale(0.95); opacity: 0.3; }
            75%  { transform: translate(20px, 10px) scale(1.05); opacity: 0.5; }
          }
          .floating-orb {
            position: absolute;
            border-radius: 50%;
            filter: blur(60px);
            animation: orbFloat 12s ease-in-out infinite;
            pointer-events: none;
            z-index: 0;
          }
          .orb-brand { background: rgba(99,102,241,0.15); width: 300px; height: 300px; }
          .orb-purple { background: rgba(168,85,247,0.1); width: 250px; height: 250px; animation-delay: -4s; }
          .orb-cyan { background: rgba(6,182,212,0.08); width: 200px; height: 200px; animation-delay: -8s; }

          /* ── Glow border animation (for featured cards) ───── */
          @keyframes glowBorderRotate {
            0%   { --glow-angle: 0deg; }
            100% { --glow-angle: 360deg; }
          }
          @property --glow-angle {
            syntax: '<angle>';
            initial-value: 0deg;
            inherits: false;
          }
          .glow-border {
            position: relative;
            overflow: hidden;
          }
          .glow-border::before {
            content: '';
            position: absolute;
            inset: -1px;
            border-radius: inherit;
            padding: 1px;
            background: conic-gradient(from var(--glow-angle), transparent 60%, rgba(99,102,241,0.4) 75%, rgba(168,85,247,0.3) 85%, transparent 95%);
            animation: glowBorderRotate 4s linear infinite;
            -webkit-mask: linear-gradient(#fff 0 0) content-box, linear-gradient(#fff 0 0);
            -webkit-mask-composite: xor;
            mask-composite: exclude;
            pointer-events: none;
            z-index: 1;
          }

          /* ── Breathing glow for live elements ──────────────── */
          @keyframes breatheGlow {
            0%, 100% { box-shadow: 0 0 15px rgba(99,102,241,0.08), inset 0 1px 0 rgba(255,255,255,0.03); }
            50%      { box-shadow: 0 0 25px rgba(99,102,241,0.15), inset 0 1px 0 rgba(255,255,255,0.06); }
          }
          .breathe-glow {
            animation: breatheGlow 3s ease-in-out infinite;
          }

          /* ── Data pulse (for live values) ──────────────────── */
          @keyframes dataPulse {
            0% { background-color: rgba(99,102,241,0.15); }
            100% { background-color: transparent; }
          }
          .data-flash {
            animation: dataPulse 0.6s ease-out;
          }

          /* ── Upgraded card-hover with glass depth ──────────── */
          .card-hover {
            transition: transform 0.25s cubic-bezier(0.34, 1.56, 0.64, 1),
                        box-shadow 0.25s ease,
                        border-color 0.25s ease,
                        backdrop-filter 0.25s ease;
          }
          .card-hover:hover {
            transform: translateY(-3px) scale(1.005);
            box-shadow: 0 12px 40px rgba(0,0,0,0.4), 0 0 20px rgba(99,102,241,0.08);
            border-color: rgba(255,255,255,0.1) !important;
          }

          /* ── Stagger reveal for lists ──────────────────────── */
          .stagger-reveal > * {
            opacity: 0;
            transform: translateY(12px);
            animation: fadeInUp 0.35s cubic-bezier(.22,.68,0,1.2) both;
          }
          .stagger-reveal > *:nth-child(1) { animation-delay: 0.05s; }
          .stagger-reveal > *:nth-child(2) { animation-delay: 0.10s; }
          .stagger-reveal > *:nth-child(3) { animation-delay: 0.15s; }
          .stagger-reveal > *:nth-child(4) { animation-delay: 0.20s; }
          .stagger-reveal > *:nth-child(5) { animation-delay: 0.25s; }
          .stagger-reveal > *:nth-child(6) { animation-delay: 0.30s; }
          .stagger-reveal > *:nth-child(7) { animation-delay: 0.35s; }
          .stagger-reveal > *:nth-child(8) { animation-delay: 0.40s; }
          .stagger-reveal > *:nth-child(n+9) { animation-delay: 0.45s; }

          /* ── Glassmorphism upgrade for card-hover ───────────── */
          .glass-card.card-hover:hover {
            backdrop-filter: blur(20px) saturate(1.6);
            -webkit-backdrop-filter: blur(20px) saturate(1.6);
          }

          /* Reduced motion: disable all animations */
          @media (prefers-reduced-motion: reduce) {
            *, *::before, *::after {
              animation-duration: 0.01ms !important;
              animation-iteration-count: 1 !important;
              transition-duration: 0.01ms !important;
            }
          }

          /* Activity ticker scroll */
          @keyframes tickerScroll {
            0% { transform: translateX(0); }
            100% { transform: translateX(-50%); }
          }

          /* Fade in cards */
          @keyframes fadeInUp {
            from { opacity: 0; transform: translateY(14px); }
            to   { opacity: 1; transform: translateY(0); }
          }
          .fade-in { animation: fadeInUp 0.35s cubic-bezier(.22,.68,0,1.2) both; }
          .fade-in-1 { animation: fadeInUp 0.35s cubic-bezier(.22,.68,0,1.2) 0.05s both; }
          .fade-in-2 { animation: fadeInUp 0.35s cubic-bezier(.22,.68,0,1.2) 0.10s both; }
          .fade-in-3 { animation: fadeInUp 0.35s cubic-bezier(.22,.68,0,1.2) 0.15s both; }
          .fade-in-4 { animation: fadeInUp 0.35s cubic-bezier(.22,.68,0,1.2) 0.20s both; }

          /* Live indicator pulse */
          @keyframes livePulse {
            0%, 100% { box-shadow: 0 0 0 0 rgba(22,163,74,.5); }
            50%       { box-shadow: 0 0 0 5px rgba(22,163,74,0); }
          }
          .live-dot { animation: livePulse 2s ease-in-out infinite; }

          /* Gradient shimmer (hero/banner elements) */
          @keyframes gradientShift {
            0%   { background-position: 0% 50%; }
            50%  { background-position: 100% 50%; }
            100% { background-position: 0% 50%; }
          }
          .gradient-text {
            background: linear-gradient(135deg, #6366f1, #a855f7, #06b6d4);
            background-size: 200% 200%;
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            background-clip: text;
            animation: gradientShift 4s ease infinite;
          }

          /* Slide-down for mobile menu */
          @keyframes slideDown {
            from { opacity: 0; transform: translateY(-8px); }
            to   { opacity: 1; transform: translateY(0); }
          }
          .slide-down { animation: slideDown 0.2s ease both; }

          /* Pill badge */
          .badge {
            display: inline-flex; align-items: center; gap: 4px;
            padding: 2px 9px; border-radius: 9999px;
            font-size: 11px; font-weight: 600; letter-spacing: .4px;
          }
          .badge-bull  { background: rgba(22,163,74,.15);  color: #4ade80; }
          .badge-bear  { background: rgba(220,38,38,.15);  color: #f87171; }
          .badge-warn  { background: rgba(217,119,6,.15);  color: #fbbf24; }
          .badge-info  { background: rgba(37,99,235,.15);  color: #60a5fa; }
          .badge-muted { background: rgba(100,116,139,.12); color: #94a3b8; }

          /* Section header style */
          .section-label {
            font-size: 11px; font-weight: 700; letter-spacing: 1.2px;
            text-transform: uppercase; color: var(--color-muted);
            display: flex; align-items: center; gap: 8px;
          }
          .section-label::after {
            content: ''; flex: 1; height: 1px;
            background: linear-gradient(to right, var(--color-border), rgba(99,102,241,0.08) 40%, transparent);
          }

          /* Scrollbar — luminous gradient track */
          ::-webkit-scrollbar { width: 5px; height: 5px; }
          ::-webkit-scrollbar-track { background: rgba(17,24,39,0.3); }
          ::-webkit-scrollbar-thumb {
            background: linear-gradient(180deg, rgba(99,102,241,0.25), rgba(168,85,247,0.15));
            border-radius: 10px;
          }
          ::-webkit-scrollbar-thumb:hover {
            background: linear-gradient(180deg, rgba(99,102,241,0.45), rgba(168,85,247,0.3));
          }

          /* Table base */
          table { border-collapse: collapse; width: 100%; }
          th { text-align: left; }

          /* Number font for data */
          .num { font-variant-numeric: tabular-nums; font-feature-settings: 'tnum'; }

          /* ── Architectural Grid Background ───────────────── */
          .bg-grid {
            background-image:
              linear-gradient(rgba(99,102,241,0.03) 1px, transparent 1px),
              linear-gradient(90deg, rgba(99,102,241,0.03) 1px, transparent 1px);
            background-size: 60px 60px;
          }
          .bg-grid-fine {
            background-image:
              linear-gradient(rgba(99,102,241,0.015) 1px, transparent 1px),
              linear-gradient(90deg, rgba(99,102,241,0.015) 1px, transparent 1px);
            background-size: 20px 20px;
          }

          /* ── Light Beam Sweep ────────────────────────────── */
          @keyframes lightSweep {
            0%   { transform: translateX(-100%) rotate(15deg); }
            100% { transform: translateX(200%) rotate(15deg); }
          }
          .light-beam {
            position: relative;
            overflow: hidden;
          }
          .light-beam::after {
            content: '';
            position: absolute;
            top: -50%;
            left: -50%;
            width: 50%;
            height: 200%;
            background: linear-gradient(90deg, transparent, rgba(255,255,255,0.02), transparent);
            transform: rotate(15deg);
            animation: lightSweep 8s ease-in-out infinite;
            pointer-events: none;
            z-index: 1;
          }

          /* ── Chromatic Aberration on Hover ────────────────── */
          .chromatic-hover {
            transition: text-shadow 0.3s ease;
          }
          .chromatic-hover:hover {
            text-shadow: -1px 0 rgba(99,102,241,0.3), 1px 0 rgba(236,72,153,0.3);
          }

          /* ── Subtle CRT Scan Lines ───────────────────────── */
          .scanlines {
            position: relative;
          }
          .scanlines::after {
            content: '';
            position: absolute;
            inset: 0;
            background: repeating-linear-gradient(
              0deg,
              transparent,
              transparent 2px,
              rgba(0,0,0,0.03) 2px,
              rgba(0,0,0,0.03) 4px
            );
            pointer-events: none;
            z-index: 2;
            border-radius: inherit;
          }

          /* ── Prismatic Border Animation ──────────────────── */
          @keyframes prismaticShift {
            0%   { --prism-angle: 0deg; }
            100% { --prism-angle: 360deg; }
          }
          @property --prism-angle {
            syntax: '<angle>';
            initial-value: 0deg;
            inherits: false;
          }
          .prismatic-border {
            position: relative;
            overflow: hidden;
          }
          .prismatic-border::before {
            content: '';
            position: absolute;
            inset: -1px;
            border-radius: inherit;
            padding: 1px;
            background: conic-gradient(
              from var(--prism-angle),
              rgba(99,102,241,0.4),
              rgba(6,182,212,0.3),
              rgba(168,85,247,0.3),
              rgba(236,72,153,0.25),
              rgba(99,102,241,0.4)
            );
            animation: prismaticShift 6s linear infinite;
            -webkit-mask: linear-gradient(#fff 0 0) content-box, linear-gradient(#fff 0 0);
            -webkit-mask-composite: xor;
            mask-composite: exclude;
            pointer-events: none;
            z-index: 1;
          }

          /* ── Refraction Edge (light along glass edges) ───── */
          .refraction-edge {
            position: relative;
          }
          .refraction-edge::before {
            content: '';
            position: absolute;
            top: 0; left: 0; right: 0;
            height: 1px;
            background: linear-gradient(90deg,
              transparent,
              rgba(99,102,241,0.3) 20%,
              rgba(6,182,212,0.4) 40%,
              rgba(168,85,247,0.3) 60%,
              rgba(236,72,153,0.2) 80%,
              transparent);
            opacity: 0.6;
            z-index: 2;
            border-radius: inherit;
          }
          .refraction-edge::after {
            content: '';
            position: absolute;
            bottom: 0; left: 0; right: 0;
            height: 1px;
            background: linear-gradient(90deg,
              transparent 10%,
              rgba(255,255,255,0.05) 50%,
              transparent 90%);
            z-index: 2;
          }

          /* ── Liquid Morphing Blob ────────────────────────── */
          @keyframes blobMorph {
            0%, 100% { border-radius: 60% 40% 30% 70% / 60% 30% 70% 40%; }
            25%      { border-radius: 30% 60% 70% 40% / 50% 60% 30% 60%; }
            50%      { border-radius: 50% 60% 30% 60% / 30% 40% 70% 60%; }
            75%      { border-radius: 60% 30% 60% 40% / 70% 60% 40% 30%; }
          }
          .morphing-blob {
            position: absolute;
            filter: blur(80px);
            animation: blobMorph 15s ease-in-out infinite;
            pointer-events: none;
          }

          /* ── Ambient Particle Drift ──────────────────────── */
          @keyframes particleDrift {
            0%   { transform: translateY(0) scale(1); opacity: 0; }
            10%  { opacity: 0.4; }
            90%  { opacity: 0.3; }
            100% { transform: translateY(-100vh) scale(0.5); opacity: 0; }
          }
          .particle-field {
            position: fixed;
            inset: 0;
            pointer-events: none;
            z-index: 0;
            overflow: hidden;
          }
          .particle {
            position: absolute;
            width: 2px;
            height: 2px;
            border-radius: 50%;
            background: rgba(99,102,241,0.4);
            animation: particleDrift var(--duration, 12s) linear infinite;
            animation-delay: var(--delay, 0s);
          }

          /* ── Vignette (darkened edges for focus) ─────────── */
          .vignette::before {
            content: '';
            position: fixed;
            inset: 0;
            background: radial-gradient(ellipse at center, transparent 55%, rgba(0,0,0,0.25) 100%);
            pointer-events: none;
            z-index: 9998;
          }

          /* ── Text Selection ──────────────────────────────── */
          ::selection {
            background: rgba(99,102,241,0.3);
            color: #f1f5f9;
          }

          /* ── Glass Crystal Surface ───────────────────────── */
          .glass-crystal {
            background: rgba(26,34,54,0.35);
            backdrop-filter: blur(40px) saturate(1.8);
            -webkit-backdrop-filter: blur(40px) saturate(1.8);
            border: 1px solid rgba(255,255,255,0.1);
            box-shadow: 0 8px 32px rgba(0,0,0,0.3), inset 0 1px 0 rgba(255,255,255,0.08), inset 0 -1px 0 rgba(255,255,255,0.02);
          }
          .glass-diamond {
            background: rgba(26,34,54,0.25);
            backdrop-filter: blur(48px) saturate(2) brightness(1.02);
            -webkit-backdrop-filter: blur(48px) saturate(2) brightness(1.02);
            border: 1px solid rgba(255,255,255,0.12);
            box-shadow: 0 12px 48px rgba(0,0,0,0.35), inset 0 2px 0 rgba(255,255,255,0.1), inset 0 -1px 0 rgba(255,255,255,0.04);
          }
          .glass-frosted {
            background: rgba(17,24,39,0.45);
            backdrop-filter: blur(60px) saturate(2);
            -webkit-backdrop-filter: blur(60px) saturate(2);
            border: 1px solid rgba(255,255,255,0.04);
            box-shadow: 0 16px 48px rgba(0,0,0,0.4);
          }

          /* ── Magnetic Card Hover ─────────────────────────── */
          .magnetic-hover {
            transition: transform 0.3s cubic-bezier(0.34, 1.56, 0.64, 1),
                        box-shadow 0.3s ease,
                        border-color 0.3s ease;
          }
          .magnetic-hover:hover {
            transform: translateY(-4px) scale(1.01);
            box-shadow: 0 20px 60px rgba(0,0,0,0.4), 0 0 30px rgba(99,102,241,0.1);
            border-color: rgba(255,255,255,0.12) !important;
          }

          /* ── Breathing Glow Variants ─────────────────────── */
          @keyframes breatheSlow {
            0%, 100% { box-shadow: 0 0 20px rgba(99,102,241,0.06), inset 0 1px 0 rgba(255,255,255,0.03); }
            50%      { box-shadow: 0 0 35px rgba(99,102,241,0.12), inset 0 1px 0 rgba(255,255,255,0.06); }
          }
          .breathe-slow { animation: breatheSlow 4s ease-in-out infinite; }
        `}</style>
      </Head>
      <body>
        <Main />
        <NextScript />
      </body>
    </Html>
  );
}
