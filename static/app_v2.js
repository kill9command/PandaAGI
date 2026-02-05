// =============================================================================
// THINKING VISUALIZATION ENABLED - BUILD 2025-12-03T17:15:00Z
// =============================================================================
console.log('%c[Pandora] BUILD 2025-12-03 v171500 - FINAL POLL LOOP FIX', 'color: #68a8ef; font-size: 14px; font-weight: bold; background: #1a1a2e; padding: 4px 8px;');

const chatWindow    = document.getElementById('chat-window');
const chatForm      = document.getElementById('chat-form');
const userInput     = document.getElementById('user-input');
const teachContainer= null; // REMOVED: Teach system not compatible
const clearBtn      = document.getElementById('clear-chat');
const copyBtn       = document.getElementById('copy-last');
const logBtn        = document.getElementById('log-turn');
const cancelBtn     = document.getElementById('cancel-btn');

// Track current running job/trace for cancellation
let currentJobId = null;
let currentTraceId = null;
let isQueryRunning = false;

// Cancel button handler
if (cancelBtn) {
  cancelBtn.addEventListener('click', async () => {
    // Try to cancel via job_id first, then trace_id
    if (!currentJobId && !currentTraceId) {
      console.log('[Cancel] No job or trace to cancel');
      return;
    }

    try {
      let resp, result;
      if (currentJobId) {
        console.log('[Cancel] Cancelling job:', currentJobId);
        resp = await fetch(`/jobs/${encodeURIComponent(currentJobId)}/cancel`, { method: 'POST' });
        result = await resp.json();
      } else if (currentTraceId) {
        console.log('[Cancel] Cancelling trace:', currentTraceId);
        resp = await fetch(`/v1/thinking/${encodeURIComponent(currentTraceId)}/cancel`, { method: 'POST' });
        result = await resp.json();
      }

      console.log('[Cancel] Result:', result);
      if (result && result.ok) {
        addMessage('Query cancelled.', 'bot');
        // Remove loading bubble
        const lastBot = chatWindow.querySelector('.msg.bot:last-child');
        if (lastBot && !lastBot.classList.contains('thinking-msg')) {
          chatWindow.removeChild(lastBot);
        }
        // Stop thinking visualization if running
        if (window.stopThinking) window.stopThinking();
      }
    } catch (err) {
      console.error('[Cancel] Error:', err);
    }
    // Hide cancel button
    hideCancelButton();
  });
}

function showCancelButton(jobId, traceId) {
  currentJobId = jobId || null;
  currentTraceId = traceId || null;
  isQueryRunning = true;
  if (cancelBtn) cancelBtn.style.display = 'inline-block';
}

function hideCancelButton() {
  currentJobId = null;
  currentTraceId = null;
  isQueryRunning = false;
  if (cancelBtn) cancelBtn.style.display = 'none';
}

/*
API base configuration (configurable via localStorage).
Default points to the local Gateway OpenAI-compatible endpoint.
*/
const API_BASE = (function() {
  try {
    return localStorage.getItem('pandora.apiBase') || '/v1';
  } catch {
    return '/v1';
  }
})();

// Preset defaults (sampling + model routed via LiteLLM)
const PRESETS = {
  creative: { temperature: 0.8, top_p: 0.95, model: 'pandora-plan' },
  chat: { temperature: 0.2, top_p: 0.9, model: 'pandora-chat' },
  code: { temperature: 0.0, top_p: 1.0, model: 'pandora-plan' },
};

// UI elements for advanced controls
const advPanel   = document.getElementById('advanced-settings');
const advToggle  = document.getElementById('advanced-toggle');
const presetSel  = document.getElementById('model-preset');
const tempSlider = document.getElementById('temperature-slider');
const tempVal    = document.getElementById('temperature-value');
const topPSlider = document.getElementById('top-p-slider');
const topPVal    = document.getElementById('top-p-value');
const styleSel   = document.getElementById('style-select');
const keepInputTgl = document.getElementById('keep-input-toggle');
const showCtxTgl   = null; // REMOVED: UI element removed
const showReqTgl   = null; // REMOVED: UI element removed
const fastModeTgl  = document.getElementById('fast-mode-toggle');
const autoSummarizeTgl = document.getElementById('auto-summarize-toggle');
const autoSummarizeThr = document.getElementById('auto-summarize-threshold');
const repoRootWrap = document.getElementById('repo-root-wrap');
const repoRootInput = document.getElementById('repo-root-input');
const repoRootSave = document.getElementById('repo-root-save');
const apiKeyWrap = document.getElementById('api-key-wrap');
const apiKeyInput = document.getElementById('api-key-input');
const apiKeySave = document.getElementById('api-key-save');
const continueWrap = null; // REMOVED: Continue IDE integration removed
const continueSendTgl = null; // REMOVED: Continue IDE integration removed
const continueWebhook = null; // REMOVED: Continue IDE integration removed
const continueSave = null; // REMOVED: Continue IDE integration removed
const useJobsTgl = document.getElementById('use-jobs-toggle');
const useLANTgl = document.getElementById('use-lan-toggle');
const lanBaseInput = null; // REMOVED: UI element removed
const lanApplyBtn = null; // REMOVED: UI element removed
const profileSelect = document.getElementById('profile-select');
const profileNameInput = document.getElementById('profile-name-input');
const profileAddBtn = document.getElementById('profile-add');
const profileRememberToggle = document.getElementById('profile-remember');

// Prompts panel elements
const promptsOpen = document.getElementById('prompts-open');
const promptsPanel = document.getElementById('prompts-panel');
const promptsSelect = document.getElementById('prompts-select');
const promptsLoad = document.getElementById('prompts-load');
const promptsSave = document.getElementById('prompts-save');
const promptsClose = document.getElementById('prompts-close');
const promptsEditor = document.getElementById('prompts-editor');
const promptsBackups = document.getElementById('prompts-backups');
const promptsRefreshBackups = document.getElementById('prompts-refresh-backups');
// Policy panel elements
const policyBtn = document.getElementById('policy-open');
const policyPanel = document.getElementById('policy-panel');
const polAllowWrites = document.getElementById('pol-allow-writes');
const polRequireConfirm = document.getElementById('pol-require-confirm');
const policyToolsWrap = document.getElementById('policy-tools');
const policySave = document.getElementById('policy-save');
const policyClose = document.getElementById('policy-close');
const connIndicator = document.getElementById('conn-indicator');
const polAllowedPaths = document.getElementById('pol-allowed-write-paths');
const writePathIndicator = document.getElementById('write-path-indicator');

// Context status bar elements
const contextStatusBar = document.getElementById('context-status-bar');
const activeRepoPath = document.getElementById('active-repo-path');
const modeName = document.getElementById('mode-name');
const modePerms = document.getElementById('mode-perms');
const cwdPath = document.getElementById('cwd-path');
const workspaceConfig = document.getElementById('workspace-config');

function getApiKey() {
  try {
    return LS.get('pandora.apiKey', 'sk-local') || 'sk-local';
  } catch {
    return 'sk-local';
  }
}

function buildBaseUrl() {
  // Return empty string for relative URLs (same origin)
  // Could be extended later to support LAN toggle
  return '';
}

async function fetchServerRepoBase() {
  try {
    const resp = await fetch(`${buildBaseUrl()}/ui/repos/base`);
    if (!resp.ok) return null;
    const data = await resp.json();
    return (data && data.path) ? data.path : null;
  } catch {
    return null;
  }
}

async function persistServerRepoBase(path) {
  if (!path) return;
  try {
    const resp = await fetch(`${buildBaseUrl()}/ui/repos/base`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path })
    });
    if (!resp.ok) {
      const text = await resp.text();
      throw new Error(text || `HTTP ${resp.status}`);
    }
    await resp.json().catch(() => null);
  } catch (err) {
    console.error('[Pandora] Failed to persist repo base:', err);
    addDebugMessage('Failed to update repo base on server.');
    throw err;
  }
}

// Local storage helpers
const LS = {
  get(k, d) { try { const v = localStorage.getItem(k); return v === null ? d : v; } catch { return d; } },
  set(k, v) { try { localStorage.setItem(k, v); } catch { /* ignore */ } },
  remove(k) { try { localStorage.removeItem(k); } catch { /* ignore */ } },
};

const PROFILE_LS_KEY = 'pandora.profile';
const PROFILE_REMEMBER_KEY = 'pandora.profileRemember';
const PROFILE_LIST_KEY = 'pandora.profileList';
const DEFAULT_PROFILE = 'default';
const DEFAULT_PROFILES = ['default', 'user2', 'user3'];
const CHAT_KEY_PREFIX = 'pandora.chat.';
let activeProfile = DEFAULT_PROFILE;
let profileOptions = [];

function safeProfileKey(profile) {
  return (profile || DEFAULT_PROFILE).replace(/[^a-z0-9_-]/gi, '_');
}

function chatStorageKey(profile) {
  return CHAT_KEY_PREFIX + safeProfileKey(profile);
}

function loadProfileOptionsFromStorage() {
  try {
    const raw = LS.get(PROFILE_LIST_KEY, '');
    if (!raw) return [...DEFAULT_PROFILES];
    const parsed = JSON.parse(raw);
    if (Array.isArray(parsed) && parsed.length) {
      return parsed
        .filter(name => typeof name === 'string' && name.trim().length)
        .map(name => name.trim());
    }
  } catch {
    /* ignore */
  }
  return [...DEFAULT_PROFILES];
}

function persistProfileList(list) {
  profileOptions = list;
  LS.set(PROFILE_LIST_KEY, JSON.stringify(list));
}

function renderProfileOptions(list, selectedValue) {
  if (!profileSelect) return;
  profileSelect.innerHTML = '';
  list.forEach(name => {
    const opt = document.createElement('option');
    opt.value = name;
    opt.textContent = name;
    profileSelect.appendChild(opt);
  });
  if (selectedValue && list.includes(selectedValue)) {
    profileSelect.value = selectedValue;
  } else if (list.length) {
    profileSelect.value = list.includes(activeProfile) ? activeProfile : list[0];
  }
}

function findProfileMatch(value) {
  const target = (value || '').toLowerCase();
  return profileOptions.find(name => name.toLowerCase() === target);
}

function applyActiveProfile(profile) {
  let normalized = (profile || '').trim() || DEFAULT_PROFILE;
  const existing = findProfileMatch(normalized);
  if (existing) {
    normalized = existing;
  }
  if (!profileOptions.includes(normalized)) {
    const next = [...profileOptions, normalized];
    persistProfileList(next);
    renderProfileOptions(next, normalized);
  } else if (profileSelect && profileSelect.value !== normalized) {
    profileSelect.value = normalized;
  }
  activeProfile = normalized;
  CHAT_LS_KEY = chatStorageKey(normalized);
  if (shouldRememberProfile()) {
    LS.set(PROFILE_LS_KEY, normalized);
  } else {
    LS.remove(PROFILE_LS_KEY);
  }
  return normalized;
}

function getActiveProfile() {
  return activeProfile;
}

function shouldRememberProfile() {
  return !profileRememberToggle || profileRememberToggle.checked;
}

let CHAT_LS_KEY = chatStorageKey(activeProfile);
let CHAT = [];
let RESTORING = false;

