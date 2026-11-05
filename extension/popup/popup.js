// popup.js
const DEFAULT_API_URL = 'http://127.0.0.1:5431';

document.addEventListener('DOMContentLoaded', () => {
  const apiUrlInput = document.getElementById('apiUrl');
  const statusDot = document.getElementById('statusDot');
  const statusText = document.getElementById('statusText');
  const saveBtn = document.getElementById('save');
  const savedMsg = document.getElementById('saved');
  const stageChecks = {
    stage1: document.getElementById('stage1'),
    stage2: document.getElementById('stage2'),
    stage3: document.getElementById('stage3'),
    stage4: document.getElementById('stage4'),
  };

  function setStatus(kind, text) {
    statusDot.className = `status-dot ${kind}`;
    statusText.textContent = text;
  }

  // "http://host:port" from user input, or null when it isn't an http(s) address.
  function normalize(raw) {
    try {
      const url = new URL(raw.trim());
      if (url.protocol !== 'http:' && url.protocol !== 'https:') return null;
      return url.origin;
    } catch {
      return null;
    }
  }

  async function checkBackend(url) {
    const origin = normalize(url);
    if (!origin) {
      setStatus('err', 'Not a valid http(s) address');
      return;
    }
    const granted = await chrome.permissions.contains({ origins: [`${origin}/*`] });
    if (!granted) {
      setStatus('err', 'No access to this address yet — press Save to allow it');
      return;
    }
    try {
      const r = await fetch(`${origin}/health`, { signal: AbortSignal.timeout(3000) });
      setStatus(r.ok ? 'ok' : 'err', r.ok ? 'Connected' : `Can't reach TradeMinder (HTTP ${r.status})`);
    } catch {
      setStatus('err', `Can't reach TradeMinder at ${origin}`);
    }
  }

  // Load saved settings
  chrome.storage.local.get(['tmApiUrl', 'tmStages'], (result) => {
    apiUrlInput.value = result.tmApiUrl || DEFAULT_API_URL;
    const stages = result.tmStages || { stage1: true, stage2: true, stage3: true, stage4: true };
    Object.entries(stageChecks).forEach(([key, el]) => {
      el.checked = stages[key] !== false;
    });
    checkBackend(apiUrlInput.value);
  });

  saveBtn.addEventListener('click', () => {
    const origin = normalize(apiUrlInput.value);
    if (!origin) {
      setStatus('err', 'Not a valid http(s) address');
      return;
    }
    // The address is user-chosen: ask for host access at runtime (must run inside the click).
    chrome.permissions.request({ origins: [`${origin}/*`] }, (granted) => {
      const stages = {};
      Object.entries(stageChecks).forEach(([key, el]) => { stages[key] = el.checked; });
      apiUrlInput.value = origin;
      chrome.storage.local.set({ tmApiUrl: origin, tmStages: stages }, () => {
        savedMsg.textContent = granted ? '✓ Saved — reload the E*TRADE tab' : '✓ Saved (access not granted)';
        savedMsg.style.display = 'block';
        setTimeout(() => { savedMsg.style.display = 'none'; }, 2500);
        checkBackend(origin);
      });
    });
  });
});
