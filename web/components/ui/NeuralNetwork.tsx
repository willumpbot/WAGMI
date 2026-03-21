'use client';
import React, { useMemo } from 'react';
import { C, alpha } from '../../src/theme';

interface AgentNode {
  id: string;
  label: string;
  color: string;
  x: number;
  y: number;
}

interface NeuralNetworkProps {
  width?: number | string;
  height?: number;
  agentData?: Record<string, { accuracy?: number | null; total_decisions?: number }>;
}

const AGENTS: AgentNode[] = [
  { id: 'regime',   label: 'Regime',   color: '#06b6d4', x: 50, y: 10 },
  { id: 'scout',    label: 'Scout',    color: '#64748b', x: 15, y: 25 },
  { id: 'trade',    label: 'Trade',    color: '#6366f1', x: 50, y: 30 },
  { id: 'risk',     label: 'Risk',     color: '#f59e0b', x: 25, y: 50 },
  { id: 'critic',   label: 'Critic',   color: '#ec4899', x: 75, y: 50 },
  { id: 'overseer', label: 'Overseer', color: '#7c3aed', x: 85, y: 25 },
  { id: 'learning', label: 'Learning', color: '#10b981', x: 25, y: 75 },
  { id: 'exit',     label: 'Exit',     color: '#ef4444', x: 75, y: 75 },
  { id: 'quant',    label: 'Quant',    color: '#3b82f6', x: 50, y: 90 },
];

const CONNECTIONS: [string, string][] = [
  ['regime', 'trade'],
  ['regime', 'scout'],
  ['regime', 'overseer'],
  ['trade', 'risk'],
  ['trade', 'critic'],
  ['risk', 'critic'],
  ['critic', 'learning'],
  ['critic', 'exit'],
  ['learning', 'quant'],
  ['exit', 'quant'],
  ['scout', 'trade'],
  ['overseer', 'critic'],
];

export function NeuralNetwork({ width = '100%', height = 400, agentData }: NeuralNetworkProps) {
  const agentMap = useMemo(() => {
    const m: Record<string, AgentNode> = {};
    AGENTS.forEach(a => { m[a.id] = a; });
    return m;
  }, []);

  return (
    <div style={{ width, height, position: 'relative' }}>
      <svg viewBox="0 0 100 100" preserveAspectRatio="xMidYMid meet" style={{ width: '100%', height: '100%' }}>
        <defs>
          {AGENTS.map(a => (
            <radialGradient key={`grad-${a.id}`} id={`node-grad-${a.id}`}>
              <stop offset="0%" stopColor={a.color} stopOpacity="0.6" />
              <stop offset="70%" stopColor={a.color} stopOpacity="0.2" />
              <stop offset="100%" stopColor={a.color} stopOpacity="0" />
            </radialGradient>
          ))}
          <filter id="nn-glow">
            <feGaussianBlur stdDeviation="0.8" result="blur" />
            <feMerge>
              <feMergeNode in="blur" />
              <feMergeNode in="SourceGraphic" />
            </feMerge>
          </filter>
        </defs>

        {/* Connection lines */}
        {CONNECTIONS.map(([from, to], i) => {
          const a = agentMap[from];
          const b = agentMap[to];
          if (!a || !b) return null;
          return (
            <g key={`conn-${i}`}>
              <line
                x1={a.x} y1={a.y} x2={b.x} y2={b.y}
                stroke={C.border}
                strokeWidth="0.3"
                opacity="0.4"
              />
              {/* Animated pulse dot along path */}
              <circle r="0.6" fill={a.color} opacity="0.8" filter="url(#nn-glow)">
                <animateMotion
                  dur={`${2.5 + i * 0.3}s`}
                  repeatCount="indefinite"
                  path={`M${a.x},${a.y} L${b.x},${b.y}`}
                />
                <animate
                  attributeName="opacity"
                  values="0;0.8;0.8;0"
                  dur={`${2.5 + i * 0.3}s`}
                  repeatCount="indefinite"
                />
              </circle>
            </g>
          );
        })}

        {/* Agent nodes */}
        {AGENTS.map((a) => {
          const data = agentData?.[a.id];
          const accuracy = data?.accuracy;
          return (
            <g key={a.id}>
              {/* Outer glow halo */}
              <circle cx={a.x} cy={a.y} r="6" fill={`url(#node-grad-${a.id})`}>
                <animate
                  attributeName="r"
                  values="5.5;6.5;5.5"
                  dur="3s"
                  repeatCount="indefinite"
                />
              </circle>
              {/* Inner orb */}
              <circle
                cx={a.x} cy={a.y} r="3"
                fill={alpha(a.color, 0.15)}
                stroke={a.color}
                strokeWidth="0.4"
                filter="url(#nn-glow)"
              />
              {/* Core dot */}
              <circle cx={a.x} cy={a.y} r="1.2" fill={a.color} opacity="0.9" />
              {/* Label */}
              <text
                x={a.x}
                y={a.y + 8.5}
                textAnchor="middle"
                fill={C.textSub}
                fontSize="3"
                fontFamily="Inter, system-ui, sans-serif"
                fontWeight="600"
              >
                {a.label}
              </text>
              {/* Accuracy % if available */}
              {accuracy != null && (
                <text
                  x={a.x}
                  y={a.y + 11}
                  textAnchor="middle"
                  fill={C.muted}
                  fontSize="2.2"
                  fontFamily="'JetBrains Mono', monospace"
                >
                  {(accuracy * 100).toFixed(0)}%
                </text>
              )}
            </g>
          );
        })}
      </svg>
    </div>
  );
}

export default NeuralNetwork;
