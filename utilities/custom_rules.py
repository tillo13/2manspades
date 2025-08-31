import random

def get_discard_value(card):
    """
    Get the numerical value of a card for discard scoring.
    J=11, Q=12, K=13, A=1, numbers are face value
    """
    rank = card['rank']
    if rank == 'A':
        return 1
    elif rank == 'J':
        return 11
    elif rank == 'Q':
        return 12
    elif rank == 'K':
        return 13
    else:
        return int(rank)

def assign_even_odd_at_game_start():
    """
    Randomly assign even/odd to players at the start of a new game.
    Also determines who leads the first trick - if player is odd, they lead first.
    Returns tuple: (player_parity, computer_parity, first_leader)
    """
    coin_flip = random.choice(['even', 'odd'])
    if coin_flip == 'even':
        player_parity = 'even'
        computer_parity = 'odd'
        first_leader = 'computer'  # Computer (odd) leads first trick
    else:
        player_parity = 'odd'
        computer_parity = 'even'
        first_leader = 'player'   # Player (odd) leads first trick
    
    return (player_parity, computer_parity, first_leader)

def is_special_card(card):
    """
    Check if a card is one of the special bag-reducing cards.
    Returns tuple: (is_special, bags_to_remove)
    """
    if card['rank'] == '7' and card['suit'] == '♦':
        return True, 2  # 7 of diamonds removes 2 bags
    elif card['rank'] == '10' and card['suit'] == '♣':
        return True, 1  # 10 of clubs removes 1 bag
    else:
        return False, 0

def check_blind_bidding_eligibility(player_score, computer_score, target_score=300):
    """
    Check if a player is eligible for blind bidding (down by 100+ points).
    
    Returns:
        dict: {
            'player_eligible': bool,
            'computer_eligible': bool,
            'player_deficit': int,
            'computer_deficit': int
        }
    """
    player_deficit = computer_score - player_score
    computer_deficit = player_score - computer_score
    
    return {
        'player_eligible': player_deficit >= 100,
        'computer_eligible': computer_deficit >= 100,
        'player_deficit': max(0, player_deficit),
        'computer_deficit': max(0, computer_deficit)
    }

def apply_blind_scoring(base_points, blind_bid, actual_tricks):
    """
    Apply blind bidding scoring rules.
    
    Args:
        base_points: Normal points that would be awarded
        blind_bid: The blind bid amount (5-10)
        actual_tricks: Actual tricks taken
        
    Returns:
        int: Modified points (doubled if successful, doubled penalty if failed)
    """
    if actual_tricks >= blind_bid:
        # Successful blind bid: double the points
        return base_points * 2
    else:
        # Failed blind bid: double the penalty
        return base_points * 2  # base_points will already be negative for failed bids

def check_special_cards_in_discard(player_discard, computer_discard, discard_winner):
    """
    Check for special cards in the discard pile and apply bag reduction to the winner.
    """
    total_reduction = 0
    special_cards_found = []
    
    # Check both discarded cards for special cards
    for card, discarder in [(player_discard, 'Tom'), (computer_discard, 'Marta')]:
        if card:
            is_special, reduction = is_special_card(card)
            if is_special:
                total_reduction += reduction
                card_name = f"{card['rank']}{card['suit']}"
                special_cards_found.append(f"{card_name} (-{reduction} bags)")
    
    # Apply all reductions to the winner of the discard pile
    player_reduction = 0
    computer_reduction = 0
    
    if total_reduction > 0:
        if discard_winner == 'player':
            player_reduction = total_reduction
        else:
            computer_reduction = total_reduction
    
    # Create explanation
    explanation = ""
    if special_cards_found:
        winner_name = "Tom" if discard_winner == 'player' else "Marta"
        cards_text = ", ".join(special_cards_found)
        explanation = f"{winner_name} won discard pile with special cards: {cards_text}"
    
    return {
        'player_bag_reduction': player_reduction,
        'computer_bag_reduction': computer_reduction,
        'explanation': explanation
    }

