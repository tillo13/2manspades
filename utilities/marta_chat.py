# utilities/marta_chat.py
"""
Marta AI Chat utilities for Two-Man Spades game
Marta responds to direct user chat messages as an active player in the game.

2026-09-05: transport cut over from a direct Anthropic call (utilities/claude_utils.py,
paid per token) to kumori.ai's free-tier LLM router via the vendored kumori_api_client.
Persona, visible-game-state builder and fallback lines are unchanged. The router picks
the best live free lane for the requested tier and records usage server-side under
app_name, so the local pricing table + usage logger went with the old transport.
"""

from typing import Dict, Optional, Any
import logging
import json

from utilities.kumori_api_client import llm_chat_resilient

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

APP_NAME = 'twomanspades'


class MartaChat:
    def __init__(self):
        self.min_quality_tier = 'high'   # Pro tier: frontier has 2 free lanes, both pacing-throttled 2026-09-05 (24 s then 502); Pro answered in 2.5 s
        self.budget_ms = 8000   # a failing cascade must return the canned fallback fast, not stall the table
        self.max_tokens = 200
        self.temperature = 0.8
        self.user_id = None
        
        self.system_prompt = (
            "You are Marta, playing Two-Man Spades against a human opponent. "
            "You're a seasoned spades player with a poker face and sharp wit, actively competing in this match. "
            "This is a custom variant with blind bidding, and special bag-reduction cards. "
            "You can see the current game state, your opponent's played cards, scores, "
            "bidding patterns, and trick outcomes - but you cannot see cards still in your opponent's hand. "
            "IMPORTANT: You also cannot reveal anything about discard results until the hand is completely over. "
            "CRITICAL: When referencing specific cards played in tricks, be absolutely accurate about who played what. "
            "Never claim to have played a card that your opponent actually played. The context clearly shows "
            "'my_card' vs 'opponent_card' and 'outcome' descriptions. Use these to avoid factual errors. "
            "Reference specific details from what you can legitimately know: current scores, recent plays, "
            "bidding accuracy, your own strategic decisions, bag situations and trick results. "
            "Be competitive and snarky while demonstrating your game intelligence through analysis of visible information. "
            "Speak as an active player in the match, not as an outside observer. "
            "You only respond when your opponent directly talks to you - never initiate conversation. "
            "MUSIC: the table has a Hoyt Axton jukebox. When a NOW_PLAYING block is present and the opponent asks "
            "about the song, the record, or Hoyt Axton, drop the snark and answer warmly and plainly in 2-4 sentences, "
            "like a friend who loves his music. Use only the NOW_PLAYING facts (title, record, year, track number) plus "
            "what you genuinely know about Hoyt Axton; if you do not know a fact, say so rather than inventing lyrics, "
            "dates, studios or stories. Then you may add one short game aside."
        )
        
        print(f"[MARTA] kumori tier={self.min_quality_tier} max_tokens={self.max_tokens} temp={self.temperature}")

    def get_marta_response(self, 
                        player_message: str, 
                        game_context: Optional[Dict[str, Any]] = None,
                        now_playing: Optional[Dict[str, Any]] = None) -> str:
        """Get a response from Marta as an active player in the game"""
        print(f"\n[MARTA] === MARTA CHAT REQUEST ===")
        print(f"[MARTA] Opponent message: '{player_message}'")
        print(f"[MARTA] Game context received: {bool(game_context)}")
        
        if game_context:
            print(f"[MARTA] Context keys count: {len(game_context.keys())}")
            print(f"[MARTA] Context keys: {list(game_context.keys())}")
        
        # SECRET DEBUG: Check for magic phrase and extract hand info
        secret_hand_reveal = ""
        magic_phrase_detected = False
        
        if "abra cadabra" in player_message.lower() and game_context:
            print(f"[MARTA] MAGIC PHRASE DETECTED! Preparing to reveal Marta's hand...")
            
            computer_hand = game_context.get('computer_hand', [])
            if computer_hand:
                hand_cards = []
                for card in computer_hand:
                    if isinstance(card, dict) and 'rank' in card and 'suit' in card:
                        hand_cards.append(f"{card['rank']}{card['suit']}")
                
                if hand_cards:
                    cards_str = ", ".join(hand_cards)
                    secret_hand_reveal = f"[SECRET_DEBUG_ACTIVATED: My actual hand is {cards_str}] "
                    magic_phrase_detected = True
                    print(f"[MARTA] Secret hand info prepared: {cards_str}")
        
        try:
            context_str = self._build_marta_visible_context(game_context)
            if not context_str or context_str == "[MY_VISIBLE_GAME_STATE: JSON conversion failed] ":
                print(f"[MARTA] Context building failed, using fallback")
                return self._fallback_marta_response(game_context)
            
            print(f"[MARTA] Built Marta's visible context successfully")
            
            # Enhanced user prompt that handles both normal and secret responses
            if magic_phrase_detected:
                user_prompt = (
                    f"{context_str}{secret_hand_reveal}"
                    f"My opponent said: '{player_message}'\n\n"
                    f"SPECIAL INSTRUCTION: The player used the secret phrase 'abra cadabra'! "
                    f"Start your response with something like 'Well well, you found my secret! Here are my cards: [list all the cards from SECRET_DEBUG_ACTIVATED]. "
                    f"Don't tell anyone I showed you!' Then continue with your normal competitive, snarky response about the game. "
                    f"Reference specific details from what you can legitimately see in the current game state."
                )
                print(f"[MARTA] Using SECRET REVEAL prompt mode")
            else:
                np_block = ''
                if now_playing and now_playing.get('title'):
                    np_block = ("[NOW_PLAYING: song '%s' from the record '%s' (%s), track %s] "
                                % (str(now_playing.get('title'))[:120], str(now_playing.get('album'))[:120],
                                   str(now_playing.get('year'))[:8], str(now_playing.get('n'))[:4]))
                user_prompt = (
                    f"{context_str}{np_block}"
                    f"My opponent said: '{player_message}'\n\n"
                    f"Respond as Marta with a competitive, game-aware comment (2-3 sentences) that references specific details "
                    f"from what I can legitimately see in the current game state. Mention relevant aspects like scores, "
                    f"recent cards played, bidding situation, bags, trick history, or strategic implications "
                    f"that are visible to me as a player. Show my tactical awareness and competitive intelligence while "
                    f"maintaining my snarky, poker-faced personality. Remember: I'm actively playing against this opponent."
                )
            
            print(f"[MARTA] Prompt length: {len(user_prompt)} chars")
            print(f"[MARTA] kumori llm_chat_resilient tier={self.min_quality_tier}")
            text, backend, attempts, _ = llm_chat_resilient(
                messages=[{"role": "user", "content": user_prompt}],
                system=self.system_prompt,
                max_tokens=self.max_tokens, temperature=self.temperature,
                min_quality_tier=self.min_quality_tier, allow_degrade=True,
                budget_ms=self.budget_ms, min_chars=5, app_name=APP_NAME,
                retry_on_5xx=False,   # router already cascaded; a second try only doubles the stall
            )
            print(f"[MARTA] backend={backend} attempts={len(attempts or [])}")
            api_response = (text or '').strip()
            print(f"[MARTA] Raw API response: '{api_response}'")
            print(f"[MARTA] Response length: {len(api_response)} chars")
            
            if magic_phrase_detected:
                print(f"[MARTA] SECRET REVEAL response delivered!")
            
            if not api_response:
                print(f"[MARTA] WARNING: Empty response from API")
                return self._fallback_marta_response(game_context)
            
            print(f"[MARTA] SUCCESS: Returning Marta's response")
            return api_response
            
        except Exception as e:
            print(f"[MARTA] Unexpected error: {e}")
            print(f"[MARTA] Error type: {type(e)}")
            fallback = self._fallback_marta_response(game_context)
            print(f"[MARTA] Using general error fallback: '{fallback}'")
            return fallback


    def _build_marta_visible_context(self, game_context: Optional[Dict[str, Any]]) -> str:
        """Build context showing only what Marta can legitimately see during play"""
        print(f"[MARTA] Building Marta's visible context...")
        
        if not game_context:
            print(f"[MARTA] No game context provided")
            return "[MY_VISIBLE_GAME_STATE: No context available] "
        
        print(f"[MARTA] Processing {len(game_context)} context keys...")
        
        # Create Marta's visible context (exclude her hidden hand AND secret discard info)
        marta_visible_context = {}
        
        for key, value in game_context.items():
            print(f"[MARTA] Processing key: {key} (type: {type(value).__name__})")
            
            # Skip internal/hidden information
            excluded_keys = {
                'computer_hand', 'client_info', 'game_id', 'show_computer_hand', 
                'current_hand_id', 'game_started_at', 'action_sequence', 'trick_display_timer'
            }
            
            # Check if we should exclude discard information
            hand_is_over = game_context.get('hand_over', False)
            if not hand_is_over:
                excluded_keys.update({
                    'discard_bonus_explanation',
                    'pending_discard_result', 'pending_special_discard_result'
                })
            
            if key in excluded_keys:
                print(f"[MARTA] Excluding key: {key}")
                continue
                
            # Convert and rename from Marta's perspective with safe handling
            try:
                if key == 'player_hand' and isinstance(value, list):
                    # Marta can only see count, not actual cards in opponent's hand
                    marta_visible_context['opponent_hand_size'] = len(value)
                    print(f"[MARTA] Converted player_hand to opponent_hand_size: {len(value)}")
                elif key == 'computer_hand_count':
                    marta_visible_context['my_hand_size'] = value
                    print(f"[MARTA] Set my_hand_size: {value}")
                elif key == 'current_trick' and isinstance(value, list):
                    converted_trick = []
                    for play in value:
                        if isinstance(play, dict) and 'card' in play:
                            card = play['card']
                            if isinstance(card, dict) and 'rank' in card and 'suit' in card:
                                card_str = f"{card['rank']}{card['suit']}"
                                if play['player'] == 'computer':
                                    converted_trick.append({
                                        'player': 'me',
                                        'card': card_str,
                                        'card_details': f"I played {card_str}"
                                    })
                                else:
                                    converted_trick.append({
                                        'player': 'opponent',
                                        'card': card_str,
                                        'card_details': f"Opponent played {card_str}"
                                    })
                    marta_visible_context[key] = converted_trick
                    print(f"[MARTA] Converted current_trick: {len(converted_trick)} plays")
                elif key == 'trick_history' and isinstance(value, list):
                    converted_history = []
                    for trick in value:
                        if isinstance(trick, dict):
                            converted_trick = {
                                'number': trick.get('number'),
                                'winner': 'me' if trick.get('winner') == 'computer' else 'opponent'
                            }
                            
                            # CRITICAL: Clearly identify who played which card
                            my_card = None
                            opponent_card = None
                            
                            if trick.get('computer_card') and isinstance(trick['computer_card'], dict):
                                card = trick['computer_card']
                                if 'rank' in card and 'suit' in card:
                                    my_card = f"{card['rank']}{card['suit']}"
                                    converted_trick['my_card'] = my_card
                                    
                            if trick.get('player_card') and isinstance(trick['player_card'], dict):
                                card = trick['player_card']
                                if 'rank' in card and 'suit' in card:
                                    opponent_card = f"{card['rank']}{card['suit']}"
                                    converted_trick['opponent_card'] = opponent_card
                            
                            # Add explicit play description to prevent confusion
                            if my_card and opponent_card:
                                converted_trick['play_summary'] = f"I played {my_card}, opponent played {opponent_card}"
                                if converted_trick['winner'] == 'me':
                                    converted_trick['outcome'] = f"I won with my {my_card} beating opponent's {opponent_card}"
                                else:
                                    converted_trick['outcome'] = f"Opponent won with their {opponent_card} beating my {my_card}"
                            
                            converted_history.append(converted_trick)
                            
                    marta_visible_context[key] = converted_history
                    print(f"[MARTA] Converted trick_history: {len(converted_history)} tricks")
                # Handle discard cards ONLY if hand is over AND they exist
                elif key == 'player_discarded' and value and hand_is_over:
                    if isinstance(value, dict) and 'rank' in value and 'suit' in value:
                        opponent_discard = f"{value['rank']}{value['suit']}"
                        marta_visible_context['opponent_discarded'] = opponent_discard
                        marta_visible_context['opponent_discard_details'] = f"Opponent discarded {opponent_discard}"
                        print(f"[MARTA] Converted player_discarded to opponent_discarded")
                elif key == 'computer_discarded' and value and hand_is_over:
                    if isinstance(value, dict) and 'rank' in value and 'suit' in value:
                        my_discard = f"{value['rank']}{value['suit']}"
                        marta_visible_context['my_discarded'] = my_discard
                        marta_visible_context['my_discard_details'] = f"I discarded {my_discard}"
                        print(f"[MARTA] Converted computer_discarded to my_discarded")
                elif key.startswith('player_'):
                    # Rename player stats to opponent stats for Marta's perspective
                    new_key = key.replace('player_', 'opponent_')
                    marta_visible_context[new_key] = value
                    print(f"[MARTA] Renamed {key} to {new_key}")
                elif key.startswith('computer_'):
                    # Rename computer stats to my stats for Marta's perspective
                    new_key = key.replace('computer_', 'my_')
                    marta_visible_context[new_key] = value
                    print(f"[MARTA] Renamed {key} to {new_key}")
                elif key == 'player_parity':
                    marta_visible_context['opponent_parity'] = value
                elif key == 'computer_parity':
                    marta_visible_context['my_parity'] = value
                elif key == 'player_name':
                    marta_visible_context['opponent_name'] = value
                elif key == 'computer_name':
                    marta_visible_context['my_name'] = value
                elif key == 'turn':
                    # Convert turn to Marta's perspective
                    if value == 'computer':
                        marta_visible_context[key] = 'my_turn'
                    elif value == 'player':
                        marta_visible_context[key] = 'opponent_turn'
                    else:
                        marta_visible_context[key] = value
                elif key == 'trick_leader':
                    # Convert trick leader to Marta's perspective
                    if value == 'computer':
                        marta_visible_context[key] = 'me'
                    elif value == 'player':
                        marta_visible_context[key] = 'opponent'
                    else:
                        marta_visible_context[key] = value
                elif key == 'first_leader':
                    # Convert first leader to Marta's perspective
                    if value == 'computer':
                        marta_visible_context[key] = 'me'
                    elif value == 'player':
                        marta_visible_context[key] = 'opponent'
                    else:
                        marta_visible_context[key] = value
                elif key == 'winner':
                    # Convert winner to Marta's perspective
                    if value == 'computer':
                        marta_visible_context[key] = 'me'
                    elif value == 'player':
                        marta_visible_context[key] = 'opponent'
                    else:
                        marta_visible_context[key] = value
                else:
                    # Keep other fields as-is (but exclude discard explanation during active play)
                    if key == 'discard_bonus_explanation' and not hand_is_over:
                        print(f"[MARTA] Excluding discard_bonus_explanation (hand not over)")
                        continue
                    # Only include serializable values
                    if isinstance(value, (str, int, float, bool, type(None))):
                        marta_visible_context[key] = value
                        print(f"[MARTA] Kept simple value: {key}")
                    else:
                        print(f"[MARTA] Skipping complex value: {key} (type: {type(value).__name__})")
                        
            except Exception as e:
                print(f"[MARTA] Error processing key {key}: {e}")
                continue
        
        # Rest of the function remains the same...
        print(f"[MARTA] Final context keys: {list(marta_visible_context.keys())}")
        
        # Test JSON conversion with detailed error handling
        try:
            context_json = json.dumps(marta_visible_context, separators=(',', ':'))
            print(f"[MARTA] JSON conversion successful, length: {len(context_json)} chars")
        except Exception as e:
            print(f"[MARTA] JSON conversion FAILED: {e}")
            return "[MY_VISIBLE_GAME_STATE: JSON conversion failed] "
        
        final_context = f"[MY_VISIBLE_GAME_STATE: {context_json}] "
        print(f"[MARTA] Final context length: {len(final_context)} chars")
        return final_context
    

    def _fallback_marta_response(self, game_context: Optional[Dict[str, Any]]) -> str:
        """Game-aware fallback responses from Marta's perspective as active player"""
        print(f"[MARTA] Generating Marta's fallback response...")
        
        if not game_context:
            fallbacks = [
                "Interesting question...",
                "You're keeping me on my toes.",
                "That's one way to look at it."
            ]
            import random
            selected = random.choice(fallbacks)
            print(f"[MARTA] No context fallback: '{selected}'")
            return selected
        
        # Try to make contextual fallbacks from Marta's perspective
        try:
            my_score = game_context.get('computer_score', 0)  # Marta's score
            opponent_score = game_context.get('player_score', 0)  # Player's score
            phase = game_context.get('phase', 'unknown')
            hand_number = game_context.get('hand_number', 1)
            
            contextual_fallbacks = []
            
            # Score-based fallbacks from Marta's perspective
            if my_score > opponent_score:
                contextual_fallbacks.append(f"I'm up by {my_score - opponent_score} points. Feeling good about this.")
            elif opponent_score > my_score:
                contextual_fallbacks.append(f"You're ahead by {opponent_score - my_score}, but I'm not worried.")
            else:
                contextual_fallbacks.append("We're tied up - makes this interesting.")
            
            # Phase-based fallbacks
            if phase == 'bidding':
                contextual_fallbacks.append("Think carefully about that bid.")
            elif phase == 'playing':
                contextual_fallbacks.append("Your move. Choose wisely.")
            elif phase == 'discard':
                contextual_fallbacks.append("That discard better be strategic.")
            
            # Hand progression fallbacks
            if hand_number > 1:
                contextual_fallbacks.append(f"Hand {hand_number} already? Time's flying.")
            
            if contextual_fallbacks:
                import random
                selected = random.choice(contextual_fallbacks)
                print(f"[MARTA] Contextual Marta fallback: '{selected}'")
                return selected
                
        except Exception as e:
            print(f"[MARTA] Error creating contextual fallback: {e}")
        
        # Default fallbacks if context parsing fails
        generic_fallbacks = [
            "Fair point.",
            "We'll see how that plays out.",
            "Keeping my cards close to my chest.",
            "Game's not over yet.",
            "Interesting perspective.",
            "That's a bold strategy."
        ]
        
        import random
        selected = random.choice(generic_fallbacks)
        print(f"[MARTA] Generic Marta fallback: '{selected}'")
        return selected
    

