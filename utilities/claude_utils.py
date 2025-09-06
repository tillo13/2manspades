# utilities/claude_utils.py
"""
Enhanced Claude API utilities for Two-Man Spades game
Full logging and debugging version to track API calls and responses
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
        print("[CLAUDE] Initializing ClaudeGameChat...")
        
        self.api_key = self._get_api_key()
        if not self.api_key:
            error_msg = "ANTHROPIC_API_KEY not found in environment or Secret Manager"
            print(f"[CLAUDE] ERROR: {error_msg}")
            raise ValueError(error_msg)
        
        print(f"[CLAUDE] API key found: {self.api_key[:10]}...{self.api_key[-4:] if len(self.api_key) > 14 else 'SHORT'}")
        
        try:
            self.client = anthropic.Anthropic(api_key=self.api_key)
            print("[CLAUDE] Anthropic client initialized successfully")
        except Exception as e:
            print(f"[CLAUDE] ERROR initializing Anthropic client: {e}")
            raise e
        
        self.model = "claude-3-5-haiku-20241022"
        self.max_tokens = 75
        self.temperature = 0.6
        
        self.system_prompt = (
            "You are Marta, a seasoned spades player with a poker face and sharp wit. "
            "You're playing Two-Man Spades - a custom variant with parity scoring, blind bidding, and special bag-reduction cards. "
            "Be snarky, witty, and competitive. Drop hints but never give away strategy. "
            "Make poker-faced comments that could be bluffs. Keep responses under 15 words. "
            "Reference the current game state cleverly without being helpful to your opponent."
        )
        
        print(f"[CLAUDE] Configuration:")
        print(f"  Model: {self.model}")
        print(f"  Max tokens: {self.max_tokens}")
        print(f"  Temperature: {self.temperature}")
        print(f"  System prompt length: {len(self.system_prompt)} chars")
    
    def get_marta_response(self, 
                          player_message: str, 
                          game_context: Optional[Dict[str, Any]] = None) -> str:
        """Get a witty, game-aware response from Marta with full logging"""
        print(f"\n[CLAUDE] === NEW CHAT REQUEST ===")
        print(f"[CLAUDE] Player message: '{player_message}'")
        print(f"[CLAUDE] Game context received: {bool(game_context)}")
        
        if game_context:
            print(f"[CLAUDE] Context keys: {list(game_context.keys())}")
        
        try:
            context_str = self._build_enhanced_context(game_context)
            print(f"[CLAUDE] Built context string: '{context_str}'")
            
            user_prompt = f"{context_str}Player said: '{player_message}'"
            print(f"[CLAUDE] Full user prompt: '{user_prompt}'")
            print(f"[CLAUDE] Prompt length: {len(user_prompt)} chars")
            
            print(f"[CLAUDE] Making API call to {self.model}...")
            print(f"[CLAUDE] API call parameters:")
            print(f"  - max_tokens: {self.max_tokens}")
            print(f"  - temperature: {self.temperature}")
            
            response = self.client.messages.create(
                model=self.model,
                max_tokens=self.max_tokens,
                temperature=self.temperature,
                system=self.system_prompt,
                messages=[{
                    "role": "user", 
                    "content": user_prompt
                }],
            )
            
            print(f"[CLAUDE] API call successful!")
            print(f"[CLAUDE] Response object type: {type(response)}")
            print(f"[CLAUDE] Response content length: {len(response.content)}")
            
            api_response = response.content[0].text.strip()
            print(f"[CLAUDE] Raw API response: '{api_response}'")
            print(f"[CLAUDE] Response length: {len(api_response)} chars")
            
            if not api_response:
                print(f"[CLAUDE] WARNING: Empty response from API")
                return self._fallback_snarky_response(game_context)
            
            print(f"[CLAUDE] SUCCESS: Returning API response")
            return api_response
            
        except anthropic.APIError as e:
            print(f"[CLAUDE] Anthropic API Error: {e}")
            print(f"[CLAUDE] Error type: {type(e)}")
            fallback = self._fallback_snarky_response(game_context)
            print(f"[CLAUDE] Using API error fallback: '{fallback}'")
            return fallback
            
        except Exception as e:
            print(f"[CLAUDE] Unexpected error: {e}")
            print(f"[CLAUDE] Error type: {type(e)}")
            fallback = self._fallback_snarky_response(game_context)
            print(f"[CLAUDE] Using general error fallback: '{fallback}'")
            return fallback
    
    def get_contextual_greeting(self, game_context: Dict[str, Any]) -> str:
        """Get a context-aware snarky greeting with logging"""
        print(f"\n[CLAUDE] === GREETING REQUEST ===")
        print(f"[CLAUDE] Game context: {json.dumps(game_context, indent=2) if game_context else 'None'}")
        
        try:
            context_str = self._build_enhanced_context(game_context)
            print(f"[CLAUDE] Greeting context: '{context_str}'")
            
            if game_context.get('hand_number', 1) == 1:
                prompt = f"{context_str}Give a brief, confident game start comment (8 words max)"
                print(f"[CLAUDE] Game start greeting prompt")
            else:
                prompt = f"{context_str}Give a brief, snarky new hand comment (8 words max)"
                print(f"[CLAUDE] New hand greeting prompt")
            
            print(f"[CLAUDE] Full greeting prompt: '{prompt}'")
            
            response = self.client.messages.create(
                model=self.model,
                max_tokens=40,
                temperature=0.7,
                system=self.system_prompt,
                messages=[{"role": "user", "content": prompt}]
            )
            
            greeting = response.content[0].text.strip()
            print(f"[CLAUDE] Greeting API response: '{greeting}'")
            
            return greeting
            
        except Exception as e:
            print(f"[CLAUDE] Greeting error: {e}")
            fallback = self._fallback_greeting(game_context)
            print(f"[CLAUDE] Using greeting fallback: '{fallback}'")
            return fallback
    
    def _build_enhanced_context(self, game_context: Optional[Dict[str, Any]]) -> str:
        """Build enhanced context for snarky, informed responses with logging"""
        print(f"[CLAUDE] Building enhanced context...")
        
        if not game_context:
            print(f"[CLAUDE] No game context provided")
            return "[Two-Man Spades game context unknown] "
        
        # Core game info
        hand = game_context.get('hand_number', 1)
        phase = game_context.get('phase', 'playing')
        player_score = game_context.get('player_score', 0)
        marta_score = game_context.get('computer_score', 0)
        player_parity = game_context.get('player_parity', 'even')
        computer_parity = game_context.get('computer_parity', 'odd')
        
        print(f"[CLAUDE] Core context - Hand: {hand}, Phase: {phase}")
        print(f"[CLAUDE] Scores - Player: {player_score}, Marta: {marta_score}")
        print(f"[CLAUDE] Parity - Player: {player_parity}, Marta: {computer_parity}")
        
        context_parts = [
            f"Two-Man Spades Hand {hand}, {phase} phase",
            f"Parity: You({player_parity}) vs Me({computer_parity})",
            f"Scores: You {player_score}, Me {marta_score}"
        ]
        
        # Add bags context
        player_bags = game_context.get('player_bags', 0)
        marta_bags = game_context.get('computer_bags', 0)
        print(f"[CLAUDE] Bags - Player: {player_bags}, Marta: {marta_bags}")
        
        if player_bags != 0 or marta_bags != 0:
            context_parts.append(f"Bags: You {player_bags}, Me {marta_bags}")
        
        # Add bidding context
        player_bid = game_context.get('player_bid')
        marta_bid = game_context.get('computer_bid')
        print(f"[CLAUDE] Bids - Player: {player_bid}, Marta: {marta_bid}")
        
        if player_bid is not None and marta_bid is not None:
            player_blind = " BLIND" if game_context.get('blind_bid') == player_bid else ""
            marta_blind = " BLIND" if game_context.get('computer_blind_bid') == marta_bid else ""
            context_parts.append(f"Bids: You {player_bid}{player_blind}, Me {marta_bid}{marta_blind}")
            print(f"[CLAUDE] Blind bids - Player: {bool(player_blind)}, Marta: {bool(marta_blind)}")
        
        # Add current trick progress
        if phase == 'playing':
            player_tricks = game_context.get('player_tricks', 0)
            marta_tricks = game_context.get('computer_tricks', 0)
            context_parts.append(f"Tricks taken: You {player_tricks}, Me {marta_tricks}")
            print(f"[CLAUDE] Tricks taken - Player: {player_tricks}, Marta: {marta_tricks}")
            
            turn = game_context.get('turn', 'unknown')
            if turn != 'unknown':
                context_parts.append(f"Turn: {turn}")
                print(f"[CLAUDE] Current turn: {turn}")
        
        # Add game status hints
        score_diff = marta_score - player_score
        if score_diff >= 100:
            context_parts.append("(I'm winning big)")
            print(f"[CLAUDE] Game status: Marta winning by {score_diff}")
        elif score_diff <= -100:
            context_parts.append("(You're ahead - for now)")
            print(f"[CLAUDE] Game status: Player winning by {abs(score_diff)}")
        elif abs(score_diff) <= 20:
            context_parts.append("(Close game)")
            print(f"[CLAUDE] Game status: Close game (diff: {abs(score_diff)})")
        
        final_context = f"[{' | '.join(context_parts)}] "
        print(f"[CLAUDE] Final context string: '{final_context}'")
        print(f"[CLAUDE] Context length: {len(final_context)} chars")
        
        return final_context
    
    def _fallback_snarky_response(self, game_context: Optional[Dict[str, Any]]) -> str:
        """Snarky fallback responses when API fails with logging"""
        print(f"[CLAUDE] Generating fallback snarky response...")
        
        snarky_fallbacks = [
            "Interesting move...",
            "We'll see about that.",
            "Playing it safe, are we?",
            "Cute strategy.",
            "My turn to surprise you.",
            "You're full of surprises.",
            "Let's see how this plays out.",
            "Confidence is key, they say.",
            "Bold choice.",
            "I see what you're doing."
        ]
        
        import random
        selected = random.choice(snarky_fallbacks)
        print(f"[CLAUDE] Selected fallback: '{selected}'")
        return selected
    
    def _fallback_greeting(self, game_context: Dict[str, Any]) -> str:
        """Snarky fallback greetings with logging"""
        print(f"[CLAUDE] Generating fallback greeting...")
        
        if game_context.get('hand_number', 1) == 1:
            greeting = "Ready to lose?"
            print(f"[CLAUDE] Game start fallback: '{greeting}'")
        else:
            greeting = "Next victim... I mean, hand!"
            print(f"[CLAUDE] New hand fallback: '{greeting}'")
        
        return greeting
    
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
    """Get singleton Claude chat instance with logging"""
    global _claude_chat
    if _claude_chat is None:
        print("[CLAUDE] Creating new ClaudeGameChat singleton instance")
        _claude_chat = ClaudeGameChat()
    else:
        print("[CLAUDE] Using existing ClaudeGameChat singleton")
    return _claude_chat

def get_smart_marta_response(player_message: str, game_state: Dict[str, Any]) -> str:
    """Convenience function to get Marta's response with logging"""
    print(f"[CLAUDE] get_smart_marta_response called")
    print(f"[CLAUDE] Message: '{player_message}'")
    print(f"[CLAUDE] Game state keys: {list(game_state.keys()) if game_state else 'None'}")
    
    claude = get_claude_chat()
    response = claude.get_marta_response(player_message, game_state)
    
    print(f"[CLAUDE] Final response from get_smart_marta_response: '{response}'")
    return response

def get_smart_marta_greeting(game_state: Dict[str, Any]) -> str:
    """Convenience function to get Marta's contextual greeting with logging"""
    print(f"[CLAUDE] get_smart_marta_greeting called")
    print(f"[CLAUDE] Game state keys: {list(game_state.keys()) if game_state else 'None'}")
    
    claude = get_claude_chat()
    greeting = claude.get_contextual_greeting(game_state)
    
    print(f"[CLAUDE] Final greeting from get_smart_marta_greeting: '{greeting}'")
    return greeting

# Test function for debugging
def test_claude_connection():
    """Test function to verify Claude API connectivity"""
    print(f"[CLAUDE] === TESTING CLAUDE CONNECTION ===")
    
    try:
        claude = get_claude_chat()
        test_response = claude.get_marta_response(
            "Hello test", 
            {'hand_number': 1, 'phase': 'testing', 'player_score': 0, 'computer_score': 0}
        )
        print(f"[CLAUDE] Test successful: '{test_response}'")
        return True, test_response
    except Exception as e:
        print(f"[CLAUDE] Test failed: {e}")
        return False, str(e)

if __name__ == "__main__":
    # Run test when script is executed directly
    success, result = test_claude_connection()
    print(f"Test result: {success} - {result}")