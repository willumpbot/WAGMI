import React, { useEffect, useState, useRef } from 'react';

// ─── Types ───────────────────────────────────────────────────────────────────

type Signal = {
  symbol: string;
  label: string;
  score: number;
  price: number;
  sma20: number;
  sma50: number;
  atr14: number;
  atr_pct?: number;
  rsi14?: number;
  vol_spike?: boolean;
  zones: {
    deepAccum: number;
    accum: number;
    distrib: number;
    safeDistrib: number;
  };
};

type SignalsPayload = {
  last_updated?: string;
  regime?: string;
  signals?: Record<string, Signal>;
};

// ─── Helpers ─────────────────────────────────────────────────────────────────

function resolveApiBase(): string {
  const envVal =
    (process.env.NEXT_PUBLIC_API_URL as string | undefined) ||
    (process.env.NEXT_PUBLIC_API_BASE_URL as string | undefined);
  if (envVal && envVal.trim().length > 0) return envVal;
  if (typeof window !== 'undefined') {
    const host = window.location.hostname;
    if (host && host !== 'localhost' && host !== '127.0.0.1') {
      return 'https://nunuirl-platform.onrender.com';
    }
  }
  return 'http://localhost:8000';
}

const fmt = new Intl.NumberFormat('en-US', {
  style: 'currency',
  currency: 'USD',
  maximumFractionDigits: 4,
});

// Map our symbol names to TradingView symbol IDs
const TV_SYMBOLS: Record<string, string> = {
  BTC: 'BINANCE:BTCUSDT',
  SOL: 'BINANCE:SOLUSDT',
  HYPE: 'BYBIT:HYPEUSDT',
};

// ─── Signal Strength ─────────────────────────────────────────────────────────

function getSignalStrength(signal: Signal): {
  direction: string;
  color: string;
  bgColor: string;
  strength: string;
  emoji: string;
} {
  const label = signal.label || '';
  const score = signal.score || 0;

  if (label.includes('Aggressive Accumulation')) {
    return { direction: 'BULLISH', color: '#16a34a', bgColor: '#dcfce7', strength: 'Strong', emoji: '' };
  }
  if (label.includes('Accumulation')) {
    return { direction: 'LEANING BULLISH', color: '#65a30d', bgColor: '#ecfccb', strength: 'Moderate', emoji: '' };
  }
  if (label.includes('Aggressive Distribution')) {
    return { direction: 'BEARISH', color: '#dc2626', bgColor: '#fee2e2', strength: 'Strong', emoji: '' };
  }
  if (label.includes('Distribution')) {
    return { direction: 'LEANING BEARISH', color: '#ea580c', bgColor: '#fff7ed', strength: 'Moderate', emoji: '' };
  }
  return { direction: 'NEUTRAL', color: '#6b7280', bgColor: '#f3f4f6', strength: 'Weak', emoji: '' };
}

// ─── TradingView Chart ───────────────────────────────────────────────────────

function TradingViewChart({ symbol }: { symbol: string }) {
  const containerRef = useRef<HTMLDivElement>(null);
  const tvSymbol = TV_SYMBOLS[symbol] || `BINANCE:${symbol}USDT`;

  useEffect(() => {
    if (!containerRef.current) return;
    // Clear previous widget
    containerRef.current.innerHTML = '';

    const script = document.createElement('script');
    script.src = 'https://s3.tradingview.com/external-embedding/embed-widget-advanced-chart.js';
    script.async = true;
    script.innerHTML = JSON.stringify({
      autosize: true,
      symbol: tvSymbol,
      interval: '60',
      timezone: 'Etc/UTC',
      theme: 'light',
      style: '1',
      locale: 'en',
      hide_top_toolbar: false,
      hide_legend: false,
      allow_symbol_change: false,
      save_image: false,
      hide_volume: false,
      support_host: 'https://www.tradingview.com',
    });
    containerRef.current.appendChild(script);
  }, [tvSymbol]);

  return (
    <div className="tradingview-widget-container" ref={containerRef} style={{ height: 400, width: '100%' }} />
  );
}

