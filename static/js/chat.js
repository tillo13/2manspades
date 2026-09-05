// Marta chat: messages, typing dots, router retries, unread badge. The sheet itself is
// owned by jukebox.js (TableSheet); this file only fills the Marta pane.
// Enhanced chat system variables
let chatOpen = false;
let unreadMessages = 0;
let chatInitialized = false;

// =============================================================================
// USER-ONLY CLAUDE CHAT SYSTEM
// =============================================================================

function toggleChat() {
    // 2026-09-05: Marta lives in the shared table sheet (jukebox.js owns it). Open = Marta tab.
    if (window.TableSheet) { TableSheet.toggle('marta'); return; }
}

// called by TableSheet whenever the Marta tab becomes visible / hidden
function onChatVisibility(visible) {
    chatOpen = visible;
    if (visible) {
        if (!chatInitialized) { addMessage("Ready when you are.", 'marta'); chatInitialized = true; }
        unreadMessages = 0;
        updateChatBadge();
    }
}

function sendMessage() {
    const input = document.getElementById('chatInput');
    const message = input.value.trim();
    if (!message) return;
    addMessage(message, 'player');
    input.value = '';
    showMartaTyping();
    askMarta(message, 1);
}

// 2026-09-05: a music question can stall the free-LLM router. The server answers
// {retry:true} instead of a canned card line; we keep the dots up, tell him once that
// we're still looking, and re-send up to MAX_TRIES times a few seconds apart.
const MARTA_MAX_TRIES = 3, MARTA_RETRY_MS = 4000;
function askMarta(message, attempt) {
    fetch('/chat_response', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: message, now_playing: (window.HoytJukebox ? HoytJukebox.nowPlaying() : null) })
    })
        .then(response => response.json())
        .then(data => {
            if (data.retry) {
                if (attempt === 1 && data.note) { addMessage(data.note, 'marta'); showMartaTyping(); }   // note above, dots stay below
                if (attempt < MARTA_MAX_TRIES) { setTimeout(() => askMarta(message, attempt + 1), MARTA_RETRY_MS); return; }
                hideMartaTyping();
                addMessage("I kept looking and came up empty this time. Ask me again in a minute.", 'marta');
                return;
            }
            if (data.response) {
                const typingDelay = Math.min(Math.max(data.response.length * 50, 800), 3000);
                setTimeout(() => { hideMartaTyping(); addMessage(data.response, 'marta'); }, typingDelay);
            } else {
                hideMartaTyping();
                addMessage("...", 'marta');
            }
        })
        .catch(error => {
            console.error('Chat error:', error);
            if (attempt < MARTA_MAX_TRIES) { setTimeout(() => askMarta(message, attempt + 1), MARTA_RETRY_MS); return; }
            hideMartaTyping();
            const fallbacks = ["Interesting move...", "We'll see about that.", "My cards are speaking to me.", "Poker face activated.", "You're full of surprises."];
            setTimeout(() => addMessage(fallbacks[Math.floor(Math.random() * fallbacks.length)], 'marta'), 800 + Math.random() * 1000);
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

document.addEventListener('DOMContentLoaded', function () {
    const chatInput = document.getElementById('chatInput');
    if (chatInput) chatInput.addEventListener('keypress', (e) => { if (e.key === 'Enter') sendMessage(); });
});
