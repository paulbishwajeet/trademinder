// content.js — TradeMinder Stage 1: Category Indicators
// Handles E*TRADE's div-based virtual scroll grid

'use strict';

// ============================================================
// ETRADE SELECTOR CONSTANTS — confirmed from live DOM
// ============================================================
const ETRADE = {
  gridRoot: '#rdt_3',
  contentArea: '.Content---root---D2Ylg',
  positionRows: '[role="row"][level="0"]:not(.Row---placeholderRow---2t5Gs)',
  placeholderRow: '.Row---placeholderRow---2t5Gs',
  footerRow: '.Footer---row---g5JDN',
  symbolContent: '.SymbolCellRenderer---content---mcwCT',
  symbolLink: 'a.SymbolCellRenderer---symbol---_S70m',
  optionClass: 'SymbolCellRenderer---option---qIlje',
  itmClass: 'SymbolCellRenderer---in-the-money---AQRUo',
  optionDesc: 'span.SymbolCellRenderer---description---KHPND',
  headerRow: '[data-header="true"] [role="row"]',
};

// ============================================================
// STATE
// ============================================================
let tmApiUrl = 'http://localhost:5431';
let stageEnabled = { stage1: true, stage2: true, stage3: true, stage4: true };

// rowId → cacheKey (ticker or fullSymbol): prevents re-processing unchanged rows
const processedRows = new Map();
// cacheKey → PositionStatus: avoids re-fetching same data
const statusCache = new Map();
// ticker → RSI-14 value (null = fetch failed)
const rsiCache = new Map();
// trade_id → commentary count (populated on first badge render)
const commentaryCountCache = new Map();
// etrade_symbol (uppercase) → session object (active WHEEL/IC/PBWB session owning that leg)
let etradeSymbolIndex = new Map();
// all sessions returned by /api/sessions/active (used for spread price lookups)
let allActiveSessions = [];
// timestamp (ms) when /api/sessions/active was last fetched; 0 = never
let activeSessionsFetchedAt = 0;
const ACTIVE_SESSIONS_TTL = 60_000; // re-fetch every 60 seconds
// ── Ticker aliases (share classes that trade interchangeably) ──
const TICKER_ALIASES = { GOOG: 'GOOGL', GOOGL: 'GOOG' };
function tickerVariants(ticker) {
  const t = ticker.toUpperCase();
  const alias = TICKER_ALIASES[t];
  return alias ? [t, alias] : [t];
}

// ── Wheel v2 slot data ──
let wheelActiveSlots = [];
let wheelSlotsFetchedAt = 0;
const WHEEL_SLOTS_TTL = 60_000;
// ticker (uppercase) → current price (number) | null (spread session price signal)
const priceCache = new Map();
// full_symbol||ticker (uppercase) → true: position is in E*TRADE but not backend
const reconcileCache = new Map();
// all base tickers seen while processing rows (for batch RSI fetch)
const seenTickers = new Set();
let isProcessing = false;
let allCategories = [];
let activeFilter = 'all';
let _panelClickOutside = null;
let _panelEsc = null;
let _threadAbortCtrl = null;
let _hoverTrigger = null;
let _hoverHideTimer = null;
let _hoverTradeId = null;
let _hoverTicker = null;
let _hoverRow = null;
let _hoverPill = null;

// column name → cell index, built once from the header row
let columnIndexCache = null;

// ============================================================
// BACKGROUND FETCH PROXY
// Chrome's Private Network Access policy blocks content scripts
// (which run under the E*TRADE origin) from fetching localhost.
// Route all API calls through the background service worker,
// which runs in an extension context exempt from PNA.
// ============================================================
function bgFetch(url, { method = 'GET', headers = {}, body, signal } = {}) {
  return new Promise((resolve, reject) => {
    chrome.runtime.sendMessage(
      { type: 'FETCH', url, method, headers, body },
      (resp) => {
        if (chrome.runtime.lastError) {
          reject(new Error(chrome.runtime.lastError.message));
          return;
        }
        if (resp.error && !resp.ok) {
          reject(new Error(resp.error));
          return;
        }
        resolve({
          ok: resp.ok,
          status: resp.status,
          json: () => Promise.resolve(resp.data),
        });
      }
    );
  });
}

// ── Technicals helpers ──────────────────────────────────────────────────────

const TECH_SELECT_FIELDS = {
  macd_signal: ['bullish', 'bearish', 'neutral'],
  rsi_result: ['rsi_oversold', 'rsi_overbought'],
  price_vs_ma200: ['above', 'below'],
  price_vs_ma50: ['above', 'below'],
  bollinger_position: ['above_upper', 'near_upper', 'mid', 'near_lower', 'below_lower'],
  day_color: ['green', 'red'],
  sentiment: ['bullish', 'bearish', 'neutral'],
};

const TECH_FIELD_ORDER = [
  ['price_action', 'Price'], ['day_color', 'Day Color'],
  ['rsi_14', 'RSI-14'], ['rsi_result', 'RSI Result'],
  ['macd_signal', 'MACD Signal'], ['macd_notes', 'MACD Notes'],
  ['ma_200d', 'MA 200D'], ['ma_50d', 'MA 50D'],
  ['price_vs_ma200', 'vs MA200'], ['price_vs_ma50', 'vs MA50'],
  ['bollinger_upper', 'BB Upper'], ['bollinger_mid', 'BB Mid'],
  ['bollinger_lower', 'BB Lower'], ['bollinger_position', 'BB Pos'],
  ['sentiment', 'Sentiment'], ['next_earnings_date', 'Earnings'],
  ['notes', 'Notes'],
];

/**
 * Injects a self-contained technicals fetch+edit panel into `container`.
 * Returns { getValue() } — call getValue() to get the current snapshot object or null.
 */
function renderTechnicalsForm(container, ticker) {
  container.innerHTML = `
    <div class="tm-tech-panel">
      <button type="button" class="tm-tech-fetch-btn">📊 Fetch Technicals</button>
      <button type="button" class="tm-tech-clear-btn tm-hidden">Clear</button>
      <div class="tm-tech-status"></div>
      <div class="tm-tech-fields tm-hidden">
        <div class="tm-tech-grid"></div>
      </div>
    </div>
  `;

  let techData = null;
  const fetchBtn = container.querySelector('.tm-tech-fetch-btn');
  const clearBtn = container.querySelector('.tm-tech-clear-btn');
  const statusEl = container.querySelector('.tm-tech-status');
  const fieldsEl = container.querySelector('.tm-tech-fields');
  const gridEl = container.querySelector('.tm-tech-grid');

  function renderFields(data) {
    gridEl.innerHTML = '';
    TECH_FIELD_ORDER.forEach(([key, label]) => {
      const isNotes = key === 'notes';
      const div = document.createElement('div');
      div.className = `tm-tech-field${isNotes ? ' full-width' : ''}`;
      const lbl = document.createElement('label');
      lbl.textContent = label;
      div.appendChild(lbl);

      if (key in TECH_SELECT_FIELDS) {
        const sel = document.createElement('select');
        sel.dataset.techField = key;
        const emptyOpt = document.createElement('option');
        emptyOpt.value = ''; emptyOpt.textContent = '—';
        sel.appendChild(emptyOpt);
        TECH_SELECT_FIELDS[key].forEach(opt => {
          const o = document.createElement('option');
          o.value = opt; o.textContent = opt;
          if (data[key] === opt) o.selected = true;
          sel.appendChild(o);
        });
        div.appendChild(sel);
      } else if (isNotes) {
        const ta = document.createElement('textarea');
        ta.dataset.techField = key;
        ta.rows = 2;
        ta.value = data[key] ?? '';
        div.appendChild(ta);
      } else {
        const inp = document.createElement('input');
        inp.dataset.techField = key;
        inp.value = data[key] != null ? String(data[key]) : '';
        div.appendChild(inp);
      }
      gridEl.appendChild(div);
    });
  }

  fetchBtn.addEventListener('click', async () => {
    fetchBtn.disabled = true;
    statusEl.textContent = 'Fetching…';
    try {
      const resp = await bgFetch(`${tmApiUrl}/api/market/technicals/${ticker.toUpperCase()}`, {
        signal: AbortSignal.timeout(20000),
      });
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const data = await resp.json();
      if (data.fetch_status === 'error') throw new Error(data.fetch_error ?? 'Fetch failed');
      techData = data;
      renderFields(data);
      fieldsEl.classList.remove('tm-hidden');
      clearBtn.classList.remove('tm-hidden');
      statusEl.textContent = '';
    } catch (e) {
      statusEl.textContent = `Error: ${e.message}`;
    } finally {
      fetchBtn.disabled = false;
    }
  });

  clearBtn.addEventListener('click', () => {
    techData = null;
    fieldsEl.classList.add('tm-hidden');
    clearBtn.classList.add('tm-hidden');
    statusEl.textContent = '';
    gridEl.innerHTML = '';
  });

  return {
    getValue() {
      if (!techData) return null;
      const snapshot = { ...techData };
      container.querySelectorAll('[data-tech-field]').forEach(el => {
        snapshot[el.dataset.techField] = el.value || null;
      });
      return snapshot;
    },
  };
}

// ============================================================
// INIT
// ============================================================
chrome.runtime.sendMessage({ type: 'GET_SETTINGS' }, (resp) => {
  if (resp) {
    tmApiUrl = resp.apiUrl || 'http://localhost:5431';
    stageEnabled = resp.stages || stageEnabled;
  }
  if (stageEnabled.stage1) {
    loadCategoriesAndStart();
  }
});

async function loadCategoriesAndStart() {
  try {
    const resp = await bgFetch(`${tmApiUrl}/api/categories`, { signal: AbortSignal.timeout(4000) });
    if (resp.ok) {
      allCategories = await resp.json();
    }
  } catch (e) {
    // Backend not running — proceed with empty categories
  }
  // Don't insert the toolbar here — the grid may not be in the DOM yet.
  // startObserver() retries until the content area exists, at which point
  // the grid root is also guaranteed to be present.
  startObserver();
}

// ============================================================
// COLUMN MAP — resolves header names to col-attribute values
// ============================================================
function buildColumnMap() {
  if (columnIndexCache) return columnIndexCache;
  const headerRow = document.querySelector(ETRADE.headerRow);
  if (!headerRow) return {};
  const map = {};
  headerRow.querySelectorAll('[role="columnheader"]').forEach((cell) => {
    const colNum = cell.getAttribute('col');
    if (colNum == null) return;
    // Use the title span to avoid picking up arrow icon text
    const titleEl = cell.querySelector('.HeaderCell---title---2VEL5');
    const raw = (titleEl ? titleEl.textContent : cell.textContent)
      .trim()
      .replace(/\u00a0/g, ' ')  // &nbsp; → regular space
      .replace(/\s+/g, ' ')
      .toLowerCase();
    if (raw) map[raw] = colNum;
  });
  columnIndexCache = map;
  return map;
}

// Use the col attribute (matches between header and data rows regardless of rowheader offset)
function getRowCellText(row, colNum) {
  const cell = row.querySelector(`[col="${colNum}"]`);
  return cell ? cell.textContent.trim() : null;
}