function escapeHtml(str) {
  return String(str || '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

function formatBotText(str) {
  if (!str) return '';
  let html = '';
  let lastIndex = 0;
  // Regex for markdown links OR raw URLs
  const linkRe = /(\[([^\]]+)\]\((https?:\/\/[^\)]+)\))|(https?:\/\/[^\s<>"'`]+)/g;
  let match;

  while ((match = linkRe.exec(str)) !== null) {
    // Append text before the link
    html += escapeHtml(str.slice(lastIndex, match.index));

    const mdFull = match[1];
    const mdLabel = match[2];
    const mdUrl = match[3];
    const rawUrl = match[4];

    if (mdFull) { // Markdown link
      const url = encodeURI(mdUrl.trim());
      html += `<a href="${url}" target="_blank" rel="noopener noreferrer" class="external-link" title="Opens in new tab">${escapeHtml(mdLabel)} ↗</a>`;
    } else if (rawUrl) { // Raw URL
      let cleanUrl = rawUrl;
      let trailingPunctuation = '';
      const punctuationMatch = cleanUrl.match(/[.,!?;:]$/);
      if (punctuationMatch) {
          trailingPunctuation = punctuationMatch[0];
          cleanUrl = cleanUrl.slice(0, -1);
      }
      const encodedUrl = encodeURI(cleanUrl);
      html += `<a href="${encodedUrl}" target="_blank" rel="noopener noreferrer" class="external-link" title="Opens in new tab">${escapeHtml(cleanUrl)} ↗</a>${trailingPunctuation}`;
    }
    lastIndex = linkRe.lastIndex;
  }

  // Append remaining text
  html += escapeHtml(str.slice(lastIndex));

  return html.replace(/\n/g, '<br>');
}

function setAdvancedVisible(visible) {
  advPanel.style.display = visible ? 'block' : 'none';
  LS.set('pandora.advOpen', visible ? '1' : '0');
}

function applyPresetToSliders(key) {
  const p = PRESETS[key] || PRESETS.chat;
  tempSlider.value = p.temperature;
  topPSlider.value = p.top_p;
  tempVal.textContent = String(p.temperature);
  topPVal.textContent = String(p.top_p);
}

function initSettingsFromStorage() {
  // Advanced visibility
  const advOpen = LS.get('pandora.advOpen', '0') === '1';
  setAdvancedVisible(advOpen);

  profileOptions = loadProfileOptionsFromStorage();
  renderProfileOptions(profileOptions, profileOptions[0] || DEFAULT_PROFILE);

  const defaultProfileOption = profileOptions[0] || DEFAULT_PROFILE;
  const rememberSaved = LS.get(PROFILE_REMEMBER_KEY, '1') === '1';
  if (profileRememberToggle) profileRememberToggle.checked = rememberSaved;
  if (!rememberSaved) {
    LS.remove(PROFILE_LS_KEY);
  }
  const storedProfile = rememberSaved ? LS.get(PROFILE_LS_KEY, defaultProfileOption) : defaultProfileOption;
  const normalizedProfile = applyActiveProfile(storedProfile);
  if (profileSelect) profileSelect.value = normalizedProfile;

  // Persona selection
  // Preset and sliders
  const preset = LS.get('pandora.preset', 'chat');
  if (presetSel) presetSel.value = preset;
  applyPresetToSliders(preset);
  // If explicit custom values were saved, apply them
  const tSaved = LS.get('pandora.temp', '');
  const pSaved = LS.get('pandora.topp', '');
  if (tSaved !== '') { tempSlider.value = tSaved; tempVal.textContent = String(tSaved); }
  if (pSaved !== '') { topPSlider.value = pSaved; topPVal.textContent = String(pSaved); }

  // Style
  if (styleSel) styleSel.value = LS.get('pandora.style', styleSel.value || 'concise');
  // Keep input after send
  if (keepInputTgl) keepInputTgl.checked = LS.get('pandora.keepInput', '0') === '1';

  // REMOVED: Teach toggle, Show context toggle, Show requests toggle
  // Fast mode toggle
  if (fastModeTgl) fastModeTgl.checked = LS.get('pandora.fastMode', '0') === '1';
  if (autoSummarizeTgl) autoSummarizeTgl.checked = LS.get('pandora.autoSummarize', '0') === '1';
  if (autoSummarizeThr) autoSummarizeThr.value = String(LS.get('pandora.autoSummarizeThreshold', autoSummarizeThr.value || '700'));

  // Mode radio
const savedMode = LS.get('pandora.mode', 'chat');
  const mNode = document.querySelector(`input[name="mode"][value="${savedMode}"]`);
  if (mNode) mNode.checked = true;
  // Repo root input visibility (Continue mode)
  const mode = (document.querySelector('input[name="mode"]:checked')||{}).value || 'chat';
  const repoSaved = LS.get('pandora.repoRoot', '');
  if (repoRootInput) repoRootInput.value = repoSaved;
  if (repoRootInput && !repoSaved) {
    fetchServerRepoBase().then((serverPath) => {
      if (serverPath && !repoRootInput.value) {
        repoRootInput.value = serverPath;
        LS.set('pandora.repoRoot', serverPath);
        updateContextStatus();
      }
    }).catch(() => {});
  }
  if (repoRootWrap) repoRootWrap.style.display = (mode === 'code') ? 'inline-block' : 'none';
  // API key
  const savedKey = getApiKey();
  if (apiKeyInput) apiKeyInput.value = savedKey;
  // Jobs toggle: default ON for non-localhost hosts
  if (useJobsTgl) {
    const defaultUse = (location.hostname !== 'localhost' && location.hostname !== '127.0.0.1');
    const saved = LS.get('pandora.useJobs', defaultUse ? '1' : '0') === '1';
    useJobsTgl.checked = saved;
  }
  // LAN toggle and base
  if (useLANTgl) {
    const saved = LS.get('pandora.useLAN', '0') === '1';
    useLANTgl.checked = saved;
  }
  // REMOVED: lanBaseInput UI element (still use localStorage value)
  // Ensure apiBase reflects current LAN toggle
  try {
    const useLAN = !!(useLANTgl && useLANTgl.checked);
    const lanBase = LS.get('pandora.lanBase', 'http://192.168.1.100:9000');
    LS.set('pandora.apiBase', useLAN ? (lanBase.replace(/\/$/, '') + '/v1') : '/v1');
  } catch {}
  // Kick off initial connection ping
  try { scheduleHealthPing(true); } catch {}
  // Continue relay controls
  if (continueSendTgl) continueSendTgl.checked = LS.get('pandora.continueSend', '0') === '1';
  if (continueWebhook) continueWebhook.value = LS.get('pandora.continueWebhook', '');
  if (continueWrap) continueWrap.style.display = (mode === 'code') ? 'inline-block' : 'none';
  // Auto-configure Continue relay defaults so user doesn't need to enter anything
  try {
    if (continueWebhook) {
      const defaultRelay = 'http://127.0.0.1:65432/relay';
      let saved = LS.get('pandora.continueWebhook', '');
      if (!saved) { saved = defaultRelay; LS.set('pandora.continueWebhook', saved); }
      continueWebhook.value = saved;
    }
    if (continueSendTgl) {
      if (LS.get('pandora.continueSend', '') === '') { LS.set('pandora.continueSend', '1'); }
      continueSendTgl.checked = true;
    }
  } catch {}
}

// Update context status bar with current repo, mode, and working directory
function updateContextStatus() {
  // Update repo path
  const repoPath = LS.get('pandora.repoRoot', '') || '/path/to/project';
  if (activeRepoPath) {
    activeRepoPath.textContent = repoPath || '<not set>';
    activeRepoPath.title = repoPath;
  }

  // Update mode and permissions
  const mode = (document.querySelector('input[name="mode"]:checked')||{}).value || 'chat';
  if (modeName) modeName.textContent = mode;
  if (modePerms) {
    const perms = mode === 'chat' ? '(read-only)' :
                  mode === 'plan' ? '(read + memory)' :
                  mode === 'act' ? '(read/write)' : '(unknown)';
    modePerms.textContent = perms;
    modePerms.style.color = mode === 'act' ? '#ff6b6b' : '#7fd288';
  }

  // Update CWD (fetch from server)
  const baseUrl = buildBaseUrl();
  fetch(`${baseUrl}/status/cwd`, {
    method: 'GET',
    headers: { 'Authorization': `Bearer ${getApiKey()}` }
  })
  .then(r => r.json())
  .then(data => {
    if (cwdPath && data.cwd) {
      cwdPath.textContent = data.cwd;
      cwdPath.title = data.cwd;
    }
  })
  .catch(() => {
    // Fallback to repo path if endpoint not available
    if (cwdPath) {
      cwdPath.textContent = repoPath || '<unknown>';
      cwdPath.title = repoPath;
    }
  });
}

function bindSettingHandlers() {
  if (advToggle) {
    advToggle.addEventListener('click', () => setAdvancedVisible(advPanel.style.display === 'none'));
  }
  if (presetSel) {
    presetSel.addEventListener('change', () => {
      LS.set('pandora.preset', presetSel.value);
      applyPresetToSliders(presetSel.value);
    });
  }
  if (tempSlider) {
    const update = () => { tempVal.textContent = String(tempSlider.value); LS.set('pandora.temp', tempSlider.value); };
    tempSlider.addEventListener('input', update);
    tempSlider.addEventListener('change', update);
  }
  if (topPSlider) {
    const update = () => { topPVal.textContent = String(topPSlider.value); LS.set('pandora.topp', topPSlider.value); };
    topPSlider.addEventListener('input', update);
    topPSlider.addEventListener('change', update);
  }
  if (styleSel) styleSel.addEventListener('change', () => LS.set('pandora.style', styleSel.value));
  if (keepInputTgl) keepInputTgl.addEventListener('change', () => LS.set('pandora.keepInput', keepInputTgl.checked ? '1' : '0'));
  if (useJobsTgl) useJobsTgl.addEventListener('change', () => LS.set('pandora.useJobs', useJobsTgl.checked ? '1' : '0'));
  // REMOVED: teach-toggle, showCtxTgl, showReqTgl event listeners
  if (fastModeTgl) fastModeTgl.addEventListener('change', () => LS.set('pandora.fastMode', fastModeTgl.checked ? '1' : '0'));
  if (autoSummarizeTgl) autoSummarizeTgl.addEventListener('change', () => LS.set('pandora.autoSummarize', autoSummarizeTgl.checked ? '1' : '0'));
  if (autoSummarizeThr) autoSummarizeThr.addEventListener('change', () => LS.set('pandora.autoSummarizeThreshold', (autoSummarizeThr.value || '700')));
  if (profileSelect) {
    profileSelect.addEventListener('change', () => {
      const updatedProfile = applyActiveProfile(profileSelect.value);
      reloadTranscriptForProfile();
      addDebugMessage(`Profile changed to ${updatedProfile}.`);
      LAST_TURN = null;
      // Store active session for research monitor
      try {
        localStorage.setItem('pandora_active_session', updatedProfile);
      } catch (e) {
        console.warn('Could not store active session:', e);
      }
    });
    // Store initial session on page load
    try {
      const currentProfile = profileSelect.value || 'default';
      localStorage.setItem('pandora_active_session', currentProfile);
    } catch (e) {
      console.warn('Could not store initial session:', e);
    }
  }
  if (profileRememberToggle) {
    profileRememberToggle.addEventListener('change', () => {
      const remember = profileRememberToggle.checked;
      LS.set(PROFILE_REMEMBER_KEY, remember ? '1' : '0');
      if (!remember) {
        LS.remove(PROFILE_LS_KEY);
      } else {
        LS.set(PROFILE_LS_KEY, getActiveProfile());
      }
      addDebugMessage(`Profile memory ${remember ? 'enabled' : 'disabled'} for this device.`);
    });
  }
  const handleProfileAdd = () => {
    if (!profileNameInput) return;
    const raw = (profileNameInput.value || '').trim();
    if (!raw) return;
    const existing = findProfileMatch(raw);
    const target = existing || raw;
    if (!existing) {
      const next = [...profileOptions, target];
      persistProfileList(next);
      renderProfileOptions(next, target);
    } else {
      renderProfileOptions(profileOptions, target);
    }
    applyActiveProfile(target);
    profileNameInput.value = '';
    addDebugMessage(`Profile "${target}" ready to use.`);
  };
  if (profileAddBtn) {
    profileAddBtn.addEventListener('click', handleProfileAdd);
  }
  if (profileNameInput) {
    profileNameInput.addEventListener('keydown', (evt) => {
      if (evt.key === 'Enter') {
        evt.preventDefault();
        handleProfileAdd();
      }
    });
  }
  // Persist mode changes
  document.querySelectorAll('input[name="mode"]').forEach(r => {
    r.addEventListener('change', () => {
      LS.set('pandora.mode', r.value);
      if (repoRootWrap) repoRootWrap.style.display = (r.value === 'code') ? 'inline-block' : 'none';
      if (continueWrap) continueWrap.style.display = (r.value === 'code') ? 'inline-block' : 'none';
      updateContextStatus();
    });
  });

  if (repoRootSave && repoRootInput) {
    repoRootSave.addEventListener('click', async () => {
      const v = (repoRootInput.value || '').trim();
      LS.set('pandora.repoRoot', v);
      addDebugMessage(v ? ('Repo root saved: ' + v) : 'Repo root cleared.');
      updateContextStatus();

      if (v) {
        try {
          await persistServerRepoBase(v);
        } catch {
          // Error already logged; keep going so user can retry
        }
      }

      // Reload file tree if in code mode
      const mode = (document.querySelector('input[name="mode"]:checked')||{}).value || 'chat';
      if (mode === 'code' && v && typeof loadFileTreeData === 'function') {
        loadFileTreeData();
      }
    });
  }
  if (apiKeySave && apiKeyInput) {
    apiKeySave.addEventListener('click', () => {
      const k = (apiKeyInput.value || '').trim();
      LS.set('pandora.apiKey', k || 'sk-local');
      addDebugMessage('API key saved.');
    });
  }
  if (continueSave) {
    continueSave.addEventListener('click', () => {
      const on = !!(continueSendTgl && continueSendTgl.checked);
      const url = (continueWebhook && continueWebhook.value || '').trim();
      LS.set('pandora.continueSend', on ? '1' : '0');
      LS.set('pandora.continueWebhook', url);
      addDebugMessage(`Continue relay ${on ? 'enabled' : 'disabled'}${url ? ' → ' + url : ''}`);
    });
  }

  // Prompts panel bindings
  if (promptsOpen) {
    promptsOpen.addEventListener('click', async () => {
      try {
        // Load list
        const res = await fetch('/prompts');
        const js = await res.json();
        promptsSelect.innerHTML = '';
        (js.prompts || []).forEach(p => {
          const opt = document.createElement('option');
          opt.value = p.name; opt.textContent = p.name;
          promptsSelect.appendChild(opt);
        });
        // Load first prompt content
        if (promptsSelect.value) {
          await loadPromptIntoEditor(promptsSelect.value);
        }
        promptsPanel.style.display = 'block';
        addDebugMessage('Prompts panel opened.');
        await refreshPromptBackups(promptsSelect.value);
      } catch (e) {
        addDebugMessage('Prompts panel error: ' + (e && (e.message || String(e))));
      }
    });
  }
  if (promptsClose) {
    promptsClose.addEventListener('click', () => { promptsPanel.style.display = 'none'; });
  }
  if (promptsLoad) {
    promptsLoad.addEventListener('click', async () => {
      if (!promptsSelect.value) return;
      await loadPromptIntoEditor(promptsSelect.value);
      // Visual indicator
      const old = promptsLoad.textContent; promptsLoad.textContent = 'Loaded ✓';
      setTimeout(() => { promptsLoad.textContent = old; }, 900);
      await refreshPromptBackups(promptsSelect.value);
    });
  }
  if (promptsSave) {
    promptsSave.addEventListener('click', async () => {
      const name = promptsSelect.value;
      const content = promptsEditor.value || '';
      try {
        const res = await fetch('/prompts/' + encodeURIComponent(name), {
          method: 'PUT', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ content })
        });
        if (res.ok) {
          const js = await res.json();
          const backup = js && js.backup ? (' backup: ' + js.backup) : '';
          addDebugMessage('Saved prompt ' + name + ' (' + content.length + ' chars).' + backup);
          // Visual indicator
          const old = promptsSave.textContent; promptsSave.textContent = 'Saved ✓'; promptsSave.disabled = true;
          setTimeout(() => { promptsSave.textContent = old; promptsSave.disabled = false; }, 1200);
          await refreshPromptBackups(name);
        } else {
          const t = await res.text();
          addDebugMessage('Save prompt failed: ' + (t || res.status));
        }
      } catch (e) {
        addDebugMessage('Save prompt error: ' + (e && (e.message || String(e))));
      }
    });
  }
  if (promptsRefreshBackups) {
    promptsRefreshBackups.addEventListener('click', async () => {
      if (promptsSelect.value) await refreshPromptBackups(promptsSelect.value);
    });
  }

  // LAN controls
  if (useLANTgl) useLANTgl.addEventListener('change', () => {
    LS.set('pandora.useLAN', useLANTgl.checked ? '1' : '0');
    const base = LS.get('pandora.lanBase', 'http://192.168.1.150:9000');
    LS.set('pandora.apiBase', useLANTgl.checked ? (base.replace(/\/$/, '') + '/v1') : '/v1');
    addDebugMessage('Use LAN ' + (useLANTgl.checked ? 'enabled' : 'disabled'));
    scheduleHealthPing(true);
  });
  // REMOVED: lanApplyBtn event listener (UI element removed)

  // Policy UI
  if (policyBtn && policyPanel) {
    policyBtn.addEventListener('click', async () => {
      try { await refreshPolicyFromServer(); renderPolicyTools(); policyPanel.style.display = 'block'; } catch {}
    });
  }
  if (policyClose && policyPanel) {
    policyClose.addEventListener('click', () => { policyPanel.style.display = 'none'; });
  }
  if (policySave) {
    policySave.addEventListener('click', async () => {
      try {
        const body = collectPolicyFromUI();
        const res = await fetch('/policy', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
        if (res.ok) {
          POLICY = await res.json();
          addDebugMessage('Policy saved.');
        } else {
          const t = await res.text();
          addDebugMessage('Policy save failed: ' + (t || res.status));
        }
      } catch (e) {
        addDebugMessage('Policy error: ' + (e && (e.message || String(e))));
      }
    });
  }
}

// Connection indicator: ping /healthz on current base
let _connTimer = null;
async function scheduleHealthPing(immediate = false) {
  if (_connTimer) { clearTimeout(_connTimer); _connTimer = null; }
  const doPing = async () => {
    try {
      const apiBase = LS.get('pandora.apiBase', '/v1');
      let healthUrl = '/healthz';
      if (/^https?:\/\//i.test(apiBase)) {
        healthUrl = apiBase.replace(/\/?v1\/?$/i, '') + '/healthz';
      }
      const useLAN = LS.get('pandora.useLAN', '0') === '1';
      const ok = await fetchWithTimeout(healthUrl, { method: 'GET' }, 4000).then(r => r.ok).catch(()=>false);
      updateConnIndicator(ok, useLAN ? 'LAN' : 'Origin');
    } catch { updateConnIndicator(false, 'Origin'); }
    finally { _connTimer = setTimeout(doPing, 10000); }
  };
  if (immediate) doPing(); else _connTimer = setTimeout(doPing, 10000);
}

function updateConnIndicator(ok, label) {
  if (!connIndicator) return;
  try {
    connIndicator.classList.remove('ok','bad');
    connIndicator.classList.add(ok ? 'ok' : 'bad');
    const lab = connIndicator.querySelector('.label');
    if (lab) lab.textContent = label;
  } catch {}
}

async function fetchWithTimeout(resource, options = {}, timeoutMs = 5000) {
  const controller = new AbortController();
  const id = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetch(resource, { ...options, signal: controller.signal });
    return response;
  } finally {
    clearTimeout(id);
  }
}

async function refreshPolicyFromServer() {
  try { const js = await (await fetch('/policy')).json(); POLICY = js || POLICY; syncPolicyUI(); }
  catch {}
}

function syncPolicyUI() {
  if (!POLICY) return;
  if (polAllowWrites) polAllowWrites.checked = !!POLICY.chat_allow_file_create;
  if (polRequireConfirm) polRequireConfirm.checked = !!POLICY.write_confirm;
  if (polAllowedPaths) {
    const list = Array.isArray(POLICY.chat_allowed_write_paths) ? POLICY.chat_allowed_write_paths : [];
    let val = list.join('\n');
    if (!val.trim()) {
      // Default suggestion when empty
      val = '/path/to/project/panda_system_docs\n/path/to/another/project';
    }
    polAllowedPaths.value = val;
  }
  renderPolicyTools();
  updateWritePathIndicator();
}

function updateWritePathIndicator() {
  if (!writePathIndicator) return;
  const list = Array.isArray(POLICY.chat_allowed_write_paths) ? POLICY.chat_allowed_write_paths : [];
  if (list.length === 0) {
    writePathIndicator.textContent = 'Write paths: None configured';
    writePathIndicator.style.color = '#ff6b6b';
  } else {
    writePathIndicator.textContent = `Write paths: ${list.length} configured`;
    writePathIndicator.style.color = '#7fd288';
    writePathIndicator.title = list.join('\n');
  }
}

function renderPolicyTools() {
  if (!(policyToolsWrap && Array.isArray(TOOL_NAMES))) return;
  policyToolsWrap.innerHTML = '';
  const enables = (POLICY && POLICY.tool_enables) || {};
  TOOL_NAMES.forEach(name => {
    const label = document.createElement('label');
    label.style.color = '#cfd3e9';
    label.style.marginRight = '12px';
    const cb = document.createElement('input');
    cb.type = 'checkbox'; cb.checked = enables[name] !== false; // default on
    cb.dataset.tool = name;
    label.appendChild(cb);
    label.appendChild(document.createTextNode(' ' + name));
    policyToolsWrap.appendChild(label);
  });
}

function collectPolicyFromUI() {
  const enables = {};
  if (policyToolsWrap) {
    policyToolsWrap.querySelectorAll('input[type="checkbox"]').forEach(cb => {
      const name = cb.dataset.tool; if (!name) return; enables[name] = !!cb.checked;
    });
  }
  // Parse allowed paths (one per line)
  let allowed = [];
  if (polAllowedPaths) {
    const lines = (polAllowedPaths.value || '').split(/\r?\n/);
    lines.forEach(s => { const t = s.trim(); if (t) allowed.push(t); });
  }
  return {
    chat_allow_file_create: !!(polAllowWrites && polAllowWrites.checked),
    write_confirm: !!(polRequireConfirm && polRequireConfirm.checked),
    chat_allowed_write_paths: allowed,
    tool_enables: enables
  };
}

async function loadPromptIntoEditor(name) {
  try {
    const res = await fetch('/prompts/' + encodeURIComponent(name));
    const js = await res.json();
    promptsEditor.value = js.content || '';
    addDebugMessage('Loaded prompt ' + name + ' (' + (js.content ? js.content.length : 0) + ' chars).');
  } catch (e) {
    addDebugMessage('Load prompt error: ' + (e && (e.message || String(e))));
  }
}

async function refreshPromptBackups(name) {
  try {
    const res = await fetch('/prompts/' + encodeURIComponent(name) + '/backups');
    const js = await res.json();
    const list = js.backups || [];
    promptsBackups.innerHTML = '';
    if (list.length === 0) {
      const li = document.createElement('li');
      li.textContent = 'No backups yet.';
      li.style.color = '#cfd3e9';
      li.style.padding = '6px 10px';
      promptsBackups.appendChild(li);
      return;
    }
    list.forEach(b => {
      const li = document.createElement('li');
      li.style.padding = '6px 10px';
      li.style.borderBottom = '1px solid #2a2a33';
      const a = document.createElement('a');
      a.href = '#';
      const dt = b.mtime ? new Date(b.mtime * 1000).toISOString() : '';
      a.textContent = `${b.file} (${b.size} bytes${dt ? ', ' + dt : ''})`;
      a.addEventListener('click', async (ev) => {
        ev.preventDefault();
        try {
          const resp = await fetch('/prompts/' + encodeURIComponent(name) + '/backup?file=' + encodeURIComponent(b.file));
          if (!resp.ok) { addDebugMessage('Fetch backup failed: ' + resp.status); return; }
          const bj = await resp.json();
          promptsEditor.value = bj.content || '';
          addDebugMessage('Loaded backup ' + b.file + ' into editor (not saved yet).');
        } catch (e) {
          addDebugMessage('Error loading backup: ' + (e && (e.message || String(e))));
        }
      });
      li.appendChild(a);
      // Restore button
      const restoreBtn = document.createElement('button');
      restoreBtn.textContent = 'Restore';
      restoreBtn.style.marginLeft = '10px';
      restoreBtn.addEventListener('click', async (ev) => {
        ev.preventDefault();
        try {
          restoreBtn.disabled = true; const prev = restoreBtn.textContent; restoreBtn.textContent = 'Restoring…';
          const resp = await fetch('/prompts/' + encodeURIComponent(name) + '/backup?file=' + encodeURIComponent(b.file));
          if (!resp.ok) { addDebugMessage('Fetch backup failed: ' + resp.status); restoreBtn.textContent = prev; restoreBtn.disabled = false; return; }
          const bj = await resp.json();
          const content = bj.content || '';
          const put = await fetch('/prompts/' + encodeURIComponent(name), { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ content }) });
          if (!put.ok) {
            const t = await put.text();
            addDebugMessage('Restore failed: ' + (t || put.status));
            restoreBtn.textContent = prev; restoreBtn.disabled = false; return;
          }
          promptsEditor.value = content;
          addDebugMessage('Restored backup ' + b.file + ' and saved as current.');
          restoreBtn.textContent = 'Restored ✓';
          setTimeout(() => { restoreBtn.textContent = prev; restoreBtn.disabled = false; }, 1200);
        } catch (e) {
          addDebugMessage('Restore error: ' + (e && (e.message || String(e))));
          restoreBtn.disabled = false;
        }
      });
      li.appendChild(restoreBtn);
      promptsBackups.appendChild(li);
    });
  } catch (e) {
    addDebugMessage('Backups error: ' + (e && (e.message || String(e))));
  }
}

// Initialize settings on load
initSettingsFromStorage();
bindSettingHandlers();
reloadTranscriptForProfile();
updateContextStatus();

// Prevent Enter key from submitting form on configuration inputs
[repoRootInput, apiKeyInput, profileNameInput].forEach(input => {
  if (input) {
    input.addEventListener('keydown', e => {
      if (e.key === 'Enter') {
        e.preventDefault();
        e.stopPropagation();
        // Click the associated save/add button instead
        const parent = input.parentElement;
        const button = parent && parent.querySelector('button[type="button"]');
        if (button) button.click();
      }
    });
  }
});

// Workspace config button - opens settings panel
if (workspaceConfig) {
  workspaceConfig.addEventListener('click', () => {
    if (advPanel) setAdvancedVisible(true);
    addDebugMessage('Opening workspace settings...');
  });
}

