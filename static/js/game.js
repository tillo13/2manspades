// Game state, polling, rendering and the play/bid/discard calls. Loads after chat.js
// (shares chatInitialized) and before ui.js (which wires the buttons to these functions).
let gameState = null;
let selectedCard = null;
let trickDisplayTimeout = null;
let lastHandNumber = null;

// Bidding confirmation variables
let selectedBid = null;
let confirmingBid = false;

// Scroll preservation for trick history
let trickHistoryScrollPosition = 0;



// =============================================================================
// MAIN GAME FUNCTIONS
// =============================================================================

async function loadGameState() {
    try {
        const response = await fetch('/state');
        gameState = await response.json();
        updateUI();
    } catch (error) {
        console.error('Error loading game state:', error);
        showMessage('Error loading game', 'error');
    }
}

function updateUI() {
    if (!gameState) return;

    preserveTrickHistoryScroll();
    updateFloatingScores();
    updatePlayAreaVisibility();
    updateHandCount();
    updateGameOverState();
    updatePhaseVisibility();
    updateMessages();
    updatePlayArea();
    updatePlayerHand();
    updateComputerHand();
    updateActionButtons();
    updateBidButtons();
    updateComputerHandToggle();
    updateHandOver();
    handleTrickCompletion();

    // Track hand changes but don't auto-call Claude
    lastHandNumber = gameState.hand_number;
    restoreTrickHistoryScroll();
}

// =============================================================================
// UI UPDATE FUNCTIONS
// =============================================================================

function updateFloatingScores() {
    const gameScoreEl = document.getElementById('floatingGameScore');
    if (gameScoreEl) {
        document.getElementById('floatingPlayerScore').textContent = gameState.player_score;
        document.getElementById('floatingComputerScore').textContent = gameState.computer_score;
        document.getElementById('floatingHandNumber').textContent = gameState.hand_number;

        const playerParityText = `(${gameState.player_parity.toUpperCase()})`;
        const computerParityText = `(${gameState.computer_parity.toUpperCase()})`;
        document.getElementById('floatingPlayerParity').textContent = playerParityText;
        document.getElementById('floatingComputerParity').textContent = computerParityText;
    }

    const handScoreEl = document.getElementById('floatingHandScore');
    if (handScoreEl) {
        // Player side
        document.getElementById('floatingPlayerTricks').textContent = gameState.player_tricks;
        const playerBid = gameState.player_bid !== null ? gameState.player_bid : '-';
        const playerBlindText = gameState.blind_bid === gameState.player_bid ? 'B' : '';
        document.getElementById('floatingPlayerBid').textContent = `${playerBid}${playerBlindText}`;

        const playerBidEl = document.getElementById('floatingPlayerBid');
        if (playerBlindText) {
            playerBidEl.style.color = '#dc3545';
            playerBidEl.style.fontWeight = 'bold';
        } else {
            playerBidEl.style.color = '#333';
            playerBidEl.style.fontWeight = '600';
        }

        document.getElementById('floatingPlayerBags').textContent = gameState.player_bags || 0;

        // Computer side
        document.getElementById('floatingComputerTricks').textContent = gameState.computer_tricks;
        const computerBid = gameState.computer_bid !== null ? gameState.computer_bid : '-';
        const computerBlindText = gameState.computer_blind_bid === gameState.computer_bid ? 'B' : '';
        document.getElementById('floatingComputerBid').textContent = `${computerBid}${computerBlindText}`;

        const computerBidEl = document.getElementById('floatingComputerBid');
        const martaWentFirst = gameState.phase === 'bidding' &&
            gameState.computer_bid !== null &&
            gameState.player_bid === null;

        if (computerBlindText) {
            computerBidEl.style.color = '#dc3545';
            computerBidEl.style.fontWeight = 'bold';
            computerBidEl.style.backgroundColor = '';
            computerBidEl.style.border = '';
            computerBidEl.style.borderRadius = '';
            computerBidEl.style.padding = '';
        } else if (martaWentFirst) {
            computerBidEl.style.color = '#1976d2';
            computerBidEl.style.fontWeight = 'bold';
            computerBidEl.style.backgroundColor = '#e3f2fd';
            computerBidEl.style.border = '2px solid #1976d2';
            computerBidEl.style.borderRadius = '4px';
            computerBidEl.style.padding = '2px 4px';
        } else {
            computerBidEl.style.color = '#333';
            computerBidEl.style.fontWeight = '600';
            computerBidEl.style.backgroundColor = '';
            computerBidEl.style.border = '';
            computerBidEl.style.borderRadius = '';
            computerBidEl.style.padding = '';
        }

        document.getElementById('floatingComputerBags').textContent = gameState.computer_bags || 0;
        document.getElementById('floatingSpadesStatus').textContent = gameState.spades_broken ? 'Broken' : 'Not Broken';
    }
}