// ─── Copy Trade Card ─────────────────────────────────────────────────────────

function CopyTradeCard({ signal }: { signal: Signal }) {
  const info = getSignalStrength(signal);
  const trendUp = signal.sma20 > signal.sma50;
  const rsiVal = signal.rsi14 ?? 50;
  const isOverbought = rsiVal > 70;
  const isOversold = rsiVal < 30;

  return (
    <div
      style={{
        border: '1px solid #e5e7eb',
        borderRadius: 12,
        background: '#fff',
        marginBottom: 32,
        overflow: 'hidden',
      }}
    >
      {/* Header */}
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          padding: '16px 20px',
          borderBottom: '1px solid #e5e7eb',
          background: '#fafafa',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <span style={{ fontSize: 24, fontWeight: 700 }}>{signal.symbol}</span>
          <span style={{ fontSize: 18, color: '#666' }}>{fmt.format(signal.price)}</span>
        </div>
        <div
          style={{
            padding: '6px 16px',
            borderRadius: 20,
            background: info.bgColor,
            color: info.color,
            fontWeight: 700,
            fontSize: 14,
          }}
        >
          {info.emoji} {info.direction}
        </div>
      </div>

      {/* Signal Summary - the "at a glance" section */}
      <div style={{ padding: '16px 20px', borderBottom: '1px solid #f0f0f0' }}>
        <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 12, color: '#374151', textTransform: 'uppercase', letterSpacing: 0.5 }}>
          What the Bot Sees
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: 12 }}>
          {/* Signal Score */}
          <div style={{ padding: 12, background: '#f9fafb', borderRadius: 8 }}>
            <div style={{ fontSize: 11, color: '#6b7280', marginBottom: 4 }}>Signal Score</div>
            <div style={{ fontSize: 24, fontWeight: 700, color: signal.score >= 60 ? '#16a34a' : signal.score >= 40 ? '#eab308' : '#dc2626' }}>
              {signal.score}/100
            </div>
            <div style={{ fontSize: 11, color: '#9ca3af' }}>
              {signal.score >= 70 ? 'Strong signal' : signal.score >= 50 ? 'Moderate signal' : 'Weak signal'}
            </div>
          </div>

          {/* Trend */}
          <div style={{ padding: 12, background: '#f9fafb', borderRadius: 8 }}>
            <div style={{ fontSize: 11, color: '#6b7280', marginBottom: 4 }}>Trend (SMA 20/50)</div>
            <div style={{ fontSize: 18, fontWeight: 700, color: trendUp ? '#16a34a' : '#dc2626' }}>
              {trendUp ? 'Uptrend' : 'Downtrend'}
            </div>
            <div style={{ fontSize: 11, color: '#9ca3af' }}>
              20: {fmt.format(signal.sma20)} / 50: {fmt.format(signal.sma50)}
            </div>
          </div>

          {/* RSI */}
          <div style={{ padding: 12, background: '#f9fafb', borderRadius: 8 }}>
            <div style={{ fontSize: 11, color: '#6b7280', marginBottom: 4 }}>RSI (14)</div>
            <div style={{ fontSize: 18, fontWeight: 700, color: isOverbought ? '#dc2626' : isOversold ? '#16a34a' : '#374151' }}>
              {rsiVal.toFixed(1)}
            </div>
            <div style={{ fontSize: 11, color: '#9ca3af' }}>
              {isOverbought ? 'Overbought - caution' : isOversold ? 'Oversold - potential bounce' : 'Normal range'}
            </div>
          </div>

          {/* Volatility */}
          <div style={{ padding: 12, background: '#f9fafb', borderRadius: 8 }}>
            <div style={{ fontSize: 11, color: '#6b7280', marginBottom: 4 }}>Volatility (ATR)</div>
            <div style={{ fontSize: 18, fontWeight: 700 }}>
              {typeof signal.atr_pct === 'number' ? signal.atr_pct.toFixed(2) + '%' : fmt.format(signal.atr14)}
            </div>
            <div style={{ fontSize: 11, color: '#9ca3af' }}>
              {signal.vol_spike ? 'Volume spike detected!' : 'Normal volume'}
            </div>
          </div>
        </div>
      </div>

      {/* Key Price Levels */}
      <div style={{ padding: '16px 20px', borderBottom: '1px solid #f0f0f0' }}>
        <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 12, color: '#374151', textTransform: 'uppercase', letterSpacing: 0.5 }}>
          Key Price Levels
        </div>
        <div style={{ fontSize: 13, color: '#374151', marginBottom: 8 }}>
          These zones show where the bot considers price to be cheap (accumulation) or expensive (distribution) based on volatility analysis.
        </div>

        {/* Visual price ladder */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6, maxWidth: 500 }}>
          <PriceLevel label="Safe Distribution (very expensive)" price={signal.zones.safeDistrib} color="#dc2626" currentPrice={signal.price} />
          <PriceLevel label="Distribution (expensive)" price={signal.zones.distrib} color="#ea580c" currentPrice={signal.price} />
          <div style={{ padding: '8px 12px', background: '#dbeafe', borderRadius: 6, fontWeight: 600, fontSize: 13 }}>
            Current Price: {fmt.format(signal.price)}
          </div>
          <PriceLevel label="Accumulation (cheap)" price={signal.zones.accum} color="#65a30d" currentPrice={signal.price} />
          <PriceLevel label="Deep Accumulation (very cheap)" price={signal.zones.deepAccum} color="#16a34a" currentPrice={signal.price} />
        </div>
      </div>

      {/* Chart */}
      <div style={{ padding: '16px 20px', borderBottom: '1px solid #f0f0f0' }}>
        <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 12, color: '#374151', textTransform: 'uppercase', letterSpacing: 0.5 }}>
          1H Chart
        </div>
        <TradingViewChart symbol={signal.symbol} />
      </div>

      {/* How to Trade This */}
      <div style={{ padding: '16px 20px' }}>
        <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 12, color: '#374151', textTransform: 'uppercase', letterSpacing: 0.5 }}>
          How to Trade This (Manual)
        </div>
        <HowToTrade signal={signal} info={info} />
      </div>
    </div>
  );
}