// Clear chat (new conversation): removes transcript and UI bubbles
if (clearBtn) {
  clearBtn.addEventListener('click', () => {
    try { localStorage.removeItem(CHAT_LS_KEY); } catch {}
    CHAT = [];
    // Remove all message nodes and context/source blocks
    while (chatWindow.firstChild) chatWindow.removeChild(chatWindow.firstChild);
    addDebugMessage('Conversation cleared.');
  });
}

// Copy last exchange (previous User + last Chat) to clipboard
if (copyBtn) {
  copyBtn.addEventListener('click', async () => {
    try {
      const lastBot = Array.from(chatWindow.querySelectorAll('.msg.bot')).pop();
      if (!lastBot) return;
      // Find the nearest preceding user message
      let prev = lastBot.previousElementSibling;
      let lastUser = null;
      while (prev) {
        if (prev.classList && prev.classList.contains('user')) { lastUser = prev; break; }
        prev = prev.previousElementSibling;
      }
      const userText = lastUser ? lastUser.innerText.trim() : '';
      const botText  = lastBot.innerText.trim();
      const payload = (userText ? userText + '\n' : '') + (botText || '');
      if (!payload) return;
      await navigator.clipboard.writeText(payload);
      addDebugMessage('Copied last exchange to clipboard.');
    } catch (e) {
      addDebugMessage('Copy failed: ' + (e && (e.message || String(e))));
    }
  });
}

// Log last turn (broker + chat request/response) to server
if (logBtn) {
  logBtn.addEventListener('click', async () => {
    try {
      if (!LAST_TURN) { addDebugMessage('No turn data to log.'); return; }
      // Try to attach verbose transcript if available via trace_id
      let verbose = null;
      try {
        const traceId = (((LAST_TURN || {}).chat_response || {}).trace_id) || null;
        if (traceId) {
          const v = await fetch('/transcripts/' + encodeURIComponent(traceId) + '/verbose');
          if (v.ok) verbose = await v.json();
        }
      } catch {}

      // Derive simple grounding metrics and citations at log time
      const ans = (LAST_TURN.answer_text || '').toString();
      const ctx = (LAST_TURN.packed_text || '').toString();
      const tops = Array.isArray(LAST_TURN.top_titles) ? LAST_TURN.top_titles : [];
      const tok = s => new Set(String(s).toLowerCase().replace(/[^a-z0-9\s]/g, ' ').split(/\s+/).filter(w => w && w.length >= 3));
      let grounding_score = null;
      try {
        const A = tok(ans), C = tok(ctx);
        const inter = [...A].filter(x => C.has(x)).length;
        grounding_score = A.size ? (inter / A.size) : null;
      } catch {}
      // Extract citations by scanning parentheses for Title — Section patterns
      let citations = [];
      try {
        const parens = ans.match(/\(([^\)]+)\)/g) || [];
        const seen = new Set();
        for (const p of parens) {
          const inner = p.slice(1, -1).trim();
          if (!inner) continue;
          if (inner.includes(' — ') || tops.some(t => inner.includes(t))) {
            if (!seen.has(inner)) { seen.add(inner); citations.push(inner); }
          }
        }
      } catch {}
      const payload = Object.assign({}, LAST_TURN, { ts: Date.now(), citations, top_titles: tops, grounding_score });
      if (verbose) payload.transcript_verbose = verbose;
      const res = await fetch('/ui/log', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });
      if (res.ok) {
        addDebugMessage('Turn logged to server' + (verbose ? ' (verbose attached).' : '.'));
      } else {
        const t = await res.text();
        addDebugMessage('Log failed: ' + (t || res.status));
      }
    } catch (e) {
      addDebugMessage('Log error: ' + (e && (e.message || String(e))));
    }
  });
}

// Heuristic: detect small-talk/greetings to skip broker
function isConversational(text) {
  const t = (text || '').trim().toLowerCase();
  if (!t) return true;
  const patterns = [
    /^hi\b|^hello\b|^hey\b|^yo\b/,
    /how are you|how's it going|whats up|what's up|how do you do/,
    /tell me a joke|make me laugh|good morning|good evening|good night/,
    /^thanks\b|^thank you\b|^ok\b|^okay\b|^cool\b|^nice\b/,
  ];
  return patterns.some(re => re.test(t));
}

// Extracts a wiki-search intent like:
//  - "search the wiki database for information on hamsters"
//  - "search the wiki for hamsters"
//  - "find hamsters in the wiki"
// Returns a cleaned topic string or null
function extractWikiSearchTopic(text) {
  const s = (text || '').trim();
  if (!s) return null;
  const lower = s.toLowerCase();
  // Patterns to match common phrasing
  const patterns = [
    /^(?:please\s+)?search(?:\s+the)?\s+(?:wiki|wikipedia|wiki database)(?:\s+for|\s+about|\s+on)?\s+(.+?)\s*$/i,
    /^(?:please\s+)?search\s+.+?\s+for\s+(?:information\s+on\s+|about\s+)?(.+?)\s*(?:in|on)\s+(?:the\s+)?(?:wiki|wikipedia)\s*$/i,
    /^(?:find|lookup|look up|retrieve)\s+(.+?)\s*(?:in|on)\s+(?:the\s+)?(?:wiki|wikipedia)\s*$/i,
  ];
  for (const re of patterns) {
    const m = s.match(re);
    if (m && m[1]) {
      // Clean trivial fillers
      let topic = m[1].trim();
      topic = topic.replace(/^information\s+on\s+/i, '').replace(/^about\s+/i, '');
      // Strip trailing punctuation
      topic = topic.replace(/[.!?\s]+$/g, '');
      return topic;
    }
  }
  // Fallback: commands starting with "search wiki:" or "wiki:"
  if (lower.startsWith('search wiki:') || lower.startsWith('wiki:')) {
    const idx = s.indexOf(':');
    if (idx !== -1) {
      const topic = s.slice(idx + 1).trim().replace(/[.!?\s]+$/g, '');
      return topic || null;
    }
  }
  return null;
}

// Load available tools once
let TOOL_NAMES = [];
let PROVIDERS = [];
let PROVIDER_SYNONYMS = {};
let LAST_TURN = null;
let POLICY = { chat_allow_file_create: false, write_confirm: true, chat_allowed_write_paths: [] };
fetch('/teach/tools').then(r => r.json()).then(data => { TOOL_NAMES = data.tools; }).catch(console.error);
fetch('/broker/providers').then(r => r.json()).then(data => {
  PROVIDERS = data.providers || [];
  // Build a synonyms->name map for routing
  PROVIDER_SYNONYMS = {};
  PROVIDERS.forEach(p => {
    const name = (p.name || '').toLowerCase();
    if (!name) return;
    const syns = Array.isArray(p.synonyms) ? p.synonyms : [];
    [name, ...syns].forEach(s => {
      const key = String(s || '').toLowerCase().trim();
      if (key) PROVIDER_SYNONYMS[key] = name;
    });
  });
}).catch(console.error);

function parseProviderCommand(text) {
  const s = (text || '').trim();
  if (!s) return null;
  const lower = s.toLowerCase();
  // 1) Prefix form: "wiki: topic" or "docs: topic"
  const colonIdx = lower.indexOf(':');
  if (colonIdx > 0) {
    const maybeProv = lower.slice(0, colonIdx).trim();
    const prov = PROVIDER_SYNONYMS[maybeProv];
    if (prov) {
      const topic = s.slice(colonIdx + 1).trim().replace(/[.!?\s]+$/g, '');
      return topic ? { provider: prov, topic } : null;
    }
  }
  // 2) Verb form: "search the {provider} for {topic}", "find {topic} in {provider}"
  const patts = [
    // "search the wiki for hamsters" / "search wiki on hamsters"
    /^(?:please\s+)?search(?:\s+the)?\s+([a-zA-Z ]+?)(?:\s+database)?(?:\s+for|\s+about|\s+on)?\s+(.+?)\s*$/i,
    // "find hamsters in docs"
    /^(?:find|lookup|look up|retrieve)\s+(.+?)\s*(?:in|on)\s+(?:the\s+)?([a-zA-Z ]+)\s*$/i,
    // "do a wiki search on hamsters" / "run a docs search for X"
    /^(?:please\s+)?(?:do|run|perform|make)\s+(?:a\s+)?([a-zA-Z ]+)\s+search(?:\s+in|\s+on|\s+of|\s+for)?\s+(.+?)\s*$/i,
    // "do a search on the wiki for hamsters"
    /^(?:please\s+)?(?:do|run|perform|make)\s+(?:a\s+)?search(?:\s+in|\s+on|\s+of)\s+(?:the\s+)?([a-zA-Z ]+)(?:\s+for|\s+about|\s+on)?\s+(.+?)\s*$/i,
  ];
  for (const re of patts) {
    const m = s.match(re);
    if (m) {
      // pattern 1: provider, topic; pattern 2: topic, provider
      let provRaw, topicRaw;
      if (re === patts[0]) { provRaw = m[1]; topicRaw = m[2]; }
      else if (re === patts[1]) { provRaw = m[2]; topicRaw = m[1]; }
      else if (re === patts[2]) { provRaw = m[1]; topicRaw = m[2]; }
      else /* patts[3] */ { provRaw = m[1]; topicRaw = m[2]; }
      const prov = PROVIDER_SYNONYMS[(provRaw || '').toLowerCase().trim()];
      const topic = (topicRaw || '').trim().replace(/[.!?\s]+$/g, '');
      if (prov && topic) return { provider: prov, topic };
    }
  }
  return null;
}

function sendFeedback(key, value) {
  const userId = getActiveProfile();
  if (!userId) {
    return;
  }

  fetch('/memory.save_search_preference', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      user_id: userId,
      key: key,
      value: value,
      category: 'search_preference',
    })
  })
  .then(response => response.json())
  .then(data => {
    if (!data.ok) {
      console.error('Failed to send feedback:', data);
    }
  })
  .catch(error => {
    console.error('Error sending feedback:', error);
  });
}

function addMessage(text, sender, ephemeral = false) {
  const msg = document.createElement('div');
  msg.classList.add('msg', sender);
  // Optional label prefix
  if (sender === 'user' || sender === 'bot') {
    const prefix = document.createElement('span');
    prefix.className = 'prefix';
    prefix.textContent = sender === 'user' ? 'User:' : 'Chat:';
    msg.appendChild(prefix);
    const span = document.createElement('span');
    // Hide chain-of-thought (<think>...</think>) from display
    if (sender === 'bot') {
      const src = String(text || '');
      const stripped = src.replace(/<think>[\s\S]*?<\/think>/g, '').trim();
      span.innerHTML = stripped ? ' ' + formatBotText(stripped) : '';

      if (stripped.startsWith("Here's what I found from the latest search:")) {
        const feedbackSection = document.createElement('div');
        feedbackSection.className = 'feedback-section';

        const badBtn = document.createElement('button');
        badBtn.className = 'feedback-bad';
        badBtn.textContent = '❌ Not what I wanted';
        feedbackSection.appendChild(badBtn);

        const reasonSelect = document.createElement('select');
        reasonSelect.className = 'feedback-reason';
        const defaultOption = document.createElement('option');
        defaultOption.value = '';
        defaultOption.textContent = 'Select reason...';
        reasonSelect.appendChild(defaultOption);

        const reasons = [
          { value: 'wrong_item_type', text: 'Wrong item type' },
          { value: 'wrong_seller_type', text: 'Wrong seller type' },
          { value: 'price_too_high', text: 'Price too high' },
          { value: 'exclude_in_future', text: 'Exclude this in future' },
        ];
        reasons.forEach(r => {
          const option = document.createElement('option');
          option.value = r.value;
          option.textContent = r.text;
          reasonSelect.appendChild(option);
        });

        const feedbackValueInput = document.createElement('input');
        feedbackValueInput.type = 'text';
        feedbackValueInput.className = 'feedback-value-input';
        feedbackValueInput.placeholder = 'Enter value to exclude...';
        feedbackValueInput.style.display = 'none'; // Hidden by default

        feedbackSection.appendChild(reasonSelect);
        feedbackSection.appendChild(feedbackValueInput);

        reasonSelect.addEventListener('change', () => {
          const reason = reasonSelect.value;
          if (reason === 'wrong_item_type' || reason === 'exclude_in_future') {
            feedbackValueInput.style.display = 'inline-block';
          } else {
            feedbackValueInput.style.display = 'none';
          }
        });

        badBtn.addEventListener('click', () => {
          const reason = reasonSelect.value;
          const value = feedbackValueInput.value.trim();

          if (!reason) {
              sendFeedback('negative_feedback', 'unspecified');
              feedbackSection.innerHTML = 'Thanks for the feedback!';
              return;
          }

          if ((reason === 'wrong_item_type' || reason === 'exclude_in_future') && !value) {
              alert('Please enter a value to exclude.');
              return;
          }

          let key = 'negative_feedback';
          if (reason === 'wrong_item_type') {
              key = 'exclude_item_type';
          } else if (reason === 'exclude_in_future') {
              key = 'exclude_keyword';
          } else if (reason === 'wrong_seller_type') {
              key = 'exclude_seller_type';
          }

          sendFeedback(key, value || reason);
          feedbackSection.innerHTML = 'Thanks for the feedback!';
        });

        msg.appendChild(feedbackSection);
      }
    } else {
      span.textContent = ' ' + (text || '');
    }
    msg.appendChild(span);
  } else {
    msg.textContent = text;
  }
  chatWindow.appendChild(msg);
  chatWindow.scrollTop = chatWindow.scrollHeight;

  // Save to transcript (skip ephemeral placeholders like loading '…')
  if (!RESTORING && !ephemeral && (sender === 'user' || sender === 'bot')) {
    try {
      CHAT.push({ sender, text: String(text || '') });
      LS.set(CHAT_LS_KEY, JSON.stringify(CHAT));
    } catch { /* ignore */ }
  }
}

// Restore transcript from previous session
function restoreTranscript() {
  try {
    const raw = LS.get(CHAT_LS_KEY, '[]');
    const arr = JSON.parse(raw);
    if (Array.isArray(arr)) {
      // Filter out empty/ephemeral entries
      CHAT = arr.filter(m => m && (m.sender === 'user' || m.sender === 'bot') && typeof m.text === 'string' && m.text.trim() !== '' && m.text.trim() !== '…');
      try { LS.set(CHAT_LS_KEY, JSON.stringify(CHAT)); } catch { /* ignore */ }
      RESTORING = true;
      CHAT.forEach(m => {
        if (m && (m.sender === 'user' || m.sender === 'bot') && typeof m.text === 'string') {
          addMessage(m.text, m.sender);
        }
      });
    }
  } catch { /* ignore */ }
  finally { RESTORING = false; }
}

function reloadTranscriptForProfile() {
  try {
    while (chatWindow.firstChild) chatWindow.removeChild(chatWindow.firstChild);
  } catch { /* ignore */ }
  CHAT = [];
  RESTORING = false;
  restoreTranscript();
}

// New: Render sources as a list under the bot message
function renderSources(sources) {
  if (!sources || !Array.isArray(sources) || sources.length === 0) return null;
  const wrapper = document.createElement('div');
  wrapper.className = 'sources-list';
  const title = document.createElement('strong');
  title.textContent = 'Sources:';
  wrapper.appendChild(title);

  const ul = document.createElement('ul');
  sources.forEach(src => {
    const li = document.createElement('li');
    const a = document.createElement('a');
    a.href = src.source_url || src.url || '#';
    a.target = '_blank';
    a.rel = 'noopener noreferrer';
    a.textContent = src.source_title || src.title || src.source_url || src.url || '[no title]';
    li.appendChild(a);
    if (src.source_type || src.source) {
      const badge = document.createElement('span');
      badge.textContent = ` (${src.source_type || src.source})`;
      badge.style.fontStyle = 'italic';
      badge.style.marginLeft = '6px';
      li.appendChild(badge);
    }
    ul.appendChild(li);
  });
  wrapper.appendChild(ul);
  return wrapper;
}

function renderPackedContext(text, approxTokens, label = 'Context') {
  if (!text) return null;
  const details = document.createElement('details');
  details.className = 'sources-list';
  details.open = false; // collapsed by default
  const summary = document.createElement('summary');
  summary.textContent = `${label} ${approxTokens ? '(~'+approxTokens+' tokens)' : ''}`;
  details.appendChild(summary);
  const pre = document.createElement('pre');
  pre.style.whiteSpace = 'pre-wrap';
  pre.style.marginTop = '6px';
  pre.textContent = text;
  details.appendChild(pre);
  return details;
}

function buildIntentHeader(meta, wikiTopic, docsTopic, webTopic) {
  // Prefer server-provided meta hint
  if (meta && typeof meta.hint === 'string' && meta.hint.trim() !== '') {
    return meta.hint.trim();
  }
  // Client-side fallback
  if (wikiTopic) return `User requested a wiki search on: "${wikiTopic}".`;
  if (docsTopic) return `User requested a docs search on: "${docsTopic}".`;
  if (webTopic)  return `User requested a web search on: "${webTopic}".`;
  return '';
}

function renderDetailsBlock(title, objOrText) {
  const details = document.createElement('details');
  details.className = 'sources-list';
  details.open = false;
  const summary = document.createElement('summary');
  summary.textContent = title;
  details.appendChild(summary);
  const pre = document.createElement('pre');
  pre.style.whiteSpace = 'pre-wrap';
  pre.style.marginTop = '6px';
  pre.textContent = (typeof objOrText === 'string') ? objOrText : JSON.stringify(objOrText, null, 2);
  details.appendChild(pre);
  return details;
}

function addDebugMessage(debugText) {
  console.log("addDebugMessage called with:", debugText);
}

async function loadTemplatesFor(tool) {
  try {
    const res = await fetch(`/teach/templates?tool=${encodeURIComponent(tool)}`);
    if (!res.ok) return [];
    const json = await res.json().catch(()=>({templates:[]}));
    return json.templates || [];
  } catch {
    return [];
  }
}