function parseNumeric(text) {
  if (!text) return null;
  // Remove $, commas, spaces; handle parentheses as negative
  const cleaned = text.replace(/[$, ]/g, '').replace(/\(([^)]+)\)/, '-$1');
  const n = parseFloat(cleaned);
  return isNaN(n) ? null : n;
}

// ============================================================
// TICKER + ROW INFO EXTRACTION
// ============================================================
function getTickerFromRow(row) {
  const symbolDiv = row.querySelector(ETRADE.symbolContent);
  if (!symbolDiv) return null;
  // aria-label: "AAPL" or "NVDA, This option is in the money"
  const label = symbolDiv.getAttribute('aria-label') || '';
  const ticker = label.split(',')[0].trim().toUpperCase();
  return ticker || null;
}

function getRowInfo(row) {
  const symbolRoot = row.querySelector('[class*="SymbolCellRenderer---root"]');
  const isOption = symbolRoot ? symbolRoot.classList.contains(ETRADE.optionClass) : false;
  const isITM = symbolRoot ? symbolRoot.classList.contains(ETRADE.itmClass) : false;

  const ticker = getTickerFromRow(row);
  if (!ticker) return null;

  let fullSymbol = null;
  let optionDetails = null;

  // Extract fullSymbol from the Trade button href (Symbol= param) for all row types
  const tradeBtn = row.querySelector('a.split-button-button[href*="Symbol="]');
  if (tradeBtn?.href) {
    const match = tradeBtn.href.match(/[?&]Symbol=([^&]+)/i);
    if (match) fullSymbol = decodeURIComponent(match[1]);
  }

  if (isOption) {
    if (fullSymbol) {
      optionDetails = parseOptionSymbol(fullSymbol);
    }
    // Fallback: try the symbol cell link if Trade button didn't yield a parseable option symbol
    if (!optionDetails) {
      const link = row.querySelector(ETRADE.symbolLink);
      if (link?.href) {
        const match = link.href.match(/[?&]symbol=([^&]+)/i);
        if (match) {
          fullSymbol = decodeURIComponent(match[1]);
          optionDetails = parseOptionSymbol(fullSymbol);
        }
      }
    }
    if (!optionDetails) {
      const descEl = row.querySelector(ETRADE.optionDesc);
      if (descEl) optionDetails = parseOptionDescription(descEl.textContent.trim());
    }
  }

  // Extract Qty and Price Paid from grid cells using header column map
  const colMap = buildColumnMap();
  // Header text after &nbsp; normalization: "qty #" and "price paid $"
  const qtyCol = colMap['qty #'] ?? colMap['qty'] ?? null;
  const pricePaidCol = colMap['price paid $'] ?? colMap['price paid'] ?? null;

  let quantity = null;
  let pricePaid = null;

  if (qtyCol != null) {
    const raw = parseNumeric(getRowCellText(row, qtyCol));
    if (raw != null) quantity = Math.abs(raw);  // qty is negative for short positions
  }
  if (pricePaidCol != null) {
    pricePaid = parseNumeric(getRowCellText(row, pricePaidCol));
  }

  return { ticker, isOption, isITM, fullSymbol, optionDetails, quantity, pricePaid };
}

function parseOptionSymbol(fullSymbol) {
  const match = fullSymbol.match(/^([A-Z]+)-{1,4}(\d{6})([CP])(\d{8})$/);
  if (!match) return null;
  const [, , dateStr, optType, strikeRaw] = match;
  const year = 2000 + parseInt(dateStr.slice(0, 2));
  const month = parseInt(dateStr.slice(2, 4)) - 1;
  const day = parseInt(dateStr.slice(4, 6));
  const expiry = new Date(year, month, day).toISOString().split('T')[0];
  const strike = parseInt(strikeRaw) / 1000;
  return {
    expiry,
    type: optType === 'C' ? 'Call' : 'Put',
    strike,
    dte: Math.round((new Date(expiry) - new Date()) / 86400000),
  };
}

function parseOptionDescription(desc) {
  const match = desc.match(/^(\w{3})\s+(\d{1,2})\s+'(\d{2})\s+\$(\d+(?:\.\d+)?)\s+(Call|Put)$/);
  if (!match) return null;
  const months = { Jan: 0, Feb: 1, Mar: 2, Apr: 3, May: 4, Jun: 5, Jul: 6, Aug: 7, Sep: 8, Oct: 9, Nov: 10, Dec: 11 };
  const [, mon, day, yr, strike, type] = match;
  const expiry = new Date(2000 + parseInt(yr), months[mon], parseInt(day)).toISOString().split('T')[0];
  return { expiry, type, strike: parseFloat(strike), dte: Math.round((new Date(expiry) - new Date()) / 86400000) };
}

// ============================================================
// VIRTUAL SCROLL PROCESSING
// ============================================================
async function processVisibleRows() {
  if (isProcessing) return;
  isProcessing = true;

  try {
    const rows = document.querySelectorAll(ETRADE.positionRows);
    const toProcess = [];

    rows.forEach(row => {
      const rowId = row.id;
      const info = getRowInfo(row);
      if (!info) return;

      seenTickers.add(info.ticker);

      const cacheKey = info.fullSymbol || info.ticker;
      const prevKey = processedRows.get(rowId);
      const badgeMissing = !row.querySelector('.tm-badge');

      if (prevKey !== cacheKey || badgeMissing) {
        if (prevKey !== cacheKey) clearTMFromRow(row);
        processedRows.set(rowId, cacheKey);
        toProcess.push({ row, info, cacheKey });
      }
    });

    if (toProcess.length === 0) return;

    // Fire-and-forget: fetch all active sessions + wheel slots, then prices for spread sessions
    Promise.all([fetchAllActiveSessions(), fetchWheelActiveSlots()]).then(async () => {
      await fetchPricesForSpreadSessions();
      // Re-apply pills now that session/price/wheel data is available
      document.querySelectorAll(ETRADE.positionRows).forEach(row => {
        applyWheelPillToRow(row);
      });
    });

    // Apply cached status immediately; collect what needs a fetch
    const needsFetch = [];
    toProcess.forEach(item => {
      if (statusCache.has(item.cacheKey)) {
        applyTMToRow(item.row, statusCache.get(item.cacheKey), item.info);
        applyFilter(item.row, statusCache.get(item.cacheKey));
        applyRsiToRow(item.row, item.info.ticker);
        applyWheelPillToRow(item.row);
        applyReconcilePillToRow(item.row, item.info);
      } else {
        needsFetch.push(item);
      }
    });

    if (needsFetch.length === 0) return;

    // Build batch payload
    const positions = needsFetch.map(item => ({
      ticker: item.info.ticker,
      full_symbol: item.info.fullSymbol || null,
      type: item.info.optionDetails?.type || (item.info.isOption ? 'Option' : 'Stock'),
      strike: item.info.optionDetails?.strike || null,
      expiry: item.info.optionDetails?.expiry || null,
      is_itm: item.info.isITM,
    }));

    const response = await bgFetch(`${tmApiUrl}/api/positions/status`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ positions }),
      signal: AbortSignal.timeout(5000),
    });

    if (!response.ok) return;
    const statusMap = await response.json();

    needsFetch.forEach(item => {
      let status = statusMap[item.cacheKey] || statusMap[item.info.ticker] || null;

      // Validate type match: reject a status whose trade strategy conflicts with the row type.
      // Prevents a stock row from inheriting an option trade (or vice versa) when _pick_best_trade
      // falls back to the only available trade regardless of type.
      if (status && status.strategy) {
        const strat = status.strategy.toLowerCase();
        const isOptionStrat = strat.includes('put') || strat.includes('call') ||
          strat.includes('leap') || strat.includes('spread');
        if (item.info.isOption && !isOptionStrat) status = null;
        else if (!item.info.isOption && isOptionStrat) status = null;
      }

      statusCache.set(item.cacheKey, status);
      applyTMToRow(item.row, status, item.info);
      applyFilter(item.row, status);
      applyRsiToRow(item.row, item.info.ticker);
      applyWheelPillToRow(item.row);
      applyReconcilePillToRow(item.row, item.info);
    });

  } catch (err) {
    if (err.name !== 'AbortError') {
      console.debug('TradeMinder: backend unavailable', err.message);
    }
  } finally {
    isProcessing = false;
  }
}

function clearTMFromRow(row) {
  row.querySelector('.tm-badge')?.remove();
  row.style.backgroundColor = '';
  row.style.borderLeft = '';
  row.style.boxSizing = '';
}

// ============================================================
// ROW COLORING + BADGE INJECTION
// ============================================================
function applyTMToRow(row, status, info) {
  applyRowColor(row, status);
  injectBadge(row, status, info);
}

function applyRowColor(row, status) {
  if (!status) {
    row.style.borderLeft = '3px solid #6b7280';
    row.style.boxSizing = 'border-box';
    return;
  }
  const colors = {
    urgent: 'rgba(239,68,68,0.18)',
    warning: 'rgba(245,158,11,0.15)',
    info: 'rgba(139,92,246,0.12)',
    ok: 'rgba(34,197,94,0.08)',
  };
  const borders = {
    urgent: '#ef4444', warning: '#f59e0b', info: '#8b5cf6', ok: '#22c55e',
  };
  // Stage 1: use category color if no alert severity
  const severity = status.alert_severity || 'ok';
  const catColor = status.category_color;
  row.style.backgroundColor = colors[severity] || (catColor ? hexToRgba(catColor, 0.10) : '');
  row.style.borderLeft = `3px solid ${borders[severity] || catColor || '#6b7280'}`;
  row.style.boxSizing = 'border-box';
}

function hexToRgba(hex, alpha) {
  const r = parseInt(hex.slice(1, 3), 16);
  const g = parseInt(hex.slice(3, 5), 16);
  const b = parseInt(hex.slice(5, 7), 16);
  return `rgba(${r},${g},${b},${alpha})`;
}

function injectBadge(row, status, info) {
  let badge = row.querySelector('.tm-badge');
  if (!badge) {
    badge = document.createElement('div');
    badge.className = 'tm-badge';
    badge.style.cssText = 'display:inline-flex;align-items:center;white-space:nowrap;pointer-events:auto;';

    const actionsCell = row.querySelector('[col="1"]');
    if (actionsCell) {
      // overflow:visible lets the badge extend past the 65px cell width
      // without changing the column layout
      actionsCell.style.overflow = 'visible';
      actionsCell.appendChild(badge);
    } else {
      // Fallback if Actions cell not found
      badge.style.cssText += 'position:absolute;left:339px;top:50%;transform:translateY(-50%);z-index:100;';
      row.style.overflow = 'visible';
      row.appendChild(badge);
    }
  }

  if (!status) {
    badge.innerHTML = `<span class="tm-tag tm-untracked">⊘</span>`;
    return;
  }

  const dte = info.optionDetails?.dte;

  badge.innerHTML = dte != null ? `<span class="tm-dte">${dte}d</span>` : '';

  if (status.trade_id) {
    const tradeId = status.trade_id;
    const btn = document.createElement('span');
    btn.className = 'tm-commentary-btn';
    const cached = commentaryCountCache.get(tradeId);
    btn.textContent = cached != null ? `💬 ${cached}` : '💬 …';

    // Hover shows the body-level trigger — clicking the pill itself would
    // propagate to E*TRADE's capture listener and expand the row.
    btn.addEventListener('mouseenter', () => showCommentaryTrigger(tradeId, info.ticker, row, btn));
    btn.addEventListener('mouseleave', () => scheduleHideCommentaryTrigger());

    badge.appendChild(btn);

    if (!commentaryCountCache.has(tradeId)) {
      // Count fetched once per session per tradeId; re-fetch happens via updateCommentaryBadge after mutations
      fetchCommentaryCount(tradeId).then(() => {
        btn.textContent = `💬 ${commentaryCountCache.get(tradeId) ?? 0}`;
      });
    }
  }
}

