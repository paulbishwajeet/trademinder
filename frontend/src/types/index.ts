// frontend/src/types/index.ts
export interface Rationale {
  id: string
  trade_id: string
  macd_signal: string | null
  macd_notes: string | null
  rsi_14: number | null
  rsi_result: string | null
  ma_200d: number | null
  ma_50d: number | null
  price_vs_ma200: string | null
  price_vs_ma50: string | null
  bollinger_upper: number | null
  bollinger_mid: number | null
  bollinger_lower: number | null
  bollinger_position: string | null
  day_color: string | null
  price_action: string | null
  sentiment: string | null
  next_earnings_date: string | null
  fetch_status: string
  fetch_error: string | null
  notes: string | null
  created_at: string
}

export interface TechnicalsData {
  macd_signal: string | null
  macd_notes: string | null
  rsi_14: number | null
  rsi_result: string | null
  ma_200d: number | null
  ma_50d: number | null
  price_vs_ma200: string | null
  price_vs_ma50: string | null
  bollinger_upper: number | null
  bollinger_mid: number | null
  bollinger_lower: number | null
  bollinger_position: string | null
  day_color: string | null
  price_action: string | null
  sentiment: string | null
  next_earnings_date: string | null
  fetch_status: string
  fetch_error: string | null
  notes: string | null
}

export interface Trade {
  id: string
  wheel_id: string | null
  session_id: string | null
  type: string
  category: string
  strategy: string
  ticker: string
  open_date: string
  expiry_date: string | null
  closed_date: string | null
  strike_price: number | null
  quantity: number
  premium: number | null
  collateral: number | null
  exit_strategy: string | null
  signal_action: string | null
  status: string
  current_price: number | null
  unrealized_pnl: number | null
  last_price_at: string | null
  created_at: string
  updated_at: string
  last_etrade_seen: string | null
  rationale?: Rationale | null
}

export interface TradeCreate {
  wheel_id?: string | null
  type: string
  category: string
  strategy: string
  ticker: string
  open_date: string
  expiry_date?: string | null
  strike_price?: number | null
  quantity: number
  premium?: number | null
  collateral?: number | null
  exit_strategy?: string | null
  signal_action?: string | null
  rationale_notes?: string | null
}

export interface TradeUpdate {
  type?: string
  category?: string
  strategy?: string
  strike_price?: number | null
  expiry_date?: string | null
  quantity?: number
  premium?: number | null
  collateral?: number | null
  status?: 'open' | 'closed' | 'expired' | 'assigned'
  closed_date?: string | null
  exit_strategy?: string | null
  rationale_notes?: string | null
  signal_action?: string | null
  session_id?: string | null
}

export interface Commentary {
  id: string
  trade_id: string
  entry_date: string
  note: string
  tags: string[] | null
  created_at: string
  rationale: Rationale | null
}

export interface Alert {
  id: string
  trade_id: string
  alert_type: string
  severity: string
  title: string
  message: string
  is_read: boolean
  is_dismissed: boolean
  triggered_at: string
  dismissed_at: string | null
}

export interface SessionSummary {
  id: string
  ticker: string
  strategy: string
  status: string
  rotation_number: number
  opened_at: string
  closed_at: string | null
  parent_session_id: string | null
}

export interface SessionLeg {
  id: string
  type: string
  strategy: string
  ticker: string
  open_date: string
  expiry_date: string | null
  strike_price: number | null
  quantity: number
  premium: number | null
  status: string
}

export interface SessionWithLegs extends SessionSummary {
  legs: SessionLeg[]
  rotation_chain: SessionSummary[]
}

export interface SessionLookupResponse {
  ticker: string
  strategy: string | null
  has_existing: boolean
  sessions: SessionSummary[]
}

// ── Wheel v2 types ──────────────────────────────────────────────

export interface WheelSessionSummary {
  id: string
  ticker: string
  total_shares: number
  status: string
  opened_at: string
  closed_at: string | null
}

export interface WheelSlotLegItem {
  id: string
  slot_id: string
  trade_id: string
  leg_role: string
  rotation_number: number
  trade_type: string | null
  trade_strategy: string | null
  trade_ticker: string | null
  trade_open_date: string | null
  trade_expiry_date: string | null
  trade_strike_price: number | null
  trade_quantity: number | null
  trade_premium: number | null
  trade_status: string | null
  trade_etrade_symbol: string | null
}

export interface WheelPremiumLogItem {
  id: string
  slot_id: string
  leg_id: string | null
  rotation_number: number
  premium_amount: string
  event_type: string
  event_date: string
  notes: string | null
  created_at: string
}

export interface WheelSlotDetail {
  id: string
  session_id: string
  slot_number: number
  contracts: number
  shares_held: number
  status: string
  needs_action: boolean
  rotation_number: number
  legs: WheelSlotLegItem[]
  premium_logs: WheelPremiumLogItem[]
  total_premium: string
}

export interface WheelSessionDetail extends WheelSessionSummary {
  slots: WheelSlotDetail[]
  total_premium: string
}

export interface WheelActiveSlot {
  id: string
  session_id: string
  slot_number: number
  contracts: number
  shares_held: number
  status: string
  needs_action: boolean
  rotation_number: number
  ticker: string
  etrade_symbols: string[]
}

// ── CC Sell Signal types ────────────────────────────────────────

export interface CCSignalFactor {
  name: string
  points: number
  max: number
  detail: string
}

export interface CCSignalResult {
  ticker: string
  score: number
  grade: string
  iv_percentile: number | null
  atm_iv: number | null
  spot_price: number | null
  factors: CCSignalFactor[]
  commentary: string | null
  strike_hint: string | null
  caution: string | null
  cached_at: string
  fetch_status: string
  fetch_error: string | null
}

export function isStale(trade: Trade): boolean {
  if (!trade.last_etrade_seen) return false
  return new Date(trade.last_etrade_seen) < new Date(Date.now() - 24 * 60 * 60 * 1000)
}
