/* RAC Server admin frontend — vanilla JS */
(function () {
  'use strict';

  const POLL_MS = 2000;

  const state = {
    deviceId: null,
    devices: [],
    uploads: [],
    filesPath: '',
    pollTimer: null,
  };

  // ---------- helpers ----------
  function $(sel, root) { return (root || document).querySelector(sel); }
  function $$(sel, root) { return Array.from((root || document).querySelectorAll(sel)); }

  function toast(msg, kind) {
    const t = $('#toast');
    t.textContent = msg;
    t.className = 'fixed top-4 left-1/2 -translate-x-1/2 z-50 max-w-md px-4 py-2 rounded shadow text-sm ' +
      (kind === 'error' ? 'bg-red-600 text-white' : 'bg-slate-800 text-white');
    t.classList.remove('hidden');
    clearTimeout(toast._t);
    toast._t = setTimeout(() => t.classList.add('hidden'), 3000);
  }

  function escapeHtml(s) {
    if (s == null) return '';
    return String(s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }

  async function api(path, opts) {
    opts = opts || {};
    const headers = Object.assign({}, opts.headers || {});
    headers['X-Requested-With'] = 'fetch';
    if (opts.json !== undefined) {
      headers['Content-Type'] = 'application/json';
      opts.body = JSON.stringify(opts.json);
      delete opts.json;
    }
    opts.headers = headers;
    opts.credentials = 'same-origin';
    const r = await fetch(path, opts);
    if (r.status === 401) {
      window.location.href = '/login';
      throw new Error('unauthorized');
    }
    if (!r.ok) {
      let msg = r.statusText;
      try {
        const data = await r.json();
        msg = data.detail || JSON.stringify(data);
      } catch (e) { /* ignore */ }
      const err = new Error(msg);
      err.status = r.status;
      throw err;
    }
    if (r.status === 204) return null;
    const ct = r.headers.get('content-type') || '';
    if (ct.includes('application/json')) return r.json();
    return r.text();
  }

  function setUrlDevice(id) {
    const u = new URL(location.href);
    if (id) u.searchParams.set('device_id', String(id));
    else u.searchParams.delete('device_id');
    history.replaceState(null, '', u.toString());
  }

  // ---------- devices ----------
  async function loadDevices() {
    try {
      state.devices = await api('/api/web/devices');
    } catch (e) {
      toast('Не удалось загрузить устройства: ' + e.message, 'error');
      return;
    }
    const sel = $('#device-select');
    const prev = sel.value;
    sel.innerHTML = '<option value="">— устройство —</option>' +
      state.devices.map(d => {
        const dot = d.online ? '🟢' : '⚪';
        return `<option value="${d.id}">${dot} ${escapeHtml(d.hostname)} (${escapeHtml(d.mac)})</option>`;
      }).join('');
    const wanted = state.deviceId ? String(state.deviceId) : prev;
    if (wanted) sel.value = wanted;
    updateDeviceStatus();
  }

  function updateDeviceStatus() {
    const span = $('#device-status');
    const d = state.devices.find(x => String(x.id) === String(state.deviceId));
    if (!d) {
      span.textContent = '';
      span.classList.add('hidden');
      return;
    }
    span.classList.remove('hidden');
    span.textContent = d.online ? '● online · ' + (d.last_ip || '') : '○ offline · ' + (d.last_ip || '');
    span.className = 'inline-flex items-center text-xs ' + (d.online ? 'text-emerald-600' : 'text-slate-400');
  }

  // ---------- commands ----------
  function commandCard(cmd) {
    const cls = ({
      pending: 'cmd-pending', in_progress: 'cmd-progress',
      done: 'cmd-done', error: 'cmd-error',
    })[cmd.status] || '';

    let inputHtml = '';
    if (cmd.input_file) {
      const fn = escapeHtml(cmd.input_file.filename);
      const url = cmd.input_file.url;
      inputHtml = `<div class="text-xs text-slate-600 mt-1">↑ файл: ` +
        (url ? `<a href="${url}" class="text-indigo-600 hover:underline" target="_blank" rel="noopener">${fn}</a>` : fn) +
        `</div>`;
    }

    let outputHtml = '';
    if (cmd.output) {
      outputHtml = `<pre class="cmd-output">${escapeHtml(cmd.output)}</pre>`;
    }

    let outFile = '';
    if (cmd.output_file) {
      outFile = `<div class="text-xs mt-1"><a href="${cmd.output_file.url}" target="_blank" rel="noopener" class="text-indigo-600 hover:underline">⬇ ${escapeHtml(cmd.output_file.filename)}</a></div>`;
    }

    return `
      <div class="cmd-card ${cls}">
        <div class="flex items-center gap-2 text-xs text-slate-500">
          <span>#${cmd.id}</span>
          <span class="font-medium text-slate-700">[${escapeHtml(cmd.status)}]</span>
          <span class="font-medium text-slate-900">${escapeHtml(cmd.name)}</span>
          <span class="ml-auto">${escapeHtml(cmd.created_at || '')}</span>
        </div>
        ${cmd.payload ? `<div class="text-xs text-slate-600 mt-1 break-all">${escapeHtml(cmd.payload)}</div>` : ''}
        ${inputHtml}
        ${outputHtml}
        ${outFile}
      </div>`;
  }

  async function loadCommands() {
    const box = $('#commands-list');
    if (!state.deviceId) {
      box.innerHTML = '<div class="text-slate-400 text-sm p-4 text-center">Выберите устройство</div>';
      return;
    }
    try {
      const list = await api(`/api/web/commands?device_id=${state.deviceId}&limit=100`);
      const stick = (box.scrollHeight - box.scrollTop - box.clientHeight) < 40;
      const html = list.slice().reverse().map(commandCard).join('') ||
        '<div class="text-slate-400 text-sm p-4 text-center">Команд нет</div>';
      box.innerHTML = html;
      if (stick) box.scrollTop = box.scrollHeight;
    } catch (e) {
      toast('Команды: ' + e.message, 'error');
    }
  }

  async function submitCommand(ev) {
    ev.preventDefault();
    if (!state.deviceId) { toast('Выберите устройство', 'error'); return; }
    const name = $('#cmd-name').value.trim();
    const uploadId = $('#cmd-upload').value;
    if (!name) { toast('Введите команду', 'error'); return; }

    const body = { device_id: Number(state.deviceId), name };
    if (uploadId) body.upload_id = Number(uploadId);

    try {
      await api('/api/web/commands', { method: 'POST', json: body });
      $('#cmd-name').value = '';
      $('#cmd-upload').value = '';
      await loadCommands();
    } catch (e) {
      toast('Не удалось отправить: ' + e.message, 'error');
    }
  }

  // ---------- uploads ----------
  async function loadUploads() {
    try {
      state.uploads = await api('/api/web/uploads');
    } catch (e) {
      toast('Загрузки: ' + e.message, 'error');
      return;
    }
    const list = state.uploads;
    $('#uploads-list').innerHTML = list.map(u => `
      <div class="flex items-center gap-2 p-1.5 hover:bg-slate-50 rounded">
        <span class="flex-1 truncate">📄 ${escapeHtml(u.filename)}</span>
        <span class="text-xs text-slate-400">${formatSize(u.size_bytes)}</span>
        <a href="/api/web/uploads/${u.id}/download" target="_blank" rel="noopener"
           class="text-indigo-600 hover:underline text-xs">⬇</a>
        <button data-up-del="${u.id}" class="text-red-600 hover:underline text-xs">🗑</button>
      </div>
    `).join('') || '<div class="text-slate-400 text-xs p-2">Нет</div>';

    // dropdown for command form
    const sel = $('#cmd-upload');
    const prev = sel.value;
    sel.innerHTML = '<option value="">— без файла —</option>' +
      list.map(u => `<option value="${u.id}">${escapeHtml(u.filename)}</option>`).join('');
    sel.value = prev;

    $$('button[data-up-del]').forEach(b => b.addEventListener('click', () => deleteUpload(b.dataset.upDel)));
  }

  async function deleteUpload(id) {
    if (!confirm('Удалить загрузку?')) return;
    try {
      const r = await fetch(`/api/web/uploads/${id}`, {
        method: 'DELETE',
        headers: { 'X-Requested-With': 'fetch' },
        credentials: 'same-origin',
      });
      if (r.status === 409) {
        const data = await r.json();
        toast('Используется командами: ' + (data.command_ids || []).join(', '), 'error');
        return;
      }
      if (!r.ok) {
        const t = await r.text();
        toast('Не удалось: ' + t, 'error');
        return;
      }
      await loadUploads();
    } catch (e) {
      toast('Ошибка: ' + e.message, 'error');
    }
  }

  function uploadFile(file) {
    const xhr = new XMLHttpRequest();
    xhr.open('POST', '/api/web/uploads');
    xhr.setRequestHeader('X-Requested-With', 'fetch');
    const fd = new FormData();
    fd.append('file', file);
    const prog = $('#uploads-progress');
    prog.classList.remove('hidden');
    prog.textContent = 'Загрузка: 0%';
    xhr.upload.onprogress = (ev) => {
      if (ev.lengthComputable) {
        prog.textContent = 'Загрузка: ' + Math.floor(100 * ev.loaded / ev.total) + '%';
      }
    };
    xhr.onload = () => {
      prog.classList.add('hidden');
      if (xhr.status === 401) { window.location.href = '/login'; return; }
      if (xhr.status >= 400) {
        let msg = xhr.statusText;
        try { msg = JSON.parse(xhr.responseText).detail || msg; } catch (e) {}
        toast('Ошибка загрузки: ' + msg, 'error');
        return;
      }
      loadUploads();
    };
    xhr.onerror = () => { prog.classList.add('hidden'); toast('Сеть: ошибка', 'error'); };
    xhr.send(fd);
  }

  function formatSize(n) {
    if (n == null) return '';
    if (n < 1024) return n + ' B';
    if (n < 1024 * 1024) return (n / 1024).toFixed(1) + ' KB';
    if (n < 1024 * 1024 * 1024) return (n / 1024 / 1024).toFixed(1) + ' MB';
    return (n / 1024 / 1024 / 1024).toFixed(2) + ' GB';
  }

  // ---------- files explorer ----------
  async function loadFiles(path) {
    state.filesPath = path || '';
    try {
      const data = await api('/api/web/files?path=' + encodeURIComponent(state.filesPath));
      renderFiles(data);
    } catch (e) {
      toast('Проводник: ' + e.message, 'error');
    }
  }

  function renderFiles(data) {
    const bc = $('#files-breadcrumbs');
    const parts = data.path ? data.path.split('/') : [];
    let crumbs = `<a href="#" data-files-go="" class="hover:underline">cmds</a>`;
    let acc = '';
    parts.forEach((p, i) => {
      acc = acc ? acc + '/' + p : p;
      crumbs += ` / <a href="#" data-files-go="${escapeHtml(acc)}" class="hover:underline">${escapeHtml(p)}</a>`;
    });
    bc.innerHTML = crumbs;

    const list = data.items.map(it => {
      const full = data.path ? data.path + '/' + it.name : it.name;
      if (it.type === 'dir') {
        return `<div class="flex items-center gap-2 p-1.5 hover:bg-slate-50 rounded">
          <a href="#" data-files-go="${escapeHtml(full)}" class="flex-1 truncate">📁 ${escapeHtml(it.name)}</a>
        </div>`;
      }
      const dl = '/api/web/files/download?path=' + encodeURIComponent(full);
      return `<div class="flex items-center gap-2 p-1.5 hover:bg-slate-50 rounded">
        <span class="flex-1 truncate">📄 ${escapeHtml(it.name)}</span>
        <span class="text-xs text-slate-400">${formatSize(it.size)}</span>
        <a href="${dl}" target="_blank" rel="noopener" class="text-indigo-600 hover:underline text-xs">⬇</a>
        <button data-files-del="${escapeHtml(full)}" class="text-red-600 hover:underline text-xs">🗑</button>
      </div>`;
    }).join('') || '<div class="text-slate-400 text-xs p-2">Пусто</div>';
    $('#files-list').innerHTML = list;

    $$('a[data-files-go]', bc).forEach(a => a.addEventListener('click', (e) => {
      e.preventDefault(); loadFiles(a.dataset.filesGo);
    }));
    $$('a[data-files-go]', $('#files-list')).forEach(a => a.addEventListener('click', (e) => {
      e.preventDefault(); loadFiles(a.dataset.filesGo);
    }));
    $$('button[data-files-del]', $('#files-list')).forEach(b => b.addEventListener('click', () => deleteFile(b.dataset.filesDel)));
  }

  async function deleteFile(p) {
    if (!confirm('Удалить файл?')) return;
    try {
      await api('/api/web/files?path=' + encodeURIComponent(p), { method: 'DELETE' });
      await loadFiles(state.filesPath);
    } catch (e) {
      toast('Не удалось удалить: ' + e.message, 'error');
    }
  }

  // ---------- polling ----------
  function startPolling() {
    stopPolling();
    state.pollTimer = setInterval(async () => {
      if (document.visibilityState !== 'visible') return;
      await loadDevices();
      if (state.deviceId) await loadCommands();
    }, POLL_MS);
  }
  function stopPolling() {
    if (state.pollTimer) { clearInterval(state.pollTimer); state.pollTimer = null; }
  }

  // ---------- init ----------
  function setActiveTab(name) {
    document.body.dataset.tab = name;
    $$('.tab-btn').forEach(b => {
      const active = b.dataset.tab === name;
      b.classList.toggle('border-indigo-500', active);
      b.classList.toggle('text-indigo-700', active);
      b.classList.toggle('border-transparent', !active);
    });
  }

  document.addEventListener('DOMContentLoaded', async () => {
    document.body.dataset.tab = 'console';

    $('#device-select').addEventListener('change', async (e) => {
      state.deviceId = e.target.value || null;
      setUrlDevice(state.deviceId);
      updateDeviceStatus();
      await loadCommands();
    });

    $('#cmd-form').addEventListener('submit', submitCommand);

    $('#upload-input').addEventListener('change', (e) => {
      const f = e.target.files && e.target.files[0];
      if (f) uploadFile(f);
      e.target.value = '';
    });

    $('#files-refresh').addEventListener('click', () => loadFiles(state.filesPath));

    $$('.tab-btn').forEach(b => b.addEventListener('click', () => setActiveTab(b.dataset.tab)));

    $('#menu-toggle').addEventListener('click', () => {
      $('#mobile-menu').classList.toggle('hidden');
    });

    document.addEventListener('visibilitychange', () => {
      if (document.visibilityState === 'visible' && state.deviceId) {
        loadDevices();
        loadCommands();
      }
    });

    // initial device selection from URL
    const initial = window.__APP__ && window.__APP__.initialDeviceId;
    if (initial) state.deviceId = initial;

    await loadDevices();
    if (state.deviceId) {
      $('#device-select').value = String(state.deviceId);
    }
    await Promise.all([loadCommands(), loadUploads(), loadFiles('')]);
    startPolling();
  });
})();
