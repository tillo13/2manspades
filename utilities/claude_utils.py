# utilities/claude_utils.py
"""
Marta AI Chat utilities for Two-Man Spades game
Marta responds to direct user chat messages as an active player in the game
"""

import os
import anthropic
from typing import Dict, Optional, Any
import logging
import json

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# For production Secret Manager
try:
    from google.cloud import secretmanager
    GOOGLE_CLOUD_AVAILABLE = True
    print("[CLAUDE] Google Cloud Secret Manager available")
except ImportError:
    GOOGLE_CLOUD_AVAILABLE = False
    print("[CLAUDE] Google Cloud Secret Manager NOT available")

# For local development
try:
    from dotenv import load_dotenv
    load_dotenv()
    print("[CLAUDE] dotenv loaded successfully")
except ImportError:
    print("[CLAUDE] dotenv NOT available")

class ClaudeGameChat:
    def __init__(self):
        print("[CLAUDE] Initializing ClaudeGameChat for Marta's responses...")
        
        self.api_key = self._get_api_key()
        if not self.api_key:
            error_msg = "ANTHROPIC_API_KEY not found in environment or Secret Manager"
            print(f"[CLAUDE] ERROR: {error_msg}")
            raise ValueError(error_msg)
        
        print(f"[CLAUDE] API key found: {self.api_key[:10]}...{self.api_key[-4:] if len(self.api_key) > 14 else 'SHORT'}")
        
        try:
            # FIXED: More aggressive timeout and better error handling
            self.client = anthropic.Anthropic(
                api_key=self.api_key,
                max_retries=1,  # Only retry once to fail faster
                timeout=10.0,   # 10 second timeout to avoid hanging
            )
            print("[CLAUDE] Anthropic client initialized successfully with fast-fail config")
        except Exception as e:
            print(f"[CLAUDE] ERROR initializing Anthropic client: {e}")
            raise e
        
        self.model = "claude-3-5-haiku-20241022"
        self.max_tokens = 150
        self.temperature = 0.8
        
        self.system_prompt = (
            "You are Marta, playing Two-Man Spades against a human opponent. "
            "You're a seasoned spades player with a poker face and sharp wit, actively competing in this match. "
            "This is a custom variant with parity scoring, blind bidding, and special bag-reduction cards. "
            "You can see the current game state, your opponent's played cards, discard pile results, scores, "
            "bidding patterns, and trick outcomes - but you cannot see cards still in your opponent's hand. "
            "IMPORTANT: You also cannot see discard results until the hand is completely over. "
            "CRITICAL: When referencing specific cards played in tricks, be absolutely accurate about who played what. "
            "Never claim to have played a card that your opponent actually played. The context clearly shows "
            "'my_card' vs 'opponent_card' and 'outcome' descriptions. Use these to avoid factual errors. "
            "Reference specific details from what you can legitimately know: current scores, recent plays, "
            "bidding accuracy, your own strategic decisions, bag situations, parity advantages, and trick results. "
            "Be competitive and snarky while demonstrating your game intelligence through analysis of visible information. "
            "Speak as an active player in the match, not as an outside observer. "
            "You only respond when your opponent directly talks to you - never initiate conversation."
        )
        
        print(f"[CLAUDE] Configuration:")
        print(f"  Model: {self.model}")
        print(f"  Max tokens: {self.max_tokens}")
        print(f"  Temperature: {self.temperature}")
        print(f"  Max retries: 1")
        print(f"  Timeout: 10.0 seconds")
        print(f"  System prompt length: {len(self.system_prompt)} chars")
        print(f"  Mode: Marta as active player")
    
    def get_marta_response(self, 
                          player_message: str, 
                          game_context: Optional[Dict[str, Any]] = None) -> str:
        """Get a response from Marta as an active player in the game"""
        print(f"\n[CLAUDE] === MARTA CHAT REQUEST ===")
        print(f"[CLAUDE] Opponent message: '{player_message}'")
        print(f"[CLAUDE] Game context received: {bool(game_context)}")
        
        if game_context:
            print(f"[CLAUDE] Context keys count: {len(game_context.keys())}")
            print(f"[CLAUDE] Context keys: {list(game_context.keys())}")
        
        try:
            context_str = self._build_marta_visible_context(game_context)
            if not context_str or context_str == "[MY_VISIBLE_GAME_STATE: JSON conversion failed] ":
                print(f"[CLAUDE] Context building failed, using fallback")
                return self._fallback_marta_response(game_context)
            
            print(f"[CLAUDE] Built Marta's visible context successfully")
            
            user_prompt = (
                f"{context_str}"
                f"My opponent said: '{player_message}'\n\n"
                f"Respond as Marta with a competitive, game-aware comment (2-3 sentences) that references specific details "
                f"from what I can legitimately see in the current game state. Mention relevant aspects like scores, "
                f"recent cards played, bidding situation, bags, parity positions, trick history, or strategic implications "
                f"that are visible to me as a player. Show my tactical awareness and competitive intelligence while "
                f"maintaining my snarky, poker-faced personality. Remember: I'm actively playing against this opponent."
            )
            
            print(f"[CLAUDE] Prompt length: {len(user_prompt)} chars")
            print(f"[CLAUDE] Making API call to {self.model}...")
            
            response = self.client.messages.create(
                model=self.model,
                max_tokens=self.max_tokens,
                temperature=self.temperature,
                system=self.system_prompt,
                messages=[{
                    "role": "user", 
                    "content": user_prompt
                }]
            )
            
            print(f"[CLAUDE] API call successful!")
            
            api_response = response.content[0].text.strip()
            print(f"[CLAUDE] Raw API response: '{api_response}'")
            print(f"[CLAUDE] Response length: {len(api_response)} chars")
            
            if not api_response:
                print(f"[CLAUDE] WARNING: Empty response from API")
                return self._fallback_marta_response(game_context)
            
            print(f"[CLAUDE] SUCCESS: Returning Marta's active player response")
            return api_response
            
        except anthropic.APITimeoutError as e:
            print(f"[CLAUDE] API Timeout Error after 10s: {e}")
            fallback = self._fallback_marta_response(game_context)
            print(f"[CLAUDE] Using timeout fallback: '{fallback}'")
            return fallback
            
        except anthropic.RateLimitError as e:
            print(f"[CLAUDE] Rate Limit Error: {e}")
            retry_after = getattr(e.response, 'headers', {}).get('retry-after', 'unknown')
            print(f"[CLAUDE] Retry-after header: {retry_after}")
            fallback = self._fallback_marta_response(game_context)
            print(f"[CLAUDE] Using rate limit fallback: '{fallback}'")
            return fallback
            
        except anthropic.APIConnectionError as e:
            print(f"[CLAUDE] Connection Error: {e}")
            fallback = self._fallback_marta_response(game_context)
            print(f"[CLAUDE] Using connection error fallback: '{fallback}'")
            return fallback
            
        except anthropic.APIError as e:
            print(f"[CLAUDE] General API Error: {e}")
            print(f"[CLAUDE] Error type: {type(e)}")
            if hasattr(e, 'status_code'):
                print(f"[CLAUDE] Status code: {e.status_code}")
            fallback = self._fallback_marta_response(game_context)
            print(f"[CLAUDE] Using API error fallback: '{fallback}'")
            return fallback
            
        except Exception as e:
            print(f"[CLAUDE] Unexpected error: {e}")
            print(f"[CLAUDE] Error type: {type(e)}")
            fallback = self._fallback_marta_response(game_context)
            print(f"[CLAUDE] Using general error fallback: '{fallback}'")
            return fallback
    


    def _build_marta_visible_context(self, game_context: Optional[Dict[str, Any]]) -> str:
        """Build context showing only what Marta can legitimately see during play"""
        print(f"[CLAUDE] Building Marta's visible context...")
        
        if not game_context:
            print(f"[CLAUDE] No game context provided")
            return "[MY_VISIBLE_GAME_STATE: No context available] "
        
        print(f"[CLAUDE] Processing {len(game_context)} context keys...")
        
        # Create Marta's visible context (exclude her hidden hand AND secret discard info)
        marta_visible_context = {}
        
        for key, value in game_context.items():
            print(f"[CLAUDE] Processing key: {key} (type: {type(value).__name__})")
            
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
                print(f"[CLAUDE] Excluding key: {key}")
                continue
                
            # Convert and rename from Marta's perspective with safe handling
            try:
                if key == 'player_hand' and isinstance(value, list):
                    # Marta can only see count, not actual cards in opponent's hand
                    marta_visible_context['opponent_hand_size'] = len(value)
                    print(f"[CLAUDE] Converted player_hand to opponent_hand_size: {len(value)}")
                elif key == 'computer_hand_count':
                    marta_visible_context['my_hand_size'] = value
                    print(f"[CLAUDE] Set my_hand_size: {value}")
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
                    print(f"[CLAUDE] Converted current_trick: {len(converted_trick)} plays")
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
                    print(f"[CLAUDE] Converted trick_history: {len(converted_history)} tricks")
                # Handle discard cards ONLY if hand is over AND they exist
                elif key == 'player_discarded' and value and hand_is_over:
                    if isinstance(value, dict) and 'rank' in value and 'suit' in value:
                        opponent_discard = f"{value['rank']}{value['suit']}"
                        marta_visible_context['opponent_discarded'] = opponent_discard
                        marta_visible_context['opponent_discard_details'] = f"Opponent discarded {opponent_discard}"
                        print(f"[CLAUDE] Converted player_discarded to opponent_discarded")
                elif key == 'computer_discarded' and value and hand_is_over:
                    if isinstance(value, dict) and 'rank' in value and 'suit' in value:
                        my_discard = f"{value['rank']}{value['suit']}"
                        marta_visible_context['my_discarded'] = my_discard
                        marta_visible_context['my_discard_details'] = f"I discarded {my_discard}"
                        print(f"[CLAUDE] Converted computer_discarded to my_discarded")
                elif key.startswith('player_'):
                    # Rename player stats to opponent stats for Marta's perspective
                    new_key = key.replace('player_', 'opponent_')
                    marta_visible_context[new_key] = value
                    print(f"[CLAUDE] Renamed {key} to {new_key}")
                elif key.startswith('computer_'):
                    # Rename computer stats to my stats for Marta's perspective
                    new_key = key.replace('computer_', 'my_')
                    marta_visible_context[new_key] = value
                    print(f"[CLAUDE] Renamed {key} to {new_key}")
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
                        print(f"[CLAUDE] Excluding discard_bonus_explanation (hand not over)")
                        continue
                    # Only include serializable values
                    if isinstance(value, (str, int, float, bool, type(None))):
                        marta_visible_context[key] = value
                        print(f"[CLAUDE] Kept simple value: {key}")
                    else:
                        print(f"[CLAUDE] Skipping complex value: {key} (type: {type(value).__name__})")
                        
            except Exception as e:
                print(f"[CLAUDE] Error processing key {key}: {e}")
                continue
        
        # Rest of the function remains the same...
        print(f"[CLAUDE] Final context keys: {list(marta_visible_context.keys())}")
        
        # Test JSON conversion with detailed error handling
        try:
            context_json = json.dumps(marta_visible_context, separators=(',', ':'))
            print(f"[CLAUDE] JSON conversion successful, length: {len(context_json)} chars")
        except Exception as e:
            print(f"[CLAUDE] JSON conversion FAILED: {e}")
            return "[MY_VISIBLE_GAME_STATE: JSON conversion failed] "
        
        final_context = f"[MY_VISIBLE_GAME_STATE: {context_json}] "
        print(f"[CLAUDE] Final context length: {len(final_context)} chars")
        return final_context
    
    def _fallback_marta_response(self, game_context: Optional[Dict[str, Any]]) -> str:
        """Game-aware fallback responses from Marta's perspective as active player"""
        print(f"[CLAUDE] Generating Marta's fallback response...")
        
        if not game_context:
            fallbacks = [
                "Interesting question...",
                "You're keeping me on my toes.",
                "That's one way to look at it."
            ]
            import random
            selected = random.choice(fallbacks)
            print(f"[CLAUDE] No context fallback: '{selected}'")
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
                print(f"[CLAUDE] Contextual Marta fallback: '{selected}'")
                return selected
                
        except Exception as e:
            print(f"[CLAUDE] Error creating contextual fallback: {e}")
        
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
        print(f"[CLAUDE] Generic Marta fallback: '{selected}'")
        return selected
    
    def _get_api_key(self) -> Optional[str]:
        """Get API key from environment or Secret Manager with detailed logging"""
        print(f"[CLAUDE] === API KEY DETECTION ===")
        
        # First try environment variable
        api_key = os.getenv('ANTHROPIC_API_KEY')
        if api_key:
            print(f"[CLAUDE] Found API key in environment variable")
            print(f"[CLAUDE] Key length: {len(api_key)} chars")
            print(f"[CLAUDE] Key starts with: {api_key[:10]}...")
            return api_key
        
        print(f"[CLAUDE] No API key in environment variable")
        
        # Check if we're in Google Cloud
        is_gcp = self._is_google_cloud_environment()
        print(f"[CLAUDE] Running in Google Cloud: {is_gcp}")
        
        if is_gcp:
            print(f"[CLAUDE] Attempting to get key from Secret Manager...")
            return self._get_secret_from_manager()
        
        print(f"[CLAUDE] Not in Google Cloud environment")
        print(f"[CLAUDE] No API key source available")
        return None
    
    def _is_google_cloud_environment(self) -> bool:
        """Detect if we're running in Google Cloud with logging"""
        gae_env = os.getenv('GAE_ENV')
        k_service = os.getenv('K_SERVICE')
        gcp_project = os.getenv('GOOGLE_CLOUD_PROJECT')
        
        print(f"[CLAUDE] Environment check:")
        print(f"  GAE_ENV: {gae_env}")
        print(f"  K_SERVICE: {k_service}")
        print(f"  GOOGLE_CLOUD_PROJECT: {gcp_project}")
        
        is_gcp = (
            gae_env == 'standard' or
            k_service is not None or
            gcp_project is not None
        )
        
        print(f"[CLAUDE] Is Google Cloud: {is_gcp}")
        return is_gcp
    
    def _get_secret_from_manager(self) -> Optional[str]:
        """Get API key from Google Secret Manager with detailed logging"""
        print(f"[CLAUDE] === SECRET MANAGER ACCESS ===")
        
        if not GOOGLE_CLOUD_AVAILABLE:
            print(f"[CLAUDE] ERROR: Google Cloud libraries not available")
            return None
        
        try:
            project_id = os.getenv('GOOGLE_CLOUD_PROJECT')
            print(f"[CLAUDE] Project ID: {project_id}")
            
            if not project_id:
                print(f"[CLAUDE] ERROR: GOOGLE_CLOUD_PROJECT not set")
                return None
            
            print(f"[CLAUDE] Creating Secret Manager client...")
            client = secretmanager.SecretManagerServiceClient()
            
            secret_name = f"projects/{project_id}/secrets/ANTHROPIC_API_KEY/versions/latest"
            print(f"[CLAUDE] Secret path: {secret_name}")
            
            print(f"[CLAUDE] Accessing secret...")
            response = client.access_secret_version(request={"name": secret_name})
            
            secret_value = response.payload.data.decode("UTF-8")
            print(f"[CLAUDE] Secret retrieved successfully")
            print(f"[CLAUDE] Secret length: {len(secret_value)} chars")
            print(f"[CLAUDE] Secret starts with: {secret_value[:10]}...")
            
            return secret_value
            
        except Exception as e:
            print(f"[CLAUDE] ERROR accessing Secret Manager: {e}")
            print(f"[CLAUDE] Error type: {type(e)}")
            return None