function updatePlayAreaVisibility() {
    const playArea = document.getElementById('playArea');
    if (!playArea) return;

    // Hide play area during these phases to save screen space
    const hiddenPhases = ['discard', 'bidding', 'blind_decision', 'blind_bidding'];

    if (hiddenPhases.includes(gameState.phase)) {
        playArea.classList.add('hidden-for-phase');
    } else {
        playArea.classList.remove('hidden-for-phase');
    }
}

function updateHandCount() {
    const playerHandCountEl = document.getElementById('playerHandCount');
    if (playerHandCountEl) {
        playerHandCountEl.textContent = `(${gameState.player_hand.length} cards)`;
    }
}

function updateGameOverState() {
    const gameOverEl = document.getElementById('gameOver');
    gameOverEl.hidden = !gameState.game_over;
    if (!gameState.game_over) return;
    hideInteractiveSections();
    renderGameOver();
}

// The final screen, drawn from data: who won and the score, the ratchet as a bar (before
// and after marks on the 0-100 dial), a four-number tally from the per-hand log, and the
// finished game's page for the full breakdown. The message sentence is the record the
// stats parse; it isn't shown here a second time.
function renderGameOver() {
    const won = gameState.winner === 'player';
    const result = document.getElementById('goResult');
    result.textContent = won ? 'You win' : 'Marta wins';
    result.className = 'go-result ' + (won ? 'won' : 'lost');
    const hands = gameState.hand_number;
    const reason = /mercy/i.test(gameState.message) ? ' · mercy rule'
        : /blind nil/i.test(gameState.message) ? ' · blind nil' : '';
    document.getElementById('goScore').textContent =
        `${gameState.player_score} to ${gameState.computer_score} · ${hands} hand${hands === 1 ? '' : 's'}${reason}`;

    const r = gameState.ratchet;
    const rBox = document.getElementById('goRatchet');
    rBox.hidden = !r;
    if (r) {
        const cap = w => w.charAt(0).toUpperCase() + w.slice(1);
        document.getElementById('goRatchetText').textContent = r.after === r.before
            ? `Marta stays at ${r.after} (${cap(r.level)})`
            : `Marta ${r.after > r.before ? 'climbs' : 'drops'}: ${cap(r.from_level)} ${r.before} → ${cap(r.level)} ${r.after}`;
        const lo = Math.min(r.before, r.after), hi = Math.max(r.before, r.after);
        const fill = document.getElementById('goBarFill');
        fill.style.left = lo + '%';
        fill.style.width = (hi - lo) + '%';
        fill.className = 'go-bar-fill ' + (r.after >= r.before ? 'up' : 'down');
        document.getElementById('goBarBefore').style.left = r.before + '%';
        document.getElementById('goBarAfter').style.left = r.after + '%';
        // the math, so the move is never a mystery: 5 a game, +1 per 25 points of margin, capped at 15
        const m = Math.abs(r.margin || 0), extra = Math.min(10, Math.floor(m / 25)), step = 5 + extra;
        const clamped = Math.abs(r.after - r.before) < step;
        document.getElementById('goRatchetWhy').textContent =
            `${r.won ? 'Won' : 'Lost'} by ${m}: ${r.won ? '+' : '−'}${step} (5 for the game` +
            (extra ? `, ${extra} more for the margin, 1 per 25 points` : ', under 25 points of margin so nothing extra') +
            `)${clamped ? `, held at the ${r.after >= r.before ? 'top' : 'bottom'} of the dial` : ''}. ` +
            `Applies because you have ${r.games} games on record (25 needed).`;
    }

    const log = gameState.hand_log || [];
    const bid = log.filter(h => h.player_bid > 0);
    const made = bid.filter(h => h.player_tricks >= h.player_bid).length;
    const bags = bid.reduce((n, h) => n + Math.max(0, h.player_tricks - h.player_bid), 0);
    const blinds = log.filter(h => h.player_blind);
    const blindsMade = blinds.filter(h => h.player_tricks >= h.player_bid).length;
    const specials = log.length ? log[log.length - 1].player_specials : 0;
    const tiles = [
        ['Bids made', `${made}/${bid.length}`],
        ['Bags taken', bags],
        ['Blinds', blinds.length ? `${blindsMade}/${blinds.length}` : '–'],
        ['Bags cut', specials],   // total the 7♦ / 10♣ took off, this game
    ];
    document.getElementById('goTally').innerHTML = tiles.map(([k, v]) =>
        `<div class="go-tile"><div class="go-tile-v">${v}</div><div class="go-tile-k">${k}</div></div>`).join('');

    const link = document.getElementById('goDetail');
    link.hidden = !gameState.game_id;
    if (gameState.game_id) link.href = '/game/' + gameState.game_id;

    // every hand of the game, one row each: bid/tricks per seat (B = blind, red = set), the
    // middle with who took it, bags after the hand, running score
    const bt = (b, t, blind) => `${blind ? 'B' : ''}${b}<span class="go-slash">/</span>${t}`;
    const red = txt => (txt || '?').replace(/(\S+[♥♦])/g, '<span class="heart">$1</span>');
    const mid = m => !m ? '' : `${red(m.player)} · ${red(m.computer)}` +
        (m.winner ? ` <span class="go-mid-w">${m.winner === 'player' ? 'you' : 'Marta'}</span>` : '');
    document.getElementById('goHands').innerHTML = `<table class="go-hands-table">
        <thead><tr><th>Hand</th><th>You</th><th>Marta</th><th>Middle</th><th>Bags</th><th>Score</th></tr></thead><tbody>` +
        log.map(h => `<tr>
            <td>${h.hand}</td>
            <td class="${h.player_bid > 0 && h.player_tricks < h.player_bid ? 'set' : ''}">${bt(h.player_bid, h.player_tricks, h.player_blind)}</td>
            <td class="${h.computer_bid > 0 && h.computer_tricks < h.computer_bid ? 'set' : ''}">${bt(h.computer_bid, h.computer_tricks, h.computer_blind)}</td>
            <td class="go-mid">${mid(h.middle)}</td>
            <td>${h.player_bags ?? ''} · ${h.computer_bags ?? ''}</td>
            <td>${h.player_score} · ${h.computer_score}</td>
        </tr>`).join('') + `</tbody></table>`;

    renderHistory();
}

