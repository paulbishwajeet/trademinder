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