/* REMOVED: Teach UI functionality - not compatible with this project
async function renderTeachUI(clauses = [], toolCalls = []) {
  const teachToggle = document.getElementById('teach-toggle');
  teachContainer.innerHTML = '';
  if (!(teachToggle && teachToggle.checked)) return;
  if (!clauses.length) return;

  const title = document.createElement('h3');
  title.textContent = 'Teach Mode';
  teachContainer.appendChild(title);

  for (let idx = 0; idx < clauses.length; idx++) {
    const clause = clauses[idx];
    const predicted = toolCalls[idx] || null;

    const panel = document.createElement('div');
    panel.classList.add('teach-panel');

    // Clause label
    const label = document.createElement('p');
    label.textContent = `Clause ${idx+1}: ${clause}`;
    panel.appendChild(label);

    // Tool dropdown
    const selectTool = document.createElement('select');
    TOOL_NAMES.forEach(tool => {
      const opt = document.createElement('option');
      opt.value = tool;
      opt.textContent = tool;
      if (predicted && predicted.tool === tool) opt.selected = true;
      selectTool.appendChild(opt);
    });
    panel.appendChild(selectTool);

    // Template dropdown & load button
    const templSelect = document.createElement('select');
    templSelect.style.margin = '0 8px';
    const loadBtn = document.createElement('button');
    loadBtn.textContent = 'Load Template';
    loadBtn.disabled = true;

    panel.appendChild(templSelect);
    panel.appendChild(loadBtn);

    // JSON textarea
    const textarea = document.createElement('textarea');
    textarea.rows = 5;
    textarea.cols = 60;
    const initial = predicted || { tool: selectTool.value, args: {} };
    textarea.value = JSON.stringify(initial, null, 2);
    panel.appendChild(textarea);

    // When tool changes, reload templates
    selectTool.addEventListener('change', async () => {
      const tool = selectTool.value;
      textarea.value = JSON.stringify({ tool, args: {} }, null, 2);
      // fetch templates
      const templates = await loadTemplatesFor(tool);
      templSelect.innerHTML = '';
      templates.forEach(t => {
        const o = document.createElement('option');
        o.value = t;
        o.textContent = t.split('\n')[0].slice(0,50) + '…';
        templSelect.appendChild(o);
      });
      loadBtn.disabled = templates.length === 0;
    });

    // Load the templates for initial tool
    (async () => {
      const tool = selectTool.value;
      const templates = await loadTemplatesFor(tool);
      templates.forEach(t => {
        const o = document.createElement('option');
        o.value = t;
        o.textContent = t.split('\n')[0].slice(0,50) + '…';
        templSelect.appendChild(o);
      });
      loadBtn.disabled = templates.length === 0;
    })();

    // Apply template into textarea
    loadBtn.addEventListener('click', () => {
      textarea.value = templSelect.value;
    });

    // Save button
    const saveBtn = document.createElement('button');
    saveBtn.textContent = 'Save Example';
    saveBtn.style.marginLeft = '8px';
    saveBtn.addEventListener('click', async () => {
      let toolCall;
      try {
        toolCall = JSON.parse(textarea.value);
      } catch {
        return alert('Invalid JSON');
      }
      const payload = {
        clause:   clause,
        label:    selectTool.value,
        tool_call: JSON.stringify(toolCall),
      };
      const resp = await fetch('/teach', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      if (resp.ok) {
        saveBtn.disabled = true;
        saveBtn.textContent = 'Saved ✅';
      } else {
        alert('Error saving example');
      }
    });
    panel.appendChild(saveBtn);

    teachContainer.appendChild(panel);
  }
}
*/

// Handle message send (from button or Enter key)
async function handleSendMessage() {
  const text = userInput.value.trim();
  if (!text) return;
  const tAllStart = (typeof performance !== 'undefined' ? performance.now() : Date.now());
  addMessage(text, 'user');
  const keepInput = keepInputTgl && keepInputTgl.checked;
  if (!keepInput) userInput.value = '';
  // Create inline thinking message immediately
  if (window.thinkingVisualizer) {
    console.log('[Thinking] Creating inline message BEFORE request');
    window.thinkingVisualizer.createInlineMessage();
  } else {
    // Fallback to old loading message
    addMessage('…', 'bot', true);
  }

  try {
    let mode = (document.querySelector('input[name="mode"]:checked')||{}).value || 'chat';
    const lowered = text.toLowerCase();
    const spreadsheetTerms = ['spreadsheet','csv','table','bill of materials','bom','parts list','pricing table','excel','ods'];
    const wantsSpreadsheet = spreadsheetTerms.some(term => lowered.includes(term));
    if (mode === 'chat' && wantsSpreadsheet) {
      const codeRadio = document.querySelector('input[name="mode"][value="code"]');
      if (codeRadio) {
        codeRadio.checked = true;
        addDebugMessage('Auto-switched to Code mode for spreadsheet/parts request.');
      }
      mode = 'code';
    }
    // Read current advanced settings
  const presetKey = (presetSel && presetSel.value) || 'chat';
  const preset = PRESETS[presetKey] || PRESETS.chat;
  const temperature = parseFloat((tempSlider && tempSlider.value) || preset.temperature);
    const top_p = parseFloat((topPSlider && topPSlider.value) || preset.top_p);
    const style = (styleSel && styleSel.value) || 'concise';

    let data = null;
    LAST_TURN = {
      ui: {
        mode,
        showContext: !!(showCtxTgl && showCtxTgl.checked),
        showRequests: !!(showReqTgl && showReqTgl.checked),
        fast: false
      },
      original_text: text,
      provider_cmd: null,
      broker_request: null,
      broker_response_meta: null,
      packed_text: null,
      approx_tokens: null,
      system_message: null,
      chat_request: null,
      chat_response: null,
      answer_text: null,
      timings: { broker_ms: null, map_ms: null, reduce_ms: null, answer_ms: null, total_ms: null }
    };
    const systemMsgByStyle = {
      concise: 'Answer concisely and directly.',
      educational: 'Explain step by step with clear reasoning and simple examples.',
      tutorial: 'Provide a tutorial-style explanation with sections, steps, and tips.',
    };
    let systemMsg = systemMsgByStyle[style] || systemMsgByStyle.concise;
    // Deterministic broker: fetch packed context only for explicit intents.
    // Regular chatting does NOT trigger retrieval anymore.
    let packedText = '';
    let summarized = false;
    const cmd = parseProviderCommand(text);

    if (cmd) {
      try {
        const needs = [];
        const fast = false;
        LAST_TURN.provider_cmd = { provider: cmd.provider, topic: cmd.topic, fast };
        if (cmd.provider === 'wiki') needs.push({ type: 'search', scopes: ['wiki'], query: cmd.topic, max_results: 8 });
        else if (cmd.provider === 'docs') needs.push({ type: 'search', scopes: ['docs'], query: cmd.topic, max_results: 6 });
        else {
          addDebugMessage(`Provider '${cmd.provider}' is not available or not yet implemented.`);
        }
        // Adjust for Fast mode
        if (fast) {
          needs.forEach(n => { if (n.scopes && n.scopes[0] === 'wiki') n.max_results = Math.min(n.max_results || 8, 4); if (n.scopes && n.scopes[0] === 'docs') n.max_results = Math.min(n.max_results || 6, 3); });
        }
        const brokerBody = {
          needs,
          token_budget_hint: fast ? 500 : 1000,
          fast: fast
        };
        LAST_TURN.broker_request = brokerBody;
        if (showReqTgl && showReqTgl.checked) {
          chatWindow.appendChild(renderDetailsBlock('Broker request', brokerBody));
        }
        const _tb0 = (typeof performance !== 'undefined' ? performance.now() : Date.now());
        const brokerRes = needs.length ? await fetch('/broker/request_context', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(brokerBody)
        }) : null;
        if (brokerRes && brokerRes.ok) {
          const bundle = await brokerRes.json();
          packedText = (bundle && bundle.packed_text) || '';
          const approx = (bundle && typeof bundle.approx_tokens === 'number') ? bundle.approx_tokens : null;
          if (approx) {
            const which = cmd.provider || 'unknown';
            addDebugMessage(`Broker (${which}) packed ~${approx} tokens for context.`);
          }
          const _tb1 = (typeof performance !== 'undefined' ? performance.now() : Date.now());
          LAST_TURN.timings.broker_ms = Math.round(_tb1 - _tb0);
          LAST_TURN.broker_response_meta = (bundle && bundle.meta) || null;
          LAST_TURN.packed_text = packedText;
          LAST_TURN.approx_tokens = approx;
          if (showReqTgl && showReqTgl.checked) {
            const metaHint = (bundle && bundle.meta && bundle.meta.hint) ? bundle.meta.hint : '';
            const preview = packedText ? packedText.slice(0, 400) + (packedText.length > 400 ? '…' : '') : '';
            chatWindow.appendChild(renderDetailsBlock('Broker response (meta)', { hint: metaHint, approx_tokens: approx }));
            if (preview) chatWindow.appendChild(renderDetailsBlock('Broker response (Context preview)', preview));
          }
          // Render context if requested
          if (showCtxTgl && showCtxTgl.checked && packedText) {
            const ctxEl = renderPackedContext(packedText, approx || undefined, 'Broker Context');
            if (ctxEl) chatWindow.appendChild(ctxEl);
          }
          // If intent is explicit, keep a short meta header to inform the model
          if (cmd) {
            try { LS.set('pandora.lastMeta', JSON.stringify(bundle.meta || {})); } catch {}
          }

          // Auto‑summarize: map → reduce when Broker Context is large
          const thr = parseInt((autoSummarizeThr && autoSummarizeThr.value) ? autoSummarizeThr.value : '700', 10) || 700;
          const wantSummarize = (autoSummarizeTgl && autoSummarizeTgl.checked) && ((approx || 0) >= thr);
          if (wantSummarize) {
            addDebugMessage(`Auto‑summarize triggered: context ~${approx} ≥ threshold ${thr}`);
            try {
              const items = Array.isArray(bundle.items) ? bundle.items : [];
              const ids = items.map(it => it && it.id).filter(Boolean);
              if (ids.length > 0) {
                const perChunkBudget = fast ? 220 : 300;
                const reduceBudget = fast ? 420 : 600;
                const mapReq = { provider: cmd.provider, topic: cmd.topic, chunk_ids: ids, per_chunk_budget: perChunkBudget, fast };
                if (showReqTgl && showReqTgl.checked) chatWindow.appendChild(renderDetailsBlock('Summarize map request', mapReq));
                const _tm0 = (typeof performance !== 'undefined' ? performance.now() : Date.now());
                const mapRes = await fetch('/broker/summarize_map', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(mapReq) });
                let summaries = [];
                if (mapRes.ok) {
                  const mj = await mapRes.json();
                  summaries = mj.summaries || [];
                  try { LAST_TURN.map_summaries = summaries; } catch {}
                  if (showReqTgl && showReqTgl.checked) chatWindow.appendChild(renderDetailsBlock(`Summarize map response (${summaries.length})`, summaries.slice(0, 5)));
                  if (showCtxTgl && showCtxTgl.checked && summaries.length > 0) {
                    const mapText = summaries.map(s => (s && s.summary_text) ? String(s.summary_text).trim() : '').filter(Boolean).join('\n');
                    const mapEl = renderPackedContext(mapText, null, `Map Summaries (${summaries.length})`);
                    if (mapEl) chatWindow.appendChild(mapEl);
                  }
                }
                if (summaries.length > 0) {
                  const redReq = { topic: cmd.topic, summaries: summaries, final_budget: reduceBudget };
                  if (showReqTgl && showReqTgl.checked) chatWindow.appendChild(renderDetailsBlock('Summarize reduce request', redReq));
                  const _tm1 = (typeof performance !== 'undefined' ? performance.now() : Date.now());
                  LAST_TURN.timings.map_ms = Math.round(_tm1 - _tm0);
                  const redRes = await fetch('/broker/summarize_reduce', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(redReq) });
                  if (redRes.ok) {
                    const rj = await redRes.json();
                    const fctx = rj.final_context || '';
                    const ftok = rj.approx_tokens || null;
                    if (fctx) {
                      try {
                        LAST_TURN.final_context = fctx;
                        LAST_TURN.final_context_tokens = ftok;
                        LAST_TURN.summarize = { auto: true, threshold: thr, approx_before: approx };
                      } catch {}
                      packedText = fctx; // override with reduced context
                      summarized = true;
                      if (showCtxTgl && showCtxTgl.checked) {
                        const ctxEl2 = renderPackedContext(packedText, ftok || undefined, 'Final Context');
                        if (ctxEl2) chatWindow.appendChild(ctxEl2);
                      }
                      if (showReqTgl && showReqTgl.checked) chatWindow.appendChild(renderDetailsBlock('Summarize reduce response (preview)', fctx.slice(0, 500)));
                    }
                  }
                  const _tm2 = (typeof performance !== 'undefined' ? performance.now() : Date.now());
                  LAST_TURN.timings.reduce_ms = Math.round(_tm2 - _tm1);
                }
              }
            } catch (e) {
              addDebugMessage('Summarize error: ' + (e && (e.message || String(e))));
            }
          }
        }
      } catch (e) { /* ignore broker errors, continue without context */ }
    }

    // If we have an explicit search intent, pass the cleaned topic as the question
    const question = cmd ? cmd.topic : text;
    // Always suppress chain-of-thought in final answers
    systemMsg = `${systemMsg} Do not include chain-of-thought or <think> content; output only the answer.`;
    if (packedText) {
      // Strengthen system guidance to use provided context
      systemMsg = `${systemMsg} Use the provided Context verbatim to answer. If the context is insufficient, say what is missing.`;
      // If this turn involved an explicit provider search, ask for citations
      if (cmd) {
        systemMsg = `${systemMsg} Cite source titles in parentheses when relevant (e.g., (Hamster — Introduction)).`;
      } else {
        // Fallback: check lastMeta for search needs
        try {
          const m = JSON.parse(LS.get('pandora.lastMeta', '{}'));
          const needs = Array.isArray(m.needs) ? m.needs : [];
          if (needs.some(n => (n && n.type === 'search'))) {
            systemMsg = `${systemMsg} Cite source titles in parentheses when relevant (e.g., (Hamster — Introduction)).`;
          }
        } catch {}
      }
      // Always suppress chain-of-thought in final answers
      systemMsg = `${systemMsg} Do not include chain-of-thought or <think> content; output only the answer.`;
      // If we summarized, guide the final formatting towards a fact sheet
      if (summarized) {
        systemMsg = `${systemMsg} Format as a short fact sheet: 3–5 brief subheadings with dash bullets only; no preface.`;
      }
    }
    // Build an intent header only for explicit provider commands
    let metaHdr = '';
    if (cmd) {
      try {
        const m = JSON.parse(LS.get('pandora.lastMeta', '{}'));
        const which = cmd.provider === 'wiki' ? 'wiki' : (cmd.provider === 'docs' ? 'docs' : '');
        metaHdr = buildIntentHeader(m, which === 'wiki' ? question : null, which === 'docs' ? question : null, null);
      } catch {
        const which = cmd.provider;
        metaHdr = buildIntentHeader(null, which === 'wiki' ? question : null, which === 'docs' ? question : null, null);
      }
    } else {
      // Clear any stale broker meta so headers like 'broker v1' are not carried over
      try { LS.set('pandora.lastMeta', '{}'); } catch {}
    }

    // Assemble final user content
    // Include intent header only for explicit searches
    const head = (metaHdr ? (metaHdr + '\n\n') : '');
    const ctx  = (packedText ? (`Context:\n${packedText}\n\n`) : '');
    const userContent = head + ctx + 'Question: ' + question;
    if (showReqTgl && showReqTgl.checked) {
      const preview = userContent.slice(0, 500) + (userContent.length > 500 ? '…' : '');
      const chatReq = { model: (preset && preset.model) || 'pandora-act', temperature, top_p, system: systemMsg, user_preview: preview };
      chatWindow.appendChild(renderDetailsBlock('Chat request (preview)', chatReq));
    }
    LAST_TURN.system_message = systemMsg;
    LAST_TURN.chat_request = { model: preset.model, temperature, top_p, endpoint: API_BASE, messages: [{ role: 'system', content: systemMsg }, { role: 'user', content: userContent }] };
    const messages = [ { role: 'system', content: systemMsg }, { role: 'user', content: userContent } ];
    // Dynamic response budget: allow longer answers when grounded in context (unless Fast mode)
    let maxTokens = 320;
    try {
      const fast = !!(fastModeTgl && fastModeTgl.checked);
      if (!fast && (packedText || summarized)) maxTokens = 512;
    } catch {}
    const stopTokens = ["<think>", "</think>", "Thought:", "Chain-of-thought:", "<think", "</think>"];
    const repoSaved = (repoRootInput && repoRootInput.value) || LS.get('pandora.repoRoot', '');
    const profileId = getActiveProfile();
    const requestPayload = {
      model: preset.model,
      messages,
      temperature,
      top_p,
      // Cap generation to reduce latency/timeouts (adaptive)
      max_tokens: maxTokens,
      // Block CoT markers proactively
      stop: stopTokens,
      user_id: profileId,
      session_id: profileId,  // Add session_id for research monitor and tool routing
      // Send mode to Gateway (chat or code)
      mode: mode === 'code' ? 'code' : 'chat',
    };
    if (repoSaved) {
      requestPayload.repo = repoSaved;
    }

    // Create timeout controller for long-running research queries
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 1800000); // 30 minute timeout (matches server-side research timeout)

    const fetchOptions = {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': 'Bearer ' + getApiKey(),
        'X-User-Id': profileId,
      },
      body: JSON.stringify(requestPayload),
      signal: controller.signal  // Add abort signal for timeout
    };

    // Continue mode adjustments: set repo root header and tighten style toward actionable steps
    if (mode === 'code') {
      try {
        const rr = repoSaved;
        if (rr) fetchOptions.headers['X-Repo-Root'] = rr;
      } catch {}
      // Nudge system message to produce actionable, concise steps
      try {
        const idx = messages.findIndex(m => m.role === 'system');
        if (idx >= 0 && messages[idx] && typeof messages[idx].content === 'string') {
          messages[idx].content = `${messages[idx].content} When proposing changes, output concise, actionable steps and filenames. Prefer diffs or minimal patches over long prose.`;
          requestPayload.messages = messages;
          fetchOptions.body = JSON.stringify(requestPayload);
        }
      } catch {}
    } else if (repoSaved) {
      // Ensure body reflects potential message mutations above while retaining repo field
      requestPayload.messages = messages;
      fetchOptions.body = JSON.stringify(requestPayload);
    }

    {
      // Connect to research progress WebSocket (uses profileId as session_id)
      if (window.researchProgressHandler) {
        try {
          window.researchProgressHandler.connect(profileId);
          console.log('[App] Research progress handler connected for session:', profileId);
        } catch (e) {
          console.warn('[App] Failed to connect research progress handler:', e);
        }
      }

      const _tc0 = (typeof performance !== 'undefined' ? performance.now() : Date.now());
    const useJobs = !!(useJobsTgl && useJobsTgl.checked);
    let res, dataRaw;
    if (useJobs) {
      // Start background job
      let start;
      try {
        start = await fetch('/jobs/start', { method: 'POST', headers: fetchOptions.headers, body: fetchOptions.body });
      } catch (e) {
        const lastBot = chatWindow.querySelector('.msg.bot:last-child');
        if (lastBot && !lastBot.classList.contains('thinking-msg')) chatWindow.removeChild(lastBot);
        addDebugMessage('Jobs start error: ' + (e && (e.message || String(e))));
        addMessage('Request in progress - check back shortly or refresh the page.', 'bot');
        return;
      }
      if (!start.ok) {
        const t = await start.text().catch(()=> '');
        const lastBot = chatWindow.querySelector('.msg.bot:last-child'); if (lastBot && !lastBot.classList.contains('thinking-msg')) chatWindow.removeChild(lastBot);
        addDebugMessage(`Jobs start failed ${start.status}: ${t.slice(0,300)}`);
        addMessage('Request failed to start. Please try again.', 'bot');
        return;
      }
      const sj = await start.json();
      const jobId = sj.job_id;
      // Show cancel button while job is running (pass null for trace_id)
      showCancelButton(jobId, null);
      // Poll until done
      const t0 = (typeof performance !== 'undefined' ? performance.now() : Date.now());
      let attempts = 0;
      let got = null;
      while (attempts < 600) { // up to ~900s (with 1.5s sleep) - extended for long research tasks
        attempts++;
        try {
          const jr = await fetch(`/jobs/${encodeURIComponent(jobId)}`);
          const jj = await jr.json();
          if (jj.status === 'done') { got = jj.result; break; }
          if (jj.status === 'cancelled') {
            hideCancelButton();
            const lastBot = chatWindow.querySelector('.msg.bot:last-child'); if (lastBot && !lastBot.classList.contains('thinking-msg')) chatWindow.removeChild(lastBot);
            addDebugMessage('Job cancelled by user');
            addMessage('Query cancelled.', 'bot');
            return;
          }
          if (jj.status === 'error') {
            hideCancelButton();
            const lastBot = chatWindow.querySelector('.msg.bot:last-child'); if (lastBot && !lastBot.classList.contains('thinking-msg')) chatWindow.removeChild(lastBot);
            addDebugMessage('Job error: ' + JSON.stringify(jj.error || {}));
            addMessage('Error contacting server.', 'bot');
            return;
          }
        } catch {}
        await new Promise(r => setTimeout(r, 1500));
      }
      hideCancelButton();
      if (!got) {
        const lastBot = chatWindow.querySelector('.msg.bot:last-child'); if (lastBot && !lastBot.classList.contains('thinking-msg')) chatWindow.removeChild(lastBot);
        addDebugMessage('Job timed out waiting for result.');
        addMessage('Error contacting server.', 'bot');
        return;
      }
      dataRaw = got;
    } else {
      const apiBase = LS.get('pandora.apiBase', '/v1');
      try {
        res = await fetch(`${apiBase}/chat/completions`, fetchOptions);
        clearTimeout(timeoutId); // Clear timeout on successful response
        let rawText = '';
        if (!res.ok) {
          try { rawText = await res.text(); } catch {}
          // remove loading bubble and show error
          const lastBot = chatWindow.querySelector('.msg.bot:last-child');
          if (lastBot && !lastBot.classList.contains('thinking-msg')) chatWindow.removeChild(lastBot);
            addDebugMessage(`Gateway error ${res.status}: ${rawText || '[no body]'}`);
          addMessage('Error contacting server.', 'bot');
          return;
        }
        dataRaw = await res.json();
      } catch (err) {
        clearTimeout(timeoutId); // Clear timeout on error
        if (err.name === 'AbortError') {
          const lastBot = chatWindow.querySelector('.msg.bot:last-child');
          if (lastBot && !lastBot.classList.contains('thinking-msg')) chatWindow.removeChild(lastBot);
          addDebugMessage('Request timed out after 10 minutes');
          addMessage('Request timed out. The server may still be processing your query. Try asking again to use cached results.', 'bot');
        } else {
          const lastBot = chatWindow.querySelector('.msg.bot:last-child');
          if (lastBot && !lastBot.classList.contains('thinking-msg')) chatWindow.removeChild(lastBot);
          addDebugMessage(`Fetch error: ${err.message}`);
          addMessage('Error contacting server.', 'bot');
        }
        return;
      }
    }
      try { data = dataRaw; }
      catch {
        const lastBot = chatWindow.querySelector('.msg.bot:last-child'); if (lastBot && !lastBot.classList.contains('thinking-msg')) chatWindow.removeChild(lastBot);
        addDebugMessage('Gateway non-JSON response');
        addMessage('Error: invalid JSON from server.', 'bot');
        return;
      }

      // Start thinking visualization ONLY if this is an async research response
      // If the response already contains the answer (not "Research started"), skip SSE
      try {
        const traceId = (data || {}).trace_id || (data || {}).id;
        const initialContent = (((data||{}).choices||[])[0]||{}).message?.content || '';
        const isAsyncResearch = initialContent.includes('Research started') || initialContent.includes('Connect to /v1/thinking');

        console.log('[Thinking] Response received, trace_id:', traceId, 'isAsyncResearch:', isAsyncResearch);

        if (traceId && window.startThinking && isAsyncResearch) {
          console.log('[Thinking] Starting SSE visualization for async research');
          window.startThinking(traceId);
          // Show cancel button for trace-based cancellation
          showCancelButton(null, traceId);
        } else if (traceId && !isAsyncResearch) {
          console.log('[Thinking] Skipping SSE - response already contains answer (fast/cached)');
          // Remove the inline thinking message since we're not using SSE
          if (window.thinkingVisualizer) {
            window.thinkingVisualizer.removeInlineMessage();
          }
        } else {
          console.warn('[Thinking] Not starting visualization:', { traceId, hasStartThinking: !!window.startThinking });
          // Also remove inline message for non-trace responses
          if (window.thinkingVisualizer) {
            window.thinkingVisualizer.removeInlineMessage();
          }
        }
      } catch (err) {
        console.error('[Thinking] Failed to start thinking visualization:', err);
      }

      // remove loading (but NOT thinking message)
      const lastBot = chatWindow.querySelector('.msg.bot:last-child');
      if (lastBot && !lastBot.classList.contains('thinking-msg')) {
        console.log('[Thinking] Removing loading message');
        chatWindow.removeChild(lastBot);
      } else if (lastBot && lastBot.classList.contains('thinking-msg')) {
        console.log('[Thinking] Preserving thinking message, not removing');
      }

      // Render answer and sources if available
      // BUT skip if this is an async research response - the real answer will come via SSE
      const content = (((data||{}).choices||[])[0]||{}).message?.content;
      const isAsyncResponse = content && (content.includes('Research started') || content.includes('Connect to /v1/thinking'));

      if (isAsyncResponse) {
        console.log('[Thinking] Skipping addMessage for async response - will receive via SSE');
        // Don't add "Research started..." - the thinking visualization handles progress
      } else if (typeof content === 'string' && content.trim() !== '') {
        const disp = content.replace(/<think>[\s\S]*?<\/think>/g, '').trim();
        addMessage(disp, 'bot');
      } else {
        addMessage('[No response]', 'bot');
      }

      // Render confirmation bar if server deferred any actions
      try {
        const reqs = Array.isArray(data.requires_confirm) ? data.requires_confirm : [];
        renderConfirmBar(reqs);
      } catch {}
      LAST_TURN.chat_response = data;
      LAST_TURN.answer_text = (content || '').replace(/<think>[\s\S]*?<\/think>/g, '').trim();
      let finishReason = null;
      try {
        const ch0 = (((data||{}).choices||[])[0]) || {};
        finishReason = ch0.finish_reason || null;
        LAST_TURN.finish_reason = finishReason;
        LAST_TURN.usage = data.usage || null;
      } catch {}
      // Auto-continue once if truncated by max_tokens
      if (finishReason === 'length') {
        addDebugMessage('Truncated by max_tokens. Auto-continuing once…');
        try {
          const contMsg = 'Continue where you stopped; complete remaining sections. Keep the same structure and include citations in parentheses.';
          const messages2 = [
            { role: 'system', content: systemMsg },
            { role: 'user', content: userContent },
            // pass only visible portion (no <think>) to continuation
            { role: 'assistant', content: (content || '').replace(/<think>[\s\S]*?<\/think>/g, '').trim() },
            { role: 'user', content: contMsg }
          ];
          const fetchOptions2 = {
            method: 'POST',
            headers: {
              'Content-Type': 'application/json',
              'Authorization': 'Bearer ' + getApiKey(),
              'X-User-Id': profileId
            },
            body: JSON.stringify({
              model: preset.model,
              messages: messages2,
              temperature,
              top_p,
              max_tokens: 320,
              stop: ["<think>", "</think>", "Thought:", "Chain-of-thought:", "<think", "</think>"],
              user_id: profileId
            })
          };
          const _tc2_0 = (typeof performance !== 'undefined' ? performance.now() : Date.now());
          // show transient loading bubble for continuation
          addMessage('…', 'bot', true);
          const apiBase2 = LS.get('pandora.apiBase', '/v1');
          const res2 = await fetch(`${apiBase2}/chat/completions`, fetchOptions2);
          let raw2 = '';
          if (!res2.ok) {
            try { raw2 = await res2.text(); } catch {}
            const lastBot2 = chatWindow.querySelector('.msg.bot:last-child');
            if (lastBot2) chatWindow.removeChild(lastBot2);
            addDebugMessage(`Gateway (continue) error ${res2.status}: ${raw2 || '[no body]'}`);
          } else {
            const data2 = await res2.json();
            const lastBot2 = chatWindow.querySelector('.msg.bot:last-child');
            if (lastBot2) chatWindow.removeChild(lastBot2);
            const content2 = ((((data2||{}).choices||[])[0]||{}).message||{}).content || '';
            const disp2 = content2.replace(/<think>[\s\S]*?<\/think>/g, '').trim();
            if (disp2) addMessage(disp2, 'bot');
            LAST_TURN.continuation = {
              request: { model: preset.model, messages_preview: '[system, user, assistant(partial), user(continue)]', temperature, top_p, max_tokens: 320 },
              response: data2,
              answer_text: disp2
            };
            const _tc2_1 = (typeof performance !== 'undefined' ? performance.now() : Date.now());
            LAST_TURN.timings.answer2_ms = Math.round(_tc2_1 - _tc2_0);
          }
        } catch (e) {
          addDebugMessage('Auto-continue failed: ' + (e && (e.message || String(e))));
        }
      }
      // Debug: show compact JSON for troubleshooting
      // try { addDebugMessage('Gateway JSON (truncated):\n' + JSON.stringify(data).slice(0, 1200)); } catch {}

      // Continue relay REMOVED - Pandora is now standalone with built-in IDE

      // Update IDE components (task tracker, terminal)
      try {
        updateTaskTrackerFromResponse(data);
        parseBashOutput(data);
      } catch (e) {
        console.error('IDE component update failed:', e);
      }

      // Show sources from the *first* research answer (optional: loop through all)
      if (data.quick_answers) {
        data.quick_answers.forEach(ans => {
          if (ans.sources && ans.sources.length > 0) {
            const srcElem = renderSources(ans.sources);
            if (srcElem) chatWindow.appendChild(srcElem);
          }
        });
      }

      if (data.debug)  addDebugMessage(data.debug);
      const _tc1 = (typeof performance !== 'undefined' ? performance.now() : Date.now());
      LAST_TURN.timings.answer_ms = Math.round(_tc1 - _tc0);
    }

    // REMOVED: Teach UI call (functionality removed)
    // if (mode === 'chat' && data) {
    //   renderTeachUI(data.clauses || [], data.tool_calls || []);
    // }
    const _tAllEnd = (typeof performance !== 'undefined' ? performance.now() : Date.now());
    LAST_TURN.timings.total_ms = Math.round(_tAllEnd - tAllStart);
  } catch (err) {
    const lastBot = chatWindow.querySelector('.msg.bot:last-child');
    if (lastBot && !lastBot.classList.contains('thinking-msg')) chatWindow.removeChild(lastBot);
    addMessage('Error contacting server.', 'bot');
    console.error(err);
    try { addDebugMessage('JS error: ' + (err && (err.stack || err.message) || String(err))); } catch {}
  }
}