// Full history for the person at the table: record, streaks, margins, per-rung. Fetched once
// per game over (the server answers null for strangers, and the block stays hidden).
let historyFor = null;
function renderHistory() {
    const box = document.getElementById('goHistory');
    if (historyFor === gameState.game_id) return;
    historyFor = gameState.game_id;
    fetch('/my_record').then(r => r.json()).then(rec => {
        box.hidden = !rec;
        if (!rec) return;
        const tile = (v, k) => `<div class="go-tile"><div class="go-tile-v">${v}</div><div class="go-tile-k">${k}</div></div>`;
        const rungs = ['easy', 'medium', 'hard', 'ruthless'].filter(l => rec.rungs[l])
            .map(l => `<span class="go-rung"><b>${l[0].toUpperCase() + l.slice(1)}</b> ${rec.rungs[l].wins}-${rec.rungs[l].losses}</span>`).join('');
        box.innerHTML = `<div class="go-history-title">Your record${rec.since ? ` <small>since ${rec.since}</small>` : ''}</div>
            <div class="go-tally">
                ${tile(`${rec.wins}-${rec.losses}`, `${rec.win_pct}% of ${rec.games}`)}
                ${tile(`${rec.streak}${rec.streak_type === 'win' ? 'W' : 'L'}`, 'Current streak')}
                ${tile(rec.best_win_streak, 'Best win streak')}
                ${tile((rec.avg_margin >= 0 ? '+' : '') + rec.avg_margin, 'Avg margin')}
            </div>
            <div class="go-tally">
                ${tile('+' + rec.biggest_win, 'Biggest win')}
                ${tile(rec.worst_loss, 'Worst loss')}
                ${tile(rec.avg_hands, 'Hands per game')}
                ${tile(rec.games, 'Games')}
            </div>
            <div class="go-rungs">${rungs}</div>`;
    }).catch(() => { box.hidden = true; });
}

function hideInteractiveSections() {
    document.getElementById('playArea').classList.add('hidden-for-phase');   // no trick to show
    document.getElementById('biddingSection').style.display = 'none';
    const blindDecisionSection = document.getElementById('blindDecisionSection');
    if (blindDecisionSection) blindDecisionSection.style.display = 'none';
    document.getElementById('discardBlindBiddingSection').style.display = 'none';
    document.getElementById('playerHandSection').style.display = 'none';
    document.getElementById('computerHandSection').style.display = 'none';
}