// ─── Price Level Row ─────────────────────────────────────────────────────────

function PriceLevel({ label, price, color, currentPrice }: { label: string; price: number; color: string; currentPrice: number }) {
  const diff = ((price - currentPrice) / currentPrice) * 100;
  return (
    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '6px 12px', background: '#f9fafb', borderRadius: 6, borderLeft: `3px solid ${color}` }}>
      <span style={{ fontSize: 12, color: '#6b7280' }}>{label}</span>
      <div style={{ textAlign: 'right' }}>
        <span style={{ fontSize: 13, fontWeight: 600 }}>{fmt.format(price)}</span>
        <span style={{ fontSize: 11, color: diff > 0 ? '#16a34a' : '#dc2626', marginLeft: 6 }}>
          ({diff > 0 ? '+' : ''}{diff.toFixed(1)}%)
        </span>
      </div>
    </div>
  );
}

// ─── How to Trade Instructions ───────────────────────────────────────────────

function HowToTrade({ signal, info }: { signal: Signal; info: ReturnType<typeof getSignalStrength> }) {
  const isBullish = info.direction.includes('BULLISH');
  const isBearish = info.direction.includes('BEARISH');
  const isNeutral = info.direction === 'NEUTRAL';

  if (isNeutral) {
    return (
      <div style={{ padding: 16, background: '#f3f4f6', borderRadius: 8, fontSize: 14, color: '#6b7280' }}>
        <strong>No clear signal right now.</strong> The bot sees mixed indicators. Best to wait for a stronger setup.
        Check back in a few minutes — signals update every 60 seconds.
      </div>
    );
  }

  const direction = isBullish ? 'Long (Buy)' : 'Short (Sell)';
  const slZone = isBullish ? signal.zones.deepAccum : signal.zones.safeDistrib;
  const tpZone = isBullish ? signal.zones.distrib : signal.zones.accum;

  return (
    <div>
      <div
        style={{
          padding: 16,
          background: info.bgColor,
          borderRadius: 8,
          marginBottom: 12,
          border: `1px solid ${info.color}20`,
        }}
      >
        <div style={{ fontSize: 16, fontWeight: 700, color: info.color, marginBottom: 4 }}>
          Signal: {direction}
        </div>
        <div style={{ fontSize: 13, color: '#374151' }}>
          Strength: {info.strength} ({signal.score}/100)
        </div>
      </div>

      <div style={{ fontSize: 14, lineHeight: 1.8 }}>
        <div style={{ fontWeight: 600, marginBottom: 8 }}>Steps on Hyperliquid:</div>
        <ol style={{ paddingLeft: 20, margin: 0 }}>
          <li style={{ marginBottom: 8 }}>
            Go to <strong>app.hyperliquid.xyz</strong> and open <strong>{signal.symbol}-USD</strong>
          </li>
          <li style={{ marginBottom: 8 }}>
            Select <strong>{isBullish ? 'Long' : 'Short'}</strong> and choose your leverage
            <div style={{ fontSize: 12, color: '#6b7280', marginTop: 2 }}>
              Recommended: 2-5x for beginners, never more than 10x
            </div>
          </li>
          <li style={{ marginBottom: 8 }}>
            Set your entry near <strong>{fmt.format(signal.price)}</strong> (current price)
          </li>
          <li style={{ marginBottom: 8 }}>
            Set a <strong>Stop Loss</strong> near <strong>{fmt.format(slZone)}</strong>
            <div style={{ fontSize: 12, color: '#6b7280', marginTop: 2 }}>
              This is the {isBullish ? 'Deep Accumulation' : 'Safe Distribution'} zone — if price reaches here, the trade idea is invalid
            </div>
          </li>
          <li style={{ marginBottom: 8 }}>
            Set a <strong>Take Profit</strong> near <strong>{fmt.format(tpZone)}</strong>
            <div style={{ fontSize: 12, color: '#6b7280', marginTop: 2 }}>
              This is the {isBullish ? 'Distribution' : 'Accumulation'} zone — where the bot expects price resistance/support
            </div>
          </li>
          <li>
            <strong>Only risk what you can afford to lose.</strong> Start small.
          </li>
        </ol>
      </div>

      {/* Risk warning */}
      <div
        style={{
          marginTop: 16,
          padding: 12,
          background: '#fef3c7',
          borderRadius: 8,
          border: '1px solid #fbbf24',
          fontSize: 12,
          color: '#92400e',
        }}
      >
        <strong>Risk Warning:</strong> This is not financial advice. The bot is showing what it sees in the data —
        you make your own decision. Always use a stop loss. Never risk more than 1-2% of your account on a single trade.
        Past signals do not guarantee future results.
      </div>
    </div>
  );
}

