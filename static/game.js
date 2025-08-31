let gameState = null;
let selectedCard = null;
let trickDisplayTimeout = null;
let lastHandNumber = null;

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

    // Update floating game scores
    updateFloatingScores();

    // Update hand count display
    const playerHandCountEl = document.getElementById('playerHandCount');
    if (playerHandCountEl) {
        playerHandCountEl.textContent = `(${gameState.player_hand.length} cards)`;
    }

    // Show/hide bidding section and blind bidding
    const biddingSection = document.getElementById('biddingSection');
    const discardBlindSection = document.getElementById('discardBlindBiddingSection');

    if (gameState.phase === 'bidding') {
        biddingSection.style.display = 'block';
        discardBlindSection.style.display = 'none';
    } else if (gameState.phase === 'discard') {
        // Check if player is eligible for blind bidding and hasn't already bid
        if (!gameState.player_bid && !gameState.blind_bid) {
            // Check if player is down by 100+ points for blind eligibility
            const deficit = gameState.computer_score - gameState.player_score;
            if (deficit >= 100) {
                discardBlindSection.style.display = 'block';
            } else {
                discardBlindSection.style.display = 'none';
            }
        } else {
            discardBlindSection.style.display = 'none';
        }
        biddingSection.style.display = 'none';
    } else {
        biddingSection.style.display = 'none';
        discardBlindSection.style.display = 'none';
    }

    // Handle results display for completed hands
    handleResultsDisplay();

    // Update message
    showMessage(gameState.message, gameState.message.includes('WIN') ? 'success' : '');

    // Update play area
    updatePlayArea();

    // Update hands
    updatePlayerHand();
    updateComputerHand();

    // Update buttons based on game state
    updateActionButtons();

    // Update computer hand toggle button - respect debug mode
    const toggleButton = document.getElementById('toggleComputerHand');
    if (toggleButton) {
        if (gameState.debug_mode) {
            // In debug mode, show the button and update text
            toggleButton.style.display = 'inline-block';
            toggleButton.textContent = gameState.show_computer_hand ? 'Hide Cards' : 'Show Cards';
            toggleButton.style.background = '#6c757d';
        } else {
            // Not in debug mode, hide the button completely
            toggleButton.style.display = 'none';
        }
    }

    // Show discards if hand is over
    updateDiscards();

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
        }, 3000);
    }

    // Check game over
    if (gameState.game_over) {
        document.getElementById('gameOver').style.display = 'block';
        document.getElementById('winnerText').textContent = gameState.message;
    } else {
        document.getElementById('gameOver').style.display = 'none';
    }

    // Track hand changes for results display
    lastHandNumber = gameState.hand_number;
}

function updateFloatingScores() {
    // Update floating game score with parity indicators
    const gameScoreEl = document.getElementById('floatingGameScore');
    if (gameScoreEl) {
        document.getElementById('floatingPlayerScore').textContent = gameState.player_score;
        document.getElementById('floatingComputerScore').textContent = gameState.computer_score;
        document.getElementById('floatingHandNumber').textContent = gameState.hand_number;

        // Update parity displays
        const playerParityText = `(${gameState.player_parity.toUpperCase()})`;
        const computerParityText = `(${gameState.computer_parity.toUpperCase()})`;

        document.getElementById('floatingPlayerParity').textContent = playerParityText;
        document.getElementById('floatingComputerParity').textContent = computerParityText;
    }

    // Update floating hand score
    const handScoreEl = document.getElementById('floatingHandScore');
    if (handScoreEl) {
        // Player side
        document.getElementById('floatingPlayerTricks').textContent = gameState.player_tricks;
        const playerBid = gameState.player_bid !== null ? gameState.player_bid : '-';
        const playerBlindText = gameState.blind_bid === gameState.player_bid ? 'B' : '';
        document.getElementById('floatingPlayerBid').textContent = `${playerBid}${playerBlindText}`;

        // Color code player bid if blind
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

        // Color code computer bid if blind
        const computerBidEl = document.getElementById('floatingComputerBid');
        if (computerBlindText) {
            computerBidEl.style.color = '#dc3545';
            computerBidEl.style.fontWeight = 'bold';
        } else {
            computerBidEl.style.color = '#333';
            computerBidEl.style.fontWeight = '600';
        }

        document.getElementById('floatingComputerBags').textContent = gameState.computer_bags || 0;

        // Spades status
        document.getElementById('floatingSpadesStatus').textContent = gameState.spades_broken ? 'Broken' : 'Not Broken';
    }
}

