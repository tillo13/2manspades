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
    
    # ENHANCED SPADES ANALYSIS
    spade_values = sorted([card['value'] for card in spades], reverse=True)
    spade_count = len(spades)
    
    # Apply your spade count expectations
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
    # Your request: more aces/kings should increase expectations
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

def should_bid_nil(hand, game_state):
    """
    Determine if computer should bid nil (much more restrictive)
    """
    player_score = game_state.get('player_score', 0)
    computer_score = game_state.get('computer_score', 0)
    player_bid = game_state.get('player_bid', 0)
    
    # Get hand strength
    sure_tricks, probable_tricks, special_bonus = analyze_hand_strength(hand)
    total_expectation = sure_tricks + probable_tricks + special_bonus
    
    # Much stricter - only consider nil with truly weak hands
    if total_expectation > 0.8:  # Lowered from 1.2
        return False
    
    # Must have very few spades and they must be low
    spades = [card for card in hand if card['suit'] == '♠']
    if len(spades) > 3:  # At most 3 spades
        return False
    
    # No high spades allowed
    for spade in spades:
        if spade['value'] >= 11:  # No J, Q, K, A of spades
            return False
    
    # CRITICAL: Must have at least 2 twos for safety
    twos = [card for card in hand if card['rank'] == '2']
    if len(twos) < 2:
        return False
    
    # Must have mostly very low cards (2-7) in other suits
    other_suits = [card for card in hand if card['suit'] != '♠']
    low_cards = [card for card in other_suits if card['value'] <= 7]
    
    if len(low_cards) < len(other_suits) - 1:  # Almost all non-spades must be low
        return False
    
    # No aces or kings in other suits
    high_other_suits = [card for card in other_suits if card['value'] >= 13]
    if len(high_other_suits) > 0:
        return False
    
    # Don't nil if player already bid nil
    if player_bid == 0:
        return False
    
    # Only nil when significantly behind (at least 50 points)
    if computer_score >= player_score - 50:
        return False
    
    # Very conservative probability - only when truly desperate with perfect nil hand
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
    Main computer bidding function with enhanced AI - targeting 3-4 average bids
    Returns tuple: (bid_amount, is_blind)
    """
    player_score = game_state.get('player_score', 0)
    computer_score = game_state.get('computer_score', 0)
    computer_bags = game_state.get('computer_bags', 0)
    
    # Check for nil opportunity first (now much more restrictive)
    if should_bid_nil(computer_hand, game_state):
        return 0, False
    
    # Check for blind bidding opportunity
    should_blind, blind_amount = should_bid_blind(computer_hand, game_state)
    if should_blind:
        return blind_amount, True
    
    # Regular bidding logic - aim for 3-4 average
    sure_tricks, probable_tricks, special_bonus = analyze_hand_strength(computer_hand)
    base_expectation = sure_tricks + probable_tricks + special_bonus
    
    # BOOST BASE EXPECTATION to target 3-4 range instead of 2
    # The current system was too conservative
    base_expectation += 0.8  # Add almost 1 full trick to expectations
    
    # Score-based adjustments (smaller now since we boosted base)
    if computer_score > player_score + 30:  # Ahead - be slightly conservative
        base_expectation *= 0.95
    elif computer_score < player_score - 30:  # Behind - be slightly aggressive
        base_expectation *= 1.05
    
    # Bag avoidance when close to penalty (smaller effect)
    if computer_bags >= 5:
        base_expectation *= 0.92
    
    # Strategic response to player's bid (reduced impact)
    if player_bid == 0:  # Player nil - be aggressive to set them
        base_expectation += 0.3
    elif player_bid <= 2:  # Player bid low
        base_expectation += 0.15
    elif player_bid >= 7:  # Player bid high
        base_expectation -= 0.2
    
    # Convert to bid
    raw_bid = max(0, min(10, round(base_expectation)))
    
    # REVISED BID RANGE PREFERENCES
    # Remove the 2-5 constraint that was keeping bids too low
    # Instead, nudge toward 3-4 range when reasonable
    if 2.5 <= base_expectation <= 5.5:
        if raw_bid < 3:
            raw_bid = 3  # Minimum reasonable bid is 3
        elif raw_bid == 5 and random.random() < 0.4:
            raw_bid = 4  # Sometimes prefer 4 over 5
    
    # Avoid obvious total-10 scenarios (reduced probability)
    if abs((raw_bid + player_bid) - 10) <= 1 and random.random() < 0.3:
        if raw_bid > 3:  # Changed from 2 to 3
            raw_bid -= 1
        elif raw_bid < 7:
            raw_bid += 1
    
    # Final bounds check
    raw_bid = max(1, min(10, raw_bid))  # Minimum bid is now 1, not 0
    
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
    
    # Categorize leads by danger level
    safe_leads = []
    risky_leads = []
    dangerous_leads = []
    
    for i, card in valid_leads:
        suit = card['suit']
        rank = card['rank']
        
        # Check if leading this suit could give opponent special cards
        if suit == '♣':
            # Leading clubs could set up 10♣ for opponent
            if rank in ['J', 'Q', 'K', 'A']:  # High clubs are dangerous
                dangerous_leads.append((i, card))
            elif rank in ['8', '9', '10']:  # Medium clubs are risky
                risky_leads.append((i, card))
            else:  # Low clubs are safer
                safe_leads.append((i, card))
        elif suit == '♦':
            # Leading diamonds could set up 7♦ for opponent  
            if rank in ['J', 'Q', 'K', 'A']:  # High diamonds are dangerous
                dangerous_leads.append((i, card))
            elif rank in ['6', '7', '8']:  # Around 7♦ is risky
                risky_leads.append((i, card))
            else:  # Other diamonds are safer
                safe_leads.append((i, card))
        else:
            # Hearts and spades are generally safer for special card purposes
            safe_leads.append((i, card))
    
    # Choose lead in order of preference: safe > risky > dangerous
    if safe_leads:
        # From safe leads, choose lowest card
        chosen = min(safe_leads, key=lambda x: x[1]['value'])
    elif risky_leads:
        # From risky leads, choose lowest card
        chosen = min(risky_leads, key=lambda x: x[1]['value'])
    else:
        # Must lead dangerous card - choose lowest
        chosen = min(dangerous_leads, key=lambda x: x[1]['value'])
    
    return chosen[0]

def computer_play_strategy(game_state):
    """
    Enhanced playing strategy for computer
    This can be expanded later for more sophisticated play decisions
    """
    # For now, this just returns to the existing play logic
    # But provides a centralized place to enhance computer play strategy later
    pass