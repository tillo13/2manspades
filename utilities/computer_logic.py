"""
Computer AI logic for Two-Man Spades
Handles all computer decision making including bidding, discarding, and play strategy
"""
import random
from .custom_rules import (
    get_discard_value, 
    is_special_card, 
    check_blind_bidding_eligibility,
    apply_blind_scoring
)

from .logging_utils import log_game_event

# =============================================================================
# GLOBAL AI DIFFICULTY SETTINGS
# =============================================================================

# Discard Strategy Settings
SINGLETON_SPECIAL_PRIORITY = 1000    # How much to prioritize discarding singleton 7♦/10♣
VOID_CREATION_PRIORITY = 500         # How much to value creating voids
SPECIAL_CARD_PROTECTION = -100       # Penalty for discarding protected special cards
SPADE_DISCARD_PENALTY = 3           # Multiplier for avoiding spade discards
PARITY_CONSIDERATION = 1            # Small bonus for parity-favorable discards

# Bidding Strategy Settings  
BID_ACCURACY_BOOST = 0.8            # How much to boost base expectations (higher = more aggressive)
NIL_RISK_TOLERANCE = 0.8            # Threshold for nil bidding (lower = more nil attempts)
BLIND_DESPERATION_THRESHOLD = 120   # Points behind before considering blind bids
SCORE_BASED_ADJUSTMENT = 0.05       # How much score differential affects bidding
NIL_STRICTNESS = 0.8                # Lower = more likely to nil (minimum expectation for non-nil)

# Playing Strategy Settings
BAG_AVOIDANCE_STRENGTH = 0.92       # Multiplier when trying to avoid bags (lower = more avoidance)
SPECIAL_CARD_FOLLOWING_PROTECTION = True  # Whether to avoid playing special cards when following
LEAD_SAFETY_CONSIDERATION = True     # Whether to avoid leading into dangerous suits

# Meta-Strategy Settings
OPPONENT_MODELING = False            # Whether to try predicting opponent plays (future feature)
RISK_TAKING_PERSONALITY = 0.5       # 0.0 = very conservative, 1.0 = very aggressive
DEFAULT_BLIND_BID = 5

# =============================================================================
# HAND ANALYSIS FUNCTIONS
# =============================================================================

