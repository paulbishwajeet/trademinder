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
let tmApiUrl = 'http://localhost:8000';
let stageEnabled = { stage1: true, stage2: true, stage3: true, stage4: true };

// rowId → cacheKey (ticker or fullSymbol): prevents re-processing unchanged rows
const processedRows = new Map();
// cacheKey → PositionStatus: avoids re-fetching same data
const statusCache = new Map();
let isProcessing = false;
let allCategories = [];
let activeFilter = 'all';

// column name → cell index, built once from the header row
let columnIndexCache = null;

// ============================================================
// INIT
// ============================================================
chrome.runtime.sendMessage({ type: 'GET_SETTINGS' }, (resp) => {
  if (resp) {
    tmApiUrl = resp.apiUrl || 'http://localhost:8000';
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
  insertFilterToolbar();
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

  if (isOption) {
    const link = row.querySelector(ETRADE.symbolLink);
    if (link?.href) {
      const match = link.href.match(/[?&]symbol=([^&]+)/);
      if (match) {
        fullSymbol = decodeURIComponent(match[1]);
        optionDetails = parseOptionSymbol(fullSymbol);
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

      const cacheKey = info.fullSymbol || info.ticker;
      const prevKey = processedRows.get(rowId);

      if (prevKey !== cacheKey) {
        clearTMFromRow(row);
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
    badge.style.cssText = [
      'position:absolute',
      'right:-195px',
      'top:50%',
      'transform:translateY(-50%)',
      'z-index:100',
      'pointer-events:auto',
      'white-space:nowrap',
    ].join(';');
    row.style.overflow = 'visible';
    row.appendChild(badge);
  }

  if (!status) {
    badge.innerHTML = `<span class="tm-tag tm-untracked">⊘ Not tracked</span>`;
    return;
  }

  const catIcon  = status.category_icon  || '';
  const catName  = status.category_name  || '';
  const severity = status.alert_severity || 'ok';
  const sevIcon  = { urgent:'🔴', warning:'🟡', info:'🟣', ok:'🟢' }[severity] || '🟢';
  const alertTitle = status.alert_title || '';
  const dte = info.optionDetails?.dte;

  // Stage 4 signal dots (inactive in Stage 1 but structure is here)
  const signalDots = stageEnabled.stage4
    ? (status.active_signals || []).map(s => {
        const bullish = ['macd_bullish','rsi_oversold','bb_breakout_lower','above_ma200','golden_cross'];
        return `<span class="tm-dot ${bullish.includes(s.type) ? 'tm-bullish' : 'tm-bearish'}" title="${s.notes || ''}">●</span>`;
      }).join('')
    : '';

  // Stage 3 alert label (inactive in Stage 1 for now)
  const alertHtml = (stageEnabled.stage3 && alertTitle)
    ? ` · <span class="tm-alert-label">${alertTitle}</span>`
    : '';

  badge.innerHTML = `
    <span class="tm-tag tm-${severity}" data-category="${catName}">
      ${sevIcon} ${catIcon} ${catName || '—'}${alertHtml}${dte != null ? ` · <span class="tm-dte">${dte}d</span>` : ''}${signalDots}
    </span>`;
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
});

// ============================================================
// ADD TRADE MODAL
// ============================================================
function showAddTradeModal(info) {
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
            <option value="Wheel">Wheel</option>
            <option value="Speculative">Speculative</option>
            <option value="Momentum">Momentum</option>
            <option value="Short Term">Short Term</option>
            <option value="Long Term">Long Term</option>
            <option value="Coach Suggested">Coach Suggested</option>
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
// MUTATION OBSERVER — virtual scroll handler
// ============================================================
function startObserver() {
  const contentArea = document.querySelector(ETRADE.contentArea);
  if (!contentArea) {
    setTimeout(startObserver, 500);
    return;
  }

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