// ─── Main Page ───────────────────────────────────────────────────────────────

export default function CopyTrade() {
  const [data, setData] = useState<SignalsPayload>({});
  const [loading, setLoading] = useState(true);
  const apiBase = resolveApiBase();

  useEffect(() => {
    const fetcher = async () => {
      try {
        const res = await fetch(`${apiBase}/v1/signals`);
        if (res.ok) {
          const json = await res.json();
          setData(json);
        }
      } catch (e) {
        console.error('Signals fetch error:', e);
      }
      setLoading(false);
    };

    fetcher();
    const interval = setInterval(fetcher, 30000);
    return () => clearInterval(interval);
  }, [apiBase]);

  const signals = data.signals || {};
  const symbolOrder = ['BTC', 'SOL', 'HYPE'];
  const orderedSignals = symbolOrder
    .map((sym) => signals[sym])
    .filter(Boolean);

  return (
    <div>
      {/* Page Header */}
      <div style={{ marginBottom: 24 }}>
        <h1 style={{ fontSize: 28, fontWeight: 700, marginBottom: 8 }}>Copy Trade</h1>
        <p style={{ fontSize: 15, color: '#6b7280', margin: 0, maxWidth: 700 }}>
          See what the bot sees, then decide for yourself. Each card below shows a symbol&apos;s current
          signal, key price levels, and step-by-step instructions for placing a trade on Hyperliquid.
        </p>
        {data.last_updated && (
          <div style={{ fontSize: 12, color: '#9ca3af', marginTop: 8 }}>
            Last updated: {new Date(data.last_updated).toLocaleString()} | Regime: {data.regime || 'Neutral'}
          </div>
        )}
      </div>

      {/* Quick Guide */}
      <div
        style={{
          background: '#eff6ff',
          border: '1px solid #bfdbfe',
          borderRadius: 10,
          padding: 20,
          marginBottom: 28,
        }}
      >
        <div style={{ fontSize: 15, fontWeight: 600, marginBottom: 10, color: '#1e40af' }}>
          How This Works
        </div>
        <div style={{ fontSize: 14, color: '#1e3a5f', lineHeight: 1.7 }}>
          <div style={{ marginBottom: 6 }}>
            <strong>1.</strong> The bot scans BTC, SOL, and HYPE every 60 seconds using 9 different strategies.
          </div>
          <div style={{ marginBottom: 6 }}>
            <strong>2.</strong> Each card below shows the bot&apos;s analysis: direction, strength, key levels.
          </div>
          <div style={{ marginBottom: 6 }}>
            <strong>3.</strong> Use the chart and levels to form your own view, then follow the steps to place a trade.
          </div>
          <div>
            <strong>4.</strong> Always use a stop loss. Start with small size. This is a tool, not a guarantee.
          </div>
        </div>
      </div>

      {/* Signal Cards */}
      {loading ? (
        <div style={{ padding: 40, textAlign: 'center', color: '#6b7280' }}>Loading signals...</div>
      ) : orderedSignals.length === 0 ? (
        <div style={{ padding: 40, textAlign: 'center', color: '#6b7280' }}>
          No signals available yet. The bot needs ~60 seconds to generate the first scan.
        </div>
      ) : (
        orderedSignals.map((signal) => <CopyTradeCard key={signal.symbol} signal={signal} />)
      )}

      {/* If some symbols are missing, show placeholder cards */}
      {!loading &&
        symbolOrder
          .filter((sym) => !signals[sym])
          .map((sym) => (
            <div
              key={sym}
              style={{
                border: '1px solid #e5e7eb',
                borderRadius: 12,
                background: '#fff',
                padding: 32,
                marginBottom: 32,
                textAlign: 'center',
              }}
            >
              <div style={{ fontSize: 24, fontWeight: 700, marginBottom: 8 }}>{sym}</div>
              <div style={{ color: '#9ca3af', marginBottom: 16 }}>Waiting for signal data...</div>
              <TradingViewChart symbol={sym} />
            </div>
          ))}

      {/* Footer */}
      <div
        style={{
          fontSize: 11,
          color: '#9ca3af',
          padding: '20px 0',
          borderTop: '1px solid #e5e7eb',
          textAlign: 'center',
          lineHeight: 1.6,
        }}
      >
        <strong>Disclaimer:</strong> This is not financial advice. All trading involves risk.
        The signals shown are generated by an automated bot and are for informational purposes only.
        You are solely responsible for your own trading decisions. Never invest more than you can afford to lose.
      </div>
    </div>
  );
}
