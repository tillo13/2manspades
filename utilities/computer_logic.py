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

# GLOBAL AI DIFFICULTY SETTINGS

# Discard Strategy Settings
SINGLETON_SPECIAL_PRIORITY = 1000    # How much to prioritize discarding singleton 7♦/10♣
VOID_CREATION_PRIORITY = 500         # How much to value creating voids
SPECIAL_CARD_PROTECTION = -100       # Penalty for discarding protected special cards
SPADE_DISCARD_PENALTY = 3           # Multiplier for avoiding spade discards
PARITY_CONSIDERATION = 1            # Small bonus for parity-favorable discards

# Bidding Strategy Settings  
BID_ACCURACY_BOOST = 0.3            # How much to boost base expectations (higher = more aggressive)
NIL_RISK_TOLERANCE = 0.8            # Threshold for nil bidding (lower = more nil attempts)
BLIND_DESPERATION_THRESHOLD = 120   # Points behind before considering blind bids
SCORE_BASED_ADJUSTMENT = 0.05       # How much score differential affects bidding
NIL_STRICTNESS = 0.8                # Lower = more likely to nil (minimum expectation for non-nil)
MAX_REASONABLE_BID = 6              # mnost she can bid


# Playing Strategy Settings
BAG_AVOIDANCE_STRENGTH = 0.92       # Multiplier when trying to avoid bags (lower = more avoidance)
LEAD_SAFETY_CONSIDERATION = True    # Whether to avoid leading into dangerous suits

# Meta-Strategy Settings
DEFAULT_BLIND_BID = 5

# HAND ANALYSIS FUNCTIONS

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
        sure_tricks += 3.0  # Expect 3 tricks from 5+ spades
        probable_tricks += 2.0
    elif spade_count == 4:
        sure_tricks += 2.0  # Expect 2 tricks from 4 spades  
        probable_tricks += 1.0
    elif spade_count == 3:
        sure_tricks += 1.5  # Expect 1.5 tricks from 3 spades
        probable_tricks += 0.5
    elif spade_count == 2:
        sure_tricks += 0.8  # Modest expectation from 2 spades
        probable_tricks += 0.4
    elif spade_count == 1:
        sure_tricks += 0.3  # Low expectation from 1 spade
    
    # High spades get additional value
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

# DISCARD STRATEGY

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

# BIDDING STRATEGY

