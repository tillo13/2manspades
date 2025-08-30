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
    
    # Analyze spades
    spade_values = sorted([card['value'] for card in spades], reverse=True)
    
    # High spades analysis
    if 14 in spade_values:  # Ace of spades
        sure_tricks += 0.95
    if 13 in spade_values:  # King of spades
        sure_tricks += 0.8 if 14 in spade_values else 0.65  # Protected vs unprotected
    if 12 in spade_values:  # Queen of spades
        if len([v for v in spade_values if v >= 11]) >= 2:
            probable_tricks += 0.6
        else:
            probable_tricks += 0.3
    
    # Long spade suits
    if len(spades) >= 5:
        probable_tricks += (len(spades) - 4) * 0.4
    elif len(spades) >= 3:
        probable_tricks += (len(spades) - 2) * 0.25
    
    # Analyze other suits
    for suit, cards in suits.items():
        if not cards:
            continue
            
        values = sorted([card['value'] for card in cards], reverse=True)
        
        # Aces in other suits (can be trumped)
        if 14 in values:
            sure_tricks += 0.75
        
        # Protected kings
        if 13 in values:
            if 14 in values:  # Protected king
                probable_tricks += 0.5
            elif len(cards) >= 3:  # King in long suit
                probable_tricks += 0.4
            else:  # Unprotected king
                probable_tricks += 0.25
        
        # Long suits can generate tricks
        if len(cards) >= 4:
            probable_tricks += (len(cards) - 3) * 0.2
    
    return sure_tricks, probable_tricks, special_card_bonus

def should_bid_nil(hand, game_state):
    """
    Determine if computer should bid nil (very conservative)
    """
    player_score = game_state.get('player_score', 0)
    computer_score = game_state.get('computer_score', 0)
    player_bid = game_state.get('player_bid', 0)
    
    # Get hand strength
    sure_tricks, probable_tricks, special_bonus = analyze_hand_strength(hand)
    total_expectation = sure_tricks + probable_tricks + special_bonus
    
    # Only consider nil with very weak hands
    if total_expectation > 1.2:
        return False
    
    # Must have very few spades
    spades = [card for card in hand if card['suit'] == '♠']
    if len(spades) > 2:
        return False
    
    # Must have mostly low cards in other suits
    other_suits = [card for card in hand if card['suit'] != '♠']
    weak_hand = all(card['value'] <= 8 for card in other_suits)
    if not weak_hand:
        return False
    
    # Don't nil if player already bid nil
    if player_bid == 0:
        return False
    
    # Only nil when behind in score (nil is worth 100 points)
    if computer_score >= player_score:
        return False
    
    # Very conservative - only nil when desperate and hand is truly weak
    return computer_score < player_score - 30

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
    
    deficit = blind_eligibility['computer_deficit']
    
    # Only consider blind when really desperate (120+ points behind)
    if deficit < 120:
        return False, 0
    
    # Analyze hand strength
    sure_tricks, probable_tricks, special_bonus = analyze_hand_strength(hand)
    total_expectation = sure_tricks + probable_tricks + special_bonus
    
    # Only go blind with reasonable hands (can realistically make 5-8 tricks)
    if total_expectation < 4.0 or total_expectation > 7.5:
        return False, 0
    
    # Calculate blind bid (conservative)
    blind_bid = max(5, min(8, round(total_expectation)))
    
    # More likely to go blind when further behind
    blind_probability = min(0.7, (deficit - 100) / 200)  # 70% max chance
    
    if random.random() < blind_probability:
        return True, blind_bid
    
    return False, 0

def computer_bidding_brain(computer_hand, player_bid, game_state):
    """
    Main computer bidding function with enhanced AI
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
    
    # Score-based adjustments
    if computer_score > player_score + 30:  # Ahead - be conservative
        base_expectation *= 0.92
    elif computer_score < player_score - 30:  # Behind - be slightly aggressive
        base_expectation *= 1.08
    
    # Bag avoidance when close to penalty
    if computer_bags >= 5:
        base_expectation *= 0.88
    
    # Strategic response to player's bid
    if player_bid == 0:  # Player nil - be aggressive to set them
        base_expectation += 0.4
    elif player_bid <= 2:  # Player bid low
        base_expectation += 0.2
    elif player_bid >= 7:  # Player bid high
        base_expectation -= 0.3
    
    # Convert to bid
    raw_bid = max(0, min(10, round(base_expectation)))
    
    # Enforce 2-5 preference for reasonable hands (as requested)
    if 1.8 <= base_expectation <= 6.2:
        raw_bid = max(2, min(5, raw_bid))
    
    # Avoid obvious total-10 scenarios
    if abs((raw_bid + player_bid) - 10) <= 1 and random.random() < 0.4:
        if raw_bid > 2:
            raw_bid -= 1
        elif raw_bid < 8:
            raw_bid += 1
    
    return raw_bid, False

def computer_discard_strategy(computer_hand, game_state):
    """
    Enhanced discard strategy considering special cards and parity
    Returns index of card to discard
    """
    player_parity = game_state.get('player_parity', 'even')
    computer_parity = game_state.get('computer_parity', 'odd')
    
    discard_candidates = []
    
    for i, card in enumerate(computer_hand):
        score = 0
        
        # Heavily avoid discarding special cards
        is_special, _ = is_special_card(card)
        if is_special:
            score -= 100  # Almost never discard special cards
        
        # Prefer discarding weak cards, avoid spades
        if card['suit'] == '♠':
            score -= card['value'] * 3  # Really avoid discarding spades
        else:
            score += (15 - card['value'])  # Prefer discarding low cards
        
        # Light parity consideration for discard scoring
        discard_value = get_discard_value(card)
        if computer_parity == 'even' and discard_value % 2 == 1:
            score += 3  # Odd values might help create even totals
        elif computer_parity == 'odd' and discard_value % 2 == 0:
            score += 3  # Even values might help create odd totals
        
        discard_candidates.append((i, score))
    
    # Return index of card with highest discard score
    return max(discard_candidates, key=lambda x: x[1])[0]

def computer_play_strategy(game_state):
    """
    Enhanced playing strategy for computer
    This can be expanded later for more sophisticated play decisions
    """
    # For now, this just returns to the existing play logic
    # But provides a centralized place to enhance computer play strategy later
    pass