// Send button click handler
const sendBtn = document.getElementById('send-btn');
console.log('Send button found:', sendBtn);
console.log('User input found:', userInput);
if (sendBtn) {
  sendBtn.addEventListener('click', () => {
    console.log('Send button clicked');
    handleSendMessage();
  });
  console.log('Send button listener attached');
}

// Command history (like terminal)
const commandHistory = [];
let historyPointer = -1;
let currentInput = ''; // Temporary storage for current typing

// Enter key handler on input field with command history support
if (userInput) {
  userInput.addEventListener('keydown', e => {
    if (e.key === 'Enter' && !e.shiftKey) {
      console.log('Enter key pressed');
      e.preventDefault();

      // Save to history before sending
      const message = userInput.value.trim();
      if (message) {
        commandHistory.push(message);
        historyPointer = commandHistory.length; // Reset to end
        currentInput = ''; // Clear temp storage
      }

      handleSendMessage();
    } else if (e.key === 'ArrowUp') {
      // Navigate backwards in history
      e.preventDefault();
      if (commandHistory.length > 0) {
        // Save current input if at the end of history
        if (historyPointer === commandHistory.length) {
          currentInput = userInput.value;
        }

        if (historyPointer > 0) {
          historyPointer--;
          userInput.value = commandHistory[historyPointer];
        }
      }
    } else if (e.key === 'ArrowDown') {
      // Navigate forwards in history
      e.preventDefault();
      if (commandHistory.length > 0 && historyPointer < commandHistory.length) {
        historyPointer++;

        if (historyPointer === commandHistory.length) {
          // Restore current input when reaching end
          userInput.value = currentInput;
        } else {
          userInput.value = commandHistory[historyPointer];
        }
      }
    }
  });
  console.log('Enter key listener attached with command history');
}
// Fetch write policy for UI controls (best-effort)
fetch('/policy').then(r => r.json()).then(js => { if (js) { POLICY = js; try { syncPolicyUI(); } catch {} } }).catch(() => {});

// Confirmation bar renderer and executor
function renderConfirmBar(items) {
  const bar = document.getElementById('confirm-bar');
  if (!bar) return;
  bar.innerHTML = '';
  const list = Array.isArray(items) ? items : [];
  if (list.length === 0) { bar.style.display = 'none'; return; }
  // Title
  const title = document.createElement('div');
  title.textContent = 'Pending actions (requires confirmation)';
  title.style.fontWeight = '700';
  title.style.marginBottom = '6px';
  bar.appendChild(title);

  list.forEach((it, idx) => {
    const row = document.createElement('div');
    row.className = 'confirm-item';
    const meta = document.createElement('div');
    meta.className = 'meta';
    meta.textContent = describeAction(it);
    row.appendChild(meta);
    // If this is a file.create action, provide root selector and path input
    if (it && it.tool === 'file.create') {
      const ctrl = document.createElement('div');
      ctrl.style.display = 'flex';
      ctrl.style.gap = '8px';
      ctrl.style.alignItems = 'center';
      ctrl.style.flexWrap = 'wrap';
      // Root selector (repo root + allowed paths)
      const rootSel = document.createElement('select');
      rootSel.className = 'root-select';
      const repoSaved = (repoRootInput && repoRootInput.value) || LS.get('pandora.repoRoot', '');
      const roots = [];
      if (repoSaved) roots.push({ label: 'Repo Root (saved)', value: repoSaved });
      (POLICY.chat_allowed_write_paths || []).forEach(p => roots.push({ label: p, value: p }));
      if (roots.length === 0) { roots.push({ label: '<set repo root in toolbar>', value: '' }); }
      roots.forEach(r => { const o = document.createElement('option'); o.value = r.value; o.textContent = r.label; rootSel.appendChild(o); });
      if (it.args && it.args.repo) rootSel.value = it.args.repo;
      ctrl.appendChild(rootSel);
      // Path input (relative)
      const pathInput = document.createElement('input');
      pathInput.type = 'text';
      pathInput.placeholder = 'relative/path/to/file.ext';
      pathInput.className = 'path-input';
      pathInput.style.minWidth = '240px';
      pathInput.value = (it.args && it.args.path) ? String(it.args.path).replace(/^\/+/, '') : '';
      ctrl.appendChild(pathInput);
      row.appendChild(ctrl);
    }
    const actions = document.createElement('div');
    actions.className = 'confirm-actions';
    const approve = document.createElement('button');
    approve.textContent = 'Approve';
    approve.addEventListener('click', () => approveAction(it, row));
    const dismiss = document.createElement('button');
    dismiss.className = 'dismiss';
    dismiss.textContent = 'Dismiss';
    dismiss.addEventListener('click', () => { row.remove(); maybeHideConfirmBar(); });
    actions.appendChild(approve);
    actions.appendChild(dismiss);
    row.appendChild(actions);
    bar.appendChild(row);
  });
  bar.style.display = 'block';
}

function describeAction(it) {
  try {
    const tool = it && it.tool;
    const args = (it && it.args) || {};
    if (tool === 'file.create') {
      const repo = args.repo || LS.get('pandora.repoRoot', '') || '<repo?>';
      return `file.create → ${repo}/${args.path || '<path?>'} (${(args.content||'').length} chars)`;
    }
    return `${tool} ${JSON.stringify(args)}`;
  } catch { return 'action'; }
}

