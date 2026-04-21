import React, { useState, useRef, useEffect } from 'react';
import { C } from '../src/theme';
import AgentDetailModal from './AgentDetailModal';

type Agent = {
  name: string;
  role: string;
  model: 'Haiku' | 'Sonnet' | 'Opus';
  x: number;
  y: number;
  tier: 1 | 2 | 3;
  /** Canonical role slug used by API endpoints (lowercase) */
  slug: string;
  /** Short descriptor shown in tooltip */
  purpose: string;
};

const AGENTS: Agent[] = [
  { name: 'Regime',    role: 'classify',    model: 'Haiku',  x: 60,  y: 120, tier: 1, slug: 'regime',   purpose: 'Classifies market regime + directional outlook' },
  { name: 'Trade',     role: 'thesis',      model: 'Sonnet', x: 180, y: 60,  tier: 2, slug: 'trade',    purpose: 'Forms directional thesis — go, skip, or flip' },
  { name: 'Risk',      role: 'size',        model: 'Haiku',  x: 180, y: 180, tier: 2, slug: 'risk',     purpose: 'Sizes position + flags portfolio risks' },
  { name: 'Critic',    role: 'stress-test', model: 'Sonnet', x: 300, y: 120, tier: 2, slug: 'critic',   purpose: 'Stress-tests thesis — must provide counter-thesis to veto' },
  { name: 'Learning',  role: 'post-close',  model: 'Haiku',  x: 420, y: 40,  tier: 3, slug: 'learning', purpose: 'Extracts lessons from closed trades' },
  { name: 'Exit',      role: 'monitor',     model: 'Haiku',  x: 420, y: 120, tier: 3, slug: 'exit',     purpose: 'Monitors open positions and reassesses thesis' },
  { name: 'Scout',     role: 'prep',        model: 'Haiku',  x: 420, y: 200, tier: 3, slug: 'scout',    purpose: 'Idle-time watchlists and pre-formed theses' },
  { name: 'Overseer',  role: 'meta-opt',    model: 'Sonnet', x: 540, y: 80,  tier: 3, slug: 'overseer', purpose: 'Meta-level supervision + coherence checks' },
  { name: 'Quant',     role: 'numeric',     model: 'Haiku',  x: 540, y: 160, tier: 3, slug: 'quant',    purpose: 'Numeric validation — leverage, sizing, risk math' },
];

const LINKS: [string, string][] = [
  ['Regime', 'Trade'],
  ['Regime', 'Risk'],
  ['Trade', 'Critic'],
  ['Risk', 'Critic'],
  ['Critic', 'Learning'],
  ['Critic', 'Exit'],
  ['Critic', 'Scout'],
  ['Learning', 'Overseer'],
  ['Exit', 'Overseer'],
  ['Scout', 'Quant'],
];

const MODEL_COLOR: Record<Agent['model'], string> = {
  Haiku: C.info,
  Sonnet: C.brand,
  Opus: C.purple,
};

function findAgent(name: string): Agent | undefined {
  return AGENTS.find((a) => a.name === name);
}

type Props = {
  width?: number;
  height?: number;
  compact?: boolean;
  /** If false, nodes are purely visual (no hover/click). Defaults to true. */
  interactive?: boolean;
};

/**
 * Visual graphic of the WAGMI 9-agent specialist brain.
 * Renders as SVG — crisp at any size, theme-matched, zero image assets.
 * Shows the deliberation pipeline that makes WAGMI unique (vs JUICE and every other bot).
 *
 * When `interactive` (default), hovering a node shows a tooltip and clicking
 * opens a detail modal with recent decisions + accuracy (from
 * `/v1/agents/{role}/performance`).
 */