function updateBagsDisplay(elementId, bags) {
    const bagsEl = document.getElementById(elementId);
    if (!bagsEl) return;

    bagsEl.textContent = `Bags: ${bags}/7`;

    // Color coding for mobile-friendly visibility
    if (bags >= 6) {
        bagsEl.style.color = '#d32f2f';
        bagsEl.style.fontWeight = 'bold';
        bagsEl.style.backgroundColor = '#ffebee';
        bagsEl.style.padding = '2px 6px';
        bagsEl.style.borderRadius = '4px';
    } else if (bags >= 4) {
        bagsEl.style.color = '#f57c00';
        bagsEl.style.fontWeight = 'bold';
        bagsEl.style.backgroundColor = '#fff3e0';
        bagsEl.style.padding = '2px 6px';
        bagsEl.style.borderRadius = '4px';
    } else if (bags <= -4) {
        bagsEl.style.color = '#1976d2';
        bagsEl.style.fontWeight = 'bold';
        bagsEl.style.backgroundColor = '#e3f2fd';
        bagsEl.style.padding = '2px 6px';
        bagsEl.style.borderRadius = '4px';
    } else {
        bagsEl.style.color = '#666';
        bagsEl.style.fontWeight = 'normal';
        bagsEl.style.backgroundColor = 'transparent';
        bagsEl.style.padding = '0';
    }
}

// NEW: Clean structured results display
// Replace the handleResultsDisplay function in your game.js with this:
function handleResultsDisplay() {
    const resultsSection = document.getElementById('resultsSection');
    const resultsContent = document.getElementById('resultsContent');

    if (gameState.hand_over && gameState.hand_results) {
        // Show results section with clean structured content
        resultsSection.classList.add('show');
        resultsContent.innerHTML = formatCleanResults(gameState.hand_results);
    } else {
        // Don't show results if no structured data available
        resultsSection.classList.remove('show');
    }
}

// NEW: Clean formatting function
function formatCleanResults(results) {
    let html = '';

    // Parity Assignment
    html += `
        <div class="result-section">
            <div class="result-header">Players</div>
            <div class="result-content">Tom (${results.parity.player}) vs Marta (${results.parity.computer})</div>
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
                <span>Tom: ${results.totals.player_score}</span>
                <span>Marta: ${results.totals.computer_score}</span>
            </div>
        </div>
    `;

    return html;
}