function updatePhaseVisibility() {
    if (gameState.game_over) return;

    const biddingSection = document.getElementById('biddingSection');
    const blindDecisionSection = document.getElementById('blindDecisionSection');
    const discardBlindSection = document.getElementById('discardBlindBiddingSection');

    // Hide all sections first
    biddingSection.style.display = 'none';
    if (blindDecisionSection) blindDecisionSection.style.display = 'none';
    discardBlindSection.style.display = 'none';

    if (gameState.phase === 'blind_decision') {
        if (blindDecisionSection) blindDecisionSection.style.display = 'block';
    } else if (gameState.phase === 'blind_bidding') {
        discardBlindSection.style.display = 'block';
    } else if (gameState.phase === 'bidding') {
        biddingSection.style.display = 'block';
        if (!biddingSection.classList.contains('active')) {
            biddingSection.classList.add('active');
            resetBiddingState();
        }
    } else {
        biddingSection.classList.remove('active');
    }
}

function updateMessages() {
    // At game over and hand over a card carries everything; the status line would only repeat it
    const carded = gameState.game_over || (gameState.hand_over && gameState.hand_results);
    document.getElementById('message').hidden = !!carded;
    if (carded) return;

    let messageToShow = gameState.message;

    showMessage(messageToShow, messageToShow.includes('WIN') || messageToShow.includes('BLIND NIL SUCCESS') ? 'success' : '');
}

function updatePlayArea() {
    const trickDisplay = document.getElementById('trickDisplay');

    if (gameState.current_trick.length === 0) {
        trickDisplay.innerHTML = '<div style="color: #999; font-size: 14px;">Waiting for play...</div>';
    } else {
        let html = '<div class="trick-container">';

        const playerCard = gameState.current_trick.find(play => play.player === 'player');
        const computerCard = gameState.current_trick.find(play => play.player === 'computer');

        // Always show side by side - You left, Marta right
        if (playerCard) {
            const card = playerCard.card;
            const suitClass = getSuitClass(card.suit);
            html += `
                <div class="trick-card ${suitClass}">
                    <div class="player-name">You</div>
                    <div class="card-content">${card.rank}${card.suit}</div>
                </div>
            `;
        } else {
            html += '<div class="trick-card-placeholder"><div style="font-size: 10px; color: #999;">You</div></div>';
        }

        if (computerCard) {
            const card = computerCard.card;
            const suitClass = getSuitClass(card.suit);
            html += `
                <div class="trick-card ${suitClass}">
                    <div class="player-name">Marta</div>
                    <div class="card-content">${card.rank}${card.suit}</div>
                </div>
            `;
        } else {
            html += '<div class="trick-card-placeholder"><div style="font-size: 10px; color: #999;">Marta</div></div>';
        }

        html += '</div>';
        trickDisplay.innerHTML = html;
    }
}

function updatePlayerHand() {
    const handEl = document.getElementById('playerHand');
    const playerHandSection = document.getElementById('playerHandSection');

    // Hide entire hand section when hand is complete
    if (gameState.hand_over && gameState.player_hand.length === 0) {
        playerHandSection.style.display = 'none';
        return;
    } else {
        playerHandSection.style.display = 'block';
    }

    handEl.innerHTML = '';

    // Hide cards during blind decision or blind bidding phases
    if (gameState.phase === 'blind_decision' || gameState.phase === 'blind_bidding') {
        handEl.innerHTML = '<div style="text-align: center; color: #666; font-style: italic; padding: 20px; border: 2px dashed #ccc; border-radius: 8px;">Cards hidden during blind bidding decision!</div>';
        return;
    }

    gameState.player_hand.forEach((card, index) => {
        const cardEl = document.createElement('div');
        cardEl.className = `card ${getSuitClass(card.suit)}`;
        cardEl.textContent = `${card.rank}${card.suit}`;

        cardEl.onclick = () => selectCard(index);
        cardEl.ontouchstart = (e) => {
            e.preventDefault();
            selectCard(index);
        };

        if (selectedCard === index) {
            cardEl.classList.add('selected');
        }

        if (!canPlayCard(card, index)) {
            cardEl.classList.add('disabled');
        }

        handEl.appendChild(cardEl);
    });
}