// ============================================================
// RSI COLUMN
// ============================================================
function getRsiClass(rsi) {
  if (rsi < 30) return 'rsi-oversold';
  if (rsi < 40) return 'rsi-near-oversold';
  if (rsi <= 60) return 'rsi-neutral';
  if (rsi <= 70) return 'rsi-near-overbought';
  return 'rsi-overbought';
}

function applyRsiToRow(row, ticker) {
  const badge = row.querySelector('.tm-badge');
  if (!badge) return;

  let pill = badge.querySelector('.tm-rsi-pill');

  if (!rsiCache.has(ticker)) {
    pill?.remove();
    return;
  }

  const rsi = rsiCache.get(ticker);

  if (!pill) {
    pill = document.createElement('span');
    badge.appendChild(pill);
  }

  if (rsi === null) {
    pill.className = 'tm-rsi-pill rsi-error';
    pill.textContent = 'RSI —';
    return;
  }

  pill.className = `tm-rsi-pill ${getRsiClass(rsi)}`;
  pill.textContent = `RSI ${rsi.toFixed(1)}`;
}

function renderWheelPillForTicker(ticker) {
  const variants = tickerVariants(ticker);
  const slots = wheelActiveSlots.filter(s => variants.includes(s.ticker.toUpperCase()));
  if (slots.length === 0) return null;

  const parts = [];
  if (slots.some(s => s.status === 'cc_active')) parts.push('CC');
  if (slots.some(s => s.status === 'sold_put_active')) parts.push('SP');
  if (slots.some(s => s.status === 'awaiting_cc') && !slots.some(s => s.status === 'cc_active')) parts.push('CC?');
  if (slots.some(s => s.status === 'awaiting_sold_put') && !slots.some(s => s.status === 'sold_put_active')) parts.push('SP?');
  const needsAction = slots.some(s => s.needs_action);
  if (parts.length === 0 && !needsAction) return null;

  const label = 'WHL: ' + (parts.length > 0 ? parts.join('+') : '') + (needsAction ? ' ⚠' : '');
  const pill = document.createElement('span');
  pill.className = 'tm-wheel-pill';
  pill.textContent = label.trim();
  pill.style.cssText = [
    'display:inline-flex',
    'align-items:center',
    'font-size:10px',
    'padding:1px 5px',
    'border-radius:3px',
    'margin-left:4px',
    'white-space:nowrap',
    `background:${needsAction ? '#FEF3C7' : '#DBEAFE'}`,
    `color:${needsAction ? '#92400E' : '#1E40AF'}`,
    `border:1px solid ${needsAction ? '#FCD34D' : '#93C5FD'}`,
  ].join(';');
  return pill;
}

function findWheelSlotForRow(info) {
  if (!info?.fullSymbol) return null;
  const sym = info.fullSymbol.toUpperCase();
  return wheelActiveSlots.find(s => s.etrade_symbols.includes(sym)) || null;
}

function computePriceSignal(session) {
  const price = priceCache.get(session.ticker?.toUpperCase());
  if (price == null) return 'unknown';
  const legs = session.legs || [];

  if (session.strategy === 'IRON_CONDOR') {
    const shortPutStrikes = legs
      .filter(l => l.strategy === 'Sell Put' && l.strike_price != null)
      .map(l => Number(l.strike_price));
    const shortCallStrikes = legs
      .filter(l => l.strategy === 'Sell Call' && l.strike_price != null)
      .map(l => Number(l.strike_price));
    if (!shortPutStrikes.length || !shortCallStrikes.length) return 'unknown';
    const sp = Math.max(...shortPutStrikes);
    const sc = Math.min(...shortCallStrikes);
    if (price <= sp || price >= sc) return 'danger';
    if (price < sp * 1.05 || price > sc * 0.95) return 'warning';
    return 'safe';
  }

  if (session.strategy === 'PUT_B_W_FLY') {
    const shortStrikes = legs
      .filter(l => l.strategy === 'Sell Put' && l.strike_price != null)
      .map(l => Number(l.strike_price));
    if (shortStrikes.length < 2) return 'unknown';
    const low = Math.min(...shortStrikes);
    const high = Math.max(...shortStrikes);
    if (price <= low || price >= high) return 'danger';
    if (price < low * 1.05 || price > high * 0.95) return 'warning';
    return 'safe';
  }
  return 'unknown';
}

function renderStrategyPill(session) {
  if (!session) return null;
  const signal = computePriceSignal(session);
  const shortLabel = session.strategy === 'IRON_CONDOR' ? 'IC' : 'PBWB';
  const icons = { safe: '✓', warning: '⚠', danger: '✗', unknown: '' };
  const icon = icons[signal] || '';
  const label = icon ? `${shortLabel} ${icon}` : shortLabel;

  const colorMap = {
    safe: session.strategy === 'IRON_CONDOR'
      ? { bg: '#EDE9FE', color: '#5B21B6', border: '#C4B5FD' }
      : { bg: '#CCFBF1', color: '#0F766E', border: '#5EEAD4' },
    warning: { bg: '#FEF3C7', color: '#92400E', border: '#FCD34D' },
    danger: { bg: '#FEE2E2', color: '#991B1B', border: '#FCA5A5' },
    unknown: session.strategy === 'IRON_CONDOR'
      ? { bg: '#EDE9FE', color: '#5B21B6', border: '#C4B5FD' }
      : { bg: '#CCFBF1', color: '#0F766E', border: '#5EEAD4' },
  };
  const c = colorMap[signal];

  const pill = document.createElement('span');
  pill.className = 'tm-strategy-pill';
  pill.textContent = label;
  pill.style.cssText = [
    'display:inline-flex', 'align-items:center', 'font-size:10px',
    'padding:1px 5px', 'border-radius:3px', 'margin-left:4px', 'white-space:nowrap',
    `background:${c.bg}`, `color:${c.color}`, `border:1px solid ${c.border}`,
  ].join(';');
  return pill;
}

// Returns the session that owns this specific row's position, or null.
// A row belongs to a session iff its etrade_symbol matches a leg's etrade_symbol exactly.
function findSessionForRow(info) {
  if (!info?.fullSymbol) return null;
  return etradeSymbolIndex.get(info.fullSymbol.toUpperCase()) || null;
}

// Non-session strategy categories — shown as a simple pill using the
// category's own color from the backend (categories table). WHEEL and the
// spread categories (PUT_SPREAD/CALL_SPREAD/IRON_CONDOR/IRON_BUTTERFLY) are
// handled via the session-based pills above and are intentionally excluded here.
const CATEGORY_PILL_LABELS = {
  SWING: 'Swing',
  HOLD: 'Hold',
  LEAP: 'Leap',
  SKIP: 'Skip',
  HOPS: 'Hops',
};

// Explicit bg/text/border triples per category — distinct hues with enough
// contrast to tell apart at a glance. A low-alpha tint of the backend's
// category_color washed out to near-identical pale colors, so these are
// hand-picked instead of derived from category_color.
const CATEGORY_PILL_STYLES = {
  SWING: { bg: '#CFFAFE', color: '#155E75', border: '#67E8F9' }, // cyan
  HOLD: { bg: '#D1FAE5', color: '#065F46', border: '#6EE7B7' }, // emerald
  LEAP: { bg: '#EDE9FE', color: '#5B21B6', border: '#C4B5FD' }, // violet
  SKIP: { bg: '#F3F4F6', color: '#374151', border: '#D1D5DB' }, // gray
  HOPS: { bg: '#ECFCCB', color: '#3F6212', border: '#BEF264' }, // lime
};

function renderCategoryPill(status) {
  if (!status?.category_name) return null;
  const label = CATEGORY_PILL_LABELS[status.category_name];
  const style = CATEGORY_PILL_STYLES[status.category_name];
  if (!label || !style) return null;

  const pill = document.createElement('span');
  pill.className = 'tm-category-pill';
  pill.textContent = label;
  pill.style.cssText = [
    'display:inline-flex', 'align-items:center', 'font-size:10px',
    'padding:1px 5px', 'border-radius:3px', 'margin-left:4px', 'white-space:nowrap',
    `background:${style.bg}`, `color:${style.color}`, `border:1px solid ${style.border}`,
  ].join(';');
  return pill;
}

function applyWheelPillToRow(row) {
  const flyoutBtn = row.querySelector('button[aria-label="Open Quote Flyout"]');
  if (!flyoutBtn) return;
  const symbolDiv = flyoutBtn.parentElement;
  symbolDiv.querySelector('.tm-wheel-pill')?.remove();
  symbolDiv.querySelector('.tm-strategy-pill')?.remove();
  symbolDiv.querySelector('.tm-category-pill')?.remove();

  const info = getRowInfo(row);

  // Wheel v2: check slot-based wheel data first
  const wheelSlot = findWheelSlotForRow(info);
  if (wheelSlot) {
    const pill = renderWheelPillForTicker(info.ticker);
    if (pill) symbolDiv.appendChild(pill);
    return;
  }
  // Show wheel pill on stock rows (non-option) by ticker match (with alias support)
  const tickerVars = info.ticker ? tickerVariants(info.ticker) : [];
  if (!info.isOption && tickerVars.length && wheelActiveSlots.some(s => tickerVars.includes(s.ticker.toUpperCase()))) {
    const pill = renderWheelPillForTicker(info.ticker);
    if (pill) symbolDiv.appendChild(pill);
    return;
  }

  // Spread sessions (IC, PBWB) — still use old session system
  const session = findSessionForRow(info);
  if (session) {
    if (session.strategy !== 'WHEEL') {
      const pill = renderStrategyPill(session);
      if (pill) symbolDiv.appendChild(pill);
    }
    return;
  }

  // No active session — fall back to a plain category pill (Swing/Hold/Leap/Skip/Hops)
  const cacheKey = info.fullSymbol || info.ticker;
  const status = statusCache.get(cacheKey);
  const pill = renderCategoryPill(status);
  if (pill) symbolDiv.appendChild(pill);
}

