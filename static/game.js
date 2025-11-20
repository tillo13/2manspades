let gameState = null;
let selectedCard = null;
let trickDisplayTimeout = null;
let lastHandNumber = null;

// Bidding confirmation variables
let selectedBid = null;
let confirmingBid = false;

// Scroll preservation for trick history
let trickHistoryScrollPosition = 0;

// Enhanced chat system variables
let chatOpen = false;
let unreadMessages = 0;
let chatInitialized = false;

// =============================================================================
// USER-ONLY CLAUDE CHAT SYSTEM
// =============================================================================

function toggleChat() {
    const chatWindow = document.getElementById('chatWindow');
    const chatIcon = document.getElementById('chatBubbleIcon');

    chatOpen = !chatOpen;

    if (chatOpen) {
        chatWindow.classList.add('open');
        chatIcon.style.display = 'none';

        // Show static welcome message only when chat first opens
        if (!chatInitialized) {
            addMessage("Ready when you are.", 'marta');
            chatInitialized = true;
        }

        // Clear unread messages when chat is opened
        unreadMessages = 0;
        updateChatBadge();
    } else {
        chatWindow.classList.remove('open');
        chatIcon.style.display = 'flex';
    }
}

function sendMessage() {
    const input = document.getElementById('chatInput');
    const message = input.value.trim();

    if (!message) return;

    // Add player message
    addMessage(message, 'player');
    input.value = '';

    // Show Marta typing indicator
    showMartaTyping();

    // Get smart response from Marta with enhanced context - ONLY user-initiated
    fetch('/chat_response', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: message })
    })
        .then(response => response.json())
        .then(data => {
            if (data.response) {
                // Simulate realistic typing time based on response length
                const typingDelay = Math.min(Math.max(data.response.length * 50, 800), 3000);

                setTimeout(() => {
                    hideMartaTyping();
                    addMessage(data.response, 'marta');
                }, typingDelay);
            } else {
                hideMartaTyping();
                addMessage("...", 'marta'); // Mysterious fallback
            }
        })
        .catch(error => {
            console.error('Chat error:', error);
            hideMartaTyping();
            // Snarky fallback responses
            const fallbacks = [
                "Interesting move...",
                "We'll see about that.",
                "My cards are speaking to me.",
                "Poker face activated.",
                "You're full of surprises."
            ];
            const response = fallbacks[Math.floor(Math.random() * fallbacks.length)];
            setTimeout(() => {
                addMessage(response, 'marta');
            }, 800 + Math.random() * 1000);
        });
}

function showMartaTyping() {
    const messagesDiv = document.getElementById('chatMessages');

    // Remove any existing typing indicator
    const existingIndicator = document.getElementById('martaTypingIndicator');
    if (existingIndicator) {
        existingIndicator.remove();
    }

    // Create typing indicator
    const typingDiv = document.createElement('div');
    typingDiv.id = 'martaTypingIndicator';
    typingDiv.className = 'marta-message typing-indicator';
    typingDiv.innerHTML = `
        <div class="message-content">
            <div class="typing-dots">
                <span></span>
                <span></span>
                <span></span>
            </div>
        </div>
    `;

    messagesDiv.appendChild(typingDiv);
    messagesDiv.scrollTop = messagesDiv.scrollHeight;
}

function hideMartaTyping() {
    const typingIndicator = document.getElementById('martaTypingIndicator');
    if (typingIndicator) {
        typingIndicator.remove();
    }
}

function addMessage(text, sender) {
    const messagesDiv = document.getElementById('chatMessages');
    const messageDiv = document.createElement('div');
    messageDiv.className = sender === 'marta' ? 'marta-message' : 'player-message';

    // Create timestamp
    const now = new Date();
    const timeString = now.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });

    // Create message structure with timestamp
    const messageContent = document.createElement('div');
    messageContent.className = 'message-content';
    messageContent.textContent = text;

    const timestamp = document.createElement('div');
    timestamp.className = 'message-timestamp';
    timestamp.textContent = timeString;

    messageDiv.appendChild(messageContent);
    messageDiv.appendChild(timestamp);

    messagesDiv.appendChild(messageDiv);
    messagesDiv.scrollTop = messagesDiv.scrollHeight;

    // If it's a Marta message and chat is closed, increment unread count
    if (sender === 'marta' && !chatOpen) {
        unreadMessages++;
        updateChatBadge();
    }
}

