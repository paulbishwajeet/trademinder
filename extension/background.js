// background.js — service worker
// Owns the TradeMinder server address, relays every API call for the content script (direct
// fetches from the E*TRADE page are blocked by Chrome's Local Network Access policy), and turns
// E*TRADE account numbers into link fingerprints. Account numbers are never stored or logged.

const DEFAULT_API_URL = 'http://127.0.0.1:5431';
const DEFAULT_STAGES = { stage1: true, stage2: true, stage3: true, stage4: true };

chrome.runtime.onInstalled.addListener(() => {
  chrome.storage.local.get(['tmApiUrl', 'tmStages'], (result) => {
    if (!result.tmApiUrl) {
      chrome.storage.local.set({ tmApiUrl: DEFAULT_API_URL });
    }
    if (!result.tmStages) {
      chrome.storage.local.set({ tmStages: DEFAULT_STAGES });
    }
  });

  chrome.contextMenus.create({
    id: 'tm-add',
    title: 'Add to TradeMinder',
    contexts: ['page'],
    documentUrlPatterns: ['https://*.etrade.com/*'],
  });

  chrome.contextMenus.create({
    id: 'tm-view',
    title: 'View / Edit Entry',
    contexts: ['page'],
    documentUrlPatterns: ['https://*.etrade.com/*'],
  });
});

// ── Server address ───────────────────────────────────────────────────────────

async function getApiUrl() {
  const { tmApiUrl } = await chrome.storage.local.get('tmApiUrl');
  return (tmApiUrl || DEFAULT_API_URL).replace(/\/+$/, '');
}

// The address is user-chosen, so host access is granted at runtime (optional_host_permissions).
async function hasHostPermission(baseUrl) {
  try {
    const origin = new URL(baseUrl).origin;
    return await chrome.permissions.contains({ origins: [`${origin}/*`] });
  } catch {
    return false;
  }
}

// Fetch a TradeMinder API path. Resolves to { ok, status, data, error?, errorKind? } where errorKind
// is 'no_permission' or 'unreachable' when TradeMinder could not be reached at all.
async function apiFetch(path, { method = 'GET', headers = {}, body } = {}) {
  const base = await getApiUrl();
  if (!(await hasHostPermission(base))) {
    return { ok: false, status: 0, data: null, error: `No permission for ${base}`, errorKind: 'no_permission', apiUrl: base };
  }
  try {
    const resp = await fetch(`${base}${path}`, {
      method,
      headers,
      body: body !== undefined ? body : undefined,
      signal: AbortSignal.timeout(15000),
    });
    let data = null;
    try { data = await resp.json(); } catch {}
    return { ok: resp.ok, status: resp.status, data, apiUrl: base };
  } catch (err) {
    return { ok: false, status: 0, data: null, error: err.message, errorKind: 'unreachable', apiUrl: base };
  }
}

// ── Account fingerprints + link resolution ───────────────────────────────────

// Hex SHA-256 of `<broker>:<full account number>`. This is the only place the number is used;
// it is never logged, stored or sent anywhere.
async function fingerprint(broker, accountNumber) {
  const bytes = new TextEncoder().encode(`${broker}:${accountNumber}`);
  const digest = await crypto.subtle.digest('SHA-256', bytes);
  return Array.from(new Uint8Array(digest)).map(b => b.toString(16).padStart(2, '0')).join('');
}

// Per-browser-session cache: fingerprint → resolve result. chrome.storage.session lives in memory
// only (never written to disk) and survives the service worker being suspended.
const RESOLVE_CACHE_KEY = 'tmResolveCache';

async function readResolveCache() {
  const { [RESOLVE_CACHE_KEY]: cache } = await chrome.storage.session.get(RESOLVE_CACHE_KEY);
  return cache || {};
}

async function writeResolveCache(fp, result) {
  const cache = await readResolveCache();
  if (result === null) delete cache[fp];
  else cache[fp] = result;
  await chrome.storage.session.set({ [RESOLVE_CACHE_KEY]: cache });
}

