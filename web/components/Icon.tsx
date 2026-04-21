import React from 'react';

type IconName =
  | 'brain'
  | 'chart'
  | 'shield'
  | 'telegram'
  | 'pulse'
  | 'arrow-right'
  | 'zap'
  | 'target'
  | 'book'
  | 'search';

type Props = {
  name: IconName;
  size?: number;
  color?: string;
  strokeWidth?: number;
  style?: React.CSSProperties;
  className?: string;
};

/**
 * Crafted SVG icon set for WAGMI. Stroke-based, theme-aware, 24x24 viewBox.
 * Uses `currentColor` so color comes from CSS/style. No emoji fallbacks.
 */
export default function Icon({ name, size = 24, color, strokeWidth = 1.8, style, className }: Props) {
  const common = {
    width: size,
    height: size,
    viewBox: '0 0 24 24',
    fill: 'none',
    stroke: color || 'currentColor',
    strokeWidth,
    strokeLinecap: 'round' as const,
    strokeLinejoin: 'round' as const,
    className,
    style,
    'aria-hidden': true,
  };

  switch (name) {
    case 'brain':
      return (
        <svg {...common}>
          <path d="M8 3c-1.5 0-3 1.2-3 3 0 .5.1 1 .3 1.4C4 8 3 9.5 3 11c0 1.2.5 2.3 1.4 3.1-.3.6-.4 1.2-.4 1.9 0 2 1.6 3.5 3.5 3.5.5 0 1-.1 1.5-.3V7V3Z" />
          <path d="M16 3c1.5 0 3 1.2 3 3 0 .5-.1 1-.3 1.4 1.3.6 2.3 2.1 2.3 3.6 0 1.2-.5 2.3-1.4 3.1.3.6.4 1.2.4 1.9 0 2-1.6 3.5-3.5 3.5-.5 0-1-.1-1.5-.3V7V3Z" />
          <path d="M12 6v12" opacity="0.5" />
          <circle cx="7.5" cy="9.5" r="0.8" fill={color || 'currentColor'} />
          <circle cx="16.5" cy="12" r="0.8" fill={color || 'currentColor'} />
          <circle cx="9" cy="15" r="0.8" fill={color || 'currentColor'} />
        </svg>
      );
    case 'chart':
      return (
        <svg {...common}>
          <path d="M3 3v18h18" />
          <path d="M7 15l4-4 3 3 5-6" />
          <circle cx="7" cy="15" r="1.5" fill={color || 'currentColor'} />
          <circle cx="11" cy="11" r="1.5" fill={color || 'currentColor'} />
          <circle cx="14" cy="14" r="1.5" fill={color || 'currentColor'} />
          <circle cx="19" cy="8" r="1.5" fill={color || 'currentColor'} />
        </svg>
      );
    case 'shield':
      return (
        <svg {...common}>
          <path d="M12 2 4 5v6c0 5 3.5 9.5 8 11 4.5-1.5 8-6 8-11V5l-8-3Z" />
          <path d="M9 12l2 2 4-4" />
        </svg>
      );
    case 'telegram':
      return (
        <svg {...common}>
          <path d="M21.5 3.5 2.5 10.5c-.5.2-.5 1 0 1.2L7 13l2 6c.2.5 1 .5 1.2 0l2.2-3.2 4.8 3.7c.6.5 1.4.2 1.6-.5L22.5 4.5c.2-.7-.5-1.3-1-1Z" />
          <path d="M7 13l10-7" />
        </svg>
      );
    case 'pulse':
      return (
        <svg {...common}>
          <path d="M3 12h3l3-9 4 18 3-9h5" />
        </svg>
      );
    case 'arrow-right':
      return (
        <svg {...common}>
          <path d="M5 12h14M13 6l6 6-6 6" />
        </svg>
      );
    case 'zap':
      return (
        <svg {...common}>
          <path d="M13 2 3 14h8l-1 8 10-12h-8l1-8Z" />
        </svg>
      );
    case 'target':
      return (
        <svg {...common}>
          <circle cx="12" cy="12" r="10" />
          <circle cx="12" cy="12" r="6" />
          <circle cx="12" cy="12" r="2" fill={color || 'currentColor'} />
        </svg>
      );
    case 'book':
      return (
        <svg {...common}>
          <path d="M4 4h12a3 3 0 0 1 3 3v13H7a3 3 0 0 1-3-3V4Z" />
          <path d="M4 17a3 3 0 0 1 3-3h12" />
          <path d="M8 8h7M8 11h5" opacity="0.6" />
        </svg>
      );
    case 'search':
      return (
        <svg {...common}>
          <circle cx="11" cy="11" r="7" />
          <path d="m21 21-4.3-4.3" />
        </svg>
      );
    default:
      return null;
  }
}