// ============================================================
// RECONCILIATION
// ============================================================
async function fireReconcile(rows) {
  const positions = [];
  const keys = [];

  rows.forEach(row => {
    const info = getRowInfo(row);
    if (!info) return;
    const key = info.fullSymbol || info.ticker;
    keys.push(key);
    positions.push({
      ticker: info.ticker,
      full_symbol: info.fullSymbol || null,
      type: info.optionDetails?.type || (info.isOption ? 'Option' : 'Stock'),
      strike: info.optionDetails?.strike || null,
      expiry: info.optionDetails?.expiry || null,
    });
  });

  if (positions.length === 0) return null;

  try {
    const resp = await bgFetch(`${tmApiUrl}/api/positions/reconcile`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ positions }),
      signal: AbortSignal.timeout(5000),
    });
    if (!resp.ok) return null;
    const data = await resp.json();

    reconcileCache.clear();
    (data.unmatched_etrade || []).forEach(item => {
      reconcileCache.set((item.full_symbol || item.ticker).toUpperCase(), true);
    });

    document.querySelectorAll(ETRADE.positionRows).forEach(row => {
      const info = getRowInfo(row);
      if (info) applyReconcilePillToRow(row, info);
    });

    return data;
  } catch (err) {
    if (err.name !== 'AbortError') {
      console.debug('TradeMinder: reconcile failed', err.message);
    }
    return null;
  }
}

function applyReconcilePillToRow(row, info) {
  const badge = row.querySelector('.tm-badge');
  if (!badge) return;

  badge.querySelector('.tm-reconcile-pill')?.remove();

  const key = (info.fullSymbol || info.ticker).toUpperCase();
  if (!reconcileCache.has(key)) return;

  const pill = document.createElement('span');
  pill.className = 'tm-reconcile-pill';
  pill.textContent = '+';
  pill.title = 'Not tracked in TradeMinder — click to add';
  pill.style.cssText = [
    'display:inline-flex',
    'align-items:center',
    'font-size:10px',
    'padding:1px 6px',
    'border-radius:3px',
    'margin-left:4px',
    'white-space:nowrap',
    'background:#FEF9C3',
    'color:#713F12',
    'border:1px solid #FDE047',
    'cursor:pointer',
  ].join(';');
  pill.addEventListener('click', e => {
    e.stopPropagation();
    showAddTradeModal(info);
  });
  badge.appendChild(pill);
}

// ============================================================
// COMMENTARY
// ============================================================
function getOrCreateTrigger() {
  if (_hoverTrigger) return _hoverTrigger;
  _hoverTrigger = document.createElement('button');
  _hoverTrigger.id = 'tm-commentary-trigger';
  _hoverTrigger.textContent = '💬 Open';
  document.body.appendChild(_hoverTrigger);

  _hoverTrigger.addEventListener('mouseenter', () => clearTimeout(_hoverHideTimer));
  _hoverTrigger.addEventListener('mouseleave', () => scheduleHideCommentaryTrigger());
  _hoverTrigger.addEventListener('click', () => {
    if (_hoverTradeId && _hoverRow) {
      openCommentaryPanel(_hoverTradeId, _hoverTicker, _hoverRow);
    }
    hideCommentaryTrigger();
  });

  return _hoverTrigger;
}

function showCommentaryTrigger(tradeId, ticker, row, pillEl) {
  clearTimeout(_hoverHideTimer);
  _hoverTradeId = tradeId;
  _hoverTicker = ticker;
  _hoverRow = row;
  _hoverPill = pillEl;

  const trigger = getOrCreateTrigger();
  const rect = pillEl.getBoundingClientRect();
  trigger.style.top = `${rect.top}px`;
  trigger.style.left = `${rect.left}px`;
  trigger.style.display = 'flex';
}

function scheduleHideCommentaryTrigger() {
  _hoverHideTimer = setTimeout(hideCommentaryTrigger, 150);
}

function hideCommentaryTrigger() {
  clearTimeout(_hoverHideTimer);
  if (_hoverTrigger) _hoverTrigger.style.display = 'none';
}

async function fetchCommentaryCount(tradeId) {
  try {
    const resp = await bgFetch(`${tmApiUrl}/api/trades/${tradeId}/commentary`, {
      signal: AbortSignal.timeout(5000),
    });
    if (resp.ok) {
      const entries = await resp.json();
      commentaryCountCache.set(tradeId, entries.length);
    }
  } catch (e) {
    if (e.name !== 'TimeoutError' && e.name !== 'AbortError') {
      console.debug('[TM] fetchCommentaryCount', tradeId, e);
    }
  }
}

function escapeHtml(s) {
  return String(s ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

function updateCommentaryBadge(tradeId, count) {
  commentaryCountCache.set(tradeId, count);
  document.querySelectorAll(ETRADE.positionRows).forEach(row => {
    const btn = row.querySelector('.tm-commentary-btn');
    if (!btn) return;
    const rowId = row.id;
    const cacheKey = processedRows.get(rowId);
    if (!cacheKey) return;
    const status = statusCache.get(cacheKey);
    if (status?.trade_id === tradeId) {
      btn.textContent = `💬 ${count}`;
    }
  });
}

function getOrCreatePanel() {
  let panel = document.getElementById('tm-commentary-panel');
  if (panel) return panel;

  panel = document.createElement('div');
  panel.id = 'tm-commentary-panel';
  panel.innerHTML = `
    <div class="tm-cp-header">
      <span class="tm-cp-title"></span>
      <button class="tm-cp-close">×</button>
    </div>
    <div class="tm-cp-thread"></div>
    <div class="tm-cp-form">
      <div class="tm-cp-form-static">
        <textarea class="tm-cp-note-input" rows="3" placeholder="What happened or what did you decide?"></textarea>
        <input class="tm-cp-tags-input" type="text" placeholder="Tags: rolled, exit-change (comma-separated)" />
      </div>
      <div class="tm-cp-form-tech">
        <div class="tm-tech-section">
          <button type="button" class="tm-tech-toggle" data-note-tech-toggle>▼ Attach Technicals</button>
          <div data-note-tech-container class="tm-hidden"></div>
        </div>
      </div>
      <div class="tm-cp-form-footer">
        <button class="tm-cp-submit" type="button">Add Note</button>
      </div>
    </div>`;
  document.body.appendChild(panel);

  panel._techControl = null;
  const noteTechToggle = panel.querySelector('[data-note-tech-toggle]');
  const noteTechContainer = panel.querySelector('[data-note-tech-container]');
  if (noteTechToggle && noteTechContainer) {
    noteTechToggle.addEventListener('click', () => {
      const isOpen = !noteTechContainer.classList.contains('tm-hidden');
      if (isOpen) {
        noteTechContainer.classList.add('tm-hidden');
        noteTechToggle.textContent = '▼ Attach Technicals';
      } else {
        if (!panel._techControl) {
          const ticker = panel.dataset.ticker || '';
          panel._techControl = renderTechnicalsForm(noteTechContainer, ticker);
        }
        noteTechContainer.classList.remove('tm-hidden');
        noteTechToggle.textContent = '▲ Hide Technicals';
      }
    });
  }

  panel.querySelector('.tm-cp-close').addEventListener('click', closeCommentaryPanel);

  panel.querySelector('.tm-cp-submit').addEventListener('click', async () => {
    const tradeId = panel.dataset.tradeId;
    if (!tradeId) return;
    const noteEl = panel.querySelector('.tm-cp-note-input');
    const tagsEl = panel.querySelector('.tm-cp-tags-input');
    const submitBtn = panel.querySelector('.tm-cp-submit');
    const note = noteEl.value.trim();
    if (!note) return;
    const tags = tagsEl.value.split(',').map(t => t.trim()).filter(Boolean);
    submitBtn.disabled = true;
    submitBtn.textContent = 'Adding…';
    try {
      const techSnapshot = panel._techControl ? panel._techControl.getValue() : null;
      const bodyObj = { note, ...(tags.length > 0 && { tags }) };
      if (techSnapshot) bodyObj.rationale = techSnapshot;
      const resp = await bgFetch(`${tmApiUrl}/api/trades/${tradeId}/commentary`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(bodyObj),
        signal: AbortSignal.timeout(8000),
      });
      if (resp.ok) {
        noteEl.value = '';
        tagsEl.value = '';
        panel._techControl = null;
        noteTechContainer.innerHTML = '';
        noteTechContainer.classList.add('tm-hidden');
        noteTechToggle.textContent = '▼ Attach Technicals';
        await renderCommentaryThread(tradeId, panel);
      }
    } catch (e) { /* silent */ } finally {
      submitBtn.disabled = false;
      submitBtn.textContent = 'Add Note';
    }
  });

  return panel;
}

function openCommentaryPanel(tradeId, ticker, anchorRow) {
  const panel = getOrCreatePanel();
  panel.dataset.tradeId = tradeId;
  panel.dataset.ticker = ticker;
  panel.querySelector('.tm-cp-title').textContent = `${ticker} · Commentary`;
  panel.querySelector('.tm-cp-note-input').value = '';
  panel.querySelector('.tm-cp-tags-input').value = '';
  panel.querySelector('.tm-cp-submit').disabled = false;
  panel.querySelector('.tm-cp-submit').textContent = 'Add Note';

  // Reset technicals panel when switching trades
  panel._techControl = null;
  const noteTechContainer = panel.querySelector('[data-note-tech-container]');
  const noteTechToggle = panel.querySelector('[data-note-tech-toggle]');
  if (noteTechContainer && noteTechToggle) {
    noteTechContainer.innerHTML = '';
    noteTechContainer.classList.add('tm-hidden');
    noteTechToggle.textContent = '▼ Attach Technicals';
  }

  panel.style.display = 'flex';

  const rect = anchorRow.getBoundingClientRect();
  const margin = 8;
  const panelW = 400;

  // Horizontal: align panel's left edge with the badge pill, clamped to viewport
  const pillRect = _hoverPill ? _hoverPill.getBoundingClientRect() : rect;
  const panelLeft = Math.max(margin, Math.min(pillRect.left, window.innerWidth - panelW - margin));
  panel.style.left = `${panelLeft}px`;

  // Vertical: open whichever direction has more room; cap maxHeight to available space
  const spaceBelow = window.innerHeight - rect.bottom - margin;
  const spaceAbove = rect.top - margin;

  if (spaceBelow >= spaceAbove || spaceBelow >= 200) {
    panel.style.top = `${rect.bottom + 4}px`;
    panel.style.bottom = '';
    panel.style.maxHeight = `${Math.min(600, spaceBelow)}px`;
  } else {
    panel.style.bottom = `${window.innerHeight - rect.top + 4}px`;
    panel.style.top = '';
    panel.style.maxHeight = `${Math.min(600, spaceAbove)}px`;
  }

  renderCommentaryThread(tradeId, panel);

  if (_panelClickOutside) document.removeEventListener('mousedown', _panelClickOutside);
  _panelClickOutside = (e) => { if (!panel.contains(e.target)) closeCommentaryPanel(); };
  setTimeout(() => document.addEventListener('mousedown', _panelClickOutside), 0);

  if (_panelEsc) document.removeEventListener('keydown', _panelEsc);
  _panelEsc = (e) => { if (e.key === 'Escape') closeCommentaryPanel(); };
  document.addEventListener('keydown', _panelEsc);
}

function closeCommentaryPanel() {
  const panel = document.getElementById('tm-commentary-panel');
  if (panel) panel.style.display = 'none';
  if (_panelClickOutside) {
    document.removeEventListener('mousedown', _panelClickOutside);
    _panelClickOutside = null;
  }
  if (_panelEsc) {
    document.removeEventListener('keydown', _panelEsc);
    _panelEsc = null;
  }
}

function buildRationaleChip(rationale) {
  const chip = document.createElement('button');
  chip.type = 'button';
  chip.className = 'tm-rationale-chip';
  chip.textContent = '📊 Technicals';
  let detailEl = null;
  chip.addEventListener('click', () => {
    if (detailEl) { detailEl.remove(); detailEl = null; return; }
    detailEl = document.createElement('div');
    detailEl.className = 'tm-rationale-detail';
    const r = rationale;
    const SHOW = [
      ['RSI', r.rsi_14], ['MACD', r.macd_signal], ['Sentiment', r.sentiment],
      ['BB Pos', r.bollinger_position], ['vs MA50', r.price_vs_ma50],
      ['Price', r.price_action], ['Earnings', r.next_earnings_date],
      ['Day', r.day_color], ['Notes', r.notes],
    ].filter(([, v]) => v != null && v !== '');
    SHOW.forEach(([label, value]) => {
      const rowEl = document.createElement('div');
      rowEl.className = 'tm-rationale-row';
      const labelSpan = document.createElement('span');
      labelSpan.textContent = `${label}: `;
      const valueSpan = document.createElement('span');
      valueSpan.textContent = String(value);
      rowEl.appendChild(labelSpan);
      rowEl.appendChild(valueSpan);
      detailEl.appendChild(rowEl);
    });
    chip.insertAdjacentElement('afterend', detailEl);
  });
  return chip;
}

async function renderCommentaryThread(tradeId, panel) {
  if (_threadAbortCtrl) _threadAbortCtrl.abort();
  _threadAbortCtrl = new AbortController();
  const signal = _threadAbortCtrl.signal;

  const threadEl = panel.querySelector('.tm-cp-thread');
  threadEl.innerHTML = '<p class="tm-cp-loading">Loading…</p>';

  try {
    const [commResp, tradeResp] = await Promise.all([
      bgFetch(`${tmApiUrl}/api/trades/${tradeId}/commentary`, { signal }),
      bgFetch(`${tmApiUrl}/api/trades/${tradeId}`, { signal }),
    ]);
    if (!commResp.ok) throw new Error(`HTTP ${commResp.status}`);
    const entries = await commResp.json();

    let entryRationale = null;
    let tradeOpenDate = null;
    if (tradeResp.ok) {
      const trade = await tradeResp.json();
      tradeOpenDate = trade.open_date || null;
      if (trade.rationale && trade.rationale.fetch_status === 'ok') {
        entryRationale = trade.rationale;
      }
    }

    updateCommentaryBadge(tradeId, entries.length);

    if (entries.length === 0 && !entryRationale) {
      threadEl.innerHTML = '<p class="tm-cp-empty">No notes yet.</p>';
      return;
    }

    threadEl.innerHTML = '';

    // Entry-time rationale displayed as the oldest item
    if (entryRationale) {
      const snapEl = document.createElement('div');
      snapEl.className = 'tm-cp-entry tm-cp-entry-snapshot';

      const headerEl = document.createElement('div');
      headerEl.className = 'tm-cp-entry-header';
      const dateSpan = document.createElement('span');
      dateSpan.className = 'tm-cp-date';
      dateSpan.textContent = tradeOpenDate ? `${tradeOpenDate} · Entry` : 'Entry Snapshot';
      headerEl.appendChild(dateSpan);
      snapEl.appendChild(headerEl);
      snapEl.appendChild(buildRationaleChip(entryRationale));
      threadEl.appendChild(snapEl);
    }

    entries.forEach(entry => {
      const entryEl = document.createElement('div');
      entryEl.className = 'tm-cp-entry';

      const headerEl = document.createElement('div');
      headerEl.className = 'tm-cp-entry-header';
      const dateSpan = document.createElement('span');
      dateSpan.className = 'tm-cp-date';
      dateSpan.textContent = entry.entry_date;
      const deleteBtn = document.createElement('button');
      deleteBtn.className = 'tm-cp-delete';
      deleteBtn.textContent = '×';
      deleteBtn.addEventListener('click', async () => {
        try {
          const r = await bgFetch(`${tmApiUrl}/api/commentary/${entry.id}`, {
            method: 'DELETE',
            signal: AbortSignal.timeout(5000),
          });
          if (r.ok || r.status === 204) renderCommentaryThread(tradeId, panel);
        } catch (e) { /* silent */ }
      });
      headerEl.appendChild(dateSpan);
      headerEl.appendChild(deleteBtn);
      entryEl.appendChild(headerEl);

      const noteP = document.createElement('p');
      noteP.className = 'tm-cp-note-text';
      noteP.textContent = entry.note;
      entryEl.appendChild(noteP);

      if (entry.tags && entry.tags.length > 0) {
        const tagsRow = document.createElement('div');
        tagsRow.className = 'tm-cp-tags-row';
        entry.tags.forEach(t => {
          const tagSpan = document.createElement('span');
          tagSpan.className = 'tm-cp-tag';
          tagSpan.textContent = t;
          tagsRow.appendChild(tagSpan);
        });
        entryEl.appendChild(tagsRow);
      }

      if (entry.rationale) {
        entryEl.appendChild(buildRationaleChip(entry.rationale));
      }

      threadEl.appendChild(entryEl);
    });

  } catch (e) {
    if (e.name !== 'AbortError') {
      threadEl.innerHTML = '<p class="tm-cp-fetch-error">Failed to load notes.</p>';
    }
  }
}

async function fetchRsiForAll() {
  const btn = document.getElementById('tm-rsi-btn');
  const tickers = [...seenTickers];
  if (!tickers.length) return;

  if (btn) { btn.disabled = true; btn.textContent = '⏳ Fetching…'; }

  try {
    const resp = await bgFetch(`${tmApiUrl}/api/market/rsi`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ tickers }),
      signal: AbortSignal.timeout(60000),
    });

    if (resp.ok) {
      const data = await resp.json();
      Object.entries(data).forEach(([ticker, val]) => {
        const rsi = val && typeof val === 'object' ? val.rsi : null;
        rsiCache.set(ticker, typeof rsi === 'number' ? rsi : null);
      });
    }
  } catch (err) {
    if (err.name !== 'AbortError') console.debug('TradeMinder RSI fetch failed:', err.message);
  }

  // Re-apply RSI to all currently visible rows
  document.querySelectorAll(ETRADE.positionRows).forEach(row => {
    const info = getRowInfo(row);
    if (info?.ticker) applyRsiToRow(row, info.ticker);
  });

  if (btn) { btn.disabled = false; btn.textContent = '🔄 Refresh RSI'; }
}