function updateChatBadge() {
    const chatIcon = document.getElementById('chatBubbleIcon');
    let badge = document.getElementById('chatBadge');

    if (unreadMessages > 0 && !chatOpen) {
        // Create badge if it doesn't exist
        if (!badge) {
            badge = document.createElement('div');
            badge.id = 'chatBadge';
            badge.className = 'chat-badge';
            chatIcon.appendChild(badge);
        }
        badge.textContent = unreadMessages > 9 ? '9+' : unreadMessages;
        badge.style.display = 'block';
    } else {
        // Hide badge when no unread messages or chat is open
        if (badge) {
            badge.style.display = 'none';
        }
    }
}

// =============================================================================
// LOGIN/LOGOUT HANDLER
// =============================================================================

function handleLoginClick() {
    const loginButton = document.getElementById('loginButton');
    const buttonText = loginButton.textContent.trim();

    // If button shows anything other than "Login", user is logged in
    if (buttonText !== 'Login') {
        // User is logged in, show logout confirmation
        if (confirm('Logout from your account?')) {
            window.location.href = '/logout';
        }
    } else {
        // User not logged in, go to login page
        window.location.href = '/login';
    }
}


// =============================================================================
// MAIN GAME FUNCTIONS (unchanged core logic)
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
    updateDiscards();
    handleResultsDisplay();
    handleTrickCompletion();

    // Track hand changes but don't auto-call Claude
    lastHandNumber = gameState.hand_number;
    restoreTrickHistoryScroll();
}

// =============================================================================
// UI UPDATE FUNCTIONS (unchanged from original)
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
    const winnerTextEl = document.getElementById('winnerText');

    if (gameState.game_over) {
        gameOverEl.style.display = 'block';
        winnerTextEl.textContent = gameState.message;
        hideInteractiveSections();

        // Show results for blind nil games
        if (gameState.hand_results && (gameState.message.includes('BLIND NIL') || gameState.message.includes('Blind Nil'))) {
            handleResultsDisplay();
        } else {
            document.getElementById('resultsSection').classList.remove('show');
        }
    } else {
        gameOverEl.style.display = 'none';
    }
}