def analyze_hand_strength(hand):
    """
    Analyze hand strength and return expected trick count
    Returns tuple: (sure_tricks, probable_tricks, special_card_bonus)
    """
    sure_tricks = 0
    probable_tricks = 0
    special_card_bonus = 0
    
    # Count special cards for strategic value
    for card in hand:
        is_special, bag_reduction = is_special_card(card)
        if is_special:
            special_card_bonus += 0.2  # Special cards provide strategic value
    
    # Separate spades from other suits
    spades = [card for card in hand if card['suit'] == '♠']
    other_suits = [card for card in hand if card['suit'] != '♠']
    
    # Group other suits
    suits = {'♥': [], '♦': [], '♣': []}
    for card in other_suits:
        suits[card['suit']].append(card)
    
    # ENHANCED SPADES ANALYSIS
    spade_values = sorted([card['value'] for card in spades], reverse=True)
    spade_count = len(spades)
    
    # Apply spade count expectations
    if spade_count >= 5:
        sure_tricks += 3.0  # Expect 5 tricks from 5+ spades
        probable_tricks += 2.0
    elif spade_count == 4:
        sure_tricks += 2.0  # Expect 3 tricks from 4 spades  
        probable_tricks += 1.0
    elif spade_count == 3:
        sure_tricks += 1.5  # Expect 2 tricks from 3 spades
        probable_tricks += 0.5
    elif spade_count == 2:
        sure_tricks += 0.8  # Modest expectation from 2 spades
        probable_tricks += 0.4
    elif spade_count == 1:
        sure_tricks += 0.3  # Low expectation from 1 spade
    
    # High spades get additional value on top of count-based expectations
    ace_spades = sum(1 for v in spade_values if v == 14)
    king_spades = sum(1 for v in spade_values if v == 13)
    queen_spades = sum(1 for v in spade_values if v == 12)
    
    if ace_spades > 0:
        sure_tricks += 0.3 * ace_spades  # Ace of spades is nearly guaranteed
    if king_spades > 0:
        sure_tricks += 0.2 * king_spades  # King of spades very likely
    if queen_spades > 0:
        probable_tricks += 0.2 * queen_spades  # Queen adds some value
    
    # ENHANCED OTHER SUITS ANALYSIS
    aces_other_suits = 0
    kings_other_suits = 0
    
    for suit, cards in suits.items():
        if not cards:
            continue
            
        values = sorted([card['value'] for card in cards], reverse=True)
        
        # Count high cards for overall hand strength
        aces_in_suit = sum(1 for v in values if v == 14)
        kings_in_suit = sum(1 for v in values if v == 13)
        
        aces_other_suits += aces_in_suit
        kings_other_suits += kings_in_suit
        
        # Aces in other suits (can be trumped but still strong)
        if 14 in values:
            sure_tricks += 0.8 * aces_in_suit  # High but not guaranteed
        
        # Protected kings (with ace)
        if 13 in values and 14 in values:
            sure_tricks += 0.6 * kings_in_suit  # Protected kings are strong
        elif 13 in values:
            if len(cards) >= 3:  # King in long suit has protection
                probable_tricks += 0.5 * kings_in_suit
            else:  # Unprotected king
                probable_tricks += 0.3 * kings_in_suit
        
        # Long suits can generate tricks through length
        if len(cards) >= 4:
            probable_tricks += (len(cards) - 3) * 0.25
    
    # MULTIPLE HIGH CARDS BONUS
    total_high_cards = aces_other_suits + kings_other_suits + ace_spades + king_spades
    
    if total_high_cards >= 4:
        sure_tricks += 0.5  # Multiple high cards create synergy
        probable_tricks += 0.3
    elif total_high_cards >= 3:
        sure_tricks += 0.3
        probable_tricks += 0.2
    elif total_high_cards >= 2:
        probable_tricks += 0.2
    
    # VOID SUITS (can trump)
    void_suits = sum(1 for cards in suits.values() if len(cards) == 0)
    if void_suits > 0 and spade_count >= 2:
        probable_tricks += void_suits * 0.4  # Void + spades = trumping opportunities
    
    return sure_tricks, probable_tricks, special_card_bonus

def analyze_suit_distribution(hand):
    """Analyze suit distribution and identify singleton/void opportunities"""
    suits = {'♥': [], '♦': [], '♣': [], '♠': []}
    
    for card in hand:
        suits[card['suit']].append(card)
    
    distribution = {}
    for suit, cards in suits.items():
        distribution[suit] = {
            'count': len(cards),
            'cards': cards,
            'is_void': len(cards) == 0,
            'is_singleton': len(cards) == 1
        }
    
    return distribution

# =============================================================================
# DISCARD STRATEGY
# =============================================================================