// Fetches all active sessions (any ticker/strategy) once per page load and
// builds an etrade_symbol → session index for exact row-to-session matching.
async function fetchAllActiveSessions(force = false) {
  if (!force && activeSessionsFetchedAt && (Date.now() - activeSessionsFetchedAt < ACTIVE_SESSIONS_TTL)) return;
  try {
    const res = await fetch(
      `${tmApiUrl}/api/sessions/active`,
      { signal: AbortSignal.timeout(5000) },
    );
    if (!res.ok) { activeSessionsFetchedAt = Date.now(); return; }
    const sessions = await res.json();
    allActiveSessions = sessions;
    const index = new Map();
    for (const session of sessions) {
      for (const leg of session.legs || []) {
        if (leg.etrade_symbol && leg.status === 'open') index.set(leg.etrade_symbol.toUpperCase(), session);
      }
    }
    etradeSymbolIndex = index;
    activeSessionsFetchedAt = Date.now();
  } catch {
    activeSessionsFetchedAt = Date.now();
  }
}

async function fetchWheelActiveSlots(force = false) {
  if (!force && wheelSlotsFetchedAt && (Date.now() - wheelSlotsFetchedAt < WHEEL_SLOTS_TTL)) return;
  try {
    const res = await fetch(`${tmApiUrl}/api/wheel/active-slots`, { signal: AbortSignal.timeout(5000) });
    if (!res.ok) { wheelSlotsFetchedAt = Date.now(); return; }
    wheelActiveSlots = await res.json();
    wheelSlotsFetchedAt = Date.now();
  } catch {
    wheelSlotsFetchedAt = Date.now();
  }
}

async function fetchPricesForSpreadSessions() {
  const spreadTickers = [...new Set(
    allActiveSessions
      .filter(s => s.strategy === 'IRON_CONDOR' || s.strategy === 'PUT_B_W_FLY')
      .map(s => s.ticker.toUpperCase()),
  )];
  await Promise.all(spreadTickers.map(async ticker => {
    if (priceCache.has(ticker)) return;
    try {
      const res = await fetch(
        `${tmApiUrl}/api/market/quote/${encodeURIComponent(ticker)}`,
        { signal: AbortSignal.timeout(5000) },
      );
      if (!res.ok) { priceCache.set(ticker, null); return; }
      const data = await res.json();
      priceCache.set(ticker, typeof data.price === 'number' ? data.price : null);
    } catch {
      priceCache.set(ticker, null);
    }
  }));
}

// ============================================================
// FILTER TOOLBAR
// ============================================================
function insertFilterToolbar() {
  if (document.getElementById('tm-toolbar')) return;
  const gridRoot = document.querySelector(ETRADE.gridRoot);
  if (!gridRoot?.parentNode) return;

  const toolbar = document.createElement('div');
  toolbar.id = 'tm-toolbar';

  const label = document.createElement('span');
  label.className = 'tm-filter-label';
  label.textContent = 'TradeMinder:';
  toolbar.appendChild(label);

  // "All" button
  const allBtn = makeFilterBtn('All', 'all');
  allBtn.classList.add('active');
  toolbar.appendChild(allBtn);

  // Category buttons
  allCategories.forEach(cat => {
    toolbar.appendChild(makeFilterBtn(`${cat.icon || ''} ${cat.name}`.trim(), cat.name));
  });

  // Divider
  const sep = document.createElement('span');
  sep.style.cssText = 'width:1px;height:16px;background:#e2e8f0;margin:0 4px;display:inline-block;vertical-align:middle';
  toolbar.appendChild(sep);

  // RSI fetch button
  const rsiBtn = document.createElement('button');
  rsiBtn.id = 'tm-rsi-btn';
  rsiBtn.className = 'tm-rsi-btn';
  rsiBtn.textContent = '📊 Fetch RSI';
  rsiBtn.addEventListener('click', fetchRsiForAll);
  toolbar.appendChild(rsiBtn);

  gridRoot.parentNode.insertBefore(toolbar, gridRoot);
}