function hideInteractiveSections() {
    document.getElementById('biddingSection').style.display = 'none';
    const blindDecisionSection = document.getElementById('blindDecisionSection');
    if (blindDecisionSection) blindDecisionSection.style.display = 'none';
    document.getElementById('discardBlindBiddingSection').style.display = 'none';
    document.getElementById('nextHandSection').style.display = 'none';
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
    if (gameState.game_over) {
        showMessage(gameState.message, gameState.winner === 'player' ? 'success' : '');
        return;
    }

    let messageToShow = gameState.message;

    // Avoid showing detailed results if structured results are shown
    if (gameState.hand_over && gameState.hand_results) {
        messageToShow = `Hand #${gameState.hand_number} complete! Click 'Next Hand' to continue, or scroll for hand stats!`;
    }

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
    const nextHandSection = document.getElementById('nextHandSection');

    if (gameState.hand_over && !gameState.game_over) {
        actionButton.style.display = 'none';
        nextHandSection.style.display = 'block';
    } else {
        nextHandSection.style.display = 'none';

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

function updateDiscards() {
    const discardsSection = document.getElementById('discardsSection');

    if (gameState.hand_over && (gameState.player_discarded || gameState.computer_discarded)) {
        discardsSection.style.display = 'block';

        const playerDiscardEl = document.getElementById('playerDiscard');
        if (gameState.player_discarded) {
            const card = gameState.player_discarded;
            playerDiscardEl.innerHTML = `<div class="card ${getSuitClass(card.suit)}">${card.rank}${card.suit}</div>`;
        } else {
            playerDiscardEl.innerHTML = '<div class="card" style="opacity: 0.5;">None</div>';
        }

        const computerDiscardEl = document.getElementById('computerDiscard');
        if (gameState.computer_discarded) {
            const card = gameState.computer_discarded;
            computerDiscardEl.innerHTML = `<div class="card ${getSuitClass(card.suit)}">${card.rank}${card.suit}</div>`;
        } else {
            computerDiscardEl.innerHTML = '<div class="card" style="opacity: 0.5;">None</div>';
        }
    } else {
        discardsSection.style.display = 'none';
    }
}

function handleResultsDisplay() {
    const resultsSection = document.getElementById('resultsSection');
    const resultsContent = document.getElementById('resultsContent');

    if (gameState.hand_over && gameState.hand_results) {
        resultsSection.classList.add('show');
        resultsContent.innerHTML = formatCleanResults(gameState.hand_results);
    } else {
        resultsSection.classList.remove('show');
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
// HELPER FUNCTIONS (unchanged from original)
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
// BIDDING FUNCTIONS (unchanged from original)
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
// RESULTS FORMATTING (unchanged from original)
// =============================================================================

function formatCleanResults(results) {
    let html = '';

    // Parity Assignment
    html += `
        <div class="result-section">
            <div class="result-header">Players</div>
            <div class="result-content">You (${results.parity.player}) vs Marta (${results.parity.computer})</div>
        </div>
    `;

    // Discard Information
    if (results.discard_info && results.discard_info !== 'No discards to score') {
        html += `
            <div class="result-section">
                <div class="result-header">Discard Pile</div>
                <div class="result-content highlight">${results.discard_info}</div>
            </div>
        `;
    }

    // Scoring Breakdown
    html += `
        <div class="result-section">
            <div class="result-header">Scoring</div>
            <div class="result-content">${formatScoring(results.scoring)}</div>
        </div>
    `;

    // Trick History
    if (results.trick_history && results.trick_history.length > 0) {
        html += `
            <div class="result-section">
                <div class="result-header">Trick History</div>
                <div class="trick-history">
        `;

        results.trick_history.forEach(trick => {
            html += `
                <div class="trick-line">
                    <span class="trick-number">T${trick.number}:</span>
                    <span class="trick-cards">${trick.player_card} vs ${trick.computer_card}</span>
                    <span class="trick-winner">→ ${trick.winner}</span>
                </div>
            `;
        });

        html += `
                </div>
            </div>
        `;
    }

    // Game Totals
    html += `
        <div class="result-section">
            <div class="result-header">Game Totals</div>
            <div class="result-content totals">
                <span>You: ${results.totals.player_score}</span>
                <span>Marta: ${results.totals.computer_score}</span>
            </div>
        </div>
    `;

    return html;
}

function formatScoring(scoringText) {
    const parts = scoringText.split(' | ');
    return parts.map(part => {
        part = part.trim();

        if (part.includes('BAG PENALTY')) {
            return `<div class="penalty-line">${part.replace('BAG PENALTY!', 'Bag Penalty')}</div>`;
        } else if (part.includes('NEGATIVE BAG BONUS')) {
            return `<div class="bonus-line">${part.replace('NEGATIVE BAG BONUS!', 'Bag Bonus')}</div>`;
        } else if (part.includes('special cards')) {
            return `<div class="special-line">${part}</div>`;
        } else if (part.includes('Bags:')) {
            return `<div class="bags-line">${part}</div>`;
        } else {
            return `<div class="score-line">${part}</div>`;
        }
    }).join('');
}

// =============================================================================
// SCROLL PRESERVATION (unchanged from original)
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
// API FUNCTIONS (unchanged from original)
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

    // Handle Enter key in chat input
    const chatInput = document.getElementById('chatInput');
    if (chatInput) {
        chatInput.addEventListener('keypress', function (e) {
            if (e.key === 'Enter') {
                sendMessage();
            }
        });
    }

    // Prevent zoom on double-tap for mobile
    let lastTouchEnd = 0;
    document.addEventListener('touchend', function (event) {
        const now = (new Date()).getTime();
        if (now - lastTouchEnd <= 300) {
            event.preventDefault();
        }
        lastTouchEnd = now;
    }, false);
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