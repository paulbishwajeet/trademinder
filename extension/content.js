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

  return { ticker, isOption, isITM, fullSymbol, optionDetails };
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
