// ─── LLM Types ────────────────────────────────────────────────────────────────

export type LlmDecision = {
  ts: number;
  ts_iso: string | null;
  symbol: string | null;
  action: string; // "proceed" | "flat" | "flip" | "unknown"
  original_action: string;
  confidence: number; // 0–1
  regime: string;
  notes: string;
  mode: string; // "ADVISORY" | "VETO_ONLY" | etc.
  trigger: string;
  trigger_context: string;
  is_veto: boolean;
  allowed: boolean;
  gate_reason: string;
  would_have_traded: boolean;
  model: string;
  size_multiplier: number | null;
};

export type LlmFeedResponse = {
  items: LlmDecision[];
  total: number;
  has_data: boolean;
};

export type LlmMarketView = {
  has_data: boolean;
  regime: string;
  overall_bias: string; // "bullish" | "neutral" | "volatile" | "mixed"
  avg_confidence: number | null;
  per_symbol: Record<string, LlmDecision>;
  last_updated: string | null;
  summary: string;
  decision_counts: {
    proceed: number;
    flat: number;
    flip: number;
    total_recent: number;
  };
};

// ─── Strategy Types ───────────────────────────────────────────────────────────

export type Strategy = {
  id: string;
  name?: string;
  lastHeartbeat?: string | null;
  lastTradeAt?: string | null;
  pnl_realized?: number | null;
  open_position?: {
    side?: string;
    size?: number;
    avg_entry?: number;
    unrealized_pnl?: number;
    unrealized_pnl_pct?: number;
    updated_at?: string;
  } | null;
};

// ─── Trade Types ──────────────────────────────────────────────────────────────

export type Trade = {
  id: string;
  ts: string;
  pair: string;
  side: string;
  qty: number;
  entry?: number;
  exit?: number;
  fee?: number;
  pnl?: number;
};

/** A row from bot/trades.csv */
export type TradeRecord = {
  symbol: string;
  side: string;
  strategy: string;
  close_reason: string;
  entry: number | null;
  exit: number | null;
  sl: number | null;
  tp1: number | null;
  tp2: number | null;
  pnl: number | null;
  fee: number | null;
  leverage: number | null;
  confidence: number | null;
  rr_achieved: number | null;
  duration_h: number | null;
  outcome: string; // "WIN" | "LOSS"
  llm_action: string | null;
  llm_regime: string | null;
  llm_confidence: number | null;
};

export type TradeHistoryResponse = {
  trades: TradeRecord[];
  total: number;
  has_data: boolean;
};

export type EquityCurvePoint = {
  ts: string;
  equity: number;
  drawdown_pct: number;
};

export type EquityCurveResponse = {
  points: EquityCurvePoint[];
  has_data: boolean;
  run: string;
  file?: string;
};

// ─── Backtest Types ───────────────────────────────────────────────────────────

export type BacktestBySymbol = {
  trades: number;
  wins: number;
  pnl: number;
  win_rate: number;
};

export type BacktestResult = {
  config: {
    symbols: string[];
    days: number;
    starting_equity: number;
    risk_per_trade: number;
    ensemble_mode: string;
    leverage_enabled: boolean;
    trailing_stop_enabled: boolean;
  };
  results: {
    final_equity: number;
    total_return_pct: number;
    max_drawdown_pct: number;
    total_signals: number;
    positions_opened: number;
    total_trades: number;
    wins: number;
    losses: number;
    win_rate: number;
    total_pnl: number;
    gross_pnl: number;
    total_fees: number;
    net_pnl: number;
    profit_factor: number;
    avg_win: number;
    avg_loss: number;
    by_action?: Record<string, number>;
  };
  by_strategy?: Record<string, { trades: number; wins: number; pnl: number; win_rate: number }>;
  by_symbol?: Record<string, BacktestBySymbol>;
  trades?: Array<{ symbol: string; side: string; entry: number; exit: number; pnl: number; pnl_pct: number; duration_bars: number; strategy: string; outcome?: string; duration_h?: number | null }>;
};

export type BacktestRunMeta = {
  id: string;
  file: string;
  created_at: string;
  size_bytes: number;
  symbols: string[];
  days: number | null;
  total_return_pct: number | null;
  win_rate: number | null;
  total_trades: number | null;
  net_pnl: number | null;
  max_drawdown_pct: number | null;
  profit_factor: number | null;
};

export type BacktestListResponse = {
  results: BacktestRunMeta[];
  count: number;
};

export type BacktestJob = {
  job_id: string;
  status: 'pending' | 'running' | 'done' | 'error';
  symbols: string;
  days: number;
  result_file: string;
  result_id: string;
  started_at: string;
  finished_at: string | null;
  error: string | null;
  log_tail: string[];
  result_summary?: {
    total_return_pct: number | null;
    win_rate: number | null;
    total_trades: number | null;
    net_pnl: number | null;
  };
};

// ─── Activity Types ───────────────────────────────────────────────────────────

export type ActivityEvent = {
  ts: number;
  ts_iso: string | null;
  event_type: string;
  symbol: string | null;
  title: string;
  detail: string;
  scalp_insight: string;
  badge: string;
  badge_color: string;
  data: Record<string, unknown>;
};

export type ActivityFeedResponse = {
  items: ActivityEvent[];
  has_data: boolean;
  sources: { decisions: number; missed_trades: number };
};