function updateComputerHand() {
    const handEl = document.getElementById('computerHand');
    const computerHandSection = handEl.closest('.hand-section');

    // Hide entire computer hand section if debug mode is off
    if (!gameState.debug_mode) {
        computerHandSection.style.display = 'none';
        return;
    }

    computerHandSection.style.display = 'block';
    handEl.innerHTML = '';

    // Only show cards if debug mode is on AND show_computer_hand is true
    if (gameState.debug_mode && gameState.show_computer_hand && gameState.computer_hand) {
        gameState.computer_hand.forEach((card, index) => {
            const cardEl = document.createElement('div');
            cardEl.className = `card ${getSuitClass(card.suit)}`;
            cardEl.textContent = `${card.rank}${card.suit}`;
            cardEl.style.cursor = 'default';
            handEl.appendChild(cardEl);
        });
    } else {
        const cardCount = gameState.computer_hand_count || 0;
        for (let i = 0; i < cardCount; i++) {
            const cardEl = document.createElement('div');
            cardEl.className = 'card';
            cardEl.style.background = '#666';
            cardEl.style.color = '#999';
            cardEl.textContent = '?';
            cardEl.style.cursor = 'default';
            handEl.appendChild(cardEl);
        }
    }
}

function updateActionButtons() {
    const actionButton = document.getElementById('actionButton');

    if (gameState.hand_over && !gameState.game_over) {
        actionButton.style.display = 'none';
    } else {
        if (gameState.phase === 'discard') {
            actionButton.textContent = 'Discard Selected';
            actionButton.onclick = discardCard;
            actionButton.style.display = 'inline-block';
        } else if (gameState.phase === 'playing') {
            actionButton.textContent = 'Play Selected';
            actionButton.onclick = playCard;
            actionButton.style.display = 'inline-block';
        } else {
            actionButton.style.display = 'none';
        }
    }

    if (selectedCard === null && actionButton.style.display !== 'none') {
        actionButton.disabled = true;
        actionButton.textContent = gameState.phase === 'discard' ? 'Select Card to Discard' : 'Select Card to Play';
    } else if (actionButton.style.display !== 'none') {
        actionButton.disabled = false;
        actionButton.textContent = gameState.phase === 'discard' ? 'Discard Selected' : 'Play Selected';
    }
}

function updateBidButtons() {
    if (gameState.phase !== 'bidding') return;

    const bidButtons = document.querySelectorAll('.bid-btn');
    const confirmButton = document.getElementById('confirmBidButton');
    const cancelButton = document.getElementById('cancelBidButton');

    if (confirmingBid && selectedBid !== null) {
        bidButtons.forEach(btn => {
            const bidValue = parseInt(btn.getAttribute('data-bid'));
            if (bidValue === selectedBid) {
                btn.classList.add('selected');
                btn.style.backgroundColor = '#28a745';
                btn.style.color = 'white';
                btn.style.border = '2px solid #1e7e34';
            } else {
                btn.classList.remove('selected');
                btn.style.backgroundColor = '';
                btn.style.color = '';
                btn.style.border = '';
                btn.style.opacity = '0.6';
            }
        });

        if (confirmButton) confirmButton.style.display = 'inline-block';
        if (cancelButton) cancelButton.style.display = 'inline-block';
    } else {
        bidButtons.forEach(btn => {
            btn.classList.remove('selected');
            btn.style.backgroundColor = '';
            btn.style.color = '';
            btn.style.border = '';
            btn.style.opacity = '';
        });

        if (confirmButton) confirmButton.style.display = 'none';
        if (cancelButton) cancelButton.style.display = 'none';
    }
}

function updateComputerHandToggle() {
    const toggleButton = document.getElementById('toggleComputerHand');
    if (toggleButton) {
        if (gameState.debug_mode) {
            toggleButton.style.display = 'inline-block';
            toggleButton.textContent = gameState.show_computer_hand ? 'Hide Cards' : 'Show Cards';
            toggleButton.style.background = '#6c757d';
        } else {
            toggleButton.style.display = 'none';
        }
    }
}