async function resolveAccount({ accountNumber, label, fresh }) {
  const fp = await fingerprint('E*TRADE', accountNumber);
  if (!fresh) {
    const cached = (await readResolveCache())[fp];
    if (cached) return { ok: true, fingerprint: fp, ...cached };
  }
  const resp = await apiFetch('/api/accounts/links/resolve', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ fingerprint: fp, label }),
  });
  if (!resp.ok) {
    return { ok: false, fingerprint: fp, status: resp.status, error: resp.data?.detail || resp.error, errorKind: resp.errorKind, apiUrl: resp.apiUrl };
  }
  const result = { linked: resp.data.linked, account: resp.data.account, is_archived: resp.data.is_archived };
  await writeResolveCache(fp, result);
  return { ok: true, fingerprint: fp, ...result };
}

// Link calls go through here so the resolve cache is updated in the same place.
async function linkAccount({ fingerprint: fp, label, accountId, createAccount }) {
  const resp = createAccount
    ? await apiFetch('/api/accounts/links', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ fingerprint: fp, label, account: createAccount }),
    })
    : await apiFetch(`/api/accounts/${accountId}/link`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ fingerprint: fp, label }),
    });
  if (!resp.ok) {
    return { ok: false, status: resp.status, error: resp.data?.detail || resp.error, errorKind: resp.errorKind };
  }
  const account = resp.data;
  const summary = { id: account.id, nickname: account.nickname, broker: account.broker, last_four: account.last_four };
  await writeResolveCache(fp, { linked: true, account: summary, is_archived: account.is_archived });
  return { ok: true, linked: true, account: summary, is_archived: account.is_archived };
}

// ── Messages ─────────────────────────────────────────────────────────────────

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message.type === 'FETCH') {
    // `path` is an API path; the stored server address is prefixed here.
    apiFetch(message.path, message).then(sendResponse);
    return true; // keep message channel open for async response
  }

  if (message.type === 'RESOLVE_ACCOUNT') {
    resolveAccount(message).then(sendResponse).catch(() => sendResponse({ ok: false, error: 'Resolve failed' }));
    return true;
  }

  if (message.type === 'LINK_ACCOUNT') {
    linkAccount(message).then(sendResponse).catch(() => sendResponse({ ok: false, error: 'Link failed' }));
    return true;
  }

  if (message.type === 'GET_SETTINGS') {
    chrome.storage.local.get(['tmApiUrl', 'tmStages'], (result) => {
      sendResponse({
        apiUrl: result.tmApiUrl || DEFAULT_API_URL,
        stages: result.tmStages || DEFAULT_STAGES,
      });
    });
    return true;
  }

  if (message.type === 'ROW_CONTEXT') {
    const isTracked = message.isTracked;
    // canAdd is false when the account on screen isn't linked (or is archived): writes need a known account.
    const canAdd = message.canAdd !== false;
    chrome.contextMenus.update('tm-add', {
      title: !canAdd ? (message.blockReason || 'Link this E*TRADE account first')
        : isTracked ? 'Already in TradeMinder' : 'Add to TradeMinder',
      enabled: canAdd && !isTracked,
    });
    chrome.contextMenus.update('tm-view', {
      title: isTracked ? 'View / Edit Entry' : 'Not in TradeMinder',
      enabled: !!isTracked,
    });
    chrome.storage.session
      ? chrome.storage.session.set({ tmPendingRow: message.info })
      : chrome.storage.local.set({ tmPendingRow: message.info });
    sendResponse({ ok: true });
    return true;
  }
});

chrome.contextMenus.onClicked.addListener((info, tab) => {
  if (!tab?.id) return;

  const fetchPending = (cb) => {
    if (chrome.storage.session) {
      chrome.storage.session.get('tmPendingRow', (r) => cb(r.tmPendingRow || null));
    } else {
      chrome.storage.local.get('tmPendingRow', (r) => cb(r.tmPendingRow || null));
    }
  };

  if (info.menuItemId === 'tm-add') {
    fetchPending((rowInfo) => {
      chrome.tabs.sendMessage(tab.id, { type: 'SHOW_ADD_MODAL', info: rowInfo });
    });
  }

  if (info.menuItemId === 'tm-view') {
    fetchPending((rowInfo) => {
      chrome.tabs.sendMessage(tab.id, { type: 'SHOW_EDIT_MODAL', info: rowInfo });
    });
  }
});
