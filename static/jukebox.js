// Hoyt Axton jukebox. One <audio>, playlist from static/jukebox/playlist.json,
// audio streamed by /jukebox/audio/<album>/<n> (private bucket proxy).
// State survives page loads (each hand reloads) via localStorage; autoplay after a
// reload is attempted and, if the browser refuses, the bubble asks for one tap.
(function () {
    const KEY = 'hoyt_jukebox_v1';
    const $ = (id) => document.getElementById(id);
    let PL = null, audio = null, state = null, order = [], panelOpen = false, lastPanel = 'now';
    let playId = null, lastSource = 'shuffle', lastBeat = 0;
    const PILLS = ["What's this song about?", "When did Hoyt record this?", "Tell me about this record", "Play something like this"];
    const IDLE_PILLS = ["Tell me about Hoyt Axton", "What record should I start with?", "What's his best song?"];

    const norm = (s) => s.toLowerCase().replace(/\(.*?\)|\[.*?\]/g, '').replace(/[^a-z0-9]/g, '');
    const albumById = (id) => PL.albums.find(a => a.id === id);
    const trackOf = (ref) => { const a = albumById(ref.album); return a && a.tracks.find(t => t.n === ref.n); };

    function loadState() {
        try { state = JSON.parse(localStorage.getItem(KEY) || 'null'); } catch (e) { state = null; }
        if (!state || !albumById(state.album)) state = { mode: 'shuffle', album: null, n: 0, pos: 0, playing: false, seed: Date.now() };
    }
    function saveState() { try { localStorage.setItem(KEY, JSON.stringify(state)); } catch (e) {} }

    // Studio-album shuffle: albums flagged shuffle=true, deduped by song title (the
    // compilations repeat Greenback Dollar six times over). Seeded so the order is
    // stable across reloads and "previous" means the previous song.
    function buildOrder() {
        const seen = new Set(), pool = [];
        for (const a of PL.albums) if (a.shuffle) for (const t of a.tracks) {
            const k = norm(t.title); if (seen.has(k)) continue; seen.add(k); pool.push({ album: a.id, n: t.n });
        }
        let s = state.seed >>> 0;
        const rnd = () => { s = (s * 1664525 + 1013904223) >>> 0; return s / 4294967296; };
        for (let i = pool.length - 1; i > 0; i--) { const j = Math.floor(rnd() * (i + 1)); [pool[i], pool[j]] = [pool[j], pool[i]]; }
        order = pool;
    }

    function current() { return state.album ? { album: state.album, n: state.n } : null; }
    function indexInOrder(ref) { return order.findIndex(o => o.album === ref.album && o.n === ref.n); }

    function neighbor(dir) {
        const cur = current();
        if (state.mode === 'album' && cur) {
            const a = albumById(cur.album), i = a.tracks.findIndex(t => t.n === cur.n) + dir;
            if (i >= 0 && i < a.tracks.length) return { album: a.id, n: a.tracks[i].n };
            return { album: a.id, n: a.tracks[(i + a.tracks.length) % a.tracks.length].n };  // loop the record
        }
        let i = cur ? indexInOrder(cur) : -1;
        if (i < 0) i = 0; else i = (i + dir + order.length) % order.length;
        return order[i];
    }

    function uuid() { return (crypto.randomUUID ? crypto.randomUUID() : 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, c => { const r = Math.random() * 16 | 0; return (c === 'x' ? r : (r & 3 | 8)).toString(16); })); }
    function beat(completed, useBeacon) {
        if (!playId || !state.album) return;
        const a = albumById(state.album), t = trackOf(current()); if (!a || !t) return;
        const body = JSON.stringify({ play_id: playId, album_id: a.id, n: t.n, title: t.title, album_title: a.title, year: a.year,
            source: lastSource, seconds: audio ? audio.currentTime : 0, duration: audio && audio.duration ? audio.duration : null, completed: !!completed });
        if (useBeacon && navigator.sendBeacon) { navigator.sendBeacon('/jukebox/event', new Blob([body], { type: 'application/json' })); return; }
        fetch('/jukebox/event', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body, keepalive: true }).catch(() => {});
    }
    function play(ref, pos, source) {
        const t = trackOf(ref); if (!t) return;
        if (playId) beat(false);                       // close out the previous play
        playId = uuid(); lastSource = source || (pos ? 'resume' : (state.mode === 'album' ? 'album' : 'shuffle')); lastBeat = 0;
        state.album = ref.album; state.n = ref.n; state.pos = pos || 0; state.playing = true; saveState();
        audio.src = `/jukebox/audio/${ref.album}/${ref.n}`;
        if (pos) audio.currentTime = pos;
        audio.play().then(() => { setResumePrompt(false); beat(false); }).catch(() => setResumePrompt(true));
        render(); renderPills();
    }
    function toggle() {
        if (!state.album) return play(neighbor(+1));
        if (audio.paused) { state.playing = true; audio.play().then(() => setResumePrompt(false)).catch(() => setResumePrompt(true)); }
        else { state.playing = false; audio.pause(); }
        saveState(); render();
    }
    function next(fromEnded) { if (fromEnded === true) beat(true); play(neighbor(+1)); }
    function prev() { if (audio.currentTime > 4) { audio.currentTime = 0; return; } play(neighbor(-1)); }
    function playAlbum(id, n, source) { state.mode = 'album'; play({ album: id, n: n || 1 }, 0, source || 'album'); }
    function shuffleAll() { state.mode = 'shuffle'; state.seed = Date.now(); buildOrder(); play(order[0]); }

    // ---------- UI ----------
    function setResumePrompt(on) {
        const b = $('chatBubbleIcon'); if (!b) return; b.classList.toggle('needs-tap', on);
        $('jbBubbleLabel').textContent = on ? 'Tap to resume' : '';
        $('jbPlay').classList.toggle('needs-tap', on);
    }
    function fmt(sec) { sec = Math.floor(sec || 0); return `${Math.floor(sec / 60)}:${String(sec % 60).padStart(2, '0')}`; }
    function render() {
        const cur = current(), a = cur && albumById(cur.album), t = cur && trackOf(cur);
        const playing = state.playing && audio && !audio.paused;
        const cover = a ? `/static/jukebox/covers/${a.id}.jpg` : '/static/jukebox/hoyt.jpg';
        $('jbBubbleImg').src = cover; $('chatBubbleIcon').classList.toggle('spinning', !!playing);
        $('jbCover').src = cover;
        $('jbTitle').textContent = t ? t.title : 'Hoyt Axton';
        $('jbAlbum').textContent = a ? `${a.title} · ${a.year}` : 'Tap play for some Hoyt';
        $('jbPlay').textContent = playing ? '❚❚' : '▶';
        $('jbPlay').setAttribute('aria-label', playing ? 'Pause' : 'Play');
        $('jbMode').textContent = state.mode === 'shuffle' ? 'All the records, shuffled' : 'Playing this record';
        const toast = $('jbToast'); if (t && toast.dataset.last !== `${cur.album}/${cur.n}`) {
            toast.textContent = `${t.title} — ${a.title}`; toast.dataset.last = `${cur.album}/${cur.n}`;
            toast.classList.add('show'); clearTimeout(toast._t); toast._t = setTimeout(() => toast.classList.remove('show'), 5000);
        }
        const mini = $('jbMini'); if (mini) {
            mini.hidden = !t;
            if (t) { $('jbMiniImg').src = cover; $('jbMiniTitle').textContent = t.title; $('jbMiniAlbum').textContent = `${a.title} · ${a.year}`; $('jbMiniPlay').textContent = playing ? '❚❚' : '▶'; }
        }
        document.querySelectorAll('#jbAlbums .jb-album').forEach(el => el.classList.toggle('current', el.dataset.id === '__all__' ? (state.mode === 'shuffle' && !!a) : (!!a && state.mode === 'album' && el.dataset.id === a.id)));
    }
    function renderAlbums(filter) {
        const q = (filter || '').trim().toLowerCase(), wrap = $('jbAlbums'); wrap.innerHTML = '';
        if (!q) {
            const all = document.createElement('div'); all.className = 'jb-album jb-album-all' + (state.mode === 'shuffle' ? ' current' : ''); all.dataset.id = '__all__';
            all.innerHTML = `<div class="jb-all-tile">⤮</div><div class="jb-album-title">All the records</div><div class="jb-album-year">shuffle</div>`;
            all.onclick = () => { shuffleAll(); showPanel('now'); }; wrap.appendChild(all);
        }
        for (const a of PL.albums) {
            const hits = q ? a.tracks.filter(t => t.title.toLowerCase().includes(q)) : [];
            if (q && !hits.length && !a.title.toLowerCase().includes(q)) continue;
            const el = document.createElement('div'); el.className = 'jb-album'; el.dataset.id = a.id;
            el.innerHTML = `<img src="/static/jukebox/covers/${a.id}.jpg" alt="" loading="lazy"><div class="jb-album-title">${a.title}</div><div class="jb-album-year">${a.year}</div>`;
            el.onclick = () => { if (q && hits.length) playAlbum(a.id, hits[0].n, 'search'); else playAlbum(a.id, 1); showPanel('now'); };
            if (q && hits.length) {
                const ul = document.createElement('div'); ul.className = 'jb-hits';
                for (const t of hits.slice(0, 6)) { const li = document.createElement('div'); li.textContent = t.title; li.onclick = (e) => { e.stopPropagation(); playAlbum(a.id, t.n, 'search'); showPanel('now'); }; ul.appendChild(li); }
                el.appendChild(ul);
            }
            wrap.appendChild(el);
        }
        render();
    }
    function renderPills() {
        const wrap = $('chatPills'); if (!wrap) return;
        const np = nowPlaying();
        const key = np ? np.album + '/' + np.n : '__idle__';
        if (wrap.dataset.for === key) { wrap.hidden = (wrap.dataset.asked === key); return; }   // asked already: stay out of the way
        wrap.hidden = false; wrap.dataset.for = key; wrap.innerHTML = '';
        for (const q of (np ? PILLS : IDLE_PILLS)) { const b = document.createElement('button'); b.type = 'button'; b.className = 'chat-pill'; b.textContent = q;
            b.onclick = () => { const i = $('chatInput'); if (!i) return; i.value = q; wrap.hidden = true; wrap.dataset.asked = key; if (typeof sendMessage === 'function') sendMessage(); }; wrap.appendChild(b); }
    }
    let statsAt = 0;
    function loadStats(force) {
        if (!$('jbStats') || (!force && Date.now() - statsAt < 120000)) return;
        statsAt = Date.now();
        fetch('/jukebox/stats').then(r => r.json()).then(s => {
            if (!s || !s.plays) { $('jbStats').hidden = true; return; }
            $('jbStatPlays').innerHTML = `<b>${s.plays}</b>plays`; $('jbStatHours').innerHTML = `<b>${s.hours}</b>hours`; $('jbStatSongs').innerHTML = `<b>${s.songs}</b>songs`;
            const top = (s.top_songs || [])[0], alb = (s.top_albums || [])[0];
            $('jbStatTop').innerHTML = (top ? `Most played: <b>${top.title}</b> (${top.plays})` : '') + (alb ? `<br>Favorite record: <b>${alb.album}</b>` : '');
            $('jbStats').hidden = false;
        }).catch(() => {});
    }
    function nowPlaying() {
        const cur = current(); if (!cur) return null;   // paused still counts: the song on the turntable is the song he is asking about
        const a = albumById(cur.album), t = trackOf(cur); if (!a || !t) return null;
        return { title: t.title, album: a.title, year: a.year, n: t.n };
    }
    window.HoytJukebox = { nowPlaying, next: () => next(), prev, toggle };

    function showPanel(which) {
        lastPanel = which;
        $('jbNow').hidden = which !== 'now'; $('jbBrowse').hidden = which !== 'browse';
        $('jbTabBrowse').hidden = which === 'browse'; $('jbTabNow').hidden = which !== 'browse';
    }
    // ---------- the table sheet (Marta + Hoyt) ----------
    const isDesktop = () => window.matchMedia('(min-width: 1150px)').matches;
    function sheetOpen() { return $('tableSheet').classList.contains('open'); }
    function showTab(tab) {
        const sh = $('tableSheet'); sh.dataset.tab = tab;
        $('tsTabMarta').classList.toggle('active', tab === 'marta'); $('tsTabHoyt').classList.toggle('active', tab === 'hoyt');
        if (typeof onChatVisibility === 'function') onChatVisibility(sheetOpen() && tab === 'marta');
        if (tab === 'hoyt') { showPanel(lastPanel); loadStats(false); }
    }
    function openSheet(tab) {
        $('tableSheet').classList.add('open'); document.body.classList.add('sheet-open'); panelOpen = true;
        showTab(tab || $('tableSheet').dataset.tab || 'marta');
    }
    function closeSheet() {
        $('tableSheet').classList.remove('open'); document.body.classList.remove('sheet-open'); panelOpen = false;
        if (typeof onChatVisibility === 'function') onChatVisibility(false);
    }
    function openPanel(open) { if (open) openSheet('hoyt'); else closeSheet(); }
    window.TableSheet = { open: openSheet, close: closeSheet, tab: showTab,
        toggle: (tab) => { if (sheetOpen() && $('tableSheet').dataset.tab === tab) closeSheet(); else openSheet(tab); } };

    function wire() {
        audio = new Audio(); audio.preload = 'auto';
        audio.addEventListener('ended', () => next(true));
        audio.addEventListener('timeupdate', () => {
            state.pos = audio.currentTime; if (!audio.paused && (audio.currentTime | 0) % 5 === 0) saveState();
            if (!audio.paused && audio.currentTime - lastBeat >= 20) { lastBeat = audio.currentTime; beat(false); }
            $('jbTime').textContent = `${fmt(audio.currentTime)} / ${fmt(audio.duration)}`;
            const p = audio.duration ? audio.currentTime / audio.duration : 0; $('jbBar').style.width = `${p * 100}%`;
        });
        audio.addEventListener('error', () => { setTimeout(next, 800); });   // skip a bad object rather than stall
        audio.addEventListener('play', () => { render(); renderPills(); }); audio.addEventListener('pause', () => { render(); renderPills(); });
        // the bubble ALWAYS opens the panel (never a dead end); on a blocked resume it also
        // retries play inside this tap gesture, which is what Safari needs. An empty player
        // starts the shuffle and opens the panel so he sees what happened.
        $('chatBubbleIcon').onclick = () => {
            const b = $('chatBubbleIcon');
            if (b.classList.contains('needs-tap')) { state.playing = true; audio.play().then(() => setResumePrompt(false)).catch(() => {}); openSheet('hoyt'); return; }
            if (sheetOpen()) { closeSheet(); return; }
            // unread Marta reply wins; otherwise whichever tab was last used
            const unread = (typeof unreadMessages !== 'undefined' && unreadMessages > 0);
            openSheet(unread ? 'marta' : ($('tableSheet').dataset.tab || 'marta'));
        };
        $('tsClose').onclick = closeSheet; $('tsTabMarta').onclick = () => showTab('marta'); $('tsTabHoyt').onclick = () => showTab('hoyt');
        $('jbPlay').onclick = toggle; $('jbNext').onclick = next; $('jbPrev').onclick = prev;
        if ($('jbMini')) {
            $('jbMiniPlay').onclick = toggle; $('jbMiniNext').onclick = () => next();
            const toJukebox = () => { showPanel('now'); openSheet('hoyt'); };
            $('jbMiniImg').onclick = toJukebox; $('jbMiniText').onclick = toJukebox;
        }
        $('jbTabNow').onclick = () => showPanel('now');
        $('jbTabBrowse').onclick = () => { $('jbSearch').value = ''; renderAlbums(''); showPanel('browse'); };
        $('jbSearch').oninput = (e) => { renderAlbums(e.target.value); showPanel('browse'); };   // typing IS the search
        $('jbBarWrap').onclick = (e) => { if (!audio.duration) return; const r = e.currentTarget.getBoundingClientRect(); audio.currentTime = ((e.clientX - r.left) / r.width) * audio.duration; };
        window.addEventListener('pagehide', () => { saveState(); beat(false, true); });
        renderAlbums(''); showPanel('now'); render(); renderPills(); loadStats(true);

        // resume across the reload that every new hand causes
        if (state.album && state.playing) play(current(), state.pos);
    }

    fetch('/static/jukebox/playlist.json').then(r => r.json()).then(pl => { PL = pl; loadState(); buildOrder(); wire(); })
        .catch(e => console.warn('[jukebox] playlist failed', e));
})();