async function approveAction(it, row) {
  try {
    const mode = (document.querySelector('input[name="mode"]:checked')||{}).value || 'answer';
    let repo = (repoRootInput && repoRootInput.value) || LS.get('pandora.repoRoot', '');
    const payload = { tool: it.tool, args: Object.assign({}, it.args), mode, repo, confirmed: true };
    // For file.create allow overriding target root and path from UI controls
    if (payload.tool === 'file.create' && row) {
      const sel = row.querySelector('.root-select');
      const pin = row.querySelector('.path-input');
      if (sel && typeof sel.value === 'string' && sel.value) repo = sel.value;
      if (pin && typeof pin.value === 'string') payload.args.path = pin.value.replace(/^\/+/, '');
      payload.repo = repo;
      payload.args.repo = repo;
    }
    // Ensure repo is filled for repo-scoped tools
    if (repo && payload.tool && ['file.create','code.apply_patch','git.commit','code.search'].includes(payload.tool)) {
      if (!payload.args.repo) payload.args.repo = repo;
    }
    const res = await fetch('/tool/execute', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
    if (!res.ok) {
      const t = await res.text();
      addDebugMessage(`Confirm failed (${res.status}): ${t.slice(0,300)}`);
      return;
    }
    const js = await res.json();
    addDebugMessage(`Action executed: ${describeAction(it)} → ${JSON.stringify(js).slice(0, 300)}`);
    // Visual success, then remove row
    row.style.opacity = '0.65';
    const ok = document.createElement('span'); ok.textContent = ' ✓'; ok.style.color = '#7fd288'; ok.style.marginLeft='6px'; row.appendChild(ok);
    setTimeout(() => { row.remove(); maybeHideConfirmBar(); }, 700);
  } catch (e) {
    addDebugMessage('Confirm error: ' + (e && (e.message || String(e))));
  }
}

function maybeHideConfirmBar() {
  const bar = document.getElementById('confirm-bar');
  if (!bar) return;
  const any = bar.querySelector('.confirm-item');
  if (!any) bar.style.display = 'none';
}

// ============================================================================
// STANDALONE IDE: Monaco Editor + File Tree + Task Tracker
// ============================================================================

let monacoEditor = null;
let currentEditorFile = null;
const editorTabs = new Map(); // file_path -> {model, viewState}

// Initialize Monaco Editor
function initMonacoEditor() {
  if (typeof require === 'undefined') {
    console.error('Monaco loader not available');
    return;
  }

  require.config({ paths: { vs: 'https://cdn.jsdelivr.net/npm/monaco-editor@0.45.0/min/vs' } });

  require(['vs/editor/editor.main'], function() {
    const container = document.getElementById('monaco-container');
    if (!container) return;

    monacoEditor = monaco.editor.create(container, {
      value: '// Select a file from the file tree to begin editing\n',
      language: 'javascript',
      theme: 'vs-dark',
      automaticLayout: true,
      fontSize: 14,
      minimap: { enabled: true },
      scrollBeyondLastLine: false,
      readOnly: true, // Read-only in chat mode by default
      lineNumbers: 'on',
      renderWhitespace: 'selection',
      tabSize: 2,
    });

    console.log('Monaco Editor initialized');
  });
}

// Show/hide IDE workspace based on mode
function updateIDEWorkspaceVisibility() {
  const modeRadios = document.querySelectorAll('input[name="mode"]');
  let isCodeMode = false;
  modeRadios.forEach(r => { if (r.checked && r.value === 'code') isCodeMode = true; });

  const ideWorkspace = document.getElementById('ide-workspace');
  const chatWindow = document.getElementById('chat-window');

  if (ideWorkspace && chatWindow) {
    if (isCodeMode) {
      ideWorkspace.style.display = 'block';
      chatWindow.style.height = '200px'; // Collapsed chat in code mode
    } else {
      ideWorkspace.style.display = 'none';
      chatWindow.style.height = ''; // Full chat in chat mode
    }
  }

  // Update editor read-only state
  if (monacoEditor) {
    monacoEditor.updateOptions({ readOnly: !isCodeMode });
  }

  // Load file tree when switching to code mode
  if (isCodeMode && typeof loadFileTreeData === 'function') {
    const repo = (repoRootInput && repoRootInput.value) || LS.get('pandora.repoRoot', '');
    if (repo) {
      loadFileTreeData();
    }
  }
}

// Load file into Monaco Editor
async function loadFileInEditor(filePath) {
  if (!monacoEditor) return;

  try {
    const base = buildBaseUrl();
    const repo = (repoRootInput && repoRootInput.value) || LS.get('pandora.repoRoot', '');

    const response = await fetch(`${base}/tool/execute`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        tool: 'file.read',
        args: { file_path: filePath, repo: repo }
      })
    });

    const data = await response.json();

    if (data && data.content) {
      // Detect language from file extension
      const ext = filePath.split('.').pop();
      const langMap = {
        'js': 'javascript', 'ts': 'typescript', 'py': 'python', 'md': 'markdown',
        'json': 'json', 'html': 'html', 'css': 'css', 'yml': 'yaml', 'yaml': 'yaml',
        'sh': 'shell', 'bash': 'shell', 'c': 'c', 'cpp': 'cpp', 'go': 'go', 'rs': 'rust'
      };
      const language = langMap[ext] || 'plaintext';

      // Create or get model for this file
      // Use monaco.Uri.file() to properly handle absolute paths
      const uri = monaco.Uri.file(filePath);
      let model = monaco.editor.getModel(uri);
      if (!model) {
        model = monaco.editor.createModel(data.content, language, uri);
      } else {
        model.setValue(data.content);
      }

      // Save current view state if switching files
      if (currentEditorFile && monacoEditor.getModel()) {
        editorTabs.set(currentEditorFile, {
          model: monacoEditor.getModel(),
          viewState: monacoEditor.saveViewState()
        });
      }

      // Set new model
      monacoEditor.setModel(model);
      currentEditorFile = filePath;

      // Restore view state if returning to a file
      const saved = editorTabs.get(filePath);
      if (saved && saved.viewState) {
        monacoEditor.restoreViewState(saved.viewState);
      }

      // Add tab
      addEditorTab(filePath);

      console.log('Loaded ' + filePath + ' into editor');
    } else {
      console.error('Failed to load file:', data);
    }
  } catch (error) {
    console.error('Error loading file:', error);
  }
}

// Add editor tab
function addEditorTab(filePath) {
  const tabsContainer = document.getElementById('editor-tabs');
  if (!tabsContainer) return;

  const fileName = filePath.split('/').pop();
  const tabId = 'tab-' + filePath.replace(/[^a-zA-Z0-9]/g, '_');
  const existingTab = document.getElementById(tabId);

  if (!existingTab) {
    const tab = document.createElement('div');
    tab.id = tabId;
    tab.className = 'editor-tab';
    tab.innerHTML = '<span class="tab-name">' + fileName + '</span><span class="tab-close" data-file="' + filePath + '">×</span>';
    tab.style.cssText = 'display:flex; align-items:center; gap:8px; padding:4px 12px; background:#2a2a33; color:#cfd3e9; border-radius:4px; cursor:pointer; font-size:0.85em;';
    tab.querySelector('.tab-name').addEventListener('click', () => loadFileInEditor(filePath));
    tab.querySelector('.tab-close').addEventListener('click', (e) => {
      e.stopPropagation();
      closeEditorTab(filePath);
    });
    tabsContainer.appendChild(tab);
  }

  // Highlight active tab
  tabsContainer.querySelectorAll('.editor-tab').forEach(t => {
    t.style.background = t.id === tabId ? '#007acc' : '#2a2a33';
  });
}

// Close editor tab
function closeEditorTab(filePath) {
  const tabId = 'tab-' + filePath.replace(/[^a-zA-Z0-9]/g, '_');
  const tab = document.getElementById(tabId);
  if (tab) tab.remove();

  editorTabs.delete(filePath);

  if (currentEditorFile === filePath) {
    currentEditorFile = null;
    if (monacoEditor) {
      monacoEditor.setValue('// Select a file from the file tree to begin editing\n');
    }
  }
}

// Initialize on load with proper library detection
document.addEventListener('DOMContentLoaded', () => {
  // Initialize research progress handler for real-time monitoring
  if (typeof ResearchProgressHandler !== 'undefined') {
    window.researchProgressHandler = new ResearchProgressHandler();
    console.log('[App] Research progress handler initialized');
  } else {
    console.warn('[App] ResearchProgressHandler not available - research_progress.js not loaded?');
  }

  // Wait for Monaco loader to be available (with retry)
  let monacoRetries = 0;
  const maxRetries = 10;
  const checkMonaco = () => {
    if (typeof require !== 'undefined' && typeof monaco === 'undefined') {
      initMonacoEditor();
    } else if (monacoRetries < maxRetries) {
      monacoRetries++;
      setTimeout(checkMonaco, 300);
    } else {
      console.error('Monaco loader failed to load after', maxRetries, 'retries');
    }
  };
  setTimeout(checkMonaco, 300);

  // Mode change handler
  const modeRadios = document.querySelectorAll('input[name="mode"]');
  modeRadios.forEach(radio => {
    radio.addEventListener('change', updateIDEWorkspaceVisibility);
  });

  // Initial visibility update
  updateIDEWorkspaceVisibility();
});

// ============================================================================
// FILE TREE with Git Status
// ============================================================================

// Initialize file tree
function initFileTree() {
  const fileTreeEl = document.getElementById('file-tree');
  if (!fileTreeEl || typeof jQuery === 'undefined' || !jQuery.fn.jstree) {
    console.warn('File tree element, jQuery, or jsTree not available yet');
    return;
  }

  loadFileTreeData();
}

// Load file tree data from server
async function loadFileTreeData() {
  try {
    const base = buildBaseUrl();
    const repo = (repoRootInput && repoRootInput.value) || LS.get('pandora.repoRoot', '');

    if (!repo) {
      console.log('No repo configured for file tree');
      return;
    }

    const response = await fetch(`${base}/ui/filetree?repo=${encodeURIComponent(repo)}`);
    const data = await response.json();

    if (data.tree) {
      renderFileTree(data.tree);
    }
  } catch (error) {
    console.error('Error loading file tree:', error);
  }
}

// Render file tree with jsTree
function renderFileTree(treeData) {
  // Ensure jQuery and jsTree are loaded before rendering
  if (typeof jQuery === 'undefined' || !jQuery.fn.jstree) {
    console.warn('jsTree not ready yet, will retry when libraries are loaded');
    return;
  }

  const fileTreeEl = jQuery('#file-tree');

  fileTreeEl.jstree('destroy'); // Clear existing tree

  fileTreeEl.jstree({
    core: {
      data: treeData,
      themes: {
        name: 'default-dark',
        dots: true,
        icons: true
      }
    },
    plugins: ['types'],
    types: {
      default: {
        icon: 'jstree-file'
      },
      folder: {
        icon: 'jstree-folder'
      }
    }
  });

  // Handle file click
  fileTreeEl.on('select_node.jstree', function(e, data) {
    if (data.node.original && data.node.original.type === 'file') {
      const filePath = data.node.original.path;
      loadFileInEditor(filePath);
    }
  });
}

// Refresh file tree button handler
document.addEventListener('DOMContentLoaded', () => {
  const refreshBtn = document.getElementById('file-tree-refresh');
  if (refreshBtn) {
    refreshBtn.addEventListener('click', () => {
      loadFileTreeData();
    });
  }

  // Initialize file tree - libraries should already be loaded by now
  if (typeof jQuery !== 'undefined' && jQuery.fn.jstree) {
    console.log('[Pandora] File tree ready - jQuery', jQuery.fn.jquery, '+ jsTree');
    // Check if we're in code mode and have a repo configured
    const mode = (document.querySelector('input[name="mode"]:checked')||{}).value || 'chat';
    const repo = (repoRootInput && repoRootInput.value) || LS.get('pandora.repoRoot', '');
    if (mode === 'code' && repo) {
      initFileTree();
    }
  } else {
    console.error('[Pandora] CRITICAL: jQuery or jsTree not loaded! This should not happen.');
    console.error('[Pandora] jQuery:', typeof jQuery, 'jsTree:', typeof jQuery !== 'undefined' ? (jQuery.fn.jstree ? 'loaded' : 'missing') : 'N/A');
  }
});

// ============================================================================
// TASK TRACKER with Real-Time Updates
// ============================================================================

let currentTasks = [];
let executionPaused = false;

// Render task tracker
function renderTaskTracker(tasks) {
  const container = document.getElementById('task-tracker-content');
  const controls = document.getElementById('task-tracker-controls');

  if (!container) return;

  if (!tasks || tasks.length === 0) {
    container.innerHTML = '<div style="color:#9aa3c2; font-size:0.85em; text-align:center; padding:20px;">No active tasks</div>';
    if (controls) controls.style.display = 'none';
    return;
  }

  currentTasks = tasks;

  // Show pause button if tasks are in progress
  const hasInProgress = tasks.some(t => t.status === 'in_progress');
  if (controls) {
    controls.style.display = hasInProgress ? 'block' : 'none';
  }

  // Calculate progress
  const completed = tasks.filter(t => t.status === 'completed').length;
  const total = tasks.length;
  const percentage = total > 0 ? Math.round((completed / total) * 100) : 0;

  let html = '';

  // Progress bar
  html += '<div style="margin-bottom:12px;">';
  html += '<div style="background:#2a2a33; border-radius:4px; overflow:hidden; height:8px; position:relative;">';
  html += '<div style="position:absolute; top:0; left:0; background:#7fd288; width:' + percentage + '%; height:100%; transition:width 0.3s;"></div>';
  html += '</div>';
  html += '<div style="color:#9aa3c2; font-size:0.75em; margin-top:4px;">' + completed + '/' + total + ' tasks completed (' + percentage + '%)</div>';
  html += '</div>';

  // Task list
  tasks.forEach((task, idx) => {
    const statusIcons = {
      'pending': '☐',
      'in_progress': '⏳',
      'completed': '☑'
    };
    const statusColors = {
      'pending': '#9aa3c2',
      'in_progress': '#68a8ef',
      'completed': '#7fd288'
    };

    const icon = statusIcons[task.status] || '○';
    const color = statusColors[task.status] || '#9aa3c2';

    html += '<div style="margin-bottom:10px; padding:8px; background:#1a1a22; border-left:3px solid ' + color + '; border-radius:4px;">';
    html += '<div style="display:flex; align-items:center; gap:8px; margin-bottom:4px;">';
    html += '<span style="font-size:1.2em;">' + icon + '</span>';
    html += '<span style="color:#cfd3e9; font-size:0.9em; flex:1;">' + (task.description || task.content || 'Task ' + (idx + 1)) + '</span>';
    html += '</div>';

    // Show tool name if available
    if (task.tool) {
      html += '<div style="color:#9aa3c2; font-size:0.75em; margin-left:28px;">Tool: <code>' + task.tool + '</code></div>';
    }

    // Show file anchors if available
    if (task.files && task.files.length > 0) {
      html += '<div style="margin-left:28px; margin-top:4px;">';
      task.files.forEach(file => {
        html += '<span style="color:#68a8ef; font-size:0.75em; font-family:monospace; margin-right:8px; cursor:pointer;" class="file-anchor" data-file="' + file + '">' + file + '</span>';
      });
      html += '</div>';
    }

    // Show duration if completed
    if (task.duration_ms) {
      const duration = task.duration_ms < 1000 ? task.duration_ms + 'ms' : (task.duration_ms / 1000).toFixed(1) + 's';
      html += '<div style="color:#9aa3c2; font-size:0.7em; margin-left:28px; margin-top:4px;">Duration: ' + duration + '</div>';
    }

    html += '</div>';
  });

  container.innerHTML = html;

  // Add click handlers for file anchors
  container.querySelectorAll('.file-anchor').forEach(anchor => {
    anchor.addEventListener('click', () => {
      const file = anchor.getAttribute('data-file');
      if (file) {
        // Parse file:line format
        const parts = file.split(':');
        const filePath = parts[0];
        loadFileInEditor(filePath);

        // If line number provided, scroll to it
        if (parts[1] && monacoEditor) {
          setTimeout(() => {
            const lineNumber = parseInt(parts[1]);
            monacoEditor.revealLineInCenter(lineNumber);
            monacoEditor.setPosition({ lineNumber: lineNumber, column: 1 });
          }, 500);
        }
      }
    });
  });
}

// Parse task_breakdown from Coordinator response
function parseTaskBreakdown(responseData) {
  try {
    // Check for task_breakdown in various locations
    if (responseData.reflection && responseData.reflection.task_breakdown) {
      return responseData.reflection.task_breakdown;
    }

    if (responseData.task_breakdown) {
      return responseData.task_breakdown;
    }

    // Check in assistant message content for structured data
    if (responseData.choices && responseData.choices[0] && responseData.choices[0].message) {
      const content = responseData.choices[0].message.content;
      // Try to extract JSON from content
      const match = content.match(/\{[\s\S]*"task_breakdown"[\s\S]*\}/);
      if (match) {
        const parsed = JSON.parse(match[0]);
        if (parsed.task_breakdown) {
          return parsed.task_breakdown;
        }
        if (parsed.reflection && parsed.reflection.task_breakdown) {
          return parsed.reflection.task_breakdown;
        }
      }
    }
  } catch (e) {
    console.error('Error parsing task_breakdown:', e);
  }

  return null;
}

// Update task tracker from response
function updateTaskTrackerFromResponse(responseData) {
  const tasks = parseTaskBreakdown(responseData);
  if (tasks) {
    renderTaskTracker(tasks);
  }
}

// Pause/resume execution
document.addEventListener('DOMContentLoaded', () => {
  const pauseBtn = document.getElementById('pause-execution');
  if (pauseBtn) {
    pauseBtn.addEventListener('click', () => {
      executionPaused = !executionPaused;
      pauseBtn.textContent = executionPaused ? '▶ Resume Execution' : '⏸ Pause Execution';
      pauseBtn.style.background = executionPaused ? '#7fd288' : '#ff6b6b';

      // TODO: Implement actual pause/resume logic in process loop
      console.log('Execution paused:', executionPaused);
    });
  }
});

// ============================================================================
// TERMINAL PANEL for Bash Output
// ============================================================================

let terminalVisible = false;

// Add line to terminal
function addTerminalOutput(text, type = 'stdout') {
  const terminal = document.getElementById('terminal-content');
  const panel = document.getElementById('terminal-panel');

  if (!terminal || !panel) return;

  // Show terminal if hidden
  if (!terminalVisible) {
    panel.style.display = 'block';
    terminalVisible = true;
  }

  const color = type === 'stderr' ? '#ff6b6b' : '#cfd3e9';
  const line = document.createElement('div');
  line.style.color = color;
  line.style.whiteSpace = 'pre-wrap';
  line.style.marginBottom = '2px';
  line.textContent = text;

  terminal.appendChild(line);
  terminal.scrollTop = terminal.scrollHeight; // Auto-scroll to bottom
}

// Clear terminal
function clearTerminal() {
  const terminal = document.getElementById('terminal-content');
  if (terminal) {
    terminal.innerHTML = '';
  }
}

// Toggle terminal visibility
function toggleTerminal() {
  const panel = document.getElementById('terminal-panel');
  const toggleBtn = document.getElementById('terminal-toggle');

  if (!panel) return;

  terminalVisible = !terminalVisible;
  panel.style.display = terminalVisible ? 'block' : 'none';

  if (toggleBtn) {
    toggleBtn.textContent = terminalVisible ? '−' : '+';
  }
}

// Parse bash output from response
function parseBashOutput(responseData) {
  try {
    // Check for bash.execute results in tool outputs
    if (responseData.tool_outputs) {
      responseData.tool_outputs.forEach(output => {
        if (output.tool === 'bash.execute' && output.result) {
          if (output.result.stdout) {
            addTerminalOutput('$ ' + (output.args?.command || 'command'), 'command');
            addTerminalOutput(output.result.stdout, 'stdout');
          }
          if (output.result.stderr) {
            addTerminalOutput(output.result.stderr, 'stderr');
          }
        }
      });
    }

    // Also check in reflection or other locations
    if (responseData.reflection && responseData.reflection.bash_output) {
      addTerminalOutput(responseData.reflection.bash_output, 'stdout');
    }
  } catch (e) {
    console.error('Error parsing bash output:', e);
  }
}

// Terminal panel handlers
document.addEventListener('DOMContentLoaded', () => {
  const clearBtn = document.getElementById('terminal-clear');
  const toggleBtn = document.getElementById('terminal-toggle');

  if (clearBtn) {
    clearBtn.addEventListener('click', clearTerminal);
  }

  if (toggleBtn) {
    toggleBtn.addEventListener('click', toggleTerminal);
  }
});

// ============================================================================
// AUTONOMOUS EXECUTION MODES
// ============================================================================

// Show/hide execution mode selector based on mode
function updateExecutionModeVisibility() {
  const modeRadios = document.querySelectorAll('input[name="mode"]');
  let isCodeMode = false;
  modeRadios.forEach(r => { if (r.checked && r.value === 'code') isCodeMode = true; });

  const execModeLabel = document.getElementById('execution-mode-label');
  if (execModeLabel) {
    execModeLabel.style.display = isCodeMode ? 'inline' : 'none';
  }
}

// Get current execution mode
function getExecutionMode() {
  const select = document.getElementById('execution-mode-select');
  return (select && select.value) || 'autonomous';
}

// Execution mode change handler
document.addEventListener('DOMContentLoaded', () => {
  const modeRadios = document.querySelectorAll('input[name="mode"]');
  modeRadios.forEach(radio => {
    radio.addEventListener('change', () => {
      updateExecutionModeVisibility();
      updateIDEWorkspaceVisibility();
    });
  });

  // Execution mode select handler
  const execModeSelect = document.getElementById('execution-mode-select');
  if (execModeSelect) {
    execModeSelect.addEventListener('change', () => {
      const mode = execModeSelect.value;
      LS.set('pandora.executionMode', mode);
      console.log('Execution mode changed to:', mode);
    });

    // Restore saved execution mode
    const saved = LS.get('pandora.executionMode', 'autonomous');
    execModeSelect.value = saved;
  }

  // Initial visibility update
  updateExecutionModeVisibility();
});