# Singleton instance
_claude_chat = None

def get_claude_chat() -> ClaudeGameChat:
    """Get singleton Claude chat instance for Marta responses"""
    global _claude_chat
    if _claude_chat is None:
        print("[CLAUDE] Creating new ClaudeGameChat singleton instance (Marta as player)")
        _claude_chat = ClaudeGameChat()
    else:
        print("[CLAUDE] Using existing ClaudeGameChat singleton (Marta as player)")
    return _claude_chat

def get_smart_marta_response(player_message: str, game_state: Dict[str, Any]) -> str:
    """Convenience function to get Marta's response as active player"""
    print(f"[CLAUDE] get_smart_marta_response called (Marta as active player)")
    print(f"[CLAUDE] Opponent message: '{player_message}'")
    print(f"[CLAUDE] Game state keys: {list(game_state.keys()) if game_state else 'None'}")
    
    claude = get_claude_chat()
    response = claude.get_marta_response(player_message, game_state)
    
    print(f"[CLAUDE] Final Marta response: '{response}'")
    return response

# Test function for debugging
def test_claude_connection():
    """Test function to verify Claude API connectivity with Marta as player"""
    print(f"[CLAUDE] === TESTING CLAUDE CONNECTION (MARTA AS PLAYER) ===")
    
    try:
        claude = get_claude_chat()
        
        # Test with rich game context - simulating opponent asking about game state
        test_context = {
            'hand_number': 2,
            'phase': 'playing',
            'player_score': 89,  # Opponent's score
            'computer_score': 127,  # Marta's score
            'player_parity': 'odd',  # Opponent's parity
            'computer_parity': 'even',  # Marta's parity
            'player_bid': 4,  # Opponent's bid
            'computer_bid': 6,  # Marta's bid
            'player_tricks': 2,  # Opponent's tricks
            'computer_tricks': 3,  # Marta's tricks
            'player_bags': 1,  # Opponent's bags
            'computer_bags': 0,  # Marta's bags
            'hand_over': False,  # Hand still in progress - no discard info
            'trick_history': [
                {'number': 1, 'player_card': {'rank': '7', 'suit': '♣'}, 'computer_card': {'rank': 'A', 'suit': '♣'}, 'winner': 'computer'},
                {'number': 2, 'player_card': {'rank': 'K', 'suit': '♠'}, 'computer_card': {'rank': 'Q', 'suit': '♠'}, 'winner': 'player'}
            ]
        }
        
        test_response = claude.get_marta_response("How do you think this hand is going?", test_context)
        print(f"[CLAUDE] Marta player test successful: '{test_response}'")
        return True, test_response
    except Exception as e:
        print(f"[CLAUDE] Marta player test failed: {e}")
        return False, str(e)

if __name__ == "__main__":
    # Run test when script is executed directly
    success, result = test_claude_connection()
    print(f"Marta player test result: {success} - {result}")