// background.js — service worker
// Provides API URL to content script and manages settings

chrome.runtime.onInstalled.addListener(() => {
  chrome.storage.local.get(['tmApiUrl', 'tmStages'], (result) => {
    if (!result.tmApiUrl) {
      chrome.storage.local.set({ tmApiUrl: 'http://localhost:8000' });
    }
    if (!result.tmStages) {
      chrome.storage.local.set({
        tmStages: { stage1: true, stage2: true, stage3: true, stage4: true }
      });
    }
  });
});

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message.type === 'GET_SETTINGS') {
    chrome.storage.local.get(['tmApiUrl', 'tmStages'], (result) => {
      sendResponse({
        apiUrl: result.tmApiUrl || 'http://localhost:8000',
        stages: result.tmStages || { stage1: true, stage2: true, stage3: true, stage4: true },
      });
    });
    return true; // async response
  }
});