function insertReconcileButton() {
  if (document.getElementById('tm-reconcile-btn')) return;

  const targets = document.querySelectorAll('.PortfoliosFilters---customize-view---Ln4bT');
  const target = Array.from(targets).find(el => el.offsetParent !== null);
  if (!target?.parentNode) {
    setTimeout(insertReconcileButton, 500);
    return;
  }

  const wrap = document.createElement('div');
  wrap.id = 'tm-reconcile-btn-wrap';
  wrap.style.cssText = 'display:inline-block;margin-right:8px;';

  const btn = document.createElement('button');
  btn.id = 'tm-reconcile-btn';
  btn.className = 'btn-block btn-link';
  btn.type = 'button';
  btn.textContent = '🔄 Reconcile';

  btn.addEventListener('click', async () => {
    btn.disabled = true;
    btn.textContent = '⏳ Reconciling…';

    const rows = document.querySelectorAll(ETRADE.positionRows);
    const data = await fireReconcile(rows);

    if (data === null) {
      btn.textContent = '✗ Failed';
    } else {
      const n = (data.unmatched_etrade || []).length;
      btn.textContent = n === 0 ? '✓ All matched' : `⚠ ${n} unmatched`;
    }

    setTimeout(() => {
      btn.disabled = false;
      btn.textContent = '🔄 Reconcile';
    }, 2000);
  });

  wrap.appendChild(btn);
  target.parentNode.insertBefore(wrap, target);
}

function makeFilterBtn(label, filterValue) {
  const btn = document.createElement('button');
  btn.className = 'tm-filter-btn';
  btn.textContent = label;
  btn.dataset.filter = filterValue;
  btn.addEventListener('click', () => {
    activeFilter = filterValue;
    document.querySelectorAll('.tm-filter-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    applyFiltersToAll();
  });
  return btn;
}

function applyFilter(row, status) {
  if (activeFilter === 'all') {
    row.style.display = '';
    return;
  }
  const catName = status?.category_name || '';
  row.style.display = catName === activeFilter ? '' : 'none';
}

function applyFiltersToAll() {
  document.querySelectorAll(ETRADE.positionRows).forEach(row => {
    const rowId = row.id;
    const cacheKey = processedRows.get(rowId);
    if (!cacheKey) return;
    const status = statusCache.get(cacheKey) || null;
    applyFilter(row, status);
  });
}

// ============================================================
// RIGHT-CLICK CONTEXT MENU — inform background of row state
// ============================================================
document.addEventListener('contextmenu', (e) => {
  const row = e.target.closest(ETRADE.positionRows);
  if (!row) return;

  const info = getRowInfo(row);
  if (!info) return;

  const cacheKey = info.fullSymbol || info.ticker;
  const status = statusCache.get(cacheKey) || null;
  const isTracked = !!(status && status.trade_id);

  chrome.runtime.sendMessage({
    type: 'ROW_CONTEXT',
    isTracked,
    info: {
      ticker: info.ticker,
      isOption: info.isOption,
      isITM: info.isITM,
      fullSymbol: info.fullSymbol || null,
      type: info.optionDetails?.type || null,
      strike: info.optionDetails?.strike || null,
      expiry: info.optionDetails?.expiry || null,
      dte: info.optionDetails?.dte || null,
      quantity: info.quantity || null,
      pricePaid: info.pricePaid || null,
      tradeId: status?.trade_id || null,
    },
  });
}, true);

// Handle message from background to show modal
chrome.runtime.onMessage.addListener((message) => {
  if (message.type === 'SHOW_ADD_MODAL') {
    showAddTradeModal(message.info || {});
  }
  if (message.type === 'SHOW_EDIT_MODAL') {
    showEditTradeModal(message.info || {});
  }
});

// ============================================================
// CATEGORY HELPERS
// ============================================================
async function fetchCategories() {
  try {
    const resp = await bgFetch(`${tmApiUrl}/api/categories`, { signal: AbortSignal.timeout(5000) });
    if (!resp.ok) return [];
    return await resp.json();
  } catch (_) {
    return [];
  }
}

function buildCategoryOptions(categories, selectedValue = 'WHEEL') {
  if (categories.length === 0) {
    return '<option value="" disabled selected>(categories unavailable)</option>';
  }
  return categories
    .map(c => `<option value="${c.name}"${c.name === selectedValue ? ' selected' : ''}>${c.name}</option>`)
    .join('');
}

// ============================================================
// SESSION DROPDOWN HELPERS (shared by add-trade & edit-trade)
// ============================================================
const WHEEL_STATUS_LABELS = {
  put_open: 'Put Open',
  shares_sitting: 'Shares Sitting',
  cc_open: 'CC Open',
  called_away: 'Called Away',
  completed: 'Completed',
};

function rebuildSessionDropdown(selectEl, sessions, strategy) {
  const isCC = strategy === 'Sell Call' || strategy === 'Covered Call';
  const isPut = strategy === 'Sell Put';

  const filtered = sessions.filter(s => {
    if (s.strategy === 'WHEEL') {
      if (isCC) return s.status === 'shares_sitting';
      if (isPut) return s.status === 'called_away';
      return false;
    }
    if (s.strategy === 'IRON_CONDOR' || s.strategy === 'PUT_B_W_FLY') {
      return !isCC;
    }
    return false;
  });

  const options = filtered.map(s => {
    let label;
    if (s.strategy === 'WHEEL') {
      const statusLabel = WHEEL_STATUS_LABELS[s.status] || s.status;
      label = `WHL · ${s.ticker} · ${statusLabel} · opened ${s.opened_at}`;
    } else {
      const tag = s.strategy === 'IRON_CONDOR' ? 'IC' : 'PBWB';
      label = `${tag} · ${s.ticker} · opened ${s.opened_at}`;
    }
    return `<option value="${s.id}">${label}</option>`;
  });

  const newOptions = [];
  if (isCC || isPut) {
    newOptions.push('<option value="__new_WHEEL__">→ New Wheel Session</option>');
  }
  if (!isCC) {
    newOptions.push('<option value="__new_IC__">→ New Iron Condor Session</option>');
    newOptions.push('<option value="__new_PBWB__">→ New Put BWB Session</option>');
  }

  selectEl.innerHTML =
    '<option value="">— None —</option>' +
    options.join('') +
    newOptions.join('');
}

function getSessionStrategyFromValue(value, sessions) {
  if (value === '__new_WHEEL__') return 'WHEEL';
  if (value === '__new_IC__') return 'IRON_CONDOR';
  if (value === '__new_PBWB__') return 'PUT_B_W_FLY';
  const match = sessions.find(s => String(s.id) === value);
  return match ? match.strategy : null;
}

// ============================================================
// ADD TRADE MODAL
// ============================================================
async function showAddTradeModal(info) {
  const categories = await fetchCategories();
  if (document.getElementById('tm-modal-overlay')) return; // already open
  let tickerSessions = [];

  const overlay = document.createElement('div');
  overlay.id = 'tm-modal-overlay';

  const today = new Date().toISOString().split('T')[0];

  // Derive sensible defaults from DOM info
  const defaultType = info.isOption ? 'Sell' : 'Buy';
  const defaultStrategy = info.isOption
    ? (info.type === 'Put' ? 'Sell Put' : 'Sell Call')
    : 'Stock';

  overlay.innerHTML = `
    <div id="tm-modal">
      <div id="tm-modal-header">
        <span id="tm-modal-title">Add to TradeMinder</span>
        <button id="tm-modal-close" title="Close">✕</button>
      </div>
      <form id="tm-modal-form" autocomplete="off">
        <div class="tm-field-row">
          <label>Ticker</label>
          <input type="text" name="ticker" value="${info.ticker || ''}" required />
        </div>
        <div class="tm-field-row">
          <label>Type (Sell/Buy)</label>
          <select name="type">
            <option value="Sell" ${defaultType === 'Sell' ? 'selected' : ''}>Sell</option>
            <option value="Buy" ${defaultType === 'Buy' ? 'selected' : ''}>Buy</option>
          </select>
        </div>
        <div class="tm-field-row tm-field-full">
          <label>Strategy <span class="tm-required">*</span></label>
          <select name="strategy">
            <option value="Sell Put" ${defaultStrategy === 'Sell Put' ? 'selected' : ''}>Sell Put</option>
            <option value="Sell Call" ${defaultStrategy === 'Sell Call' ? 'selected' : ''}>Sell Call</option>
            <option value="Buy Put" ${defaultStrategy === 'Buy Put' ? 'selected' : ''}>Buy Put</option>
            <option value="Buy Call" ${defaultStrategy === 'Buy Call' ? 'selected' : ''}>Buy Call</option>
            <option value="Put Credit Spread" ${defaultStrategy === 'Put Credit Spread' ? 'selected' : ''}>Put Credit Spread</option>
            <option value="Call Credit Spread">Call Credit Spread</option>
            <option value="Covered Call" ${defaultStrategy === 'Covered Call' ? 'selected' : ''}>Covered Call</option>
            <option value="Stock" ${defaultStrategy === 'Stock' ? 'selected' : ''}>Stock</option>
          </select>
        </div>
        <div class="tm-field-row tm-field-full">
          <label>Category <span class="tm-required">*</span></label>
          <select name="category">
            ${buildCategoryOptions(categories, 'WHEEL')}
          </select>
        </div>
        ${info.isOption ? `
        <div class="tm-field-row tm-field-full" id="tm-session-row">
          <label>Session <span style="font-weight:normal;color:#6B7280">(optional)</span></label>
          <select name="session_id" id="tm-session-select">
            <option value="">— None —</option>
          </select>
        </div>` : ''}
        <div class="tm-field-row">
          <label>Strike</label>
          <input type="number" name="strike_price" step="0.01" value="${info.strike != null ? info.strike : ''}" placeholder="optional" />
        </div>
        <div class="tm-field-row">
          <label>Expiry</label>
          <input type="date" name="expiry_date" value="${info.expiry || ''}" />
        </div>
        <div class="tm-field-row">
          <label>Qty</label>
          <input type="number" name="quantity" min="1" step="1" value="${info.quantity != null ? info.quantity : 1}" required />
        </div>
        <div class="tm-field-row">
          <label>Premium <span class="tm-required">*</span></label>
          <input type="number" name="premium" step="0.01" min="0" value="${info.pricePaid != null ? Math.round(info.pricePaid * 100) / 100 : ''}" placeholder="0.00" required />
        </div>
        <div class="tm-field-row">
          <label>Open Date</label>
          <input type="date" name="open_date" value="${today}" required />
        </div>
        <div class="tm-field-row tm-field-full">
          <label>Exit Strategy</label>
          <input type="text" name="exit_strategy" placeholder="e.g. Close at 50% profit" />
        </div>
        <div class="tm-field-row tm-field-full">
          <label>Notes</label>
          <textarea name="rationale_notes" rows="2" placeholder="Why are you entering this trade?"></textarea>
        </div>
        <div class="tm-tech-section">
          <button type="button" class="tm-tech-toggle" id="tm-modal-tech-toggle">▼ Attach Technicals (optional)</button>
          <div id="tm-modal-tech-container" class="tm-hidden"></div>
        </div>
        <div id="tm-modal-error" class="tm-hidden"></div>
        <div id="tm-modal-actions">
          <button type="button" id="tm-modal-cancel">Cancel</button>
          <button type="submit" id="tm-modal-submit">Add Trade</button>
        </div>
      </form>
    </div>`;

  document.body.appendChild(overlay);

  // Populate session picker for option rows (WHEEL, IC, PBWB)
  if (info.isOption) {
    const sessionSelect = overlay.querySelector('#tm-session-select');
    const strategySelect = overlay.querySelector('[name="strategy"]');
    const categorySelect = overlay.querySelector('[name="category"]');
    const ticker = (info.ticker || '').toUpperCase();

    await fetchAllActiveSessions(true);
    tickerSessions = allActiveSessions.filter(
      s => s.ticker.toUpperCase() === ticker,
    );

    rebuildSessionDropdown(sessionSelect, tickerSessions, strategySelect.value);

    strategySelect.addEventListener('change', () => {
      rebuildSessionDropdown(sessionSelect, tickerSessions, strategySelect.value);
    });

    sessionSelect.addEventListener('change', () => {
      const strat = getSessionStrategyFromValue(sessionSelect.value, tickerSessions);
      if (strat) {
        const catMap = { WHEEL: 'WHEEL', IRON_CONDOR: 'IRON_CONDOR', PUT_B_W_FLY: 'PUT_B_W_FLY' };
        const catName = catMap[strat];
        if (catName) {
          const catOption = categorySelect.querySelector(`option[value="${catName}"]`);
          if (catOption) categorySelect.value = catName;
        }
      }
    });
  }

  const closeModal = () => overlay.remove();
  overlay.querySelector('#tm-modal-close').addEventListener('click', closeModal);
  overlay.querySelector('#tm-modal-cancel').addEventListener('click', closeModal);
  overlay.addEventListener('click', (e) => { if (e.target === overlay) closeModal(); });

  // Wire technicals toggle for add-trade modal
  let techFormControl = null;
  const techToggle = overlay.querySelector('#tm-modal-tech-toggle');
  const techContainer = overlay.querySelector('#tm-modal-tech-container');
  if (techToggle && techContainer) {
    techToggle.addEventListener('click', () => {
      const isOpen = !techContainer.classList.contains('tm-hidden');
      if (isOpen) {
        techContainer.classList.add('tm-hidden');
        techToggle.textContent = '▼ Attach Technicals (optional)';
      } else {
        if (!techFormControl) {
          techFormControl = renderTechnicalsForm(techContainer, info.ticker);
        }
        techContainer.classList.remove('tm-hidden');
        techToggle.textContent = '▲ Hide Technicals';
      }
    });
  }

  overlay.querySelector('#tm-modal-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const errorEl = overlay.querySelector('#tm-modal-error');
    const submitBtn = overlay.querySelector('#tm-modal-submit');
    errorEl.classList.add('tm-hidden');
    submitBtn.disabled = true;
    submitBtn.textContent = 'Adding…';

    const fd = new FormData(e.target);
    const strike_price = fd.get('strike_price') ? parseFloat(fd.get('strike_price')) : null;
    const expiry_date = fd.get('expiry_date') || null;
    const payload = {
      ticker: fd.get('ticker').trim().toUpperCase(),
      type: fd.get('type'),
      strategy: fd.get('strategy'),
      category: fd.get('category'),
      quantity: parseInt(fd.get('quantity'), 10),
      premium: parseFloat(fd.get('premium')),
      open_date: fd.get('open_date'),
      ...(strike_price != null && { strike_price }),
      ...(expiry_date && { expiry_date }),
      // Store the E*TRADE full symbol (e.g. "AAPL--260508C00290000") so future
      // position lookups can match directly instead of reconstructing from fields.
      ...(info.fullSymbol && { etrade_symbol: info.fullSymbol }),
      ...(fd.get('exit_strategy') && { exit_strategy: fd.get('exit_strategy').trim() }),
      ...(fd.get('rationale_notes')?.trim() && { rationale_notes: fd.get('rationale_notes').trim() }),
    };

    // Resolve session_id: create a new session if requested, or use existing
    let resolvedSessionId = null;
    let resolvedSessionStrategy = null;
    const rawSession = info.isOption ? (fd.get('session_id') || '') : '';
    if (rawSession && !rawSession.startsWith('__new_')) {
      resolvedSessionId = rawSession;
      resolvedSessionStrategy = getSessionStrategyFromValue(rawSession, tickerSessions);
    } else if (rawSession.startsWith('__new_')) {
      if (rawSession === '__new_WHEEL__') {
        const wheelStatus = (fd.get('strategy') === 'Sell Put') ? 'put_open' : 'cc_open';
        const sessionResp = await fetch(`${tmApiUrl}/api/sessions`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            ticker: payload.ticker,
            strategy: 'WHEEL',
            status: wheelStatus,
            opened_at: payload.open_date,
          }),
          signal: AbortSignal.timeout(8000),
        });
        if (!sessionResp.ok) {
          const err = await sessionResp.json().catch(() => ({}));
          throw new Error(err.detail || 'Failed to create session');
        }
        const newSession = await sessionResp.json();
        resolvedSessionId = newSession.id;
        resolvedSessionStrategy = 'WHEEL';
      } else {
        const strategy = rawSession === '__new_IC__' ? 'IRON_CONDOR' : 'PUT_B_W_FLY';
        const sessionResp = await fetch(`${tmApiUrl}/api/sessions`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            ticker: payload.ticker,
            strategy,
            status: 'open',
            opened_at: payload.open_date,
          }),
          signal: AbortSignal.timeout(8000),
        });
        if (!sessionResp.ok) {
          const err = await sessionResp.json().catch(() => ({}));
          throw new Error(err.detail || 'Failed to create session');
        }
        const newSession = await sessionResp.json();
        resolvedSessionId = newSession.id;
        resolvedSessionStrategy = strategy;
      }
    }
    if (resolvedSessionId) payload.session_id = resolvedSessionId;

    try {
      const resp = await fetch(`${tmApiUrl}/api/trades`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
        signal: AbortSignal.timeout(8000),
      });

      if (!resp.ok) {
        const err = await resp.json().catch(() => ({}));
        throw new Error(err.detail || `HTTP ${resp.status}`);
      }

      const trade = await resp.json();

      // Auto-transition WHEEL session status when a leg is attached
      if (resolvedSessionId && resolvedSessionStrategy === 'WHEEL') {
        const tradeStrategy = fd.get('strategy');
        const selectedSession = tickerSessions.find(s => String(s.id) === resolvedSessionId);
        let newStatus = null;
        if ((tradeStrategy === 'Sell Call' || tradeStrategy === 'Covered Call')
          && selectedSession?.status === 'shares_sitting') {
          newStatus = 'cc_open';
        } else if (tradeStrategy === 'Sell Put' && selectedSession?.status === 'called_away') {
          newStatus = 'put_open';
        }
        if (newStatus) {
          try {
            await fetch(`${tmApiUrl}/api/sessions/${resolvedSessionId}`, {
              method: 'PATCH',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ status: newStatus }),
              signal: AbortSignal.timeout(5000),
            });
          } catch (e) {
            console.debug('[TM] session auto-transition failed:', e.message);
          }
        }
      }

      // Save technicals snapshot if user fetched them
      const techSnapshot = techFormControl ? techFormControl.getValue() : null;
      if (techSnapshot) {
        try {
          await bgFetch(`${tmApiUrl}/api/trades/${trade.id}/rationale`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(techSnapshot),
            signal: AbortSignal.timeout(10000),
          });
        } catch (e) {
          console.debug('[TM] technicals save failed:', e.message);
          // Non-fatal — trade was already created
        }
      }

      // Invalidate cache so the row refreshes
      const cacheKey = info.fullSymbol || info.ticker;
      statusCache.delete(cacheKey);
      if (info.ticker) statusCache.delete(info.ticker);
      processedRows.forEach((val, key) => {
        if (val === cacheKey || val === info.ticker) processedRows.delete(key);
      });
      // Refresh active sessions + wheel slots so the new/updated session's legs are indexed
      await Promise.all([fetchAllActiveSessions(true), fetchWheelActiveSlots(true)]);
      processVisibleRows();
      closeModal();

    } catch (err) {
      errorEl.textContent = err.message || 'Failed to add trade';
      errorEl.classList.remove('tm-hidden');
      submitBtn.disabled = false;
      submitBtn.textContent = 'Add Trade';
    }
  });
}

