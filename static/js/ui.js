// Page chrome: login banner/button, difficulty modal, and the one delegated click
// listener that replaces every inline onclick= (buttons carry data-action="fn" and an
// optional data-arg). Loads after game.js and chat.js since it calls into both.
// =============================================================================
// LOGIN PROMPT BANNER
// =============================================================================

function dismissLoginPrompt() {
    const banner = document.getElementById('loginPromptBanner');
    if (banner) {
        banner.style.display = 'none';
        // Remember dismissal for this session
        sessionStorage.setItem('loginPromptDismissed', 'true');
    }
}

// Check if banner was already dismissed this session
document.addEventListener('DOMContentLoaded', function() {
    if (sessionStorage.getItem('loginPromptDismissed') === 'true') {
        const banner = document.getElementById('loginPromptBanner');
        if (banner) {
            banner.style.display = 'none';
        }
    }
});

// =============================================================================
// LOGIN/LOGOUT HANDLER
// =============================================================================

// ============================================================================= 
// LOGIN HANDLER - DISPLAY ONLY
// ============================================================================= 
function handleLoginClick() {
    const loginButton = document.getElementById('loginButton');
    const buttonText = loginButton.textContent.trim();

    // If button shows "Login", go to login page
    if (buttonText === 'Login') {
        // logging in from the Hoyt tab: come back with the sheet on Hoyt and the music started
        const sheet = document.getElementById('tableSheet');
        if (sheet && sheet.classList.contains('open') && sheet.dataset.tab === 'hoyt') {
            try { sessionStorage.setItem('hoyt_after_login', '1'); } catch (e) {}
        }
        window.location.href = '/login';
        return;
    }
    // Logged in: the name opens your panel — the same card as the gear, with your page + log out
    openDifficultyModal();
}

// DIFFICULTY SETTINGS
function openDifficultyModal() {
    fetch('/get_difficulty')
        .then(r => r.json())
        .then(data => {
            const current = data.difficulty || 'easy';
            RUNGS = data.levels || [];
            document.getElementById('difficultyRange').value = data.strength || 0;
            previewDifficulty(data.strength || 0);
            // your completed-game record on each rung (known players only)
            RUNGS.forEach(l => {
                const el = document.querySelector(`.difficulty-record[data-level="${l.level}"]`);
                if (el) el.textContent = (l.wins || l.losses) ? `You: ${l.wins}-${l.losses}` : '';
            });
            // who you are: name, your player page, log out (hidden when anonymous)
            const you = document.getElementById('difficultyYou');
            if (you) {
                you.hidden = !data.player;
                if (data.player) {
                    you.querySelector('.you-name').textContent = data.player.name;
                    you.querySelector('.you-page').href = '/player/' + encodeURIComponent(data.player.page);
                }
            }
            const pref = document.getElementById('difficultyPref');
            if (pref) { pref.hidden = !data.player; document.getElementById('jukeboxPop').checked = data.jukebox_pop !== false; }
            // the ratchet line: where she is on the 0-100 dial and whether it moves for you yet
            const note = document.getElementById('difficultyNote');
            const r = data.ratchet || {};
            if (note && data.strength !== undefined) {
                const where = `Marta is at ${data.strength}/100 (${current.charAt(0).toUpperCase() + current.slice(1)}).`;
                note.textContent = r.eligible
                    ? `${where} She climbs when you win and drops when you lose. Slide or tap a level to set her yourself; she moves on from there.`
                    : r.logged_in
                        ? `${where} After ${r.needed} games she'll climb when you win and drop when you lose (you're at ${r.games}).`
                        : `${where} Log in and she'll start climbing with your wins after ${r.needed} games.`;
            }
            document.getElementById('difficultyModal').classList.add('show');
        });
}

function closeDifficultyModal(event) {
    if (!event || event.target.id === 'difficultyModal') {
        document.getElementById('difficultyModal').classList.remove('show');
    }
}

// The slider is the truth (0-100); the four rungs are presets on it, and the rung whose
// floor the number has crossed is highlighted. RUNGS arrives with the gear payload.
let RUNGS = [];
function rungOf(strength) {
    return [...RUNGS].reverse().find(l => strength >= l.floor) || RUNGS[0];
}
function previewDifficulty(strength) {
    strength = parseInt(strength, 10) || 0;
    const rung = rungOf(strength);
    document.getElementById('difficultyStrength').textContent = strength;
    document.getElementById('difficultyRung').textContent = rung ? rung.level.charAt(0).toUpperCase() + rung.level.slice(1) : '';
    document.querySelectorAll('.difficulty-option').forEach(el =>
        el.classList.toggle('active', !!rung && el.dataset.arg === rung.level));
}
function pickRung(el) {
    const rung = RUNGS.find(l => l.level === el.dataset.arg);
    if (!rung) return;
    document.getElementById('difficultyRange').value = rung.preset;
    previewDifficulty(rung.preset);
    setDifficulty(rung.preset);
}
function setDifficulty(strength) {
    fetch('/set_difficulty', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ strength: parseInt(strength, 10) })
    }).then(() => {
        setTimeout(() => closeDifficultyModal(), 300);
    });
}

// =============================================================================
// DELEGATED HANDLERS
// =============================================================================
const ACTIONS = {
    startNewGame, nextHand, performAction, toggleComputerHand, sendMessage,   // the bubble is wired by jukebox.js
    openDifficultyModal, dismissLoginPrompt, handleLoginClick, confirmSelectedBid, cancelBidSelection,
    chooseNormalBidding, chooseBlindNil, chooseBlindBidding,
    selectBid: (el) => selectBid(parseInt(el.dataset.arg, 10)),
    makeBlindBid: (el) => makeBlindBid(parseInt(el.dataset.arg, 10)),
    open: (el) => window.open(el.dataset.arg, '_blank'),
    closeDifficultyModal: (el, e) => closeDifficultyModal(e),
    pickRung,
    stop: () => {},   // clicks inside the difficulty card must not reach the overlay's close
};
document.addEventListener('click', (e) => {
    const el = e.target.closest('[data-action]');
    if (!el) return;
    const fn = ACTIONS[el.dataset.action];
    if (fn) fn(el, e);
});
document.addEventListener('change', (e) => {
    const el = e.target.closest('[data-change="setDifficulty"]');
    if (el) setDifficulty(el.value);
    const pop = e.target.closest('[data-change="setJukeboxPop"]');
    if (pop) {
        document.body.dataset.jukeboxPop = pop.checked ? 'true' : 'false';
        fetch('/set_jukebox_pop', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ on: pop.checked }) });
    }
});
document.addEventListener('input', (e) => {
    const el = e.target.closest('[data-input="previewDifficulty"]');
    if (el) previewDifficulty(el.value);
});

// Prevent zoom on double-tap for mobile
let lastTouchEnd = 0;
document.addEventListener('touchend', function (event) {
    const now = (new Date()).getTime();
    if (now - lastTouchEnd <= 300) event.preventDefault();
    lastTouchEnd = now;
}, false);