export default function AgentBrainGraphic({ width = 620, height = 260, compact = false, interactive = true }: Props) {
  const nodeR = compact ? 16 : 20;
  const labelSize = compact ? 10 : 11;
  const subSize = compact ? 8 : 9;

  const [hovered, setHovered] = useState<Agent | null>(null);
  const [openAgent, setOpenAgent] = useState<Agent | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const [tooltipPos, setTooltipPos] = useState<{ left: number; top: number } | null>(null);

  // Compute tooltip position relative to container when hover node changes
  useEffect(() => {
    if (!hovered || !containerRef.current) {
      setTooltipPos(null);
      return;
    }
    const rect = containerRef.current.getBoundingClientRect();
    // Node position on the SVG viewbox → mapped into container coords
    const xPct = hovered.x / width;
    const yPct = hovered.y / height;
    const left = xPct * rect.width;
    const top = yPct * rect.height;
    setTooltipPos({ left, top });
  }, [hovered, width, height]);

  return (
    <div ref={containerRef} style={{ width: '100%', maxWidth: width, position: 'relative' }}>
      <svg
        viewBox={`0 0 ${width} ${height}`}
        preserveAspectRatio="xMidYMid meet"
        style={{ width: '100%', height: 'auto', display: 'block' }}
        role="img"
        aria-label="WAGMI nine-agent specialist brain diagram"
      >
        <defs>
          <radialGradient id="nodeGlow" cx="50%" cy="50%" r="50%">
            <stop offset="0%" stopColor={C.brand} stopOpacity="0.35" />
            <stop offset="60%" stopColor={C.brand} stopOpacity="0.1" />
            <stop offset="100%" stopColor={C.brand} stopOpacity="0" />
          </radialGradient>
          <linearGradient id="linkGrad" x1="0" y1="0" x2="1" y2="0">
            <stop offset="0%" stopColor={C.brand} stopOpacity="0.05" />
            <stop offset="50%" stopColor={C.brand} stopOpacity="0.25" />
            <stop offset="100%" stopColor={C.brand} stopOpacity="0.05" />
          </linearGradient>
          <filter id="nodeShadow" x="-50%" y="-50%" width="200%" height="200%">
            <feDropShadow dx="0" dy="1" stdDeviation="2" floodColor="#000" floodOpacity="0.5" />
          </filter>
        </defs>

        {/* Subtle background grid dots */}
        <g opacity="0.12">
          {[...Array(Math.floor(width / 40) + 1)].map((_, ix) =>
            [...Array(Math.floor(height / 40) + 1)].map((_, iy) => (
              <circle key={`${ix}-${iy}`} cx={ix * 40} cy={iy * 40} r={0.7} fill="#ffffff" />
            ))
          )}
        </g>

        {/* Tier dividers */}
        <g opacity="0.08">
          <line x1={120} y1={10} x2={120} y2={height - 10} stroke="#ffffff" strokeDasharray="2 4" />
          <line x1={360} y1={10} x2={360} y2={height - 10} stroke="#ffffff" strokeDasharray="2 4" />
        </g>

        {/* Links */}
        <g>
          {LINKS.map(([fromName, toName], i) => {
            const a = findAgent(fromName);
            const b = findAgent(toName);
            if (!a || !b) return null;
            const midX = (a.x + b.x) / 2;
            const isActive =
              hovered && (hovered.name === fromName || hovered.name === toName);
            return (
              <g key={`link-${i}`}>
                <path
                  d={`M ${a.x} ${a.y} Q ${midX} ${a.y} ${midX} ${(a.y + b.y) / 2} T ${b.x} ${b.y}`}
                  fill="none"
                  stroke={isActive ? C.brand : 'url(#linkGrad)'}
                  strokeOpacity={isActive ? 0.7 : 1}
                  strokeWidth={isActive ? 2 : 1.5}
                  style={{ transition: 'stroke 0.2s ease, stroke-opacity 0.2s ease, stroke-width 0.2s ease' }}
                />
              </g>
            );
          })}
        </g>

        {/* Nodes */}
        {AGENTS.map((agent) => {
          const color = MODEL_COLOR[agent.model];
          const isHovered = hovered?.name === agent.name;
          return (
            <g
              key={agent.name}
              transform={`translate(${agent.x}, ${agent.y})`}
              style={{
                cursor: interactive ? 'pointer' : 'default',
                transition: 'transform 0.15s ease',
              }}
              onMouseEnter={() => interactive && setHovered(agent)}
              onMouseLeave={() => interactive && setHovered((h) => (h?.name === agent.name ? null : h))}
              onClick={() => interactive && setOpenAgent(agent)}
              onKeyDown={(e) => {
                if (!interactive) return;
                if (e.key === 'Enter' || e.key === ' ') {
                  e.preventDefault();
                  setOpenAgent(agent);
                }
              }}
              tabIndex={interactive ? 0 : -1}
              role={interactive ? 'button' : undefined}
              aria-label={interactive ? `${agent.name} agent — view details` : undefined}
            >
              {/* Glow (pops on hover) */}
              <circle
                r={isHovered ? nodeR * 2.1 : nodeR * 1.8}
                fill="url(#nodeGlow)"
                style={{ transition: 'r 0.2s ease' }}
              />
              {/* Ring */}
              <circle
                r={isHovered ? nodeR + 1.5 : nodeR}
                fill={C.card}
                stroke={color}
                strokeWidth={isHovered ? 2.5 : 1.5}
                filter="url(#nodeShadow)"
                style={{ transition: 'r 0.2s ease, stroke-width 0.2s ease' }}
              />
              {/* Inner dot */}
              <circle
                r={nodeR / 2.6}
                fill={color}
                opacity={isHovered ? 0.7 : 0.4}
                style={{ transition: 'opacity 0.2s ease' }}
              />
              {/* Name */}
              <text
                x={0}
                y={nodeR + 14}
                textAnchor="middle"
                fontSize={labelSize}
                fontWeight="700"
                fill={C.text}
                fontFamily="Inter, system-ui, sans-serif"
              >
                {agent.name}
              </text>
              {/* Role/model */}
              <text
                x={0}
                y={nodeR + 26}
                textAnchor="middle"
                fontSize={subSize}
                fill={C.muted}
                fontFamily="JetBrains Mono, monospace"
                letterSpacing="0.5"
              >
                {agent.model.toUpperCase()}
              </text>
            </g>
          );
        })}

        {/* Tier labels */}
        <g opacity="0.5">
          <text x={60} y={24} textAnchor="middle" fontSize={9} fontWeight="700"
                fill={C.muted} fontFamily="JetBrains Mono, monospace" letterSpacing="1">
            CLASSIFY
          </text>
          <text x={240} y={24} textAnchor="middle" fontSize={9} fontWeight="700"
                fill={C.muted} fontFamily="JetBrains Mono, monospace" letterSpacing="1">
            DECIDE
          </text>
          <text x={480} y={24} textAnchor="middle" fontSize={9} fontWeight="700"
                fill={C.muted} fontFamily="JetBrains Mono, monospace" letterSpacing="1">
            LEARN & MONITOR
          </text>
        </g>
      </svg>

      {/* Hover tooltip (absolute-positioned over the SVG) */}
      {interactive && hovered && tooltipPos && (
        <div
          style={{
            position: 'absolute',
            left: Math.max(8, Math.min(tooltipPos.left - 110, (containerRef.current?.clientWidth ?? width) - 228)),
            top: Math.max(0, tooltipPos.top - 74),
            width: 220,
            padding: '10px 12px',
            background: 'rgba(8,8,12,0.96)',
            border: `1px solid ${MODEL_COLOR[hovered.model]}40`,
            borderRadius: 8,
            boxShadow: '0 6px 18px rgba(0,0,0,0.55)',
            fontSize: 11,
            color: C.textSub,
            pointerEvents: 'none',
            zIndex: 10,
            backdropFilter: 'blur(6px)',
            WebkitBackdropFilter: 'blur(6px)',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 4 }}>
            <span style={{ fontSize: 12, fontWeight: 800, color: C.text }}>
              {hovered.name}
            </span>
            <span style={{
              fontSize: 9,
              fontWeight: 700,
              padding: '1px 6px',
              borderRadius: 4,
              background: `${MODEL_COLOR[hovered.model]}18`,
              color: MODEL_COLOR[hovered.model],
              textTransform: 'uppercase',
              letterSpacing: 0.5,
              fontFamily: 'JetBrains Mono, monospace',
            }}>
              {hovered.model}
            </span>
          </div>
          <div style={{ fontSize: 11, color: C.textSub, lineHeight: 1.4, marginBottom: 4 }}>
            {hovered.purpose}
          </div>
          <div style={{ fontSize: 10, color: C.brand, fontWeight: 600, letterSpacing: 0.3 }}>
            Click for recent decisions →
          </div>
        </div>
      )}

      {/* Detail modal — only mounted when open */}
      {openAgent && (
        <AgentDetailModal
          name={openAgent.name}
          slug={openAgent.slug}
          model={openAgent.model}
          color={MODEL_COLOR[openAgent.model]}
          purpose={openAgent.purpose}
          onClose={() => setOpenAgent(null)}
        />
      )}
    </div>
  );
}