// Undo last file change (for autonomous mode safety)
let lastFileChange = null;

function recordFileChange(filePath, oldContent, newContent) {
  lastFileChange = { filePath, oldContent, newContent, timestamp: Date.now() };
}

async function undoLastChange() {
  if (!lastFileChange) {
    alert('No recent changes to undo');
    return;
  }

  const { filePath, oldContent } = lastFileChange;

  try {
    const base = buildBaseUrl();
    const repo = (repoRootInput && repoRootInput.value) || LS.get('pandora.repoRoot', '');

    const response = await fetch(`${base}/tool/execute`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        tool: 'file.write',
        args: { file_path: filePath, content: oldContent, repo: repo }
      })
    });

    if (response.ok) {
      console.log('Successfully undid change to', filePath);
      lastFileChange = null;
      // Reload file in editor
      loadFileInEditor(filePath);
    } else {
      console.error('Failed to undo change');
    }
  } catch (error) {
    console.error('Error undoing change:', error);
  }
}

// ============================================================================
// THINKING VISUALIZATION
// ============================================================================

class ThinkingVisualizer {
  constructor() {
    this.panel = document.getElementById('thinking-panel');
    this.statusSpan = document.getElementById('thinking-status');
    this.spinner = document.getElementById('thinking-spinner');
    this.toggleBtn = document.getElementById('thinking-toggle');
    this.content = document.getElementById('thinking-content');
    this.eventSource = null;
    this.currentTraceId = null;
    this.isCollapsed = false;
    this.inlineMsgElement = null; // Track inline chat message for thinking status
    this.pollingInterval = null; // Fallback polling when SSE drops
    this.backupPollingInterval = null; // Backup polling that runs alongside SSE
    this.heartbeatInterval = null; // Check for dead connections
    this.lastEventTime = null; // Track last event for heartbeat
    this.responseReceived = false; // Flag to prevent double message adds

    // Phase configuration for 9-phase pipeline
    this.phaseConfig = {
      phase_0: { name: 'Query Analyzer', icon: '\u{1F4E9}', color: '#68a8ef' },
      phase_1: { name: 'Reflection', icon: '\u{1F914}', color: '#9b6bef' },
      phase_2: { name: 'Context Gatherer', icon: '\u{1F4DA}', color: '#6bef9b' },
      phase_3: { name: 'Planner', icon: '\u{1F4CB}', color: '#ffa500' },
      phase_4: { name: 'Executor', icon: '\u2699\uFE0F', color: '#ef6b9b' },
      phase_5: { name: 'Coordinator', icon: '\u{1F527}', color: '#ef9b6b' },
      phase_6: { name: 'Synthesis', icon: '\u2728', color: '#6befa8' },
      phase_7: { name: 'Validation', icon: '\u2713', color: '#a8ef6b' },
      phase_8: { name: 'Complete', icon: '\u2705', color: '#7fd288' }
    };

    // Enhanced debugging with actual element checks
    const initStatus = {
      panel: !!this.panel,
      statusSpan: !!this.statusSpan,
      spinner: !!this.spinner,
      toggleBtn: !!this.toggleBtn,
      content: !!this.content,
      domState: document.readyState,
      timestamp: new Date().toISOString()
    };

    console.log('[Thinking] ThinkingVisualizer initialized:', initStatus);

    // Warn if critical elements are missing
    if (!this.panel) {
      console.error('[Thinking] CRITICAL: thinking-panel element not found! Visualization will not work.');
      console.error('[Thinking] Attempted to find element with ID: thinking-panel');
      console.error('[Thinking] Current document.readyState:', document.readyState);
    }

    // Bind toggle handler
    if (this.toggleBtn) {
      this.toggleBtn.addEventListener('click', () => this.togglePanel());
    }

    // Also allow header to toggle
    const header = document.getElementById('thinking-panel-header');
    if (header) {
      header.addEventListener('click', (e) => {
        if (e.target !== this.toggleBtn) {
          this.togglePanel();
        }
      });
    }
  }

