// popup.js
document.addEventListener('DOMContentLoaded', () => {
  const apiUrlInput = document.getElementById('apiUrl');
  const statusDot = document.getElementById('statusDot');
  const saveBtn = document.getElementById('save');
  const savedMsg = document.getElementById('saved');
  const stageChecks = {
    stage1: document.getElementById('stage1'),
    stage2: document.getElementById('stage2'),
    stage3: document.getElementById('stage3'),
    stage4: document.getElementById('stage4'),
  };

  // Load saved settings
  chrome.storage.local.get(['tmApiUrl', 'tmStages'], (result) => {
    apiUrlInput.value = result.tmApiUrl || 'http://localhost:8000';
    const stages = result.tmStages || { stage1: true, stage2: true, stage3: true, stage4: true };
    Object.entries(stageChecks).forEach(([key, el]) => {
      el.checked = stages[key] !== false;
    });
    checkBackend(apiUrlInput.value);
  });

  function checkBackend(url) {
    fetch(`${url}/health`, { signal: AbortSignal.timeout(3000) })
      .then(r => {
        statusDot.className = 'status-dot ' + (r.ok ? 'ok' : 'err');
      })
      .catch(() => {
        statusDot.className = 'status-dot err';
      });
  }

  saveBtn.addEventListener('click', () => {
    const stages = {};
    Object.entries(stageChecks).forEach(([key, el]) => { stages[key] = el.checked; });
    chrome.storage.local.set({ tmApiUrl: apiUrlInput.value.trim(), tmStages: stages }, () => {
      savedMsg.style.display = 'block';
      setTimeout(() => { savedMsg.style.display = 'none'; }, 1500);
      checkBackend(apiUrlInput.value.trim());
    });
  });
});