def check_special_cards_in_trick(trick, winner):
    """
    Check for special cards in a completed trick and apply bag reduction to winner.
    """
    total_reduction = 0
    special_cards_found = []
    
    for play in trick:
        card = play['card']
        is_special, reduction = is_special_card(card)
        if is_special:
            total_reduction += reduction
            card_name = f"{card['rank']}{card['suit']}"
            special_cards_found.append(f"{card_name} (-{reduction} bags)")
    
    explanation = ""
    if special_cards_found:
        winner_name = "Tom" if winner == 'player' else "Marta"
        cards_text = ", ".join(special_cards_found)
        explanation = f"{winner_name} won trick with special cards: {cards_text}"
    
    return {
        'bag_reduction': total_reduction,
        'explanation': explanation
    }

def calculate_discard_score_with_winner(player_discard, computer_discard, player_parity, computer_parity):
    """Calculate the bonus points from discarded cards and determine winner."""
    if not player_discard or not computer_discard:
        return {
            'player_bonus': 0,
            'computer_bonus': 0, 
            'total': 0,
            'is_double': False,
            'winner': None,
            'explanation': 'No discards to score'
        }
    
    # Calculate total value
    player_value = get_discard_value(player_discard)
    computer_value = get_discard_value(computer_discard)
    total = player_value + computer_value
    
    # Check for doubles (same suit OR same rank)
    is_double = (player_discard['suit'] == computer_discard['suit'] or 
                 player_discard['rank'] == computer_discard['rank'])
    
    # Determine base points (10 for normal, 20 for doubles)
    base_points = 20 if is_double else 10
    
    # Award points based on parity and determine winner
    player_bonus = 0
    computer_bonus = 0
    winner = None
    
    is_total_even = (total % 2 == 0)
    
    if is_total_even and player_parity == 'even':
        player_bonus = base_points
        winner = 'player'
    elif not is_total_even and player_parity == 'odd':
        player_bonus = base_points
        winner = 'player'
    elif is_total_even and computer_parity == 'even':
        computer_bonus = base_points
        winner = 'computer'
    elif not is_total_even and computer_parity == 'odd':
        computer_bonus = base_points
        winner = 'computer'
    
    # Create explanation
    double_text = ""
    if is_double:
        if player_discard['suit'] == computer_discard['suit']:
            double_text = f" (DOUBLE: Both {player_discard['suit']} suit!)"
        else:
            double_text = f" (DOUBLE: Both {player_discard['rank']}s!)"
    
    parity_text = "even" if is_total_even else "odd"
    
    explanation = f"Discards: {player_discard['rank']}{player_discard['suit']} ({player_value}) + {computer_discard['rank']}{computer_discard['suit']} ({computer_value}) = {total} ({parity_text}){double_text}"
    
    if player_bonus > 0:
        explanation += f" → Tom gets {player_bonus} pts!"
    elif computer_bonus > 0:
        explanation += f" → Marta gets {computer_bonus} pts!"
    else:
        explanation += " → No bonus points this hand."
    
    return {
        'player_bonus': player_bonus,
        'computer_bonus': computer_bonus,
        'total': total,
        'is_double': is_double,
        'winner': winner,
        'explanation': explanation
    }

def apply_bags_penalty(score, bags):
    """Apply bags penalty system."""
    penalty_applied = False
    bonus_applied = False
    
    while bags >= 7:
        score -= 100
        bags -= 7
        penalty_applied = True
    
    while bags <= -5:
        score += 100
        bags += 5
        bonus_applied = True
    
    return score, bags, penalty_applied, bonus_applied

def reduce_bags_safely(current_bags, reduction):
    """Reduce bags by the specified amount. Bags can go negative."""
    return current_bags - reduction