function formatScoring(scoringText) {
    // Split by " | " and format each piece nicely
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

// OLD: Legacy formatting function - keeping for fallback compatibility
function formatResultsForMobile(explanation) {
    if (!explanation || explanation === 'No discards to score') {
        return '<div class="result-line" style="color: #666; font-style: italic;">No special scoring this hand</div>';
    }

    // Split explanation by pipe separators and format each section cleanly
    const sections = explanation.split(' | ');
    let formatted = '';

    sections.forEach((section) => {
        section = section.trim();

        if (section.includes('complete!')) {
            // Skip the "Hand complete" line - already shown in header
            return;
        } else if (section.includes('vs') && (section.includes('Even') || section.includes('Odd'))) {
            // Parity assignment - make it cleaner
            const clean = section.replace(/Tom \(Even\) vs Marta \(Odd\)|Tom \(Odd\) vs Marta \(Even\)/,
                section.includes('Tom (Even)') ? 'Tom: Even, Marta: Odd' : 'Tom: Odd, Marta: Even');
            formatted += `<div class="result-line" style="font-weight: 500; color: #6c757d;">${clean}</div>`;
        } else if (section.includes('DISCARD PILE REVEALS:')) {
            // Clean up discard reveals
            const clean = section.replace('DISCARD PILE REVEALS: Discards:', 'Discard pile:');
            formatted += `<div class="result-line highlight">${clean}</div>`;
        } else if (section.includes('Tom:') && section.includes('bid')) {
            // Player scoring line
            formatted += `<div class="result-line">${section}</div>`;
        } else if (section.includes('Marta:') && section.includes('bid')) {
            // Computer scoring line  
            formatted += `<div class="result-line">${section}</div>`;
        } else if (section.includes('BAG PENALTY')) {
            // Penalty formatting
            const clean = section.replace('BAG PENALTY!', 'Bag penalty');
            formatted += `<div class="result-line penalty">${clean}</div>`;
        } else if (section.includes('NEGATIVE BAG BONUS')) {
            // Bonus formatting
            const clean = section.replace('NEGATIVE BAG BONUS!', 'Bag bonus');
            formatted += `<div class="result-line bonus">${clean}</div>`;
        } else if (section.includes('won') && section.includes('special cards')) {
            // Special card wins
            formatted += `<div class="result-line" style="color: #17a2b8;">${section}</div>`;
        } else if (section.includes('Bags:')) {
            // Bag status
            formatted += `<div class="result-line" style="color: #6c757d; font-size: 11px; text-align: center; border-top: 1px solid #e9ecef; padding-top: 6px; margin-top: 4px;">${section}</div>`;
        } else if (section.includes('Game totals:')) {
            // Game totals - make prominent but clean
            formatted += `<div class="result-line" style="font-weight: 600; text-align: center; margin-top: 6px; padding-top: 6px; border-top: 1px solid #e9ecef;">${section}</div>`;
        } else if (section.includes('TRICK HISTORY:')) {
            // Format trick history nicely
            const clean = section.replace('TRICK HISTORY: ', '');
            const tricks = clean.split(' | ');
            let historyHtml = '<div class="result-line" style="font-weight: 500; margin-top: 8px; color: #495057;">Trick History:</div>';
            tricks.forEach(trick => {
                historyHtml += `<div class="result-line" style="font-size: 11px; color: #495057; padding-left: 8px; font-family: monospace;">${trick}</div>`;
            });
            formatted += historyHtml;
        } else if (section.includes('Click') || section.includes('continue')) {
            // Skip instructions - handled by button
            return;
        } else if (section.length > 0) {
            // Any other content
            formatted += `<div class="result-line">${section}</div>`;
        }
    });

    return formatted;
}

function updateActionButtons() {
    const actionButton = document.getElementById('actionButton');
    const nextHandButton = document.getElementById('nextHandButton');

    if (gameState.hand_over && !gameState.game_over) {
        actionButton.style.display = 'none';
        nextHandButton.style.display = 'inline-block';
    } else if (gameState.phase === 'discard') {
        // Hide discard button if player is blind eligible and no bid made yet
        const deficit = gameState.computer_score - gameState.player_score;
        const isBlindEligible = deficit >= 100;
        const noBidMadeYet = !gameState.player_bid && !gameState.blind_bid;

        if (isBlindEligible && noBidMadeYet) {
            actionButton.style.display = 'none';
        } else {
            actionButton.textContent = 'Discard Selected';
            actionButton.onclick = discardCard;
            actionButton.style.display = 'inline-block';
        }
        nextHandButton.style.display = 'none';
    } else if (gameState.phase === 'playing') {
        actionButton.textContent = 'Play Selected';
        actionButton.onclick = playCard;
        actionButton.style.display = 'inline-block';
        nextHandButton.style.display = 'none';
    } else {
        actionButton.style.display = 'none';
        nextHandButton.style.display = 'none';
    }

    if (selectedCard === null && actionButton.style.display !== 'none') {
        actionButton.disabled = true;
        actionButton.textContent = gameState.phase === 'discard' ? 'Select Card to Discard' : 'Select Card to Play';
    } else if (actionButton.style.display !== 'none') {
        actionButton.disabled = false;
        actionButton.textContent = gameState.phase === 'discard' ? 'Discard Selected' : 'Play Selected';
    }
}

function updatePlayArea() {
    const trickDisplay = document.getElementById('trickDisplay');

    if (gameState.current_trick.length === 0) {
        trickDisplay.innerHTML = '<div style="color: #999; font-size: 14px;">Waiting for play...</div>';
    } else {
        let html = '<div class="trick-container">';

        const playerCard = gameState.current_trick.find(play => play.player === 'player');
        const computerCard = gameState.current_trick.find(play => play.player === 'computer');

        // Always show side by side - Tom left, Marta right
        if (playerCard) {
            const card = playerCard.card;
            const suitClass = getSuitClass(card.suit);
            html += `
                <div class="trick-card ${suitClass}">
                    <div class="player-name">Tom</div>
                    <div class="card-content">${card.rank}${card.suit}</div>
                </div>
            `;
        } else {
            html += '<div class="trick-card-placeholder"><div style="font-size: 10px; color: #999;">Tom</div></div>';
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
    handEl.innerHTML = '';

    // Hide cards if in discard phase, no bid made yet, and player is down by 100+ points
    const deficit = gameState.computer_score - gameState.player_score;
    const isBlindEligible = deficit >= 100;
    const noBidMadeYet = !gameState.player_bid && !gameState.blind_bid;

    if (gameState.phase === 'discard' && isBlindEligible && noBidMadeYet) {
        handEl.innerHTML = '<div style="text-align: center; color: #666; font-style: italic; padding: 20px; border: 2px dashed #ccc; border-radius: 8px;">Cards hidden - make blind bid decision first!</div>';
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
    handEl.innerHTML = '';

    // Only show cards if debug mode is on AND show_computer_hand is true
    if (gameState.debug_mode && gameState.show_computer_hand && gameState.computer_hand) {
        // Show actual cards
        gameState.computer_hand.forEach((card, index) => {
            const cardEl = document.createElement('div');
            cardEl.className = `card ${getSuitClass(card.suit)}`;
            cardEl.textContent = `${card.rank}${card.suit}`;
            cardEl.style.cursor = 'default';
            handEl.appendChild(cardEl);
        });
    } else {
        // Show hidden cards with count
        const cardCount = gameState.computer_hand_count;
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

function updateDiscards() {
    const discardsSection = document.getElementById('discardsSection');

    if (gameState.hand_over && (gameState.player_discarded || gameState.computer_discarded)) {
        discardsSection.style.display = 'block';

        // Show player discard
        const playerDiscardEl = document.getElementById('playerDiscard');
        if (gameState.player_discarded) {
            const card = gameState.player_discarded;
            playerDiscardEl.innerHTML = `<div class="card ${getSuitClass(card.suit)}">${card.rank}${card.suit}</div>`;
        } else {
            playerDiscardEl.innerHTML = '<div class="card" style="opacity: 0.5;">None</div>';
        }

        // Show computer discard
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

async function nextHand() {
    try {
        const response = await fetch('/next_hand', { method: 'POST' });
        if (response.ok) {
            if (trickDisplayTimeout) {
                clearTimeout(trickDisplayTimeout);
                trickDisplayTimeout = null;
            }
            selectedCard = null;
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
        // Add haptic feedback on mobile if available
        if (navigator.vibrate) {
            navigator.vibrate(100);
        }
        return;
    }

    selectedCard = index;
    updatePlayerHand();
    updateActionButtons(); // Update button state when card is selected

    // Add subtle haptic feedback on mobile if available
    if (navigator.vibrate) {
        navigator.vibrate(50);
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

async function makeBid(bidAmount) {
    try {
        const response = await fetch('/bid', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ bid: bidAmount })
        });

        if (response.ok) {
            await loadGameState();
            // Haptic feedback for successful bid
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
            // Stronger haptic feedback for blind bid
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

async function startNewGame() {
    try {
        if (trickDisplayTimeout) {
            clearTimeout(trickDisplayTimeout);
            trickDisplayTimeout = null;
        }

        await fetch('/new_game', { method: 'POST' });
        selectedCard = null;
        await loadGameState();
    } catch (error) {
        console.error('Error starting new game:', error);
        showMessage('Error starting new game', 'error');
    }
}

function showMessage(text, type = '') {
    const messageEl = document.getElementById('message');
    if (messageEl) {
        messageEl.textContent = text;
        messageEl.className = 'message ' + type;

        // Auto-scroll to message on mobile for better visibility
        if (window.innerWidth < 768) {
            messageEl.scrollIntoView({ behavior: 'smooth', block: 'center' });
        }
    }
}

// Initialize game on load
document.addEventListener('DOMContentLoaded', function () {
    loadGameState();

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
}, 2500); // Slightly longer interval for mobile battery life

// Handle orientation changes on mobile
window.addEventListener('orientationchange', function () {
    setTimeout(() => {
        updatePlayArea();
    }, 100);
});