// Hand over: the summary sits where the board was, built from the per-hand log (bids,
// tricks, scores, bags) with the scoring record's notable lines (nil, blind, bag penalty or
// bonus, special cards) underneath. Next Hand is the card's primary action.
function updateHandOver() {
    const card = document.getElementById('handOver');
    const show = gameState.hand_over && gameState.hand_results;
    card.hidden = !show;
    if (!show) return;
    document.getElementById('playArea').classList.add('hidden-for-phase');   // no trick to show
    document.getElementById('nextHandButton').hidden = !!gameState.game_over;   // at game over the result card has the actions

    const r = gameState.hand_results;
    const log = gameState.hand_log || [];
    const h = log[log.length - 1] || {};
    const prev = log[log.length - 2] || { player_score: 0, computer_score: 0, player_bags: 0, computer_bags: 0 };

    document.getElementById('hoTitle').textContent = `Hand ${r.hand_number}`;
    const took = (bid, tricks, blind) => {
        const b = blind ? `blind ${bid}` : bid === 0 ? 'nil' : bid;
        const over = tricks - bid;
        if (bid === 0) return tricks === 0 ? 'made nil' : `took ${tricks} on nil`;
        if (over < 0) return `took ${tricks} on ${b}, set`;
        return `made ${b}${over > 0 ? ` +${over} bag${over === 1 ? '' : 's'}` : ''}`;
    };
    document.getElementById('hoLine').textContent =
        `You ${took(h.player_bid, h.player_tricks, h.player_blind)} · Marta ${took(h.computer_bid, h.computer_tricks, h.computer_blind)}`;

    const delta = n => (n >= 0 ? '+' : '') + n;
    const scoreCell = (id, score, was, bags, hadBags) => {
        const el = document.getElementById(id);
        const d = score - was, db = bags - hadBags;
        el.innerHTML = `${score} <small class="${d >= 0 ? 'up' : 'down'}">${delta(d)}</small>` +
            (db ? ` <small class="bags">${delta(db)} bag${Math.abs(db) === 1 ? '' : 's'}</small>` : '');
    };
    scoreCell('hoYou', h.player_score ?? gameState.player_score, prev.player_score, h.player_bags ?? 0, prev.player_bags ?? 0);
    scoreCell('hoMarta', h.computer_score ?? gameState.computer_score, prev.computer_score, h.computer_bags ?? 0, prev.computer_bags ?? 0);

    // the middle: both cards, then the record's own line about who took it
    const cardEl = c => c ? `<div class="card ${getSuitClass(c.suit)}">${c.rank}${c.suit}</div>` : '<div class="card" style="opacity:.5">?</div>';
    document.getElementById('hoMidYou').innerHTML = cardEl(gameState.player_discarded);
    document.getElementById('hoMidMarta').innerHTML = cardEl(gameState.computer_discarded);
    const info = (r.discard_info || '').replace(/^Discards:\s*/, '').replace(/(\S+[♥♦])/g, '<span class="heart">$1</span>');
    document.getElementById('hoMiddle').innerHTML = info;

    // every line of the scoring record, as written
    const lines = (r.scoring || '').split(' | ').map(x => x.trim()).filter(Boolean);
    if (r.auto_resolution) lines.unshift(r.auto_resolution);
    document.getElementById('hoNotes').innerHTML = lines.map(n =>
        `<div class="ho-note ${/PENALTY|FAILED/.test(n) ? 'bad' : /BONUS|SUCCESS|special/.test(n) ? 'good' : ''}">${n.replace(/!+/g, '')}</div>`).join('');

    // the back and forth: who led what, what came back, who took it
    const tricks = r.trick_history || [];
    const suit = c => `<span class="${/[♥♦]/.test(c) ? 'heart' : ''}">${c}</span>`;
    document.getElementById('hoTricksLabel').textContent = `Tricks · you ${h.player_tricks ?? gameState.player_tricks}, Marta ${h.computer_tricks ?? gameState.computer_tricks}`;
    document.getElementById('hoTricks').innerHTML = tricks.map(t => {
        const youLed = t.leader === 'You';
        const led = youLed ? t.player_card : t.computer_card, ans = youLed ? t.computer_card : t.player_card;
        return `<div class="trick-line">
            <span class="trick-number">${t.number}</span>
            <span class="trick-cards"><b>${t.leader || '?'}</b> led ${suit(led)} · ${youLed ? 'Marta' : 'You'} ${suit(ans)}</span>
            <span class="trick-winner ${t.winner === 'You' ? 'you' : 'marta'}">${t.winner}</span>
        </div>`;
    }).join('');

    pulseLoginIfNotLoggedIn();
}

function pulseLoginIfNotLoggedIn() {
    const loginBtn = document.getElementById('loginButton');
    if (loginBtn && loginBtn.textContent.trim() === 'Login') {
        // Remove existing animation class first
        loginBtn.classList.remove('login-pulse');
        // Force reflow to restart animation
        void loginBtn.offsetWidth;
        // Add animation class
        loginBtn.classList.add('login-pulse');
    }
}

