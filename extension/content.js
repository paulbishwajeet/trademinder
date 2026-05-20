// content.js — TradeMinder Stage 1: Category Indicators
// Handles E*TRADE's div-based virtual scroll grid

'use strict';

// ============================================================
// ETRADE SELECTOR CONSTANTS — confirmed from live DOM
// ============================================================
const ETRADE = {
  gridRoot:       '#rdt_3',
  contentArea:    '.Content---root---D2Ylg',
  positionRows:   '[role="row"][level="0"]:not(.Row---placeholderRow---2t5Gs)',
  placeholderRow: '.Row---placeholderRow---2t5Gs',
  footerRow:      '.Footer---row---g5JDN',
  symbolContent:  '.SymbolCellRenderer---content---mcwCT',
  symbolLink:     'a.SymbolCellRenderer---symbol---_S70m',
  optionClass:    'SymbolCellRenderer---option---qIlje',
  itmClass:       'SymbolCellRenderer---in-the-money---AQRUo',
  optionDesc:     'span.SymbolCellRenderer---description---KHPND',
  headerRow:      '[data-header="true"] [role="row"]',
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

// column name → cell index, built once from the header row
let columnIndexCache = null;

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
      const resp = await fetch(`${tmApiUrl}/api/market/technicals/${ticker.toUpperCase()}`, {
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
    const resp = await fetch(`${tmApiUrl}/api/categories`, { signal: AbortSignal.timeout(4000) });
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
  const isITM    = symbolRoot ? symbolRoot.classList.contains(ETRADE.itmClass)    : false;

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
  const qtyCol       = colMap['qty #']       ?? colMap['qty'] ?? null;
  const pricePaidCol = colMap['price paid $'] ?? colMap['price paid'] ?? null;

  let quantity  = null;
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
  const year  = 2000 + parseInt(dateStr.slice(0, 2));
  const month = parseInt(dateStr.slice(2, 4)) - 1;
  const day   = parseInt(dateStr.slice(4, 6));
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
  const months = { Jan:0,Feb:1,Mar:2,Apr:3,May:4,Jun:5,Jul:6,Aug:7,Sep:8,Oct:9,Nov:10,Dec:11 };
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

    // Apply cached status immediately; collect what needs a fetch
    const needsFetch = [];
    toProcess.forEach(item => {
      if (statusCache.has(item.cacheKey)) {
        applyTMToRow(item.row, statusCache.get(item.cacheKey), item.info);
        applyFilter(item.row, statusCache.get(item.cacheKey));
        applyRsiToRow(item.row, item.info.ticker);
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

    const response = await fetch(`${tmApiUrl}/api/positions/status`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ positions }),
      signal: AbortSignal.timeout(5000),
    });

    if (!response.ok) return;
    const statusMap = await response.json();

    needsFetch.forEach(item => {
      const status = statusMap[item.cacheKey] || statusMap[item.info.ticker] || null;
      statusCache.set(item.cacheKey, status);
      applyTMToRow(item.row, status, item.info);
      applyFilter(item.row, status);
      applyRsiToRow(item.row, item.info.ticker);
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
    urgent:  'rgba(239,68,68,0.18)',
    warning: 'rgba(245,158,11,0.15)',
    info:    'rgba(139,92,246,0.12)',
    ok:      'rgba(34,197,94,0.08)',
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
  const r = parseInt(hex.slice(1,3), 16);
  const g = parseInt(hex.slice(3,5), 16);
  const b = parseInt(hex.slice(5,7), 16);
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
    badge.innerHTML = `<span class="tm-tag tm-untracked">⊘ Not tracked</span>`;
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
    const resp = await fetch(`${tmApiUrl}/api/trades/${tradeId}/commentary`, {
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
      <div class="tm-cp-form-fields">
        <textarea class="tm-cp-note-input" rows="3" placeholder="What happened or what did you decide?"></textarea>
        <input class="tm-cp-tags-input" type="text" placeholder="Tags: rolled, exit-change (comma-separated)" />
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
      const resp = await fetch(`${tmApiUrl}/api/trades/${tradeId}/commentary`, {
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
  const panelW = 380;

  // Horizontal: align panel's right edge with the row's right edge, clamped to viewport
  const rightEdge = Math.min(rect.right, window.innerWidth - margin);
  panel.style.left = `${Math.max(margin, rightEdge - panelW)}px`;

  // Vertical: open whichever direction has more room; cap maxHeight to available space
  const spaceBelow = window.innerHeight - rect.bottom - margin;
  const spaceAbove = rect.top - margin;

  if (spaceBelow >= spaceAbove || spaceBelow >= 200) {
    panel.style.top = `${rect.bottom + 4}px`;
    panel.style.bottom = '';
    panel.style.maxHeight = `${Math.min(520, spaceBelow)}px`;
  } else {
    panel.style.bottom = `${window.innerHeight - rect.top + 4}px`;
    panel.style.top = '';
    panel.style.maxHeight = `${Math.min(520, spaceAbove)}px`;
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

async function renderCommentaryThread(tradeId, panel) {
  if (_threadAbortCtrl) _threadAbortCtrl.abort();
  _threadAbortCtrl = new AbortController();
  const signal = _threadAbortCtrl.signal;

  const threadEl = panel.querySelector('.tm-cp-thread');
  threadEl.innerHTML = '<p class="tm-cp-loading">Loading…</p>';

  try {
    const resp = await fetch(`${tmApiUrl}/api/trades/${tradeId}/commentary`, { signal });
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    const entries = await resp.json();

    updateCommentaryBadge(tradeId, entries.length);

    if (entries.length === 0) {
      threadEl.innerHTML = '<p class="tm-cp-empty">No notes yet.</p>';
      return;
    }

    threadEl.innerHTML = '';
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
          const r = await fetch(`${tmApiUrl}/api/commentary/${entry.id}`, {
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
        const chip = document.createElement('button');
        chip.type = 'button';
        chip.className = 'tm-rationale-chip';
        chip.textContent = '📊 Technicals';
        let detailEl = null;
        chip.addEventListener('click', () => {
          if (detailEl) {
            detailEl.remove();
            detailEl = null;
            return;
          }
          detailEl = document.createElement('div');
          detailEl.className = 'tm-rationale-detail';
          const r = entry.rationale;
          const SHOW = [
            ['RSI', r.rsi_14], ['MACD', r.macd_signal], ['Sentiment', r.sentiment],
            ['BB Pos', r.bollinger_position], ['vs MA50', r.price_vs_ma50],
            ['Price', r.price_action], ['Earnings', r.next_earnings_date],
            ['Day', r.day_color], ['Notes', r.notes],
          ].filter(([, v]) => v != null && v !== '');
          SHOW.forEach(([label, value]) => {
            const row = document.createElement('div');
            row.className = 'tm-rationale-row';
            const labelSpan = document.createElement('span');
            labelSpan.textContent = `${label}: `;
            const valueSpan = document.createElement('span');
            valueSpan.textContent = String(value);
            row.appendChild(labelSpan);
            row.appendChild(valueSpan);
            detailEl.appendChild(row);
          });
          chip.insertAdjacentElement('afterend', detailEl);
        });
        entryEl.appendChild(chip);
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
    const resp = await fetch(`${tmApiUrl}/api/market/rsi`, {
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
    const resp = await fetch(`${tmApiUrl}/api/categories`, { signal: AbortSignal.timeout(5000) });
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
// ADD TRADE MODAL
// ============================================================
async function showAddTradeModal(info) {
  const categories = await fetchCategories();
  if (document.getElementById('tm-modal-overlay')) return; // already open

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
          <input type="number" name="premium" step="0.01" min="0" value="${info.pricePaid != null ? info.pricePaid : ''}" placeholder="0.00" required />
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

      // Save technicals snapshot if user fetched them
      const techSnapshot = techFormControl ? techFormControl.getValue() : null;
      if (techSnapshot) {
        try {
          await fetch(`${tmApiUrl}/api/trades/${trade.id}/rationale`, {
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
    const searchResp = await fetch(searchUrl, { signal: AbortSignal.timeout(6000) });
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
    const detailResp = await fetch(`${tmApiUrl}/api/trades/${tradeId}`, { signal: AbortSignal.timeout(6000) });
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
            ${!['Sell Put','Sell Call','Buy Put','Buy Call','Put Credit Spread','Call Credit Spread','Covered Call','Stock'].includes(trade.strategy)
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

      // Invalidate cache so the row badge refreshes
      const cacheKey = info.fullSymbol || info.ticker;
      statusCache.delete(cacheKey);
      if (info.ticker) statusCache.delete(info.ticker);
      processedRows.forEach((val, key) => {
        if (val === cacheKey || val === info.ticker) processedRows.delete(key);
      });
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