def calculate_hand_scores_with_bags(game):
    """
    Calculate hand scoring including bags system, nil bids, and blind bidding for both players.
    """
    player_bid = game.get('player_bid', 0)
    computer_bid = game.get('computer_bid', 0)
    player_actual = game.get('player_tricks', 0)
    computer_actual = game.get('computer_tricks', 0)
    
    # Check blind bids for both players
    is_player_blind = game.get('blind_bid') == player_bid and game.get('blind_bid') is not None
    is_computer_blind = game.get('computer_blind_bid') == computer_bid and game.get('computer_blind_bid') is not None
    
    # Get current bags
    current_player_bags = game.get('player_bags', 0)
    current_computer_bags = game.get('computer_bags', 0)
    
    # Calculate player points
    if player_bid == 0:
        if player_actual == 0:
            player_hand_points = 100
            player_bags_added = 0
        else:
            player_hand_points = -100
            player_bags_added = player_actual
    elif player_actual >= player_bid:
        player_hand_points = (player_bid * 10)
        player_bags_added = player_actual - player_bid
        if is_player_blind:
            player_hand_points = apply_blind_scoring(player_hand_points, player_bid, player_actual)
    else:
        player_hand_points = -(player_bid * 10)
        player_bags_added = 0
        if is_player_blind:
            player_hand_points = apply_blind_scoring(player_hand_points, player_bid, player_actual)
    
    # Calculate computer points (now with blind support!)
    if computer_bid == 0:
        if computer_actual == 0:
            computer_hand_points = 100
            computer_bags_added = 0
        else:
            computer_hand_points = -100
            computer_bags_added = computer_actual
    elif computer_actual >= computer_bid:
        computer_hand_points = (computer_bid * 10)
        computer_bags_added = computer_actual - computer_bid
        if is_computer_blind:
            computer_hand_points = apply_blind_scoring(computer_hand_points, computer_bid, computer_actual)
    else:
        computer_hand_points = -(computer_bid * 10)
        computer_bags_added = 0
        if is_computer_blind:
            computer_hand_points = apply_blind_scoring(computer_hand_points, computer_bid, computer_actual)
    
    # Update bag counts
    new_player_bags = current_player_bags + player_bags_added
    new_computer_bags = current_computer_bags + computer_bags_added
    
    # Apply bag penalties/bonuses
    player_score = game.get('player_score', 0) + player_hand_points
    computer_score = game.get('computer_score', 0) + computer_hand_points
    
    player_score, final_player_bags, player_penalty, player_bonus = apply_bags_penalty(player_score, new_player_bags)
    computer_score, final_computer_bags, computer_penalty, computer_bonus = apply_bags_penalty(computer_score, new_computer_bags)
    
    # Update game state
    game['player_bags'] = final_player_bags
    game['computer_bags'] = final_computer_bags
    game['player_score'] = player_score
    game['computer_score'] = computer_score
    
    # Get special card tracking for summary
    player_trick_special_cards = game.get('player_trick_special_cards', 0)
    computer_trick_special_cards = game.get('computer_trick_special_cards', 0)
    
    # Reset special card tracking for next hand
    game['player_trick_special_cards'] = 0
    game['computer_trick_special_cards'] = 0
    
    # Create explanation with blind bid support
    explanation_parts = []
    
    # Player explanation
    if player_bid == 0:
        if player_actual == 0:
            explanation_parts.append(f"Tom: NIL SUCCESS! 0 bid, 0 tricks (+100 pts)")
        else:
            explanation_parts.append(f"Tom: NIL FAILED! 0 bid, {player_actual} tricks (-100 pts, +{player_bags_added} bags)")
    elif is_player_blind:
        if player_actual >= player_bid:
            explanation_parts.append(f"Tom: BLIND {player_bid} SUCCESS! {player_actual} tricks (DOUBLE POINTS: +{player_hand_points} pts)")
        else:
            explanation_parts.append(f"Tom: BLIND {player_bid} FAILED! {player_actual} tricks (DOUBLE PENALTY: {player_hand_points} pts)")
        if player_bags_added > 0:
            explanation_parts[-1] += f", +{player_bags_added} bags"
    elif player_bags_added > 0:
        explanation_parts.append(f"Tom: {player_bid} bid, {player_actual} tricks (+{player_bags_added} bags)")
    else:
        explanation_parts.append(f"Tom: {player_bid} bid, {player_actual} tricks")
    
    # Computer explanation with blind support
    if computer_bid == 0:
        if computer_actual == 0:
            explanation_parts.append(f"Marta: NIL SUCCESS! 0 bid, 0 tricks (+100 pts)")
        else:
            explanation_parts.append(f"Marta: NIL FAILED! 0 bid, {computer_actual} tricks (-100 pts, +{computer_bags_added} bags)")
    elif is_computer_blind:
        if computer_actual >= computer_bid:
            explanation_parts.append(f"Marta: BLIND {computer_bid} SUCCESS! {computer_actual} tricks (DOUBLE POINTS: +{computer_hand_points} pts)")
        else:
            explanation_parts.append(f"Marta: BLIND {computer_bid} FAILED! {computer_actual} tricks (DOUBLE PENALTY: {computer_hand_points} pts)")
        if computer_bags_added > 0:
            explanation_parts[-1] += f", +{computer_bags_added} bags"
    elif computer_bags_added > 0:
        explanation_parts.append(f"Marta: {computer_bid} bid, {computer_actual} tricks (+{computer_bags_added} bags)")
    else:
        explanation_parts.append(f"Marta: {computer_bid} bid, {computer_actual} tricks")
    
    # Show special card effects from tricks
    if player_trick_special_cards > 0:
        explanation_parts.append(f"Tom won special cards: -{player_trick_special_cards} bags")
    if computer_trick_special_cards > 0:
        explanation_parts.append(f"Marta won special cards: -{computer_trick_special_cards} bags")
    
    # Show penalties and bonuses
    if player_penalty:
        penalty_count = (current_player_bags + player_bags_added) // 7
        explanation_parts.append(f"Tom: BAG PENALTY! -{penalty_count * 100} pts")
    
    if player_bonus:
        bonus_count = abs((current_player_bags + player_bags_added) // -5)
        explanation_parts.append(f"Tom: NEGATIVE BAG BONUS! +{bonus_count * 100} pts")
        
    if computer_penalty:
        penalty_count = (current_computer_bags + computer_bags_added) // 7
        explanation_parts.append(f"Marta: BAG PENALTY! -{penalty_count * 100} pts")
    
    if computer_bonus:
        bonus_count = abs((current_computer_bags + computer_bags_added) // -5)
        explanation_parts.append(f"Marta: NEGATIVE BAG BONUS! +{bonus_count * 100} pts")
    
    # Show current bag counts
    if final_player_bags != 0 or final_computer_bags != 0:
        explanation_parts.append(f"Bags: Tom {final_player_bags}/7, Marta {final_computer_bags}/7")

    # REMOVED: The trick history section that was causing duplication
    # The trick history is now only shown in the structured frontend display
    
    return {
        'player_hand_points': player_hand_points,
        'computer_hand_points': computer_hand_points,
        'player_bags_added': player_bags_added,
        'computer_bags_added': computer_bags_added,
        'player_penalty': player_penalty,
        'computer_penalty': computer_penalty,
        'player_bonus': player_bonus,
        'computer_bonus': computer_bonus,
        'explanation': " | ".join(explanation_parts)
    }

def get_player_names_with_parity(player_parity, computer_parity):
    """
    Get display names that include the parity assignment.
    """
    player_name = f"Tom ({player_parity.title()})"
    computer_name = f"Marta ({computer_parity.title()})"
    
    return (player_name, computer_name)