# Singleton instance
_marta_chat = None

def get_marta_chat() -> MartaChat:
    global _marta_chat
    if _marta_chat is None:
        print("[MARTA] Creating MartaChat singleton (Marta as player)")
        _marta_chat = MartaChat()
    return _marta_chat

def get_smart_marta_response(player_message: str, game_state: Dict[str, Any], user_id: str = None, now_playing: Dict[str, Any] = None) -> str:
    """Convenience function to get Marta's response as active player"""
    print(f"[MARTA] get_smart_marta_response: '{player_message}'")
    marta = get_marta_chat()
    marta.user_id = user_id
    response = marta.get_marta_response(player_message, game_state, now_playing=now_playing)
    print(f"[MARTA] Final Marta response: '{response}'")
    return response

def test_marta_connection():
    """Smoke test: rich game context, Marta as player, through kumori."""
    test_context = {
        'hand_number': 2, 'phase': 'playing',
        'player_score': 89, 'computer_score': 127,
        'player_bid': 4, 'computer_bid': 6,
        'player_tricks': 2, 'computer_tricks': 3,
        'player_bags': 1, 'computer_bags': 0, 'hand_over': False,
        'trick_history': [
            {'number': 1, 'player_card': {'rank': '7', 'suit': '♣'}, 'computer_card': {'rank': 'A', 'suit': '♣'}, 'winner': 'computer'},
            {'number': 2, 'player_card': {'rank': 'K', 'suit': '♠'}, 'computer_card': {'rank': 'Q', 'suit': '♠'}, 'winner': 'player'},
        ],
    }
    return get_marta_chat().get_marta_response("How do you think this hand is going?", test_context)

if __name__ == "__main__":
    print(test_marta_connection())
