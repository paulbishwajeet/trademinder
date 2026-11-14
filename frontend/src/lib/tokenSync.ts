// frontend/src/lib/tokenSync.ts
// Token follower (dev) display helpers. The status carries only pull times and outcome codes, never tokens.
import type { MarketDataStatus, PullOutcome } from '../api/marketData'

export const PULL_OUTCOME_LABEL: Record<PullOutcome, string> = {
  ok: 'OK',
  unreachable: 'production unreachable',
  upstream_offline: 'production is offline — reconnect in production',
  unauthorized: 'secret rejected by production',
  disabled: 'token sync not enabled on production',
  invalid_response: 'unusable response from production',
}

export function isFollower(status: MarketDataStatus | null): boolean {
  return status?.token_source === 'production'
}

/** "Tokens from production · last pull 11/13/2026, 3:05 PM (OK)" for the banner and Settings → Market data. */
export function lastPullText(status: MarketDataStatus): string {
  if (!status.last_pull_at) return 'Tokens from production · not pulled yet'
  const outcome = status.last_pull_outcome ? ` (${PULL_OUTCOME_LABEL[status.last_pull_outcome]})` : ''
  return `Tokens from production · last pull ${new Date(status.last_pull_at).toLocaleString()}${outcome}`
}
