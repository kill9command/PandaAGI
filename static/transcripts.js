async function fetchJSON(url) {
  const r = await fetch(url);
  if (!r.ok) throw new Error('HTTP ' + r.status);
  return r.json();
}

function el(tag, attrs = {}, text = null) {
  const e = document.createElement(tag);
  Object.entries(attrs).forEach(([k,v]) => e.setAttribute(k, v));
  if (text !== null) e.textContent = text;
  return e;
}

async function loadList() {
  const listDiv = document.getElementById('transcripts-list');
  listDiv.innerHTML = '';
  try {
    const q = (document.getElementById('query')?.value || '').trim();
    const qs = q ? ('&q=' + encodeURIComponent(q)) : '';
    const js = await fetchJSON('/transcripts?limit=50' + qs);
    const items = js.items || [];
    if (items.length === 0) { listDiv.appendChild(el('div', {}, 'No transcripts yet.')); return; }
    const ul = el('ul');
    items.forEach(it => {
      const li = el('li');
      // Checkbox per transcript
      const cb = document.createElement('input'); cb.type = 'checkbox'; cb.className = 'sel-cb'; cb.dataset.id = it.id;
      cb.style.marginRight = '8px';
      li.appendChild(cb);
      const label = `${it.ts || ''} [${it.mode || ''}] ${it.user_preview || ''}`;
      const a = el('a', { href: '#'} , label);
      a.addEventListener('click', async (ev) => { ev.preventDefault(); await loadDetail(it.id); });
      li.appendChild(a);
      ul.appendChild(li);
    });
    listDiv.appendChild(ul);
  } catch (e) {
    listDiv.appendChild(el('div', {}, 'Error: ' + (e.message || String(e))));
  }
}

function renderKV(title, obj, cls = '', idAttr = null) {
  const d = document.createElement('details'); d.open = true; d.className='sources-list' + (cls ? (' ' + cls) : '');
  if (idAttr) d.id = idAttr;
  d.appendChild(document.createElement('summary')).textContent = title;
  const pre = document.createElement('pre'); pre.style.whiteSpace='pre-wrap'; pre.textContent = typeof obj==='string'?obj: JSON.stringify(obj, null, 2); d.appendChild(pre);
  return d;
}

// Compact prompts in verbose JSON (keep everything else full)
function compactPrompts(obj) {
  if (typeof obj !== 'object' || obj === null) return obj;
  if (Array.isArray(obj)) return obj.map(compactPrompts);

  const result = {};
  for (const [key, value] of Object.entries(obj)) {
    // Compact these specific fields
    if (key === 'messages_full' || key === 'system' || key === 'content') {
      if (typeof value === 'string' && value.length > 200) {
        result[key] = value.slice(0, 200) + `... [${value.length - 200} more chars]`;
      } else if (Array.isArray(value)) {
        result[key] = value.map(msg => {
          if (typeof msg === 'object' && msg.content && typeof msg.content === 'string' && msg.content.length > 200) {
            return { ...msg, content: msg.content.slice(0, 200) + `... [${msg.content.length - 200} more chars]` };
          }
          return msg;
        });
      } else {
        result[key] = value;
      }
    } else {
      result[key] = compactPrompts(value);
    }
  }
  return result;
}