def computer_discard_strategy(computer_hand, game_state):
    """
    Enhanced discard strategy prioritizing singleton special cards and void creation
    Returns index of card to discard
    """
    player_parity = game_state.get('player_parity', 'even')
    computer_parity = game_state.get('computer_parity', 'odd')
    
    # Analyze suit distribution
    suit_distribution = analyze_suit_distribution(computer_hand)
    
    discard_candidates = []
    
    for i, card in enumerate(computer_hand):
        score = 0
        suit_info = suit_distribution[card['suit']]
        
        # PRIORITY 1: Singleton special cards - MUST discard these
        if suit_info['is_singleton'] and card['suit'] != '♠':
            is_special, _ = is_special_card(card)
            if is_special:
                score += SINGLETON_SPECIAL_PRIORITY
                discard_candidates.append((i, score))
                continue  # Don't apply other penalties to singleton specials
        
        # PRIORITY 2: Void creation (singleton non-specials in non-spade suits)
        elif suit_info['is_singleton'] and card['suit'] != '♠':
            spade_count = suit_distribution['♠']['count']
            # More spades = void is more valuable
            void_value = (spade_count * VOID_CREATION_PRIORITY) // 10
            if spade_count >= 4:  # Strong spade holding
                void_value += (VOID_CREATION_PRIORITY // 4)
            void_value -= card['value']  # Prefer discarding low cards
            score += void_value
        
        # PRIORITY 3: Normal special card protection (protected specials)
        else:
            is_special, _ = is_special_card(card)
            if is_special:
                score += SPECIAL_CARD_PROTECTION  # Negative score
        
        # PRIORITY 4: Avoid discarding spades
        if card['suit'] == '♠':
            score -= card['value'] * SPADE_DISCARD_PENALTY
        else:
            # Prefer discarding low cards from other suits
            score += (15 - card['value'])
        
        # PRIORITY 5: Light parity consideration
        discard_value = get_discard_value(card)
        if computer_parity == 'even' and discard_value % 2 == 1:
            score += PARITY_CONSIDERATION
        elif computer_parity == 'odd' and discard_value % 2 == 0:
            score += PARITY_CONSIDERATION
        
        discard_candidates.append((i, score))
    
    # Return index of card with highest discard score
    return max(discard_candidates, key=lambda x: x[1])[0]

# =============================================================================
# BIDDING STRATEGY
# =============================================================================

def should_bid_nil(hand, game_state):
    """
    Determine if computer should bid nil (using configurable strictness)
    """
    player_score = game_state.get('player_score', 0)
    computer_score = game_state.get('computer_score', 0)
    player_bid = game_state.get('player_bid', 0)
    
    # Get hand strength
    sure_tricks, probable_tricks, special_bonus = analyze_hand_strength(hand)
    total_expectation = sure_tricks + probable_tricks + special_bonus
    
    # Use configurable nil threshold
    if total_expectation > NIL_STRICTNESS:
        return False
    
    # Must have very few spades and they must be low
    spades = [card for card in hand if card['suit'] == '♠']
    if len(spades) > 3:  # At most 3 spades
        return False
    
    # No high spades allowed
    for spade in spades:
        if spade['value'] >= 11:  # No J, Q, K, A of spades
            return False
    
    # Must have at least 2 twos for safety
    twos = [card for card in hand if card['rank'] == '2']
    if len(twos) < 2:
        return False
    
    # Must have mostly very low cards (2-7) in other suits
    other_suits = [card for card in hand if card['suit'] != '♠']
    low_cards = [card for card in other_suits if card['value'] <= 7]
    
    if len(low_cards) < len(other_suits) - 1:
        return False
    
    # No aces or kings in other suits
    high_other_suits = [card for card in other_suits if card['value'] >= 13]
    if len(high_other_suits) > 0:
        return False
    
    # Don't nil if player already bid nil
    if player_bid == 0:
        return False
    
    # Only nil when significantly behind
    if computer_score >= player_score - 50:
        return False
    
    # Conservative probability - only when truly desperate
    return computer_score < player_score - 80

def should_bid_blind(hand, game_state):
    """
    Determine if computer should bid blind when eligible
    Returns tuple: (should_blind, blind_bid_amount)
    """
    player_score = game_state.get('player_score', 0)
    computer_score = game_state.get('computer_score', 0)
    
    # Check eligibility
    blind_eligibility = check_blind_bidding_eligibility(player_score, computer_score)
    if not blind_eligibility['computer_eligible']:
        return False, 0
    
    # If down by 100+, just go blind 5 (simplest aggressive strategy)
    return True, DEFAULT_BLIND_BID

def computer_bidding_brain(computer_hand, player_bid, game_state):
    """
    Main computer bidding function with configurable AI settings
    Returns tuple: (bid_amount, is_blind)
    """
    player_score = game_state.get('player_score', 0)
    computer_score = game_state.get('computer_score', 0)
    computer_bags = game_state.get('computer_bags', 0)
    
    # Check for nil opportunity first
    if should_bid_nil(computer_hand, game_state):
        return 0, False
    
    # Check for blind bidding opportunity
    should_blind, blind_amount = should_bid_blind(computer_hand, game_state)
    if should_blind:
        return blind_amount, True
    
    # Regular bidding logic
    sure_tricks, probable_tricks, special_bonus = analyze_hand_strength(computer_hand)
    base_expectation = sure_tricks + probable_tricks + special_bonus
    
    # Apply configurable accuracy boost
    base_expectation += BID_ACCURACY_BOOST
    
    # Score-based adjustments (using configurable multiplier)
    score_diff = computer_score - player_score
    if score_diff > 30:  # Ahead - be slightly conservative
        base_expectation *= (1 - SCORE_BASED_ADJUSTMENT)
    elif score_diff < -30:  # Behind - be slightly aggressive
        base_expectation *= (1 + SCORE_BASED_ADJUSTMENT)
    
    # Bag avoidance when close to penalty
    if computer_bags >= 5:
        base_expectation *= BAG_AVOIDANCE_STRENGTH
    
    # Strategic response to player's bid
    if player_bid is not None:
        if player_bid == 0:  # Player nil - be aggressive to set them
            base_expectation += 0.3
        elif player_bid <= 2:  # Player bid low
            base_expectation += 0.15
        elif player_bid >= 7:  # Player bid high
            base_expectation -= 0.2
    
    # Convert to bid
    raw_bid = max(0, min(10, round(base_expectation)))
    
    # Bid range preferences
    if 2.5 <= base_expectation <= 5.5:
        if raw_bid < 3:
            raw_bid = 3  # Minimum reasonable bid is 3
        elif raw_bid == 5 and random.random() < 0.4:
            raw_bid = 4  # Sometimes prefer 4 over 5
    
    # Avoid obvious total-10 scenarios
    if player_bid is not None and abs((raw_bid + player_bid) - 10) <= 1 and random.random() < 0.3:
        if raw_bid > 3:
            raw_bid -= 1
        elif raw_bid < 7:
            raw_bid += 1
    
    # Final bounds check
    raw_bid = max(1, min(10, raw_bid))
    
    return raw_bid, False

# =============================================================================
# PLAYING STRATEGY
# =============================================================================

def computer_lead_strategy(computer_hand, spades_broken):
    """
    Enhanced leading strategy - avoid leading into special cards when possible
    Returns index of best card to lead, or None if no valid leads
    """
    if not computer_hand:
        return None
    
    # Find all valid leads
    valid_leads = []
    for i, card in enumerate(computer_hand):
        if card['suit'] != '♠' or spades_broken or all(c['suit'] == '♠' for c in computer_hand):
            valid_leads.append((i, card))
    
    if not valid_leads:
        return None
    
    # Categorize leads by danger level (if safety consideration is enabled)
    if LEAD_SAFETY_CONSIDERATION:
        safe_leads = []
        risky_leads = []
        dangerous_leads = []
        
        for i, card in valid_leads:
            suit = card['suit']
            rank = card['rank']
            
            # Check if leading this suit could give opponent special cards
            if suit == '♣':
                # Leading clubs could set up 10♣ for opponent
                if rank in ['J', 'Q', 'K', 'A']:
                    dangerous_leads.append((i, card))
                elif rank in ['8', '9', '10']:
                    risky_leads.append((i, card))
                else:
                    safe_leads.append((i, card))
            elif suit == '♦':
                # Leading diamonds could set up 7♦ for opponent  
                if rank in ['J', 'Q', 'K', 'A']:
                    dangerous_leads.append((i, card))
                elif rank in ['6', '7', '8']:
                    risky_leads.append((i, card))
                else:
                    safe_leads.append((i, card))
            else:
                # Hearts and spades are generally safer
                safe_leads.append((i, card))
        
        # Choose lead in order of preference: safe > risky > dangerous
        if safe_leads:
            chosen = min(safe_leads, key=lambda x: x[1]['value'])
        elif risky_leads:
            chosen = min(risky_leads, key=lambda x: x[1]['value'])
        else:
            chosen = min(dangerous_leads, key=lambda x: x[1]['value'])
    else:
        # Simple strategy - just lead lowest valid card
        chosen = min(valid_leads, key=lambda x: x[1]['value'])
    
    return chosen[0]

def computer_follow_strategy(computer_hand, current_trick, game_state):
    """
    Enhanced strategy for when computer must follow suit - includes bag avoidance and special card protection
    Returns index of best card to play
    """
    if not current_trick or not computer_hand:
        return None
    
    computer_bid = game_state.get('computer_bid', 0)
    computer_tricks = game_state.get('computer_tricks', 0)
    
    # Check if computer has already made their bid
    bid_already_made = computer_tricks >= computer_bid and computer_bid > 0
    
    lead_card = current_trick[0]['card']
    lead_suit = lead_card['suit']
    lead_value = lead_card['value']
    
    # Find valid plays and categorize by special card status
    same_suit = []
    same_suit_special = []
    spades = []
    spades_special = []
    other = []
    other_special = []
    
    for i, card in enumerate(computer_hand):
        is_special, _ = is_special_card(card)
        
        if card['suit'] == lead_suit:
            if is_special:
                same_suit_special.append((i, card))
            else:
                same_suit.append((i, card))
        elif card['suit'] == '♠':
            if is_special:
                spades_special.append((i, card))
            else:
                spades.append((i, card))
        else:
            if is_special:
                other_special.append((i, card))
            else:
                other.append((i, card))
    
    # Combine same suit cards (prioritize non-special if protection is enabled)
    if SPECIAL_CARD_FOLLOWING_PROTECTION:
        all_same_suit = same_suit + same_suit_special
        all_spades = spades + spades_special
        all_other = other + other_special
    else:
        all_same_suit = same_suit_special + same_suit
        all_spades = spades_special + spades
        all_other = other_special + other
    
    if all_same_suit:
        # Must follow suit
        winners = [(i, c) for i, c in all_same_suit if c['value'] > lead_value]
        losers = [(i, c) for i, c in all_same_suit if c['value'] <= lead_value]
        
        if SPECIAL_CARD_FOLLOWING_PROTECTION:
            # Separate special cards from regular cards in each category
            winners_regular = [(i, c) for i, c in winners if not is_special_card(c)[0]]
            winners_special = [(i, c) for i, c in winners if is_special_card(c)[0]]
            losers_regular = [(i, c) for i, c in losers if not is_special_card(c)[0]]
            losers_special = [(i, c) for i, c in losers if is_special_card(c)[0]]
            
            if bid_already_made:
                # Try to avoid winning (avoid bags), protect special cards
                if losers_regular:
                    return max(losers_regular, key=lambda x: x[1]['value'])[0]
                elif losers_special:
                    return max(losers_special, key=lambda x: x[1]['value'])[0]
                elif winners_regular:
                    return min(winners_regular, key=lambda x: x[1]['value'])[0]
                else:
                    return min(winners_special, key=lambda x: x[1]['value'])[0]
            else:
                # Still need tricks - try to win, avoid wasting special cards
                if winners_regular:
                    return min(winners_regular, key=lambda x: x[1]['value'])[0]
                elif winners_special:
                    return min(winners_special, key=lambda x: x[1]['value'])[0]
                elif losers_regular:
                    return min(losers_regular, key=lambda x: x[1]['value'])[0]
                else:
                    return min(losers_special, key=lambda x: x[1]['value'])[0]
        else:
            # Simple strategy without special card protection
            if bid_already_made:
                if losers:
                    return max(losers, key=lambda x: x[1]['value'])[0]
                else:
                    return min(winners, key=lambda x: x[1]['value'])[0]
            else:
                if winners:
                    return min(winners, key=lambda x: x[1]['value'])[0]
                else:
                    return min(losers, key=lambda x: x[1]['value'])[0]
                
    elif lead_suit != '♠' and all_spades:
        # Can trump with spade
        if bid_already_made:
            # Try to avoid trumping unless forced
            if all_other:
                if SPECIAL_CARD_FOLLOWING_PROTECTION:
                    non_special_other = [x for x in all_other if not is_special_card(x[1])[0]]
                    if non_special_other:
                        return min(non_special_other, key=lambda x: x[1]['value'])[0]
                    else:
                        return min(all_other, key=lambda x: x[1]['value'])[0]
                else:
                    return min(all_other, key=lambda x: x[1]['value'])[0]
            else:
                # Must trump
                if SPECIAL_CARD_FOLLOWING_PROTECTION:
                    non_special_spades = [x for x in all_spades if not is_special_card(x[1])[0]]
                    if non_special_spades:
                        return min(non_special_spades, key=lambda x: x[1]['value'])[0]
                    else:
                        return min(all_spades, key=lambda x: x[1]['value'])[0]
                else:
                    return min(all_spades, key=lambda x: x[1]['value'])[0]
        else:
            # Still need tricks - trump but protect special cards if possible
            if SPECIAL_CARD_FOLLOWING_PROTECTION:
                non_special_spades = [x for x in all_spades if not is_special_card(x[1])[0]]
                if non_special_spades:
                    return min(non_special_spades, key=lambda x: x[1]['value'])[0]
                else:
                    return min(all_spades, key=lambda x: x[1]['value'])[0]
            else:
                return min(all_spades, key=lambda x: x[1]['value'])[0]
    else:
        # Can't follow or trump - discard lowest
        if SPECIAL_CARD_FOLLOWING_PROTECTION:
            non_special_other = [x for x in all_other if not is_special_card(x[1])[0]]
            if non_special_other:
                return min(non_special_other, key=lambda x: x[1]['value'])[0]
            else:
                all_cards = [(i, c) for i, c in enumerate(computer_hand)]
                return min(all_cards, key=lambda x: x[1]['value'])[0]
        else:
            all_cards = [(i, c) for i, c in enumerate(computer_hand)]
            return min(all_cards, key=lambda x: x[1]['value'])[0]

# =============================================================================
# DIFFICULTY ADJUSTMENT FUNCTIONS (Future Enhancement)
# =============================================================================

def set_difficulty_easy():
    """Set all AI parameters for easy difficulty"""
    global SINGLETON_SPECIAL_PRIORITY, VOID_CREATION_PRIORITY, BID_ACCURACY_BOOST
    global NIL_RISK_TOLERANCE, SPECIAL_CARD_FOLLOWING_PROTECTION
    
    # Make poor decisions
    SINGLETON_SPECIAL_PRIORITY = 50  # Sometimes keeps singleton specials
    VOID_CREATION_PRIORITY = 100     # Doesn't prioritize voids much
    BID_ACCURACY_BOOST = 0.2         # Under-bids frequently
    NIL_RISK_TOLERANCE = 1.5         # Rarely goes nil
    SPECIAL_CARD_FOLLOWING_PROTECTION = False  # Doesn't protect specials

def set_difficulty_hard():
    """Set all AI parameters for hard difficulty"""
    global SINGLETON_SPECIAL_PRIORITY, VOID_CREATION_PRIORITY, BID_ACCURACY_BOOST
    global NIL_RISK_TOLERANCE, SPECIAL_CARD_FOLLOWING_PROTECTION
    
    # Optimal play
    SINGLETON_SPECIAL_PRIORITY = 1000
    VOID_CREATION_PRIORITY = 500
    BID_ACCURACY_BOOST = 0.8
    NIL_RISK_TOLERANCE = 0.8
    SPECIAL_CARD_FOLLOWING_PROTECTION = True

def set_difficulty_custom(settings_dict):
    """Set AI parameters from a dictionary"""
    globals().update(settings_dict)


def autoplay_remaining_cards(game, session_obj=None):
    """
    Check for mathematically certain scenarios and auto-resolve remaining tricks.
    Only auto-resolves when 3-9 cards remain to preserve engagement.
    Returns (was_auto_resolved, explanation)
    """
    player_hand_size = len(game['player_hand'])
    computer_hand_size = len(game['computer_hand'])
    
    # Only auto-resolve if 3-9 cards remain (don't auto-play final 1-2 tricks)
    if player_hand_size == 0 or computer_hand_size == 0:
        return False, ""
    if player_hand_size < 3 or player_hand_size > 9:
        return False, ""
    
    player_suits = set(card['suit'] for card in game['player_hand'])
    computer_suits = set(card['suit'] for card in game['computer_hand'])
    winner = game.get('trick_winner')
    
    auto_resolved = False
    explanation = ""
    tricks_to_award = 0
    
    # Case 1: One player only spades, other no spades
    if player_suits == {'♠'} and '♠' not in computer_suits:
        tricks_to_award = len(game['player_hand'])
        game['player_tricks'] += tricks_to_award
        auto_resolved = True
        explanation = f"Auto-resolved: You had only spades ({tricks_to_award} cards), Marta had none"
        winner_of_remaining = 'player'
    elif computer_suits == {'♠'} and '♠' not in player_suits:
        tricks_to_award = len(game['computer_hand'])
        game['computer_tricks'] += tricks_to_award
        auto_resolved = True
        explanation = f"Auto-resolved: Marta had only spades ({tricks_to_award} cards), you had none"
        winner_of_remaining = 'computer'
    # Case 2: Trick winner has one suit, loser has none of it and no spades
    elif winner == 'player' and len(player_suits) == 1:
        player_suit = list(player_suits)[0]
        if player_suit not in computer_suits and '♠' not in computer_suits:
            tricks_to_award = len(game['player_hand'])
            game['player_tricks'] += tricks_to_award
            auto_resolved = True
            explanation = f"Auto-resolved: You had only {player_suit} ({tricks_to_award} cards), Marta had none and no spades"
            winner_of_remaining = 'player'
    elif winner == 'computer' and len(computer_suits) == 1:
        computer_suit = list(computer_suits)[0]
        if computer_suit not in player_suits and '♠' not in player_suits:
            tricks_to_award = len(game['computer_hand'])
            game['computer_tricks'] += tricks_to_award
            auto_resolved = True
            explanation = f"Auto-resolved: Marta had only {computer_suit} ({tricks_to_award} cards), you had none and no spades"
            winner_of_remaining = 'computer'
    
    if auto_resolved:
        # Simulate the remaining tricks and add to history
        player_cards = game['player_hand'].copy()
        computer_cards = game['computer_hand'].copy()
        current_trick_number = len(game.get('trick_history', [])) + 1
        
        # Log console message for auto-resolution
        print(f"AUTO-RESOLVE: {explanation}")
        
        # Play out remaining tricks in any order since outcome is predetermined
        while player_cards and computer_cards:
            # Just take first card from each hand (order doesn't matter)
            player_card = player_cards.pop(0)
            computer_card = computer_cards.pop(0)
            
            # Add to trick history
            game.setdefault('trick_history', []).append({
                'number': current_trick_number,
                'player_card': player_card,
                'computer_card': computer_card,
                'winner': winner_of_remaining  # Predetermined winner
            })
            
            # Log each auto-played trick to console
            p_text = f"{player_card['rank']}{player_card['suit']}"
            c_text = f"{computer_card['rank']}{computer_card['suit']}"
            winner_name = "You" if winner_of_remaining == 'player' else "Marta"
            print(f"AUTO-TRICK {current_trick_number}: {p_text} vs {c_text} -> {winner_name} wins")
            
            current_trick_number += 1
        
        # Clear hands and mark as over
        game['player_hand'] = []
        game['computer_hand'] = []
        game['hand_over'] = True
        
        # Log the auto-resolution
        if session_obj:
            log_game_event(
                event_type='hand_auto_resolved',
                event_data={
                    'explanation': explanation,
                    'tricks_simulated': tricks_to_award,
                    'cards_remaining_when_triggered': player_hand_size,
                    'final_player_tricks': game['player_tricks'],
                    'final_computer_tricks': game['computer_tricks']
                },
                session=session_obj
            )
    
    return auto_resolved, explanation