function handleTrickCompletion() {
    // Check for completed trick that needs to be displayed
    if (gameState.current_trick && gameState.current_trick.length === 2 && !trickDisplayTimeout) {
        trickDisplayTimeout = setTimeout(async () => {
            try {
                await fetch('/clear_trick', { method: 'POST' });
                await loadGameState();
                trickDisplayTimeout = null;
            } catch (error) {
                console.error('Error clearing trick:', error);
                trickDisplayTimeout = null;
            }
        }, 1500);
    }
}

// =============================================================================
// HELPER FUNCTIONS
// =============================================================================

function getSuitClass(suit) {
    switch (suit) {
        case '♠': return 'spade';
        case '♥': return 'heart';
        case '♦': return 'diamond';
        case '♣': return 'club';
        default: return '';
    }
}

function canPlayCard(card, index) {
    if (gameState.phase === 'discard') return true;
    if (gameState.turn !== 'player') return false;

    if (gameState.current_trick.length === 1) {
        const leadSuit = gameState.current_trick[0].card.suit;
        const hasSuit = gameState.player_hand.some(c => c.suit === leadSuit);
        if (hasSuit) {
            return card.suit === leadSuit;
        }
        return true;
    }

    if (gameState.current_trick.length === 0) {
        if (card.suit === '♠' && !gameState.spades_broken) {
            return gameState.player_hand.every(c => c.suit === '♠');
        }
        return true;
    }

    return false;
}

function selectCard(index) {
    if (!canPlayCard(gameState.player_hand[index], index)) {
        showMessage('Cannot play this card!', 'error');
        if (navigator.vibrate) {
            navigator.vibrate(100);
        }
        return;
    }

    selectedCard = index;
    updatePlayerHand();
    updateActionButtons();

    if (navigator.vibrate) {
        navigator.vibrate(50);
    }
}

function showMessage(text, type = '') {
    const messageEl = document.getElementById('message');
    if (messageEl) {
        messageEl.textContent = text;
        messageEl.className = 'message ' + type;
    }
}

function isSpecialCard(card) {
    return (card.rank === '7' && card.suit === '♦') || (card.rank === '10' && card.suit === '♣');
}

// =============================================================================
// BIDDING FUNCTIONS
// =============================================================================

function selectBid(bidAmount) {
    if (confirmingBid) return;

    selectedBid = bidAmount;
    confirmingBid = true;

    updateBidButtons();

    const biddingPrompt = document.querySelector('.bidding-prompt');
    if (biddingPrompt) {
        const bidText = bidAmount === 0 ? 'NIL (0 tricks)' : `${bidAmount} tricks`;
        biddingPrompt.innerHTML = `You selected: <strong>${bidText}</strong>`;
    }

    if (navigator.vibrate) navigator.vibrate(50);
}

function confirmSelectedBid() {
    if (selectedBid === null || !confirmingBid) return;

    makeBid(selectedBid);
    resetBiddingState();
}

function cancelBidSelection() {
    resetBiddingState();

    const biddingPrompt = document.querySelector('.bidding-prompt');
    if (biddingPrompt) {
        biddingPrompt.innerHTML = `How many tricks will you take?`;
    }
}

function resetBiddingState() {
    selectedBid = null;
    confirmingBid = false;
    updateBidButtons();
}

// =============================================================================
// SCROLL PRESERVATION
// =============================================================================

function preserveTrickHistoryScroll() {
    const trickHistory = document.querySelector('.trick-history');
    if (trickHistory) {
        trickHistoryScrollPosition = trickHistory.scrollTop;
    }
}

function restoreTrickHistoryScroll() {
    const trickHistory = document.querySelector('.trick-history');
    if (trickHistory && trickHistoryScrollPosition > 0) {
        setTimeout(() => {
            trickHistory.scrollTop = trickHistoryScrollPosition;
        }, 10);
    }
}

function resetTrickHistoryScroll() {
    trickHistoryScrollPosition = 0;
}

// =============================================================================
// API FUNCTIONS
// =============================================================================

async function chooseBlindNil() {
    try {
        const response = await fetch('/choose_blind_nil', { method: 'POST' });
        if (response.ok) {
            await loadGameState();
        } else {
            const error = await response.json();
            showMessage(error.error, 'error');
        }
    } catch (error) {
        console.error('Error choosing blind nil:', error);
        showMessage('Error choosing blind nil', 'error');
    }
}

async function chooseBlindBidding() {
    try {
        const response = await fetch('/choose_blind_bidding', { method: 'POST' });
        if (response.ok) {
            await loadGameState();
        } else {
            const error = await response.json();
            showMessage(error.error, 'error');
        }
    } catch (error) {
        console.error('Error choosing blind bidding:', error);
        showMessage('Error choosing blind bidding', 'error');
    }
}