  start(traceId) {
    if (!traceId) {
      console.warn('[Thinking] No trace ID provided');
      return;
    }

    // Stop any existing stream (this will also remove old inline message)
    this.stop();

    this.currentTraceId = traceId;
    this.show();
    this.reset();

    // Connect to SSE endpoint
    const baseUrl = window.location.origin;
    const sseUrl = `${baseUrl}/v1/thinking/${traceId}`;

    console.log('[Thinking] Connecting to:', sseUrl);

    this.eventSource = new EventSource(sseUrl);
    this.lastEventTime = Date.now();

    // Heartbeat check - if no events for 45 seconds, assume connection is dead
    this.heartbeatInterval = setInterval(() => {
      const elapsed = Date.now() - this.lastEventTime;
      if (elapsed > 45000 && this.eventSource && !this.pollingInterval) {
        console.warn('[Thinking] No events for 45s, connection may be dead - starting polling');
        this.startPollingFallback();
      }
    }, 10000);

    this.eventSource.addEventListener('ping', () => {
      // Keepalive ping
      console.log('[Thinking] Ping received');
      this.lastEventTime = Date.now();
    });

    this.eventSource.addEventListener('thinking', (e) => {
      try {
        this.lastEventTime = Date.now();
        const event = JSON.parse(e.data);
        console.log('[Thinking] Event received:', event);
        this.updateStage(event);
      } catch (err) {
        console.error('[Thinking] Failed to parse event:', err);
      }
    });

    this.eventSource.addEventListener('complete', (e) => {
      // FIRST LINE OF HANDLER - log immediately to confirm event arrived
      console.error('🎉🎉🎉 COMPLETE EVENT HANDLER FIRED 🎉🎉🎉');

      try {
        console.log('[Thinking] ========== COMPLETE EVENT RECEIVED ==========');
        console.log('[Thinking] Raw event data:', e.data);
        console.log('[Thinking] Raw event data length:', e.data ? e.data.length : 0);

        // DEBUG: Super obvious indicator - use error level for visibility
        console.error('🎉 COMPLETE EVENT RECEIVED - MESSAGE SHOULD DISPLAY');

        // FAILSAFE: Immediately try to show something on screen
        const debugDiv = document.getElementById('chat-window');
        if (debugDiv) {
          console.error('chat-window found, will add message...');
        } else {
          console.error('❌ chat-window NOT FOUND!');
        }

        // Check for duplicate response (backup polling might have already added it)
        if (this.responseReceived) {
          console.log('[Thinking] Response already received (via polling), skipping SSE message add');
          this.stop();
          return;
        }

        const event = JSON.parse(e.data);
        console.log('[Thinking] Parsed event:', event);
        console.log('[Thinking] Message length:', event.message ? event.message.length : 'NO MESSAGE');
        console.log('[Thinking] Message preview:', event.message ? event.message.substring(0, 100) : 'N/A');

        // Display final response
        if (event.message) {
          // CRITICAL: Set responseReceived IMMEDIATELY to prevent race condition with backup polling
          // This must happen BEFORE any async operations or DOM manipulation
          this.responseReceived = true;
          console.log('[Thinking] ✓ Set responseReceived=true (SSE complete)');

          console.log('[Thinking] About to add message to chat...');

          // Save message before any operations
          const finalMessage = event.message;

          // CRITICAL: Add the message FIRST, before calling stop()
          // This ensures the message is displayed even if stop() has side effects
          const chatWindow = document.getElementById('chat-window');
          let messageAdded = false;

          if (chatWindow) {
            try {
              const msg = document.createElement('div');
              msg.classList.add('msg', 'bot', 'research-result');
              msg.setAttribute('data-trace-id', event.trace_id || '');
              const prefix = document.createElement('span');
              prefix.className = 'prefix';
              prefix.textContent = 'Chat:';
              msg.appendChild(prefix);
              const span = document.createElement('span');
              // Wrap formatBotText in try/catch
              let formattedText;
              try {
                formattedText = formatBotText(finalMessage);
              } catch (formatErr) {
                console.error('[Thinking] formatBotText error:', formatErr);
                // Fallback: escape HTML and show raw text
                formattedText = finalMessage.replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/\n/g, '<br>');
              }
              span.innerHTML = ' ' + formattedText;
              msg.appendChild(span);
              chatWindow.appendChild(msg);
              chatWindow.scrollTop = chatWindow.scrollHeight;
              messageAdded = true;
              console.log('[Thinking] ✅ Message added to DOM directly!');
              console.warn('✅ MESSAGE SHOULD NOW BE VISIBLE IN CHAT');
            } catch (domErr) {
              console.error('[Thinking] DOM manipulation error:', domErr);
            }
          } else {
            console.error('[Thinking] ❌ chatWindow element not found!');
          }

          // responseReceived already set at start of handler to prevent race condition

          // Stop SSE stream and clear backup polling
          this.stop();

          // SAFETY NET: If message wasn't added, try again with addMessage()
          if (!messageAdded && typeof addMessage === 'function') {
            console.warn('[Thinking] Fallback: using addMessage()');
            try {
              addMessage(finalMessage, 'bot');
            } catch (addErr) {
              console.error('[Thinking] addMessage fallback error:', addErr);
            }
          }
        } else {
          console.warn('[Thinking] Complete event has no message field!');
          console.warn('[Thinking] Event keys:', Object.keys(event));
          // Still need to stop and clean up even if no message
          this.responseReceived = true;
          this.stop();
        }
      } catch (err) {
        console.error('[Thinking] Failed to parse complete event:', err);
        console.error('[Thinking] Raw data was:', e.data);
        // Still try to stop on error
        this.responseReceived = true;
        this.stop();

        // CRITICAL FALLBACK: Try to extract and display message even on parse error
        try {
          const rawData = e.data;
          const messageMatch = rawData.match(/"message"\s*:\s*"([^"]+)"/);
          if (messageMatch && messageMatch[1]) {
            console.warn('[Thinking] Emergency fallback: extracting message from raw data');
            const chatWindow = document.getElementById('chat-window');
            if (chatWindow) {
              const msg = document.createElement('div');
              msg.classList.add('msg', 'bot');
              msg.innerHTML = '<span class="prefix">Chat:</span> ' + messageMatch[1].replace(/\\n/g, '<br>');
              chatWindow.appendChild(msg);
              this.responseReceived = true;
              this.stop();
            }
          }
        } catch (fallbackErr) {
          console.error('[Thinking] Fallback extraction failed:', fallbackErr);
        }
      }
    });

    this.eventSource.addEventListener('error', async (e) => {
      console.error('[Thinking] SSE error:', e, 'readyState:', this.eventSource?.readyState);

      if (this.eventSource) {
        const state = this.eventSource.readyState;
        console.log('[Thinking] Connection state:', state, '(0=CONNECTING, 1=OPEN, 2=CLOSED)');

        // When connection closes (state=2), do a final safety poll
        if (state === EventSource.CLOSED) {
          console.log('[Thinking] Connection CLOSED - doing final safety poll');
          // Wait a moment for any in-flight data, then poll
          await new Promise(r => setTimeout(r, 500));
          await this.doFinalPoll();
        } else if (state === EventSource.CONNECTING) {
          // Auto-reconnecting, start fallback polling
          console.log('[Thinking] Connection reconnecting - starting fallback polling');
          this.startPollingFallback();
        }
      }
    });

    this.statusSpan.textContent = 'Starting...';
    this.spinner.style.display = 'inline-block';

    // Only create inline message if it doesn't exist yet
    if (!this.inlineMsgElement) {
      console.log('[Thinking] Creating inline message in start()');
      this.createInlineMessage();
    } else {
      console.log('[Thinking] Inline message already exists, reusing it');
    }

    // Start backup polling immediately - SSE is unreliable through Cloudflared
    // This runs alongside SSE and will catch the response if SSE fails
    this.startBackupPolling();

    // EMERGENCY: Add global function to manually fetch response
    // User can call window.emergencyFetchResponse() from console if nothing works
    window.emergencyFetchResponse = async () => {
      const traceId = this.currentTraceId;
      if (!traceId) {
        console.error('No trace ID available');
        return;
      }
      console.log('Emergency fetching response for trace:', traceId);
      try {
        const resp = await fetch(`${window.location.origin}/v1/response/${traceId}`);
        const data = await resp.json();
        console.log('Emergency fetch result:', data);
        if (data.status === 'complete' && data.response) {
          alert('Response found! Length: ' + data.response.length + ' chars. Check console for full response.');
          console.log('FULL RESPONSE:', data.response);
          // Also try to add it to chat
          const chatWindow = document.getElementById('chat-window');
          if (chatWindow) {
            const msg = document.createElement('div');
            msg.classList.add('msg', 'bot');
            msg.innerHTML = '<span class="prefix">Chat:</span> <span>' + data.response.replace(/</g, '&lt;').replace(/\n/g, '<br>') + '</span>';
            chatWindow.appendChild(msg);
            console.log('Message added to chat via emergency function');
          }
        } else {
          console.log('Response not ready yet:', data.status);
        }
      } catch (e) {
        console.error('Emergency fetch failed:', e);
      }
    };
    console.log('[Thinking] Emergency fetch function available: window.emergencyFetchResponse()');
  }

  createInlineMessage() {
    console.log('[Thinking] ===== createInlineMessage() CALLED =====');
    console.log('[Thinking] chat-window element:', document.getElementById('chat-window'));

    // Create a bot message that shows thinking status
    const msg = document.createElement('div');
    msg.classList.add('msg', 'bot', 'thinking-msg');
    msg.style.opacity = '0.9';
    msg.style.borderLeft = '3px solid #68a8ef';

    console.log('[Thinking] Created msg element:', msg);

    const prefix = document.createElement('span');
    prefix.className = 'prefix';
    prefix.textContent = 'Chat:';
    msg.appendChild(prefix);

    const statusText = document.createElement('span');
    statusText.className = 'thinking-status-text';
    statusText.style.marginLeft = '8px';
    statusText.style.color = '#9aa3c2';
    statusText.innerHTML = '<span style="display:inline-block;width:12px;height:12px;border:2px solid #68a8ef;border-top-color:transparent;border-radius:50%;animation:spin 1s linear infinite;margin-right:8px;vertical-align:middle;"></span>Thinking...';
    msg.appendChild(statusText);

    const chatWindow = document.getElementById('chat-window');
    if (chatWindow) {
      chatWindow.appendChild(msg);
      chatWindow.scrollTop = chatWindow.scrollHeight;
      this.inlineMsgElement = msg;
      console.log('[Thinking] Inline message created in chat');
    }
  }

  updateInlineMessage(text) {
    if (!this.inlineMsgElement) return;

    const statusText = this.inlineMsgElement.querySelector('.thinking-status-text');
    if (statusText) {
      statusText.innerHTML = `<span style="display:inline-block;width:12px;height:12px;border:2px solid #68a8ef;border-top-color:transparent;border-radius:50%;animation:spin 1s linear infinite;margin-right:8px;vertical-align:middle;"></span>${text}`;
    }
  }

  removeInlineMessage() {
    // Remove tracked element if exists
    if (this.inlineMsgElement && this.inlineMsgElement.parentNode) {
      this.inlineMsgElement.parentNode.removeChild(this.inlineMsgElement);
      this.inlineMsgElement = null;
      console.log('[Thinking] Inline message removed (tracked element)');
    }

    // FALLBACK: Also remove any orphaned thinking messages from DOM
    // This handles edge cases where the element reference was lost
    const chatWindow = document.getElementById('chat-window');
    if (chatWindow) {
      const orphanedThinking = chatWindow.querySelectorAll('.msg.bot.thinking-msg');
      orphanedThinking.forEach((el, i) => {
        console.log(`[Thinking] Removing orphaned thinking message #${i + 1}`);
        el.parentNode.removeChild(el);
      });
    }
  }

  async doFinalPoll() {
    // Safety net: keep polling after SSE closes until we get the response
    // This is critical because SSE complete event may be dropped by Cloudflared
    if (!this.currentTraceId) {
      console.log('[Thinking] Final poll: no trace ID');
      return;
    }

    if (this.responseReceived) {
      console.log('[Thinking] Final poll: response already received');
      return;
    }

    const traceId = this.currentTraceId;
    const baseUrl = window.location.origin;
    const maxRetries = 60;  // 60 retries at 2s = 2 minutes max
    let retryCount = 0;

    console.log('[Thinking] Starting final poll loop for trace:', traceId);

    const pollOnce = async () => {
      // Stop if a new query has started (different trace ID)
      if (this.currentTraceId !== traceId) {
        console.log('[Thinking] Final poll: new query started, abandoning old poll');
        return true;
      }

      if (this.responseReceived) {
        console.log('[Thinking] Final poll: response received elsewhere, stopping');
        return true;
      }

      retryCount++;
      console.log(`[Thinking] Final poll attempt ${retryCount}/${maxRetries} for trace:`, traceId);

      try {
        const response = await fetch(`${baseUrl}/v1/response/${traceId}`);
        const data = await response.json();

        console.log('[Thinking] Final poll result:', data.status);

        if (data.status === 'complete' && data.response) {
          console.log('[Thinking] FINAL POLL CAUGHT RESPONSE!', data.response.length, 'chars');

          // Check for duplicate or stale query
          if (this.responseReceived || this.currentTraceId !== traceId) {
            console.log('[Thinking] Response already received or query changed, skipping');
            return true;
          }

          // Set responseReceived IMMEDIATELY to prevent race condition
          this.responseReceived = true;
          console.log('[Thinking] ✓ Set responseReceived=true (final poll)');

          // CRITICAL: Add message to DOM FIRST, before stopping
          // Use direct DOM manipulation as primary method for reliability
          const chatWindow = document.getElementById('chat-window');
          let messageAdded = false;
          if (chatWindow) {
            try {
              const msg = document.createElement('div');
              msg.classList.add('msg', 'bot', 'research-result');
              msg.setAttribute('data-trace-id', traceId);
              const prefix = document.createElement('span');
              prefix.className = 'prefix';
              prefix.textContent = 'Chat:';
              msg.appendChild(prefix);
              const span = document.createElement('span');
              // Wrap formatBotText in try/catch
              let formattedText;
              try {
                formattedText = formatBotText(data.response);
              } catch (formatErr) {
                console.error('[Thinking] formatBotText error in final poll:', formatErr);
                formattedText = data.response.replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/\n/g, '<br>');
              }
              span.innerHTML = ' ' + formattedText;
              msg.appendChild(span);
              chatWindow.appendChild(msg);
              chatWindow.scrollTop = chatWindow.scrollHeight;
              messageAdded = true;
              console.log('[Thinking] ✅ Message added via FINAL POLL!');
            } catch (domErr) {
              console.error('[Thinking] DOM error in final poll:', domErr);
            }
          }

          // responseReceived already set earlier to prevent race condition
          this.stop();
          return true;
        } else if (data.status === 'not_found') {
          console.log('[Thinking] Final poll: trace not found, giving up');
          return true;
        }
        // status is 'pending', keep trying
        return false;
      } catch (err) {
        console.error('[Thinking] Final poll error:', err);
        return false;  // Keep trying on error
      }
    };

    // Poll immediately, then every 2 seconds
    while (retryCount < maxRetries) {
      const done = await pollOnce();
      if (done) return;
      await new Promise(r => setTimeout(r, 2000));
    }

    console.warn('[Thinking] Final poll gave up after', maxRetries, 'attempts');
  }

  stop() {
    if (this.eventSource) {
      this.eventSource.close();
      this.eventSource = null;
    }
    if (this.pollingInterval) {
      clearInterval(this.pollingInterval);
      this.pollingInterval = null;
    }
    if (this.backupPollingInterval) {
      // New format: object with stop() method
      if (typeof this.backupPollingInterval.stop === 'function') {
        this.backupPollingInterval.stop();
      } else {
        // Old format: interval ID
        clearInterval(this.backupPollingInterval);
      }
      this.backupPollingInterval = null;
    }
    if (this.heartbeatInterval) {
      clearInterval(this.heartbeatInterval);
      this.heartbeatInterval = null;
    }
    if (this.spinner) {
      this.spinner.style.display = 'none';
    }
    // Clean up inline message
    this.removeInlineMessage();
  }

  startBackupPolling() {
    // Start backup polling that runs alongside SSE
    // This catches responses when SSE silently fails through Cloudflared
    if (this.backupPollingInterval) {
      console.log('[Thinking] Backup polling already running');
      return;
    }

    if (!this.currentTraceId) {
      return;
    }

    console.log('[Thinking] Starting backup polling for trace:', this.currentTraceId);

    // Save trace ID in closure so polling continues even if this.currentTraceId is cleared
    const traceId = this.currentTraceId;
    // Store reference to this for use inside interval
    const self = this;
    let pollCount = 0;
    const maxPolls = 600; // Poll for up to 600 * 0.75s = 7.5 minutes (research can be slow)
    let stopped = false;

    // Create a self-contained polling function that uses setTimeout instead of setInterval
    // This is more reliable because it doesn't depend on `this` state
    let messageAdded = false;  // Local flag - only stops when message is actually displayed

    const poll = async () => {
      if (messageAdded) return;  // Only stop if we successfully added the message

      // Stop if a new query has started (different trace ID)
      if (self.currentTraceId !== traceId) {
        console.log('[Thinking] Backup poll: new query started, abandoning old poll');
        return;
      }

      pollCount++;

      // Stop after max polls
      if (pollCount > maxPolls) {
        console.log('[Thinking] Backup polling max reached, stopping');
        return;
      }

      try {
        const baseUrl = window.location.origin;
        const response = await fetch(`${baseUrl}/v1/response/${traceId}`);
        const data = await response.json();

        console.log(`[Thinking] Poll #${pollCount}: status=${data.status}`);

        if (data.status === 'complete' && data.response) {
          console.error('[Thinking] 🎉 BACKUP POLL GOT RESPONSE!', data.response.length, 'chars');
          console.error('[Thinking] Response preview:', data.response.substring(0, 150));

          // CRITICAL: Check responseReceived FIRST to prevent race condition with SSE
          if (self.responseReceived) {
            console.error('[Thinking] Backup poll: SSE already handled response, skipping');
            messageAdded = true;  // Stop polling
            return;
          }

          // Double-check trace ID hasn't changed
          if (self.currentTraceId !== traceId) {
            console.log('[Thinking] Backup poll: trace ID changed, discarding response');
            return;
          }

          // Set responseReceived IMMEDIATELY to prevent SSE from also adding
          self.responseReceived = true;
          console.log('[Thinking] ✓ Set responseReceived=true (backup polling)');

          // Add the response message using direct DOM for reliability
          const chatWindow = document.getElementById('chat-window');
          if (chatWindow) {
            // Check if message already exists using data-trace-id attribute (more reliable than content matching)
            const existingByTraceId = chatWindow.querySelector(`.msg.bot[data-trace-id="${traceId}"]`);

            // Also check by content as fallback, but use longer substring and exact match
            let alreadyExists = !!existingByTraceId;
            if (!alreadyExists) {
              const existingMsgs = chatWindow.querySelectorAll('.msg.bot.research-result');
              const checkString = data.response.substring(0, 100);
              existingMsgs.forEach(m => {
                // Check if this exact response content exists
                if (m.textContent.includes(checkString)) {
                  alreadyExists = true;
                }
              });
            }

            if (!alreadyExists) {
              try {
                const msg = document.createElement('div');
                msg.classList.add('msg', 'bot', 'research-result');
                msg.setAttribute('data-trace-id', traceId);
                const prefix = document.createElement('span');
                prefix.className = 'prefix';
                prefix.textContent = 'Chat:';
                msg.appendChild(prefix);
                const span = document.createElement('span');
                // Wrap formatBotText in try/catch
                let formattedText;
                try {
                  formattedText = formatBotText(data.response);
                } catch (formatErr) {
                  console.error('[Thinking] formatBotText error in poll:', formatErr);
                  formattedText = data.response.replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/\n/g, '<br>');
                }
                span.innerHTML = ' ' + formattedText;
                msg.appendChild(span);
                chatWindow.appendChild(msg);
                chatWindow.scrollTop = chatWindow.scrollHeight;
                console.error('[Thinking] ✅ MESSAGE ADDED VIA BACKUP POLLING!');
                console.error('[Thinking] Message text preview:', msg.textContent.substring(0, 100));
              } catch (domErr) {
                console.error('[Thinking] DOM error in backup poll:', domErr);
              }
            } else {
              console.error('[Thinking] ⚠️ MESSAGE ALREADY EXISTS (duplicate detected), skipping');
              console.error('[Thinking] existingByTraceId:', !!existingByTraceId);
            }

            // Mark as done and stop everything
            // responseReceived already set earlier to prevent race condition
            messageAdded = true;
            self.stop();
            return;
          }
        }
        // If pending, keep polling
      } catch (err) {
        console.log('[Thinking] Backup poll error (will retry):', err.message);
      }

      // Schedule next poll - DON'T check stopped, only check messageAdded
      // Poll every 750ms for faster response display once ready
      if (!messageAdded) {
        setTimeout(poll, 750);
      }
    };

    // Start polling immediately, then every 750ms
    setTimeout(poll, 750);

    // Store a way to stop polling externally (but polling will also check responseReceived)
    this.backupPollingInterval = { stop: () => { stopped = true; } };
  }

  startPollingFallback() {
    // Prevent multiple polling intervals
    if (this.pollingInterval) {
      console.log('[Thinking] Polling already in progress, skipping');
      return;
    }

    if (!this.currentTraceId) {
      console.warn('[Thinking] No trace ID for polling fallback');
      this.stop();
      return;
    }

    // Close the dead SSE connection but keep the inline message
    if (this.eventSource) {
      this.eventSource.close();
      this.eventSource = null;
    }

    console.log('[Thinking] Starting polling fallback for trace:', this.currentTraceId);
    this.updateInlineMessage('Reconnecting...');

    // Poll every 2 seconds for up to 5 minutes
    const maxPolls = 150;  // 5 minutes at 2s intervals
    let pollCount = 0;

    this.pollingInterval = setInterval(async () => {
      pollCount++;
      if (pollCount > maxPolls) {
        console.warn('[Thinking] Polling timeout - gave up after', maxPolls, 'attempts');
        clearInterval(this.pollingInterval);
        this.pollingInterval = null;
        this.updateInlineMessage('Request timed out - please try again');
        setTimeout(() => this.stop(), 3000);
        return;
      }

      try {
        const baseUrl = window.location.origin;
        const response = await fetch(`${baseUrl}/v1/response/${this.currentTraceId}`);
        const data = await response.json();

        console.log('[Thinking] Poll response:', data.status);

        if (data.status === 'complete' && data.response) {
          console.log('[Thinking] Got response via polling!', data.response.length, 'chars');
          clearInterval(this.pollingInterval);
          this.pollingInterval = null;
          this.stop();
          addMessage(data.response, 'bot');
        } else if (data.status === 'not_found') {
          // Trace doesn't exist - might have been cleaned up
          console.warn('[Thinking] Trace not found - may have been cleaned up');
          clearInterval(this.pollingInterval);
          this.pollingInterval = null;
          this.updateInlineMessage('Request expired - please try again');
          setTimeout(() => this.stop(), 3000);
        }
        // If status is 'pending', just keep polling
      } catch (err) {
        console.error('[Thinking] Polling error:', err);
        // Keep trying
      }
    }, 2000);
  }

  show() {
    console.log('[Thinking] show() called, panel:', this.panel);
    if (this.panel) {
      this.panel.style.display = 'block';
      console.log('[Thinking] Panel display set to block');
    } else {
      console.error('[Thinking] Panel element not found!');
    }
  }

  hide() {
    if (this.panel) {
      this.panel.style.display = 'none';
    }
    this.stop();
  }

  reset() {
    // Reset response received flag for new request
    this.responseReceived = false;

    // Hide all stages (handles both old and new phase naming)
    const stages = this.panel.querySelectorAll('.thinking-stage');
    stages.forEach(stage => {
      stage.style.display = 'none';
      // Reset status badge (supports both .stage-status and .stage-badge)
      const statusBadge = stage.querySelector('.stage-status') || stage.querySelector('.stage-badge');
      if (statusBadge) {
        statusBadge.textContent = 'pending';
        statusBadge.className = statusBadge.className.replace(/\b(active|completed|error)\b/g, '').trim() + ' pending';
      }
      // Reset duration
      const durationSpan = stage.querySelector('.stage-duration');
      if (durationSpan) durationSpan.textContent = '—';
      // Reset reasoning
      const reasoningDiv = stage.querySelector('.stage-reasoning');
      if (reasoningDiv) reasoningDiv.textContent = 'Awaiting...';
      // Reset confidence bar (supports both naming conventions)
      const confBar = stage.querySelector('.confidence-bar') || stage.querySelector('.confidence-fill');
      if (confBar) confBar.style.width = '0%';
      const confValue = stage.querySelector('.confidence-value');
      if (confValue) confValue.textContent = '0%';
      // Clear tool calls container (for phase_5)
      const toolCalls = stage.querySelector('.tool-calls');
      if (toolCalls) toolCalls.innerHTML = '';
    });
  }

  updateStage(event) {
    const {stage, status, confidence, duration_ms, reasoning, details} = event;

    // Legacy stage names mapping (for backwards compatibility)
    const legacyStageNames = {
      query_received: 'Query received',
      guide_analyzing: 'Analyzing query',
      coordinator_planning: 'Planning execution',
      orchestrator_executing: 'Executing tools',
      guide_synthesizing: 'Synthesizing answer',
      response_complete: 'Complete'
    };

    // Try to extract phase from new naming convention (e.g., "phase_3_planner" -> "phase_3")
    const phaseMatch = stage.match(/^(phase_\d)/);
    let phaseKey = null;
    let stageText = '';

    if (phaseMatch) {
      // New phase naming convention
      phaseKey = phaseMatch[1];
      const phaseInfo = this.phaseConfig[phaseKey];
      stageText = phaseInfo ? phaseInfo.name : stage;
    } else {
      // Legacy naming convention
      stageText = legacyStageNames[stage] || stage;
    }

    this.statusSpan.textContent = stageText;

    // Update inline chat message with current stage
    if (stage === 'response_complete' || phaseKey === 'phase_8') {
      this.removeInlineMessage();
    } else {
      this.updateInlineMessage(stageText + (reasoning ? ` - ${reasoning}` : ''));
    }

    // Find the stage element - try new phase naming first, then legacy
    let stageEl = null;
    if (phaseKey) {
      stageEl = this.panel.querySelector(`.thinking-stage[data-stage="${phaseKey}"]`);
    }
    if (!stageEl) {
      stageEl = this.panel.querySelector(`.thinking-stage[data-stage="${stage}"]`);
    }

    if (!stageEl) {
      console.warn('[Thinking] Stage element not found:', stage, '(phaseKey:', phaseKey, ')');
      return;
    }

    stageEl.style.display = 'flex';

    // Update status badge (supports both .stage-status and .stage-badge)
    const statusBadge = stageEl.querySelector('.stage-status') || stageEl.querySelector('.stage-badge');
    if (statusBadge) {
      statusBadge.textContent = status;
      // Update class for styling
      statusBadge.className = statusBadge.className.replace(/\b(pending|active|completed|error)\b/g, '').trim();
      statusBadge.classList.add(status);
      // Color code status
      if (status === 'active') {
        statusBadge.style.background = '#3a5a9a';
        statusBadge.style.color = '#68a8ef';
      } else if (status === 'completed') {
        statusBadge.style.background = '#2a5a3a';
        statusBadge.style.color = '#7fd288';
      } else if (status === 'error') {
        statusBadge.style.background = '#5a2a2a';
        statusBadge.style.color = '#ff6b6b';
      }
    }

    // Update duration
    const durationSpan = stageEl.querySelector('.stage-duration');
    if (durationSpan && duration_ms > 0) {
      if (duration_ms < 1000) {
        durationSpan.textContent = `${duration_ms}ms`;
      } else {
        durationSpan.textContent = `${(duration_ms / 1000).toFixed(2)}s`;
      }
    }

    // Update reasoning
    const reasoningDiv = stageEl.querySelector('.stage-reasoning');
    if (reasoningDiv && reasoning) {
      reasoningDiv.textContent = reasoning;
    }

    // Update confidence bar (supports both naming conventions)
    const confBar = stageEl.querySelector('.confidence-bar') || stageEl.querySelector('.confidence-fill');
    const confValue = stageEl.querySelector('.confidence-value');
    if (confBar) {
      const confPercent = Math.round((confidence || 0) * 100);
      confBar.style.width = `${confPercent}%`;
      if (confValue) confValue.textContent = `${confPercent}%`;
    }

    // Handle tool calls for Phase 5 (Coordinator)
    if (phaseKey === 'phase_5' && details && details.tool) {
      this.addToolCall(stageEl, details);
    }

    // If response is complete, update UI but DO NOT close connection yet
    // The 'complete' event (with the actual message) still needs to arrive!
    if (stage === 'response_complete' || (phaseKey === 'phase_8' && status === 'completed')) {
      // DO NOT call this.stop() here - that closes the EventSource before
      // the 'complete' event (with the message) arrives!
      this.statusSpan.textContent = 'Receiving response...';
      // Hide cancel button when research/thinking completes
      if (typeof hideCancelButton === 'function') {
        hideCancelButton();
      }
    }

    // Auto-scroll to show latest stage
    if (stageEl) {
      stageEl.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    }
  }

  addToolCall(stageEl, details) {
    const toolCallsContainer = stageEl.querySelector('.tool-calls');
    if (!toolCallsContainer) {
      console.warn('[Thinking] Tool calls container not found for phase_5');
      return;
    }

    // Check if this tool call already exists (avoid duplicates)
    const existingTool = toolCallsContainer.querySelector(`[data-tool="${details.tool}"]`);
    if (existingTool) {
      // Update existing tool call status
      const statusEl = existingTool.querySelector('.tool-status');
      if (statusEl) {
        statusEl.textContent = details.status || 'running';
        statusEl.className = 'tool-status ' + (details.status || 'pending');
      }
      const durationEl = existingTool.querySelector('.tool-duration');
      if (durationEl && details.duration_ms) {
        durationEl.textContent = details.duration_ms < 1000
          ? `${details.duration_ms}ms`
          : `${(details.duration_ms / 1000).toFixed(2)}s`;
      }
      return;
    }

    // Create new tool call item
    const toolEl = document.createElement('div');
    toolEl.className = 'tool-call-item';
    toolEl.setAttribute('data-tool', details.tool);
    toolEl.style.cssText = 'display:flex; align-items:center; gap:8px; padding:4px 8px; margin-top:4px; background:#1a1a2e; border-radius:4px; font-size:12px;';

    const toolName = document.createElement('span');
    toolName.className = 'tool-name';
    toolName.textContent = details.tool;
    toolName.style.cssText = 'color:#9aa3c2; flex:1;';
    toolEl.appendChild(toolName);

    const toolStatus = document.createElement('span');
    toolStatus.className = 'tool-status ' + (details.status || 'pending');
    toolStatus.textContent = details.status || 'running';
    toolStatus.style.cssText = 'padding:2px 6px; border-radius:3px; font-size:10px; text-transform:uppercase;';
    if (details.status === 'success') {
      toolStatus.style.background = '#2a5a3a';
      toolStatus.style.color = '#7fd288';
    } else if (details.status === 'error') {
      toolStatus.style.background = '#5a2a2a';
      toolStatus.style.color = '#ff6b6b';
    } else {
      toolStatus.style.background = '#3a5a9a';
      toolStatus.style.color = '#68a8ef';
    }
    toolEl.appendChild(toolStatus);

    if (details.duration_ms) {
      const toolDuration = document.createElement('span');
      toolDuration.className = 'tool-duration';
      toolDuration.textContent = details.duration_ms < 1000
        ? `${details.duration_ms}ms`
        : `${(details.duration_ms / 1000).toFixed(2)}s`;
      toolDuration.style.cssText = 'color:#666; font-size:10px;';
      toolEl.appendChild(toolDuration);
    }

    toolCallsContainer.appendChild(toolEl);
  }

  togglePanel() {
    this.isCollapsed = !this.isCollapsed;
    if (this.isCollapsed) {
      this.content.style.display = 'none';
      this.toggleBtn.textContent = '+';
      this.toggleBtn.title = 'Expand thinking panel';
    } else {
      this.content.style.display = 'block';
      this.toggleBtn.textContent = '−';
      this.toggleBtn.title = 'Collapse thinking panel';
    }
  }
}

// Initialize thinking visualizer after DOM is ready
let thinkingVisualizer = null;

// Initialize when DOM is ready
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', function() {
    thinkingVisualizer = new ThinkingVisualizer();
    window.thinkingVisualizer = thinkingVisualizer; // Make globally accessible
    console.log('[Thinking] ThinkingVisualizer initialized after DOM ready');
  });
} else {
  // DOM already loaded (script loaded after body)
  thinkingVisualizer = new ThinkingVisualizer();
  window.thinkingVisualizer = thinkingVisualizer; // Make globally accessible
  console.log('[Thinking] ThinkingVisualizer initialized (DOM already ready)');
}

// Add global helper functions
window.startThinking = function(traceId) {
  if (traceId && thinkingVisualizer) {
    console.log('[Thinking] Starting visualization for trace:', traceId);
    thinkingVisualizer.start(traceId);
  } else if (!thinkingVisualizer) {
    console.warn('[Thinking] ThinkingVisualizer not yet initialized, deferring start');
    // Retry after a short delay
    setTimeout(() => {
      if (thinkingVisualizer) {
        console.log('[Thinking] Retrying visualization start for trace:', traceId);
        thinkingVisualizer.start(traceId);
      }
    }, 100);
  }
};

window.stopThinking = function() {
  if (thinkingVisualizer) {
    thinkingVisualizer.stop();
  }
};
