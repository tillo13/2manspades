// Hoyt Axton jukebox. One <audio>, playlist from static/jukebox/playlist.json,
// audio streamed by /jukebox/audio/<album>/<n> (private bucket proxy).
// State survives page loads (each hand reloads) via localStorage; autoplay after a
// reload is attempted and, if the browser refuses, the bubble asks for one tap.
(function () {
    const KEY = 'hoyt_jukebox_v1';
    const $ = (id) => document.getElementById(id);
    let PL = null, audio = null, state = null, order = [], panelOpen = false, lastPanel = 'now';

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

    function play(ref, pos) {
        const t = trackOf(ref); if (!t) return;
        state.album = ref.album; state.n = ref.n; state.pos = pos || 0; state.playing = true; saveState();
        audio.src = `/jukebox/audio/${ref.album}/${ref.n}`;
        if (pos) audio.currentTime = pos;
        audio.play().then(() => setResumePrompt(false)).catch(() => setResumePrompt(true));
        render();
    }
    function toggle() {
        if (!state.album) return play(neighbor(+1));
        if (audio.paused) { state.playing = true; audio.play().catch(() => setResumePrompt(true)); }
        else { state.playing = false; audio.pause(); }
        saveState(); render();
    }
    function next() { play(neighbor(+1)); }
    function prev() { if (audio.currentTime > 4) { audio.currentTime = 0; return; } play(neighbor(-1)); }
    function playAlbum(id, n) { state.mode = 'album'; play({ album: id, n: n || 1 }); }
    function shuffleAll() { state.mode = 'shuffle'; state.seed = Date.now(); buildOrder(); play(order[0]); }

    // ---------- UI ----------
    function setResumePrompt(on) {
        const b = $('jbBubble'); if (!b) return; b.classList.toggle('needs-tap', on);
        $('jbBubbleLabel').textContent = on ? 'Tap to resume' : '';
    }
    function fmt(sec) { sec = Math.floor(sec || 0); return `${Math.floor(sec / 60)}:${String(sec % 60).padStart(2, '0')}`; }
    function render() {
        const cur = current(), a = cur && albumById(cur.album), t = cur && trackOf(cur);
        const playing = state.playing && audio && !audio.paused;
        const cover = a ? `/static/jukebox/covers/${a.id}.jpg` : '/static/jukebox/hoyt.jpg';
        $('jbBubbleImg').src = cover; $('jbBubble').classList.toggle('spinning', !!playing);
        $('jbCover').src = cover;
        $('jbTitle').textContent = t ? t.title : 'Hoyt Axton';
        $('jbAlbum').textContent = a ? `${a.title} · ${a.year}` : 'Tap play for some Hoyt';
        $('jbPlay').textContent = playing ? '❚❚' : '▶';
        $('jbPlay').setAttribute('aria-label', playing ? 'Pause' : 'Play');
        $('jbMode').textContent = state.mode === 'shuffle' ? 'Shuffle: all the records' : 'Playing this record';
        const toast = $('jbToast'); if (t && toast.dataset.last !== `${cur.album}/${cur.n}`) {
            toast.textContent = `${t.title} — ${a.title}`; toast.dataset.last = `${cur.album}/${cur.n}`;
            toast.classList.add('show'); clearTimeout(toast._t); toast._t = setTimeout(() => toast.classList.remove('show'), 5000);
        }
        document.querySelectorAll('#jbAlbums .jb-album').forEach(el => el.classList.toggle('current', !!a && el.dataset.id === a.id));
    }
    function renderAlbums(filter) {
        const q = (filter || '').trim().toLowerCase(), wrap = $('jbAlbums'); wrap.innerHTML = '';
        for (const a of PL.albums) {
            const hits = q ? a.tracks.filter(t => t.title.toLowerCase().includes(q)) : [];
            if (q && !hits.length && !a.title.toLowerCase().includes(q)) continue;
            const el = document.createElement('div'); el.className = 'jb-album'; el.dataset.id = a.id;
            el.innerHTML = `<img src="/static/jukebox/covers/${a.id}.jpg" alt="" loading="lazy"><div class="jb-album-title">${a.title}</div><div class="jb-album-year">${a.year}</div>`;
            el.onclick = () => { if (q && hits.length) playAlbum(a.id, hits[0].n); else playAlbum(a.id, 1); showPanel('now'); };
            if (q && hits.length) {
                const ul = document.createElement('div'); ul.className = 'jb-hits';
                for (const t of hits.slice(0, 6)) { const li = document.createElement('div'); li.textContent = t.title; li.onclick = (e) => { e.stopPropagation(); playAlbum(a.id, t.n); showPanel('now'); }; ul.appendChild(li); }
                el.appendChild(ul);
            }
            wrap.appendChild(el);
        }
        render();
    }
    function showPanel(which) {
        lastPanel = which;
        $('jbNow').hidden = which !== 'now'; $('jbBrowse').hidden = which !== 'browse';
        $('jbTabNow').classList.toggle('active', which === 'now'); $('jbTabBrowse').classList.toggle('active', which === 'browse');
    }
    function openPanel(open) {
        panelOpen = open; $('jbPanel').classList.toggle('open', open);
        if (open && typeof chatOpen !== 'undefined' && chatOpen && typeof toggleChat === 'function' && !window.matchMedia('(min-width: 1150px)').matches) toggleChat();
    }

    function wire() {
        audio = new Audio(); audio.preload = 'auto';
        audio.addEventListener('ended', next);
        audio.addEventListener('timeupdate', () => {
            state.pos = audio.currentTime; if (!audio.paused && (audio.currentTime | 0) % 5 === 0) saveState();
            $('jbTime').textContent = `${fmt(audio.currentTime)} / ${fmt(audio.duration)}`;
            const p = audio.duration ? audio.currentTime / audio.duration : 0; $('jbBar').style.width = `${p * 100}%`;
        });
        audio.addEventListener('error', () => { setTimeout(next, 800); });   // skip a bad object rather than stall
        audio.addEventListener('play', render); audio.addEventListener('pause', render);
        $('jbBubble').onclick = () => { if ($('jbBubble').classList.contains('needs-tap')) { toggle(); return; } if (!state.album) { toggle(); return; } openPanel(!panelOpen); };
        $('jbClose').onclick = () => openPanel(false);
        $('jbPlay').onclick = toggle; $('jbNext').onclick = next; $('jbPrev').onclick = prev;
        $('jbShuffle').onclick = shuffleAll;
        $('jbTabNow').onclick = () => showPanel('now'); $('jbTabBrowse').onclick = () => showPanel('browse');
        $('jbSearch').oninput = (e) => renderAlbums(e.target.value);
        $('jbBarWrap').onclick = (e) => { if (!audio.duration) return; const r = e.currentTarget.getBoundingClientRect(); audio.currentTime = ((e.clientX - r.left) / r.width) * audio.duration; };
        window.addEventListener('pagehide', saveState);
        renderAlbums(''); showPanel('now'); render();
        // resume across the reload that every new hand causes
        if (state.album && state.playing) play(current(), state.pos);
    }

    fetch('/static/jukebox/playlist.json').then(r => r.json()).then(pl => { PL = pl; loadState(); buildOrder(); wire(); })
        .catch(e => console.warn('[jukebox] playlist failed', e));
})();
