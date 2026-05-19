// background.js — service worker
// Provides API URL to content script and manages settings

chrome.runtime.onInstalled.addListener(() => {
  chrome.storage.local.get(['tmApiUrl', 'tmStages'], (result) => {
    if (!result.tmApiUrl) {
      chrome.storage.local.set({ tmApiUrl: 'http://localhost:5431' });
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

  chrome.contextMenus.create({
    id: 'tm-view',
    title: 'View / Edit Entry',
    contexts: ['page'],
    documentUrlPatterns: ['https://*.etrade.com/*'],
  });
});

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message.type === 'GET_SETTINGS') {
    chrome.storage.local.get(['tmApiUrl', 'tmStages'], (result) => {
      sendResponse({
        apiUrl: result.tmApiUrl || 'http://localhost:5431',
        stages: result.tmStages || { stage1: true, stage2: true, stage3: true, stage4: true },
      });
    });
    return true;
  }

  if (message.type === 'ROW_CONTEXT') {
    const isTracked = message.isTracked;
    chrome.contextMenus.update('tm-add', {
      title: isTracked ? 'Already in TradeMinder' : 'Add to TradeMinder',
      enabled: !isTracked,
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
