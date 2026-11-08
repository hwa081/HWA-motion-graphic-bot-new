/* Generate, progress, results. The page starts the bot (GitHub Actions), watches the run and shows outputs/index.json from the repository. */
(function () {
  'use strict';
  const S = window.Studio, G = S.gh, $ = S.$, st = S.state, store = S.store;
  let pend = store.get('pending', []);       // {job, label, prompt, size, dur, mode, inputs, dispatched, t0, run}

  /* ---------------- auto-continue: a video that stops is continued by itself until it is finished ---------------- */
  const AUTO_MAX = 30;                                           // safety stop: 30 automatic tries per video
  let autoOn = !!store.get('autoRetry', false);
  const autoDelay = n => Math.min(600, 60 + 45 * n) * 1000;      // waits 1:00, 1:45, 2:30 ... at most 10 minutes between tries
  const resumable = p => !!(p.inputs && ['ai', 'spec'].includes(p.inputs.mode));
  function renderAuto() {
    const b = document.getElementById('btnAuto'); if (!b) return;
    b.classList.toggle('on', autoOn); b.setAttribute('aria-pressed', String(autoOn));
    const l = b.querySelector('.atl'); if (l) l.textContent = autoOn ? 'Auto-continue ON' : 'Auto-continue';
  }
  S.autoOn = () => autoOn;
  S.setAuto = function (on) {
    autoOn = !!on; store.set('autoRetry', autoOn); renderAuto();
    for (const p of pend) if (!autoOn) p.retryAt = 0;
    savePend(); autoTick(); if (S.hooks.refresh) S.hooks.refresh(true);
    S.toast(autoOn ? 'Auto-continue ON - stopped videos continue by themselves' : 'Auto-continue off');
  };
  function restart(p, auto) {            // same brief again: the bot finds its saved work (work/<key>.json) and goes on from there
    const nj = jid(); p.job = nj; if (p.inputs) { p.inputs.job = nj; p.inputs.resume = 'auto'; }
    p.lastFail = p.detail || p.label || '';
    p.attempts = auto ? (p.attempts || 0) + 1 : 0;
    Object.assign(p, { failed: false, dispatched: 0, run: null, runUrl: '', approveTried: 0, approveOk: false, ok: false, doneAt: 0, retryAt: 0, userStopped: false, autoGaveUp: false,
      label: 'Queued', detail: auto ? 'auto-continue: try ' + p.attempts + ' (it goes on from the saved work)' : 'continuing from the saved work', prog: null, t0: Date.now() });
  }
  function autoTick() {
    let changed = false;
    for (const p of pend) {
      if (!p.failed || p.userStopped || !resumable(p) || p.label === 'Needs approval') continue;
      if (!autoOn) { if (p.retryAt) { p.retryAt = 0; changed = true; } continue; }
      if ((p.attempts || 0) >= AUTO_MAX) { if (!p.autoGaveUp) { p.autoGaveUp = true; p.detail = 'auto-continue stopped after ' + AUTO_MAX + ' tries - fix the cause (see Log), then press Continue'; changed = true; } continue; }
      if (!p.retryAt) { p.retryAt = Date.now() + autoDelay(p.attempts || 0); changed = true; }
      else if (Date.now() >= p.retryAt) { restart(p, true); changed = true; }
    }
    if (changed) { savePend(); if (S.hooks.refresh) S.hooks.refresh(true); }
  }
  S._autoTick = autoTick;
  function clock(ms) { const t = Math.max(0, Math.round(ms / 1000)), h = Math.floor(t / 3600), m = Math.floor(t % 3600 / 60), x = t % 60; return (h ? h + ':' + String(m).padStart(2, '0') : String(m)) + ':' + String(x).padStart(2, '0'); }
  setInterval(function () {              // once a second: countdowns, run timers, and the retry itself
    document.querySelectorAll('[data-retry]').forEach(e => { e.textContent = 'Auto-continue in ' + clock(+e.dataset.retry - Date.now()); });
    document.querySelectorAll('[data-t0]').forEach(e => { e.textContent = clock(Date.now() - +e.dataset.t0); });
    autoTick();
  }, 1000);
  document.addEventListener('DOMContentLoaded', renderAuto); renderAuto();
  let rawIndex = [], timer = null, busy = false, again = false;
  const jid = () => 'j' + Date.now().toString(36) + Math.random().toString(36).slice(2, 5);
  const savePend = () => store.set('pending', pend);
  const safe = n => String(n).replace(/[^A-Za-z0-9._-]+/g, '_').slice(-60);
  const b64 = str => btoa(unescape(encodeURIComponent(str)));
  const sleep = ms => new Promise(r => setTimeout(r, ms));

  function toItem(e) {
    const it = { id: e.id, job: e.job, kind: e.kind === 'video' ? 'video' : (e.kind === 'storyboard' ? 'storyboard' : 'report'), title: e.title, prompt: e.prompt, mode: e.mode, size: e.size, dur: e.dur, date: Date.parse(e.date) || 0,
      trashed: !!e.trashed, design_id: e.design_id, ai: e.ai, report: e.report, spec: e.spec, video: e.video, note: e.note,
      project: e.project, long: e.long, quality: e.quality, parent: e.parent, formats: e.formats, files: e.files, video_name: e.video_name, shots: e.shots, redo: e.redo, awaiting: e.awaiting, no_mp4: e.no_mp4 };
    if (e.video) it.url = G.rawUrl(e.video);
    if (e.poster) it.poster = G.rawUrl(e.poster);
    if (e.storyboard) { it.url = G.rawUrl(e.storyboard); it.poster = it.url; }
    return it;
  }

  /* ---------------- refresh ---------------- */
  S.hooks.refresh = async function (force) {
    renderAuto();
    if (busy) { if (force) again = true; return; } busy = true;
    try {
      if (!G.ready()) { st.media = []; st.jobs = []; S.renderGrid(); return; }
      const txt = await G.readText('outputs/index.json');
      try { rawIndex = txt ? JSON.parse(txt) : []; } catch (e) { rawIndex = []; }
      st.media = rawIndex.map(toItem);
      try { const pt = await G.readText('outputs/projects.json'); if (pt && S.setProjects) S.setProjects(JSON.parse(pt)); } catch (e) {}
      if (S.renderProjMenu) S.renderProjMenu();
      await syncRuns();
      st.jobs = pend.map(p => ({ id: p.job, label: p.label || (p.failed ? 'Failed' : 'Working'), detail: p.detail || '', size: p.size, failed: !!p.failed, runUrl: p.runUrl, jobId: p.job, prog: p.failed ? null : p.prog, project: p.project, prompt: p.prompt, mode: p.mode, canResume: !!(p.inputs && ['ai', 'spec'].includes(p.inputs.mode)), retryAt: p.retryAt || 0, attempts: p.attempts || 0, lastFail: p.lastFail || '', t0: p.t0, autoGaveUp: !!p.autoGaveUp, dispatched: !!p.dispatched }));
      const nb = $('#actBadge'); if (nb) { const n = pend.filter(p => !p.failed).length; nb.textContent = n; nb.hidden = !n; }
      if (st.view === 'media') S.renderGrid();
      if (st.view === 'activity') S.hooks.renderActivity();
      if (st.view === 'tools' && S.hooks.renderTools) S.hooks.renderTools();
    } catch (e) { if (force) S.toast(e.message, true); }
    finally { busy = false; if (again) { again = false; return S.hooks.refresh(true); } schedule(); }
  };
  function schedule() {
    clearTimeout(timer);
    if (!G.ready()) return;
    timer = setTimeout(() => S.hooks.refresh(), pend.some(p => !p.failed) ? 6000 : 45000);
  }

  async function syncRuns() {
    if (!pend.length) return;
    const runs = await G.runs(25);
    for (const p of pend) {
      if (p.failed) continue;
      const run = runs.find(r => (r.display_title || r.name || '').includes(p.job));
      const indexed = rawIndex.find(e => e.id === p.job);
      if (run) {
        p.run = run.id; p.runUrl = run.html_url;
        if (run.conclusion === 'action_required' || (run.status === 'waiting' && !run.conclusion)) {
          // GitHub holds the run until it is approved: try to approve it from here
          if (!p.approveTried) {
            p.approveTried = Date.now();
            const r = await G.req('POST', '/repos/' + G.cfg().repo + '/actions/runs/' + run.id + '/approve');
            p.approveOk = !!(r && r.ok);
            if (!p.approveOk) p.approveMsg = (r && r.json && r.json.message) || ('HTTP ' + (r && r.status));
          }
          if (p.approveOk) { p.label = 'Approved'; p.detail = 'starting...'; if (Date.now() - p.approveTried > 90000) { p.failed = true; p.label = 'Failed'; p.detail = 'approved but it did not start - open the run in GitHub'; } }
          else { p.failed = true; p.label = 'Needs approval'; p.detail = 'GitHub wants you to click "Approve and run" on this run (click here to open it)'; }
        } else if (run.status === 'completed') {
          if (run.conclusion === 'success') { p.ok = true; if (!p.doneAt) p.doneAt = Date.now(); p.label = 'Finishing'; p.detail = 'saving the result'; }
          else if (run.conclusion === 'cancelled') { p.failed = true; p.label = 'Stopped'; p.detail = 'stopped. Continue goes on from the saved work'; }
          else { p.failed = true; p.label = 'Failed'; p.detail = 'the run stopped (' + String(run.conclusion).replace('_', ' ') + '). Continue goes on from the saved work'; }
        } else {
          p.label = run.status === 'queued' ? 'Queued' : 'Running';
          if (run.status === 'in_progress') { try { const jr = await G.req('GET', '/repos/' + G.cfg().repo + '/actions/runs/' + run.id + '/jobs'); const stp = ((jr.json && jr.json.jobs && jr.json.jobs[0] && jr.json.jobs[0].steps) || []); const cur = stp.find(x => x.status === 'in_progress') || stp.filter(x => x.status === 'completed').pop(); p.detail = cur ? cur.name.replace(/^Run$/, 'Making the video') : ''; } catch (e) {}
            try { const t = await G.readRef('progress/' + p.job + '.json', 'bot-progress'); const d = t ? JSON.parse(t) : null; if (d && d.job === p.job && !d.done) p.prog = d; } catch (e) {} }
        }
      } else if (p.dispatched) {
        if (Date.now() - p.dispatched > 4 * 60000) { p.failed = true; p.label = 'Failed'; p.detail = 'the run did not start - is the bot workflow in the repository?'; }
        else { p.label = 'Starting'; p.detail = 'waiting for GitHub'; }
      }
    }
    // the bot stopped but published the reason: keep the tile as failed and show why (Continue goes on from the saved work)
    for (const p of pend) { const e = rawIndex.find(x => x.id === p.job); if (e && e.ok === false && e.kind !== 'video' && !p.failed) { p.failed = true; p.ok = false; p.label = 'Failed'; p.detail = e.note || 'The run stopped before the video was ready'; } }
    // finished jobs leave the list
    const done = pend.filter(p => !p.failed && (rawIndex.find(e => e.id === p.job) || (p.ok && (!p.expectOutput || Date.now() - p.doneAt > 20000))));
    if (done.length) {
      pend = pend.filter(p => !done.includes(p)); 
      for (const p of done) { if (p.onDone) S.toast(p.onDone); if (p.mode === 'checks' && S.hooks.showCloudChecks) setTimeout(S.hooks.showCloudChecks, 300); }
    }
    // client-side queue: up to MAX_PAR videos run together (workflow slot 1 and slot 2; each slot runs one run at a time)
    const MAX_PAR = 2;
    for (let guard = 0; guard < MAX_PAR; guard++) {
      const running = pend.filter(p => p.dispatched && !p.failed);
      if (running.length >= MAX_PAR) break;
      const next = pend.find(p => !p.dispatched && !p.failed); if (!next) break;
      const used = new Set(running.map(p => String(p.slot || '1')));
      next.slot = used.has('1') ? '2' : '1'; next.inputs = Object.assign({}, next.inputs, { slot: next.slot });
      try { await G.dispatch(next.inputs); next.dispatched = Date.now(); next.label = 'Starting'; }
      catch (e) { next.failed = true; next.label = 'Failed'; next.detail = e.message; S.toast(e.message, true); break; }
    }
    pend.filter(p => !p.dispatched && !p.failed).forEach(p => { p.label = 'Waiting'; p.detail = 'in the queue (2 videos can run together)'; });
    savePend();
  }
  S.hooks.onJobAction = async function (jobId, act) {
    const p = pend.find(x => x.job === jobId); if (!p) return;
    if (act === 'log') { if (p.runUrl) window.open(p.runUrl, '_blank', 'noopener'); return; }
    if (act === 'cancel') {                // stop a running or waiting video (the saved work stays, Continue goes on later)
      try {
        if (p.dispatched && !p.run) { const rs = await G.runs(25); const r0 = rs.find(r => (r.display_title || r.name || '').includes(p.job)); if (r0) p.run = r0.id; }
        if (p.run && p.dispatched) await G.cancelRun(p.run);
        p.userStopped = true; p.retryAt = 0; p.failed = true; p.label = 'Stopped'; p.detail = p.dispatched ? 'stopped by you. Continue goes on from the saved work' : 'removed from the queue'; p.prog = null;
        if (!p.dispatched) pend = pend.filter(x => x !== p);
        savePend(); S.toast('Stopped'); S.hooks.refresh(true);
      } catch (e) { S.toast(e.message, true); }
      return;
    }
    if (act === 'remove') { pend = pend.filter(x => x !== p); savePend(); S.hooks.refresh(true); return; }
    if (act === 'continue') {
      restart(p, false);
      savePend(); S.toast('Continuing - the bot picks up its saved work'); S.hooks.refresh(true);
    }
  };
  /* ---------------- start something ---------------- */
  S.queue = function (p) {
    pend.push(Object.assign({ job: jid(), t0: Date.now(), dispatched: 0 }, p)); savePend();
    st.jobs = pend.map(x => ({ id: x.job, label: x.label || 'Queued', detail: x.detail || '', size: x.size, failed: x.failed, jobId: x.job, prog: x.prog, project: x.project }));
    if (st.view === 'media') S.renderGrid();
    clearTimeout(timer); S.hooks.refresh(true);
  };
  async function ensureKeys() {
    if (!S.settings.loaded) await S.settingsLoad();
    const sec = S.settings.secrets || [];
    return sec.includes('GEMINI_API_KEY') || sec.some(x => x.startsWith('AI_KEY_'));
  }
  S.tool = async function (mode, prompt, files, label, extra, opts) {
    if (!G.ready()) { S.toast('Connect GitHub in Settings first', true); S.show('settings'); return false; }
    if (['study', 'ai', 'code', 'compare', 'evolve', 'learn'].includes(mode) && mode !== 'compare' && !(await ensureKeys())) { S.toast('Add an AI key in Settings first', true); S.show('settings'); return false; }
    const job = jid();
    const inputs = Object.assign({ mode, prompt: prompt || '', files: files || '', formats: 'none', sound: 'none', ai: st.cfg.model === 'gemini' ? 'gemini' : st.cfg.model, job }, extra || {});
    S.queue(Object.assign({ job, label: label || 'Queued', mode, prompt, inputs, expectOutput: false }, opts || {}));
    S.toast((label || mode) + ' - started'); return true;
  };

  S.hooks.onSend = async function (text, cfg, attach) {
    if (!G.ready()) { S.toast('Connect GitHub in Settings first', true); S.show('settings'); return false; }
    if (!(await ensureKeys())) { S.toast('Add an AI key (Gemini or another) in Settings first', true); S.show('settings'); return false; }
    const files = [];
    try {
      let i = 0;
      for (const a of attach) {
        if (a.repoPath) { files.push(a.repoPath); continue; }
        S.toast('Uploading ' + a.file.name + '…');
        const path = (a.kind === 'video' ? 'reference/' : 'assets/uploads/') + Date.now().toString(36) + (i++) + '_' + safe(a.file.name);
        await G.putFile(path, await G.fileToB64(a.file), 'upload from studio'); files.push(path);
      }
    } catch (e) { S.toast(e.message, true); return false; }
    if (cfg.mode === 'code' && attach.some(a => a.kind === 'audio')) { S.toast('Voice-over needs AI plan (Code Studio does not use it)', true); return false; }
    if (cfg.mode === 'code' && cfg.dur > 60) { S.toast('Code Studio makes up to 60 seconds. For a longer video use AI plan (it works in parts).', true); return false; }
    const n = Math.max(1, cfg.n | 0);
    for (let k = 0; k < n; k++) {
      const job = jid();
      const fm = (cfg.formats || []).filter(f => ['wfp', 'fcpxml', 'xml', 'native'].includes(f));
      const mp4 = cfg.mp4 !== false;
      if (!mp4 && !fm.length) { S.toast('MP4 is off - pick at least one file (.wfp / FCPXML / XML / .wfp native), or turn MP4 on', true); return false; }
      if (!mp4) fm.push('nomp4');
      const quality = cfg.mode === 'code' || !mp4 ? 'final' : (cfg.quality === 'final' ? 'final' : 'draft');
      const vsecs = attach.some(a => a.kind === 'audio') ? (attach.find(a => a.kind === 'audio').secs || 0) : 0;
      const sb = cfg.storyboard !== false && cfg.mode === 'ai' && (vsecs ? vsecs <= 60 : cfg.dur <= 60) ? 'ask' : 'off';
      const project = S.currentProject ? S.currentProject() : 'default';
      const inputs = { mode: cfg.mode, prompt: text, duration: String(vsecs ? Math.ceil(vsecs) : cfg.dur), size: cfg.size, review: String(cfg.speed === 'quality'), speed: cfg.speed === 'quality' ? 'quality' : 'fast', files: files.join(','), formats: fm.length ? fm.join(',') : 'none', sound: cfg.sound ? (cfg.soundStyle || 'premium') : 'none', ai: cfg.model === 'gemini' ? 'gemini' : cfg.model, job, quality, project, resume: 'auto', storyboard: sb };
      S.queue({ job, label: 'Queued', prompt: text, size: cfg.size, dur: cfg.dur, mode: cfg.mode, inputs, expectOutput: true, project });
    }
    S.toast(n > 1 ? n + ' videos queued (2 run together, the rest wait)' : 'Started - it will appear here when it is ready');
    return true;
  };

  S.hooks.approve = async function (m) {
    const r = m.redo;
    if (!r || !r.prompt) { S.toast('This storyboard has no saved settings - make it again', true); return false; }
    const job = jid();
    const inputs = { mode: 'ai', prompt: r.prompt, duration: String(r.dur), size: r.size, review: 'false', speed: r.speed || 'fast', files: r.files || '', formats: r.formats || 'none', sound: r.sound || 'none', ai: r.ai || 'gemini', job, quality: r.quality || 'draft', project: r.project || 'default', resume: 'auto', storyboard: 'approved', parent: m.job || '' };
    S.queue({ job, label: 'Queued', prompt: r.prompt, size: r.size, dur: r.dur, mode: 'ai', inputs, expectOutput: true, project: r.project });
    S.toast('Approved - making the video from this storyboard');
    return true;
  };

  S.hooks.useAsReference = function (m) {
    if (!m.video) return;
    st.attach = st.attach.filter(a => a.kind !== 'video'); st.attach.push({ kind: 'video', repoPath: m.video, file: { name: (m.title || 'reference') }, url: '' });
    S.renderAttach(); S.closeViewer(); S.toast('Added as the reference video - now describe your own video');
  };
  S.hooks.feedback = async function (m, stars, note) {
    if (!m.design_id) { S.toast('This video has no design id (feedback works for AI plan / Code videos)', true); return; }
    const ok = await S.tool('feedback', note || '(rating only)', '', 'Learning from your feedback', { rating: String(stars), design_id: m.design_id });
    if (ok) S.closeViewer();
  };
  S.hooks.trash = async function (m, flag) {
    try {
      const e = rawIndex.find(x => x.id === m.id); if (!e) return;
      e.trashed = flag; m.trashed = flag;
      await G.putFile('outputs/index.json', b64(JSON.stringify(rawIndex, null, 1)), (flag ? 'trash ' : 'restore ') + m.id);
      S.renderGrid(); S.toast(flag ? 'Moved to trash' : 'Restored');
    } catch (err) { S.toast(err.message, true); }
  };
  S.hooks.bulkTrash = async function (ids, flag) {
    try {
      let n = 0;
      ids.forEach(id => { const e = rawIndex.find(x => x.id === id); const m = st.media.find(x => x.id === id); if (e) { e.trashed = flag; n++; } if (m) m.trashed = flag; });
      if (!n) return;
      await G.putFile('outputs/index.json', b64(JSON.stringify(rawIndex, null, 1)), (flag ? 'trash ' : 'restore ') + n + ' videos');
      S.toast(flag ? n + ' moved to trash' : n + ' restored');
    } catch (err) { S.toast(err.message, true); }
  };
  S.hooks.purge = async function (ids) {
    try {
      let done = 0;
      for (const id of ids) {
        S.toast('Deleting ' + (done + 1) + ' of ' + ids.length + ' ...');
        await G.delTree('outputs/' + id);
        const k = rawIndex.findIndex(x => x.id === id); if (k >= 0) rawIndex.splice(k, 1);
        const m = st.media.findIndex(x => x.id === id); if (m >= 0) st.media.splice(m, 1);
        done++;
      }
      await G.putFile('outputs/index.json', b64(JSON.stringify(rawIndex, null, 1)), 'delete ' + done + ' videos');
      S.toast(done + ' deleted forever');
    } catch (err) { S.toast(err.message, true); }
  };
  S.hooks.onOpen = async function (m) {
    try {
      const t = m.report ? await G.readText(m.report) : null;
      const txt = t || (m.note || 'No report for this item.');
      S.setReport(txt);
      if (m.kind === 'report') { const pre = $('#vMedia pre'); if (pre) pre.textContent = txt; }
    } catch (e) { S.setReport(e.message); }
  };
  S.hooks.rawUrl = G.rawUrl;
  const when = t => { const d = Date.parse(t); if (!d) return ''; const m = Math.round((Date.now() - d) / 60000); return m < 1 ? 'just now' : m < 60 ? m + ' min ago' : m < 1440 ? Math.round(m / 60) + ' h ago' : new Date(d).toLocaleDateString(); };
  S.hooks.renderActivity = async function () {
    const live = $('#actLive'), runsBox = $('#actRuns'); if (!live) return;
    if (!G.ready()) { live.innerHTML = '<div class="status">Connect GitHub in Settings first.</div>'; runsBox.innerHTML = ''; return; }
    live.innerHTML = st.jobs.length ? st.jobs.map(j => `<div class="actcard ${j.failed ? 'fail' : ''}"><div class="act-main"><div class="act-title">${S.esc((j.prompt || j.mode || 'Job').slice(0, 120))}</div><div class="act-meta">${S.esc([j.mode, j.size].filter(Boolean).join(' · '))}</div></div><div class="jobbox">${S.jobHtml(j)}</div></div>`).join('') : '<div class="status">Nothing is running. Type what you want to create below.</div>';
    live.querySelectorAll('.jb').forEach(b => b.onclick = () => S.hooks.onJobAction(b.dataset.job, b.dataset.act));
    try {
      const runs = await G.runs(12);
      runsBox.innerHTML = runs.length ? runs.map(r => { const c = r.conclusion || r.status; const cls = c === 'success' ? 'ok' : (c === 'failure' || c === 'cancelled' || c === 'timed_out' || c === 'action_required' ? 'bad' : 'busy'); return `<a class="runrow" href="${S.esc(r.html_url)}" target="_blank" rel="noopener"><span class="dot ${cls}"></span><span class="rr-t">${S.esc(r.display_title || r.name || 'run')}</span><span class="rr-s">${S.esc(String(c).replace('_', ' '))}</span><span class="rr-w">${S.esc(when(r.created_at))}</span></a>`; }).join('') : '<div class="status">No runs yet.</div>';
    } catch (e) { runsBox.innerHTML = '<div class="status">' + S.esc(e.message) + '</div>'; }
  };
  S.hooks.viewerExtra = function (m, mk) {
    if (m.quality === 'draft' && m.long) {
      mk('Make final' + (String(m.formats || '').match(/wfp|xml|fcpxml/) ? ' + files' : ''), async () => {
        const ok = await S.tool('ai', m.prompt || m.title || '', '', 'Final quality', { duration: String(m.dur || 300), size: m.size || '16:9', formats: m.formats || 'none', sound: st.cfg.sound ? (st.cfg.soundStyle || 'premium') : 'none', quality: 'final', parent: m.id, project: m.project || 'default', review: 'false', resume: 'auto' }, { expectOutput: true, size: m.size, project: m.project || 'default' });
        if (ok) S.closeViewer();
      }, 'primary');
    } else if (m.quality === 'draft' && m.spec) {
      mk('Make final' + (String(m.formats || '').match(/wfp|xml|fcpxml/) ? ' + files' : ''), async () => {
        const ok = await S.tool('spec', m.prompt || m.title || '', m.spec, 'Final quality', { duration: String(m.dur || 10), size: m.size || '16:9', formats: m.formats || 'none', sound: st.cfg.sound ? (st.cfg.soundStyle || 'premium') : 'none', quality: 'final', parent: m.id, project: m.project || 'default' }, { expectOutput: true, size: m.size, project: m.project || 'default' });
        if (ok) S.closeViewer();
      }, 'primary');
    }
  };
  S.hooks.moveProject = async function (from, to) {
    try {
      let n = 0; rawIndex.forEach(e => { if (e.project === from) { e.project = to; n++; } });
      if (n) await G.putFile('outputs/index.json', b64(JSON.stringify(rawIndex, null, 1)), 'move videos to ' + to);
    } catch (e) { S.toast(e.message, true); }
  };
  S.reports = () => st.media.filter(m => m.kind === 'report' && !m.trashed);

  S.hooks.cloudCheck = async function () {
    const ok = await S.tool('checks', '', '', 'Testing your keys', {});
    if (ok) { const m = $('#cloudMsg'); if (m) { m.className = 'status busy'; m.textContent = 'Started - the result appears below in about a minute'; } }
  };
  S.hooks.showCloudChecks = async function () {
    const box = $('#cloudRes'); if (!box || !G.ready()) return;
    try {
      const t = await G.readText('outputs/checks.json'); if (!t) { box.innerHTML = ''; return; }
      const d = JSON.parse(t);
      box.innerHTML = '<div>Last test</div><div class="status">' + S.esc(new Date(d.date).toLocaleString()) + '</div>' + d.results.map(r => `<div>${S.esc(r.name)}</div><div class="status ${r.ok === true ? 'ok' : (r.ok === false ? 'bad' : '')}">${r.ok === true ? '✓' : (r.ok === false ? '✕' : '•')} ${S.esc(r.msg)}</div>`).join('');
    } catch (e) { box.innerHTML = ''; }
  };

  S.boot = (S.boot || []).concat([() => { if (G.ready()) S.hooks.refresh(true); }]);
  document.addEventListener('visibilitychange', () => { if (!document.hidden && G.ready()) S.hooks.refresh(true); });
})();