async function chooseNormalBidding() {
    try {
        const response = await fetch('/choose_normal_bidding', { method: 'POST' });
        if (response.ok) {
            await loadGameState();
        } else {
            const error = await response.json();
            showMessage(error.error, 'error');
        }
    } catch (error) {
        console.error('Error choosing normal bidding:', error);
        showMessage('Error choosing normal bidding', 'error');
    }
}

async function makeBid(bidAmount) {
    try {
        const response = await fetch('/bid', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ bid: bidAmount })
        });

        if (response.ok) {
            await loadGameState();
            if (navigator.vibrate) navigator.vibrate(50);
        } else {
            const error = await response.json();
            showMessage(error.error, 'error');
        }
    } catch (error) {
        console.error('Error making bid:', error);
        showMessage('Error making bid', 'error');
    }
}

async function makeBlindBid(bidAmount) {
    try {
        const response = await fetch('/blind_bid', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ bid: bidAmount })
        });

        if (response.ok) {
            await loadGameState();
            if (navigator.vibrate) navigator.vibrate([100, 50, 100]);
        } else {
            const error = await response.json();
            showMessage(error.error, 'error');
        }
    } catch (error) {
        console.error('Error making blind bid:', error);
        showMessage('Error making blind bid', 'error');
    }
}

async function discardCard() {
    if (selectedCard === null) {
        showMessage('Please select a card to discard', 'error');
        if (navigator.vibrate) navigator.vibrate(100);
        return;
    }

    try {
        const response = await fetch('/discard', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ index: selectedCard })
        });

        if (response.ok) {
            selectedCard = null;
            await loadGameState();
        } else {
            const error = await response.json();
            showMessage(error.error, 'error');
        }
    } catch (error) {
        console.error('Error discarding card:', error);
        showMessage('Error discarding card', 'error');
    }
}

async function playCard() {
    if (selectedCard === null) {
        showMessage('Please select a card to play', 'error');
        if (navigator.vibrate) navigator.vibrate(100);
        return;
    }

    try {
        const response = await fetch('/play', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ index: selectedCard })
        });

        if (response.ok) {
            selectedCard = null;
            await loadGameState();
        } else {
            const error = await response.json();
            showMessage(error.error, 'error');
        }
    } catch (error) {
        console.error('Error playing card:', error);
        showMessage('Error playing card', 'error');
    }
}

async function performAction() {
    if (gameState && gameState.phase === 'discard') {
        await discardCard();
    } else {
        await playCard();
    }
}

async function toggleComputerHand() {
    try {
        const response = await fetch('/toggle_computer_hand', { method: 'POST' });
        if (response.ok) {
            await loadGameState();
        } else {
            const error = await response.json();
            showMessage(error.error, 'error');
        }
    } catch (error) {
        console.error('Error toggling computer hand:', error);
        showMessage('Error toggling computer hand', 'error');
    }
}

async function nextHand() {
    try {
        const response = await fetch('/next_hand', { method: 'POST' });
        if (response.ok) {
            if (trickDisplayTimeout) {
                clearTimeout(trickDisplayTimeout);
                trickDisplayTimeout = null;
            }
            selectedCard = null;
            resetBiddingState();
            resetTrickHistoryScroll();
            await loadGameState();
        } else {
            const error = await response.json();
            showMessage(error.error, 'error');
        }
    } catch (error) {
        console.error('Error starting next hand:', error);
        showMessage('Error starting next hand', 'error');
    }
}

async function startNewGame() {
    try {
        if (trickDisplayTimeout) {
            clearTimeout(trickDisplayTimeout);
            trickDisplayTimeout = null;
        }

        await fetch('/new_game', { method: 'POST' });
        selectedCard = null;
        resetBiddingState();
        resetTrickHistoryScroll();

        // Reset chat state for new game
        chatInitialized = false;

        await loadGameState();
    } catch (error) {
        console.error('Error starting new game:', error);
        showMessage('Error starting new game', 'error');
    }
}

// =============================================================================
// INITIALIZATION AND EVENT HANDLERS
// =============================================================================

document.addEventListener('DOMContentLoaded', function () {
    loadGameState();
});

// Auto-refresh with mobile-friendly timing
setInterval(() => {
    if (gameState && !gameState.game_over && !trickDisplayTimeout) {
        loadGameState();
    }
}, 2500);

// Handle orientation changes on mobile
window.addEventListener('orientationchange', function () {
    setTimeout(() => {
        updatePlayArea();
    }, 100);
});
