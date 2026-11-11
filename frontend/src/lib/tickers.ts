// frontend/src/lib/tickers.ts
// Share classes that trade interchangeably. Mirrors TICKER_ALIASES in backend/app/routers/wheel.py and
// extension/content.js — keep the three in step.
const TICKER_ALIASES: Record<string, string> = { GOOG: 'GOOGL', GOOGL: 'GOOG' }

/** The symbol plus its alias, uppercased: every ticker that should count as a match for `symbol`. */
export function matchSymbols(symbol: string): Set<string> {
  const s = symbol.trim().toUpperCase()
  const alias = TICKER_ALIASES[s]
  return new Set(alias ? [s, alias] : [s])
}
