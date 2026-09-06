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
    }
    // Otherwise, button just shows name - do nothing on click
}

// DIFFICULTY SETTINGS
function openDifficultyModal() {
    fetch('/get_difficulty')
        .then(r => r.json())
        .then(data => {
            const current = data.difficulty || 'easy';
            document.querySelector(`input[name="difficulty"][value="${current}"]`).checked = true;
            // your completed-game record on each rung (logged-in players only)
            (data.levels || []).forEach(l => {
                const el = document.querySelector(`.difficulty-record[data-level="${l.level}"]`);
                if (el) el.textContent = (l.wins || l.losses) ? `You: ${l.wins}-${l.losses}` : '';
            });
            document.getElementById('difficultyModal').classList.add('show');
        });
}

function closeDifficultyModal(event) {
    if (!event || event.target.id === 'difficultyModal') {
        document.getElementById('difficultyModal').classList.remove('show');
    }
}

function setDifficulty(level) {
    fetch('/set_difficulty', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ difficulty: level })
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
});

// Prevent zoom on double-tap for mobile
let lastTouchEnd = 0;
document.addEventListener('touchend', function (event) {
    const now = (new Date()).getTime();
    if (now - lastTouchEnd <= 300) event.preventDefault();
    lastTouchEnd = now;
}, false);