def should_bid_nil(hand, game_state):
    """
    Determine if computer should bid nil
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
    Main computer bidding function
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
    
    # Score-based adjustments
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

    # Apply maximum reasonable bid cap
    raw_bid = min(raw_bid, MAX_REASONABLE_BID)

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
        # Remove the elif raw_bid < 7 clause since we're capping at 6

    # Final bounds check with new maximum
    raw_bid = max(1, min(MAX_REASONABLE_BID, raw_bid))
    
    return raw_bid, False

# PLAYING STRATEGY

def computer_lead_strategy(computer_hand, spades_broken, game_state=None):
    """
    Enhanced leading strategy with absolute special card protection
    """
    if not computer_hand:
        return None
    
    # Import special card check
    from .custom_rules import is_special_card
    
    # Find all valid leads (respecting spades rules)
    valid_leads = []
    for i, card in enumerate(computer_hand):
        if card['suit'] != '♠' or spades_broken or all(c['suit'] == '♠' for c in computer_hand):
            valid_leads.append((i, card))
    
    if not valid_leads:
        return None
    
    # CRITICAL: Never lead special cards unless absolutely no choice
    non_special_leads = []
    special_leads = []
    
    for i, card in valid_leads:
        is_special, _ = is_special_card(card)
        if is_special:
            special_leads.append((i, card))
        else:
            non_special_leads.append((i, card))
    
    # If we have ANY non-special cards to lead, NEVER lead special cards
    if non_special_leads:
        leads_to_consider = non_special_leads
    else:
        # Only consider special cards if we literally have no other choice
        leads_to_consider = special_leads
    
    # Advanced bag forcing logic (only if we have non-special cards)
    if game_state and leads_to_consider == non_special_leads:
        computer_bid = game_state.get('computer_bid', 0)
        computer_tricks = game_state.get('computer_tricks', 0) 
        player_bags = game_state.get('player_bags', 0)
        
        # If we've made our bid and player has 5+ bags, lead high to force them
        if computer_tricks >= computer_bid > 0 and player_bags >= 5:
            return max(leads_to_consider, key=lambda x: x[1]['value'])[0]
    
    # Normal strategy: lead lowest safe card
    return min(leads_to_consider, key=lambda x: x[1]['value'])[0]

def computer_follow_strategy(computer_hand, current_trick, game_state):
    """
    Enhanced following strategy with special card protection and acquisition
    Returns index of best card to play
    """
    if not current_trick or not computer_hand:
        return None

    from .custom_rules import is_special_card

    computer_bid = game_state.get('computer_bid', 0)
    computer_tricks = game_state.get('computer_tricks', 0)
    
    # Check if computer has already made their bid
    made_bid = computer_tricks >= computer_bid and computer_bid > 0

    lead_card = current_trick[0]['card']
    lead_suit = lead_card['suit']
    lead_value = lead_card['value']

    # Check if player played a special card that we want to win
    player_has_special = is_special_card(lead_card)[0]

    # Categorize all cards by suit and special status
    same_suit_cards = []
    spade_cards = []
    other_suit_cards = []
    
    for i, card in enumerate(computer_hand):
        if card['suit'] == lead_suit:
            same_suit_cards.append((i, card))
        elif card['suit'] == '♠':
            spade_cards.append((i, card))
        else:
            other_suit_cards.append((i, card))

    # CASE 1: Must follow suit
    if same_suit_cards:
        # Separate winners and losers
        winners = [(i, c) for i, c in same_suit_cards if c['value'] > lead_value]
        losers = [(i, c) for i, c in same_suit_cards if c['value'] <= lead_value]
        
        # Separate special and non-special cards
        special_winners = [(i, c) for i, c in winners if is_special_card(c)[0]]
        non_special_winners = [(i, c) for i, c in winners if not is_special_card(c)[0]]
        special_losers = [(i, c) for i, c in losers if is_special_card(c)[0]]
        non_special_losers = [(i, c) for i, c in losers if not is_special_card(c)[0]]
        
        # PRIORITY 1: If player played special card, try to win it (but not with our special cards)
        if player_has_special and non_special_winners:
            return min(non_special_winners, key=lambda x: x[1]['value'])[0]
        
        # PRIORITY 2: Computer has made bid - avoid extra tricks but protect special cards
        if made_bid:
            # Prefer to lose with non-special cards
            if non_special_losers:
                return max(non_special_losers, key=lambda x: x[1]['value'])[0]
            # If only special losers available, use lowest
            elif special_losers:
                return min(special_losers, key=lambda x: x[1]['value'])[0]
            # Must win - prefer non-special winners
            elif non_special_winners:
                return min(non_special_winners, key=lambda x: x[1]['value'])[0]
            # Only special winners left
            elif special_winners:
                return min(special_winners, key=lambda x: x[1]['value'])[0]
            # Fallback - should never reach here if same_suit_cards is not empty
            else:
                return same_suit_cards[0][0]
        
        # PRIORITY 3: Computer still needs tricks - try to win but protect special cards
        else:
            # Try to win with non-special cards first
            if non_special_winners:
                return min(non_special_winners, key=lambda x: x[1]['value'])[0]
            # Use special winners only if player has special card (worth the trade)
            elif special_winners and player_has_special:
                return min(special_winners, key=lambda x: x[1]['value'])[0]
            # Can't win without special cards - lose with non-special if possible
            elif non_special_losers:
                return min(non_special_losers, key=lambda x: x[1]['value'])[0]
            # Only special losers available
            elif special_losers:
                return min(special_losers, key=lambda x: x[1]['value'])[0]
            # Fallback
            else:
                return same_suit_cards[0][0]
    
    # CASE 2: Can't follow suit, can trump with spade
    elif lead_suit != '♠' and spade_cards:
        special_spades = [(i, c) for i, c in spade_cards if is_special_card(c)[0]]
        non_special_spades = [(i, c) for i, c in spade_cards if not is_special_card(c)[0]]
        
        # If player has special card, trump to win it (but not with special spades)
        if player_has_special and non_special_spades:
            return min(non_special_spades, key=lambda x: x[1]['value'])[0]
        
        if made_bid:
            # Try to avoid trumping - discard from other suits instead
            special_others = [(i, c) for i, c in other_suit_cards if is_special_card(c)[0]]
            non_special_others = [(i, c) for i, c in other_suit_cards if not is_special_card(c)[0]]
            
            if non_special_others:
                return min(non_special_others, key=lambda x: x[1]['value'])[0]
            elif special_others:
                return min(special_others, key=lambda x: x[1]['value'])[0]
            # Must trump - use non-special spades first
            elif non_special_spades:
                return min(non_special_spades, key=lambda x: x[1]['value'])[0]
            elif special_spades:
                return min(special_spades, key=lambda x: x[1]['value'])[0]
            else:
                return 0  # Fallback to first card
        else:
            # Still need tricks - trump with lowest spade, prefer non-special
            if non_special_spades:
                return min(non_special_spades, key=lambda x: x[1]['value'])[0]
            elif special_spades:
                return min(special_spades, key=lambda x: x[1]['value'])[0]
            else:
                return 0  # Fallback
    
    # CASE 3: Can't follow or trump - must discard
    else:
        # Separate special and non-special cards from all remaining cards
        all_remaining = other_suit_cards + spade_cards  # spade_cards is empty in this case, but kept for clarity
        special_cards = [(i, c) for i, c in all_remaining if is_special_card(c)[0]]
        non_special_cards = [(i, c) for i, c in all_remaining if not is_special_card(c)[0]]
        
        # Always prefer to discard non-special cards
        if non_special_cards:
            return min(non_special_cards, key=lambda x: x[1]['value'])[0]
        elif special_cards:
            return min(special_cards, key=lambda x: x[1]['value'])[0]
        else:
            # Should never happen, but fallback to first card
            return 0

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