// ============================================================
// EDIT TRADE MODAL
// ============================================================
async function showEditTradeModal(info) {
  if (document.getElementById('tm-modal-overlay')) return;

  // 1. Look up the trade by etrade_symbol or ticker fallback
  let tradeId;
  let trade;
  try {
    const searchUrl = info.fullSymbol
      ? `${tmApiUrl}/api/trades?etrade_symbol=${encodeURIComponent(info.fullSymbol)}`
      : `${tmApiUrl}/api/trades?ticker=${encodeURIComponent(info.ticker || '')}&status=open`;
    const searchResp = await bgFetch(searchUrl, { signal: AbortSignal.timeout(6000) });
    if (!searchResp.ok) throw new Error(`HTTP ${searchResp.status}`);
    const matches = await searchResp.json();
    if (!matches.length) {
      alert('Trade not found in TradeMinder. Add it first via "Add to TradeMinder".');
      return;
    }
    tradeId = matches[0].id;
  } catch (err) {
    alert('Could not reach TradeMinder backend: ' + (err.message || 'unknown error'));
    return;
  }

  // 2. Fetch full trade detail (includes rationale.notes)
  try {
    const detailResp = await bgFetch(`${tmApiUrl}/api/trades/${tradeId}`, { signal: AbortSignal.timeout(6000) });
    if (!detailResp.ok) throw new Error(`HTTP ${detailResp.status}`);
    trade = await detailResp.json();
  } catch (err) {
    alert('Failed to load trade details: ' + (err.message || 'unknown error'));
    return;
  }

  // 3. Fetch categories for the dropdown
  const categories = await fetchCategories();

  // 4. Render modal
  const overlay = document.createElement('div');
  overlay.id = 'tm-modal-overlay';

  overlay.innerHTML = `
    <div id="tm-modal">
      <div id="tm-modal-header">
        <span id="tm-modal-title">✏️ Edit Trade — ${trade.ticker}</span>
        <button id="tm-modal-close" title="Close">✕</button>
      </div>
      <form id="tm-modal-form" autocomplete="off">
        <div class="tm-field-row">
          <label>Type</label>
          <select name="type">
            <option value="Sell" ${trade.type === 'Sell' ? 'selected' : ''}>Sell</option>
            <option value="Buy" ${trade.type === 'Buy' ? 'selected' : ''}>Buy</option>
            <option value="Assigned" ${trade.type === 'Assigned' ? 'selected' : ''}>Assigned</option>
          </select>
        </div>
        <div class="tm-field-row">
          <label>Strategy</label>
          <select name="strategy">
            ${!['Sell Put', 'Sell Call', 'Buy Put', 'Buy Call', 'Put Credit Spread', 'Call Credit Spread', 'Covered Call', 'Stock'].includes(trade.strategy)
      ? `<option value="${trade.strategy}" selected>${trade.strategy}</option>`
      : ''}
            <option value="Sell Put" ${trade.strategy === 'Sell Put' ? 'selected' : ''}>Sell Put</option>
            <option value="Sell Call" ${trade.strategy === 'Sell Call' ? 'selected' : ''}>Sell Call</option>
            <option value="Buy Put" ${trade.strategy === 'Buy Put' ? 'selected' : ''}>Buy Put</option>
            <option value="Buy Call" ${trade.strategy === 'Buy Call' ? 'selected' : ''}>Buy Call</option>
            <option value="Put Credit Spread" ${trade.strategy === 'Put Credit Spread' ? 'selected' : ''}>Put Credit Spread</option>
            <option value="Call Credit Spread" ${trade.strategy === 'Call Credit Spread' ? 'selected' : ''}>Call Credit Spread</option>
            <option value="Covered Call" ${trade.strategy === 'Covered Call' ? 'selected' : ''}>Covered Call</option>
            <option value="Stock" ${trade.strategy === 'Stock' ? 'selected' : ''}>Stock</option>
          </select>
        </div>
        <div class="tm-field-row tm-field-full">
          <label>Category <span class="tm-required">*</span></label>
          <select name="category">
            ${buildCategoryOptions(categories, trade.category || 'WHEEL')}
          </select>
        </div>
        <div class="tm-field-row tm-field-full" id="tm-session-row">
          <label>Session <span style="font-weight:normal;color:#6B7280">(optional)</span></label>
          <select name="session_id" id="tm-session-select">
            <option value="">— None —</option>
          </select>
        </div>
        <div class="tm-field-row">
          <label>Strike</label>
          <input type="number" name="strike_price" step="0.01" value="${trade.strike_price != null ? trade.strike_price : ''}" placeholder="optional" />
        </div>
        <div class="tm-field-row">
          <label>Expiry</label>
          <input type="date" name="expiry_date" value="${trade.expiry_date || ''}" />
        </div>
        <div class="tm-field-row">
          <label>Qty</label>
          <input type="number" name="quantity" min="1" step="1" value="${trade.quantity}" required />
        </div>
        <div class="tm-field-row">
          <label>Premium</label>
          <input type="number" name="premium" step="0.01" min="0" value="${trade.premium != null ? trade.premium : ''}" placeholder="0.00" />
        </div>
        <div class="tm-field-row tm-field-full">
          <label>Exit Strategy</label>
          <input type="text" name="exit_strategy" value="${escapeHtml(trade.exit_strategy)}" placeholder="e.g. Close at 50% profit" />
        </div>
        <div class="tm-field-row tm-field-full">
          <label>Notes</label>
          <textarea name="rationale_notes" rows="2">${escapeHtml(trade.rationale?.notes)}</textarea>
        </div>
        <div id="tm-modal-error" class="tm-hidden"></div>
        <div id="tm-modal-actions">
          <button type="button" id="tm-modal-cancel">Cancel</button>
          <button type="submit" id="tm-modal-submit">Save Changes</button>
        </div>
      </form>
    </div>`;

  document.body.appendChild(overlay);

  // Populate session picker
  let tickerSessions = [];
  {
    const sessionSelect = overlay.querySelector('#tm-session-select');
    const strategySelect = overlay.querySelector('[name="strategy"]');
    const categorySelect = overlay.querySelector('[name="category"]');
    const ticker = (trade.ticker || '').toUpperCase();

    await fetchAllActiveSessions(true);
    tickerSessions = allActiveSessions.filter(
      s => s.ticker.toUpperCase() === ticker,
    );

    rebuildSessionDropdown(sessionSelect, tickerSessions, strategySelect.value);

    // Pre-select current session if trade is linked
    if (trade.session_id) {
      const currentId = String(trade.session_id);
      const exists = sessionSelect.querySelector(`option[value="${currentId}"]`);
      if (exists) {
        sessionSelect.value = currentId;
      } else {
        // Session exists but filtered out (different status) — add as disabled option
        const s = allActiveSessions.find(s => String(s.id) === currentId);
        if (s) {
          const tag = s.strategy === 'WHEEL' ? 'WHL'
            : s.strategy === 'IRON_CONDOR' ? 'IC' : 'PBWB';
          const lbl = s.strategy === 'WHEEL'
            ? `${tag} · ${s.ticker} · ${WHEEL_STATUS_LABELS[s.status] || s.status} · opened ${s.opened_at}`
            : `${tag} · ${s.ticker} · opened ${s.opened_at}`;
          const opt = document.createElement('option');
          opt.value = currentId;
          opt.textContent = lbl;
          sessionSelect.insertBefore(opt, sessionSelect.options[1]);
          sessionSelect.value = currentId;
        }
      }
    }

    strategySelect.addEventListener('change', () => {
      const prevValue = sessionSelect.value;
      rebuildSessionDropdown(sessionSelect, tickerSessions, strategySelect.value);
      // Restore selection if it's still in the rebuilt list
      const stillExists = sessionSelect.querySelector(`option[value="${prevValue}"]`);
      if (stillExists) sessionSelect.value = prevValue;
    });

    sessionSelect.addEventListener('change', () => {
      const strat = getSessionStrategyFromValue(sessionSelect.value, tickerSessions);
      if (strat) {
        const catMap = { WHEEL: 'WHEEL', IRON_CONDOR: 'IRON_CONDOR', PUT_B_W_FLY: 'PUT_B_W_FLY' };
        const catName = catMap[strat];
        if (catName) {
          const catOption = categorySelect.querySelector(`option[value="${catName}"]`);
          if (catOption) categorySelect.value = catName;
        }
      }
    });
  }

  const closeModal = () => overlay.remove();
  overlay.querySelector('#tm-modal-close').addEventListener('click', closeModal);
  overlay.querySelector('#tm-modal-cancel').addEventListener('click', closeModal);
  overlay.addEventListener('click', (e) => { if (e.target === overlay) closeModal(); });

  overlay.querySelector('#tm-modal-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const errorEl = overlay.querySelector('#tm-modal-error');
    const submitBtn = overlay.querySelector('#tm-modal-submit');
    errorEl.classList.add('tm-hidden');
    submitBtn.disabled = true;
    submitBtn.textContent = 'Saving…';

    const fd = new FormData(e.target);
    const strike_price = fd.get('strike_price') ? parseFloat(fd.get('strike_price')) : null;
    const expiry_date = fd.get('expiry_date') || null;
    const premium = fd.get('premium') ? parseFloat(fd.get('premium')) : null;
    const payload = {
      type: fd.get('type'),
      strategy: fd.get('strategy'),
      category: fd.get('category'),
      quantity: parseInt(fd.get('quantity'), 10),
      exit_strategy: fd.get('exit_strategy') || null,
      rationale_notes: fd.get('rationale_notes')?.trim() || null,
      ...(strike_price != null && { strike_price }),
      ...(expiry_date && { expiry_date }),
      ...(premium != null && { premium }),
    };

    // Resolve session_id: create new if sentinel, use existing if UUID, omit if unchanged
    const rawSession = fd.get('session_id') || '';
    let resolvedSessionId = null;
    let resolvedSessionStrategy = null;
    const sessionChanged = rawSession !== String(trade.session_id || '');

    if (sessionChanged && rawSession && !rawSession.startsWith('__new_')) {
      resolvedSessionId = rawSession;
      resolvedSessionStrategy = getSessionStrategyFromValue(rawSession, tickerSessions);
      payload.session_id = resolvedSessionId;
    } else if (rawSession.startsWith('__new_')) {
      if (rawSession === '__new_WHEEL__') {
        const wheelStatus = (fd.get('strategy') === 'Sell Put') ? 'put_open' : 'cc_open';
        const sessionResp = await fetch(`${tmApiUrl}/api/sessions`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            ticker: payload.ticker || trade.ticker.toUpperCase(),
            strategy: 'WHEEL',
            status: wheelStatus,
            opened_at: trade.open_date,
          }),
          signal: AbortSignal.timeout(8000),
        });
        if (!sessionResp.ok) {
          const err = await sessionResp.json().catch(() => ({}));
          throw new Error(err.detail || 'Failed to create session');
        }
        const newSession = await sessionResp.json();
        resolvedSessionId = newSession.id;
        resolvedSessionStrategy = 'WHEEL';
        payload.session_id = resolvedSessionId;
      } else {
        const strategy = rawSession === '__new_IC__' ? 'IRON_CONDOR' : 'PUT_B_W_FLY';
        const sessionResp = await fetch(`${tmApiUrl}/api/sessions`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            ticker: payload.ticker || trade.ticker.toUpperCase(),
            strategy,
            status: 'open',
            opened_at: trade.open_date,
          }),
          signal: AbortSignal.timeout(8000),
        });
        if (!sessionResp.ok) {
          const err = await sessionResp.json().catch(() => ({}));
          throw new Error(err.detail || 'Failed to create session');
        }
        const newSession = await sessionResp.json();
        resolvedSessionId = newSession.id;
        resolvedSessionStrategy = strategy;
        payload.session_id = resolvedSessionId;
      }
    }

    try {
      const resp = await fetch(`${tmApiUrl}/api/trades/${tradeId}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
        signal: AbortSignal.timeout(8000),
      });

      if (!resp.ok) {
        const err = await resp.json().catch(() => ({}));
        throw new Error(err.detail || `HTTP ${resp.status}`);
      }

      // Auto-transition WHEEL session status when a leg is attached
      if (resolvedSessionId && resolvedSessionStrategy === 'WHEEL') {
        const tradeStrategy = fd.get('strategy');
        const selectedSession = tickerSessions.find(s => String(s.id) === resolvedSessionId);
        let newStatus = null;
        if ((tradeStrategy === 'Sell Call' || tradeStrategy === 'Covered Call')
          && selectedSession?.status === 'shares_sitting') {
          newStatus = 'cc_open';
        } else if (tradeStrategy === 'Sell Put' && selectedSession?.status === 'called_away') {
          newStatus = 'put_open';
        }
        if (newStatus) {
          try {
            await fetch(`${tmApiUrl}/api/sessions/${resolvedSessionId}`, {
              method: 'PATCH',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ status: newStatus }),
              signal: AbortSignal.timeout(5000),
            });
          } catch (e) {
            console.debug('[TM] session auto-transition failed:', e.message);
          }
        }
      }

      // Invalidate cache so the row badge refreshes
      const cacheKey = info.fullSymbol || info.ticker;
      statusCache.delete(cacheKey);
      if (info.ticker) statusCache.delete(info.ticker);
      processedRows.forEach((val, key) => {
        if (val === cacheKey || val === info.ticker) processedRows.delete(key);
      });
      await Promise.all([fetchAllActiveSessions(true), fetchWheelActiveSlots(true)]);
      processVisibleRows();
      closeModal();

    } catch (err) {
      errorEl.textContent = err.message || 'Failed to save changes';
      errorEl.classList.remove('tm-hidden');
      submitBtn.disabled = false;
      submitBtn.textContent = 'Save Changes';
    }
  });
}

// ============================================================
// MUTATION OBSERVER — virtual scroll handler
// ============================================================
function startObserver() {
  const contentArea = document.querySelector(ETRADE.contentArea);
  if (!contentArea) {
    setTimeout(startObserver, 500);
    return;
  }

  // Grid is in the DOM — safe to insert toolbar now.
  // The guard inside insertFilterToolbar prevents duplicate insertion on retries.
  insertFilterToolbar();
  insertReconcileButton();

  processVisibleRows();

  const observer = new MutationObserver(() => {
    clearTimeout(window._tmScrollDebounce);
    window._tmScrollDebounce = setTimeout(processVisibleRows, 150);
  });

  observer.observe(contentArea, {
    childList: true,
    subtree: true,
    attributes: false,
    characterData: false,
  });
}