async function loadDetail(id) {
  const det = document.getElementById('transcript-detail');
  det.innerHTML='';
  try {
    const js = await fetchJSON('/transcripts/' + encodeURIComponent(id));
    // Action bar
    const actions = document.createElement('div');
    actions.style.display = 'flex';
    actions.style.gap = '8px';
    const viewCompactBtn = document.createElement('button'); viewCompactBtn.textContent = 'View compact'; viewCompactBtn.addEventListener('click', () => {
      const n = document.getElementById('compact-json'); if (n) n.scrollIntoView({ behavior: 'smooth', block: 'start' });
    });
    const viewVerboseBtn = document.createElement('button'); viewVerboseBtn.textContent = 'View verbose'; viewVerboseBtn.addEventListener('click', async () => {
      try {
        // Avoid duplicating
        if (!document.getElementById('verbose-json')) {
          const vj = await fetchJSON('/transcripts/' + encodeURIComponent(id) + '/verbose');
          det.appendChild(renderKV('Verbose JSON', vj, 'section-raw', 'verbose-json'));
        }
        const n = document.getElementById('verbose-json'); if (n) n.scrollIntoView({ behavior: 'smooth', block: 'start' });
      } catch (e) {
        det.appendChild(document.createTextNode('Verbose not found or error: ' + (e.message || String(e))));
      }
    });
    const viewSemiCompactBtn = document.createElement('button'); viewSemiCompactBtn.textContent = 'View semi-compact'; viewSemiCompactBtn.addEventListener('click', async () => {
      try {
        // Avoid duplicating
        if (!document.getElementById('semicompact-json')) {
          const vj = await fetchJSON('/transcripts/' + encodeURIComponent(id) + '/verbose');
          const compacted = compactPrompts(vj);
          det.appendChild(renderKV('Semi-Compact JSON', compacted, 'section-raw', 'semicompact-json'));
        }
        const n = document.getElementById('semicompact-json'); if (n) n.scrollIntoView({ behavior: 'smooth', block: 'start' });
      } catch (e) {
        det.appendChild(document.createTextNode('Semi-compact not found or error: ' + (e.message || String(e))));
      }
    });
    const openCompact = document.createElement('a'); openCompact.textContent = 'Open compact'; openCompact.href = '/transcripts/' + encodeURIComponent(id); openCompact.target = '_blank'; openCompact.rel = 'noopener noreferrer';
    const openVerbose = document.createElement('a'); openVerbose.textContent = 'Open verbose'; openVerbose.href = '/transcripts/' + encodeURIComponent(id) + '/verbose'; openVerbose.target = '_blank'; openVerbose.rel = 'noopener noreferrer';
    actions.appendChild(viewCompactBtn);
    actions.appendChild(viewSemiCompactBtn);
    actions.appendChild(viewVerboseBtn);
    actions.appendChild(openCompact);
    actions.appendChild(openVerbose);
    det.appendChild(actions);

    det.appendChild(renderKV('Envelope', { id: js.id, ts: js.ts, mode: js.mode, repo: js.repo, dur_ms: js.dur_ms }, 'section-envelope'));
    det.appendChild(renderKV('User', js.user || '', 'section-user'));
    det.appendChild(renderKV('Profile', js.profile || '', 'section-profile'));
    det.appendChild(renderKV('Policy', js.policy || {}, 'section-policy'));
    det.appendChild(renderKV('Injected Context', (js.injected_context || []).join('\n\n'), 'section-context'));
    det.appendChild(renderKV('Policy Notes', (js.policy_notes || []).join('\n'), 'section-policy-notes'));
    det.appendChild(renderKV('Deferred', js.deferred || [], 'section-deferred'));
    det.appendChild(renderKV('Guide Calls', js.guide_calls || [], 'section-solver'));
    det.appendChild(renderKV('Coordinator Calls', js.coordinator_calls || [], 'section-thinking'));
    det.appendChild(renderKV('Tools Executed', js.tools_executed || [], 'section-tools'));
    det.appendChild(renderKV('Memory Saves', js.memory_saves || [], 'section-memory'));
    det.appendChild(renderKV('Final', js.final || '', 'section-final'));
    det.appendChild(renderKV('Compact JSON', js, 'section-raw', 'compact-json'));
    // Auto-load verbose (if available) so both are visible without clicks
    try {
      const vj = await fetchJSON('/transcripts/' + encodeURIComponent(id) + '/verbose');
      det.appendChild(renderKV('Verbose JSON', vj, 'section-raw', 'verbose-json'));
    } catch (e) {
      // Silently ignore; button can still fetch it on demand
    }
  } catch (e) {
    det.appendChild(el('div', {}, 'Error: ' + (e.message || String(e))));
  }
}

document.getElementById('refresh').addEventListener('click', loadList);
document.getElementById('search').addEventListener('click', loadList);
document.getElementById('clear').addEventListener('click', () => { const q = document.getElementById('query'); if (q) q.value=''; loadList(); });
document.getElementById('query').addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); loadList(); }});
document.getElementById('select-all').addEventListener('change', (e) => {
  const on = !!e.target.checked;
  document.querySelectorAll('.sel-cb').forEach(cb => { cb.checked = on; });
});
document.getElementById('delete-selected').addEventListener('click', async () => {
  try {
    const ids = Array.from(document.querySelectorAll('.sel-cb')).filter(cb => cb.checked).map(cb => cb.dataset.id).filter(Boolean);
    if (ids.length === 0) { alert('No transcripts selected.'); return; }
    if (!confirm(`Delete ${ids.length} transcript(s)? This cannot be undone.`)) return;
    const res = await fetch('/transcripts/delete', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ ids }) });
    if (!res.ok) {
      const t = await res.text().catch(()=> '');
      alert('Delete failed: ' + (t || res.status));
      return;
    }
    await loadList();
    const det = document.getElementById('transcript-detail');
    if (det) det.innerHTML = '';
    const sa = document.getElementById('select-all'); if (sa) sa.checked = false;
  } catch (e) {
    alert('Error: ' + (e && (e.message || String(e))));
  }
});
loadList();
