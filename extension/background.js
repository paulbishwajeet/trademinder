// background.js — service worker
// Provides API URL to content script and manages settings

chrome.runtime.onInstalled.addListener(() => {
  chrome.storage.local.get(['tmApiUrl', 'tmStages'], (result) => {
    if (!result.tmApiUrl) {
      chrome.storage.local.set({ tmApiUrl: 'http://localhost:3001' });
    }
    if (!result.tmStages) {
      chrome.storage.local.set({
        tmStages: { stage1: true, stage2: true, stage3: true, stage4: true }
      });
    }
  });

  chrome.contextMenus.create({
    id: 'tm-add',
    title: 'Add to TradeMinder',
    contexts: ['page'],
    documentUrlPatterns: ['https://*.etrade.com/*'],
  });
});

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message.type === 'GET_SETTINGS') {
    chrome.storage.local.get(['tmApiUrl', 'tmStages'], (result) => {
      sendResponse({
        apiUrl: result.tmApiUrl || 'http://localhost:3001',
        stages: result.tmStages || { stage1: true, stage2: true, stage3: true, stage4: true },
      });
    });
    return true; // async response
  }

  if (message.type === 'ROW_CONTEXT') {
    // Update context menu title/state based on whether position is tracked
    const isTracked = message.isTracked;
    chrome.contextMenus.update('tm-add', {
      title: isTracked ? 'Already in TradeMinder' : 'Add to TradeMinder',
      enabled: !isTracked,
    });
    // Store row info so we can use it when context menu is clicked
    chrome.storage.session
      ? chrome.storage.session.set({ tmPendingRow: message.info })
      : chrome.storage.local.set({ tmPendingRow: message.info });
    sendResponse({ ok: true });
    return true;
  }
});

chrome.contextMenus.onClicked.addListener((info, tab) => {
  if (info.menuItemId !== 'tm-add') return;
  if (!tab?.id) return;

  const fetchPending = (cb) => {
    if (chrome.storage.session) {
      chrome.storage.session.get('tmPendingRow', (r) => cb(r.tmPendingRow || null));
    } else {
      chrome.storage.local.get('tmPendingRow', (r) => cb(r.tmPendingRow || null));
    }
  };

  fetchPending((rowInfo) => {
    chrome.tabs.sendMessage(tab.id, { type: 'SHOW_ADD_MODAL', info: rowInfo });
  });
});
