import random

def create_deck():
    """Create a standard 52-card deck"""
    suits = ['♠', '♥', '♦', '♣']
    ranks = ['2', '3', '4', '5', '6', '7', '8', '9', '10', 'J', 'Q', 'K', 'A']
    deck = []
    for suit in suits:
        for rank in ranks:
            deck.append({'rank': rank, 'suit': suit, 'value': get_card_value(rank)})
    return deck

def get_card_value(rank):
    """Get numerical value of a card rank"""
    if rank == 'A':
        return 14
    elif rank == 'K':
        return 13
    elif rank == 'Q':
        return 12
    elif rank == 'J':
        return 11
    else:
        return int(rank)

def sort_hand(hand):
    """Sort hand by suit (clubs, diamonds, hearts, spades) then by value"""
    suit_order = {'♣': 0, '♦': 1, '♥': 2, '♠': 3}
    return sorted(hand, key=lambda x: (suit_order[x['suit']], x['value']))

def init_game(player_parity='even', computer_parity='odd', first_leader='player'):
    """Initialize a new game"""
    deck = create_deck()
    random.shuffle(deck)
    
    return {
        'player_hand': sort_hand(deck[:11]),
        'computer_hand': sort_hand(deck[11:22]),
        'current_trick': [],
        'player_tricks': 0,
        'computer_tricks': 0,
        'spades_broken': False,
        'phase': 'discard',
        'turn': 'player',  # Both players can discard simultaneously
        'trick_leader': None,
        'hand_over': False,
        'game_over': False,
        'winner': None,
        'message': 'Select a card to discard',
        'player_discarded': None,
        'computer_discarded': None,
        'show_computer_hand': False,
        'trick_display_timer': None,
        'player_bid': None,
        'computer_bid': None,
        'total_tricks': 10,
        'player_score': 0,
        'computer_score': 0,
        'player_bags': 0,
        'computer_bags': 0,
        'player_trick_special_cards': 0,
        'computer_trick_special_cards': 0,
        'hand_number': 1,
        'target_score': 300,
        'player_parity': player_parity,
        'computer_parity': computer_parity,
        'first_leader': first_leader,  # Who leads the first trick of each hand
        'discard_bonus_explanation': None,
        'pending_discard_result': None,
        'pending_special_discard_result': None,
        'blind_bidding_available': False,
        'blind_bid': None,
        'computer_blind_bid': None,
        'blind_multiplier': 2,
        'trick_history': []  # Track all tricks played this hand
    }

def init_new_hand(game):
    """Start a new hand while preserving scores, bags, and parity assignments"""
    deck = create_deck()
    random.shuffle(deck)
    
    # Alternate who leads the first trick each hand
    current_first_leader = game.get('first_leader', 'player')
    next_first_leader = 'computer' if current_first_leader == 'player' else 'player'
    
    # Check blind bidding eligibility before setting phase
    from .custom_rules import check_blind_bidding_eligibility
    player_base_score = game.get('player_score', 0)
    computer_base_score = game.get('computer_score', 0)
    blind_eligibility = check_blind_bidding_eligibility(player_base_score, computer_base_score)
    
    # Set initial phase and message based on blind eligibility
    if blind_eligibility['player_eligible']:
        initial_phase = 'blind_decision'
        deficit = computer_base_score - player_base_score
        initial_message = f'You are down by {deficit} points. Choose: Go BLIND for double points/penalties, or bid normally?'
    else:
        initial_phase = 'discard'
        initial_message = f'Hand #{game["hand_number"]} - Select a card to discard'
    
    game.update({
        'player_hand': sort_hand(deck[:11]),
        'computer_hand': sort_hand(deck[11:22]),
        'current_trick': [],
        'player_tricks': 0,
        'computer_tricks': 0,
        'spades_broken': False,
        'phase': initial_phase,  # This is the key change
        'turn': 'player',
        'trick_leader': None,
        'hand_over': False,
        'message': initial_message,  # This is also updated
        'player_discarded': None,
        'computer_discarded': None,
        'show_computer_hand': False,
        'trick_display_timer': None,
        'player_bid': None,
        'computer_bid': None,
        'total_tricks': 10,
        'discard_bonus_explanation': None,
        'player_trick_special_cards': 0,
        'computer_trick_special_cards': 0,
        'pending_discard_result': None,
        'pending_special_discard_result': None,
        'blind_bidding_available': blind_eligibility['player_eligible'],
        'blind_bid': None,
        'computer_blind_bid': None,
        'first_leader': next_first_leader,
        'trick_history': []
    })

def computer_bidding_brain(computer_hand, player_bid, game_state=None):
    """
    Computer bidding function - now delegates to computer_logic module
    """
    if game_state is None:
        # Fallback for backward compatibility
        game_state = {'player_score': 0, 'computer_score': 0, 'computer_bags': 0}
    
    from .computer_logic import computer_bidding_brain as enhanced_brain
    return enhanced_brain(computer_hand, player_bid, game_state)

def computer_discard_strategy(computer_hand, game_state=None):
    """
    Computer discard strategy - now delegates to computer_logic module
    """
    if game_state is None:
        # Fallback to simple strategy for backward compatibility
        computer_discards = []
        for i, card in enumerate(computer_hand):
            if card['suit'] != '♠':
                computer_discards.append((i, card['value']))
        
        if computer_discards:
            return min(computer_discards, key=lambda x: x[1])[0]
        else:
            return 0
    
    from .computer_logic import computer_discard_strategy as enhanced_discard
    return enhanced_discard(computer_hand, game_state)

def is_valid_play(card, hand, trick, spades_broken):
    """Check if a card play is valid according to Spades rules"""
    if len(trick) == 0:
        # Leading
        if card['suit'] == '♠' and not spades_broken:
            # Can only lead spades if no other suits
            for c in hand:
                if c['suit'] != '♠':
                    return False
        return True
    else:
        # Following
        lead_suit = trick[0]['card']['suit']
        # Must follow suit if possible
        has_suit = any(c['suit'] == lead_suit for c in hand)
        if has_suit:
            return card['suit'] == lead_suit
        return True

def determine_trick_winner(trick):
    """
    Determine who won a completed trick
    Returns the player who won ('player' or 'computer')
    """
    if len(trick) != 2:
        return None
    
    first = trick[0]
    second = trick[1]
    
    if first['card']['suit'] == second['card']['suit']:
        # Same suit, higher value wins
        if first['card']['value'] > second['card']['value']:
            return first['player']
        else:
            return second['player']
    elif first['card']['suit'] == '♠':
        # First player trumped
        return first['player']
    elif second['card']['suit'] == '♠':
        # Second player trumped  
        return second['player']
    else:
        # Different suits, no trump - first player (leader) wins
        return first['player']

def resolve_trick_with_delay(game):
    """Resolve trick and set it up to be displayed for 3 seconds"""
    if len(game['current_trick']) != 2:
        return
    
    winner = determine_trick_winner(game['current_trick'])
    
    # SAVE TRICK TO HISTORY BEFORE PROCESSING
    trick_number = len(game.get('trick_history', [])) + 1
    player_card = next((play['card'] for play in game['current_trick'] if play['player'] == 'player'), None)
    computer_card = next((play['card'] for play in game['current_trick'] if play['player'] == 'computer'), None)
    
    game.setdefault('trick_history', []).append({
        'number': trick_number,
        'player_card': player_card,
        'computer_card': computer_card,
        'winner': winner
    })
    
    # LOG EACH TRICK TO CONSOLE
    p_text = f"{player_card['rank']}{player_card['suit']}" if player_card else "?"
    c_text = f"{computer_card['rank']}{computer_card['suit']}" if computer_card else "?"
    winner_name = "You" if winner == 'player' else "Marta"
    print(f"TRICK {trick_number}: {p_text} vs {c_text} -> {winner_name} wins")
    
    
    # Check for special cards in the trick and apply bag reduction IMMEDIATELY
    from utilities.custom_rules import check_special_cards_in_trick, reduce_bags_safely
    special_result = check_special_cards_in_trick(game['current_trick'], winner)
    
    if special_result['bag_reduction'] > 0:
        if winner == 'player':
            current_bags = game.get('player_bags', 0)
            game['player_bags'] = reduce_bags_safely(current_bags, special_result['bag_reduction'])
            game['player_trick_special_cards'] = game.get('player_trick_special_cards', 0) + special_result['bag_reduction']
        else:
            current_bags = game.get('computer_bags', 0)
            game['computer_bags'] = reduce_bags_safely(current_bags, special_result['bag_reduction'])
            game['computer_trick_special_cards'] = game.get('computer_trick_special_cards', 0) + special_result['bag_reduction']
        
        game['special_card_message'] = special_result['explanation']
    
    # Award trick
    if winner == 'player':
        game['player_tricks'] += 1
        base_message = 'You won the trick!'
    else:
        game['computer_tricks'] += 1
        base_message = 'Marta won the trick!'
    
    # Add special card info to message if present
    if special_result['explanation']:
        game['message'] = f"{base_message} {special_result['explanation']} Cards will clear in 3 seconds..."
    else:
        game['message'] = f"{base_message} Cards will clear in 3 seconds..."
    
    # Mark trick as completed but don't clear yet
    game['trick_completed'] = True
    game['trick_winner'] = winner

def computer_follow(game):
    """Computer plays a card when following - now uses bag avoidance strategy"""
    hand = game['computer_hand']
    trick = game['current_trick']
    
    if not trick or not hand:
        return
    
    # Use enhanced following strategy from computer_logic
    from .computer_logic import computer_follow_strategy
    chosen_idx = computer_follow_strategy(hand, trick, game)
    
    if chosen_idx is None:
        # Fallback to original simple logic if strategy fails
        lead_card = trick[0]['card']
        lead_suit = lead_card['suit']
        lead_value = lead_card['value']
        
        # Find valid plays
        same_suit = [(i, c) for i, c in enumerate(hand) if c['suit'] == lead_suit]
        spades = [(i, c) for i, c in enumerate(hand) if c['suit'] == '♠']
        
        if same_suit:
            # Must follow suit - try to win with lowest winning card
            winners = [(i, c) for i, c in same_suit if c['value'] > lead_value]
            if winners:
                chosen_idx = min(winners, key=lambda x: x[1]['value'])[0]
            else:
                # Can't win, play lowest
                chosen_idx = min(same_suit, key=lambda x: x[1]['value'])[0]
        elif lead_suit != '♠' and spades:
            # Can't follow suit, can trump with spade
            chosen_idx = min(spades, key=lambda x: x[1]['value'])[0]
        else:
            # Can't follow or trump, discard lowest
            all_cards = [(i, c) for i, c in enumerate(hand)]
            chosen_idx = min(all_cards, key=lambda x: x[1]['value'])[0]
    
    # Play the chosen card
    card = hand.pop(chosen_idx)
    game['current_trick'].append({'player': 'computer', 'card': card})
    
    if card['suit'] == '♠':
        game['spades_broken'] = True

def computer_lead(game):
    """Computer plays a card when leading - now uses enhanced strategy"""
    hand = game['computer_hand']
    
    if not hand:
        return
    
    # Use enhanced leading strategy from computer_logic
    from .computer_logic import computer_lead_strategy
    chosen_idx = computer_lead_strategy(hand, game['spades_broken'])
    
    if chosen_idx is None:
        # Fallback to original simple logic if strategy fails
        valid = []
        for i, card in enumerate(hand):
            if card['suit'] != '♠' or game['spades_broken'] or all(c['suit'] == '♠' for c in hand):
                valid.append((i, card))
        
        if valid:
            chosen = min(valid, key=lambda x: (x[1]['suit'] == '♠', x[1]['value']))
            chosen_idx = chosen[0]
        else:
            return
    
    # Play the chosen card
    card = hand.pop(chosen_idx)
    game['current_trick'] = [{'player': 'computer', 'card': card}]
    game['trick_leader'] = 'computer'
    
    if card['suit'] == '♠':
        game['spades_broken'] = True

def check_game_over(game):
    """
    Check if the game is over (someone reached target score OR down by 300+ points)
    Updates game state with winner information if game is over
    Uses proper tie-breaking logic considering base scores and bags
    """
    player_base_score = game['player_score']
    computer_base_score = game['computer_score']
    player_bags = game.get('player_bags', 0)
    computer_bags = game.get('computer_bags', 0)
    target_score = game['target_score']
    
    # Calculate display scores inline (no import needed)
    def calc_display_score(base_score, bags):
        if bags >= 0:
            if base_score < 0:
                tens_and_higher = (base_score // 10) * 10
                return tens_and_higher - bags
            else:
                tens_and_higher = (base_score // 10) * 10
                return tens_and_higher + bags
        else:
            return base_score
    
    player_display_score = calc_display_score(player_base_score, player_bags)
    computer_display_score = calc_display_score(computer_base_score, computer_bags)
    
    # Check for 300-point deficit rule (mercy rule) using display scores
    if player_display_score - computer_display_score >= 300:
        game['game_over'] = True
        game['winner'] = 'player'
        game['message'] = f"GAME OVER! You WIN by mercy rule {player_display_score} to {computer_display_score}! (300+ point lead)"
        return True
    elif computer_display_score - player_display_score >= 300:
        game['game_over'] = True
        game['winner'] = 'computer'
        game['message'] = f"GAME OVER! Marta WINS by mercy rule {computer_display_score} to {player_display_score}! (300+ point lead)"
        return True
    
    # Check for regular target score (300 points) using display scores
    if player_display_score >= target_score or computer_display_score >= target_score:
        game['game_over'] = True
        
        if player_display_score > computer_display_score:
            game['winner'] = 'player'
            game['message'] = f"GAME OVER! You WIN {player_display_score} to {computer_display_score}!"
        elif computer_display_score > player_display_score:
            game['winner'] = 'computer'
            game['message'] = f"GAME OVER! Marta WINS {computer_display_score} to {player_display_score}!"
        else:
            # Tie-breaking logic
            if player_base_score > computer_base_score:
                game['winner'] = 'player'
                game['message'] = f"GAME OVER! You WIN {player_display_score} to {computer_display_score} (tie-breaker)!"
            elif computer_base_score > player_base_score:
                game['winner'] = 'computer'
                game['message'] = f"GAME OVER! Marta WINS {computer_display_score} to {player_display_score} (tie-breaker)!"
            else:
                # Bags tie-breaker - negative bags lose
                if player_bags < 0 and computer_bags >= 0:
                    game['winner'] = 'computer'
                    game['message'] = f"GAME OVER! Marta WINS {computer_display_score} to {player_display_score} (negative bags lose)!"
                elif computer_bags < 0 and player_bags >= 0:
                    game['winner'] = 'player'
                    game['message'] = f"GAME OVER! You WIN {player_display_score} to {computer_display_score} (negative bags lose)!"
                elif player_bags < computer_bags:
                    game['winner'] = 'player'
                    game['message'] = f"GAME OVER! You WIN {player_display_score} to {computer_display_score} (fewer bags)!"
                elif computer_bags < player_bags:
                    game['winner'] = 'computer' 
                    game['message'] = f"GAME OVER! Marta WINS {computer_display_score} to {player_display_score} (fewer bags)!"
                else:
                    game['winner'] = 'tie'
                    game['message'] = f"GAME OVER! TIE at {player_display_score} points each!"
        
        return True
    
    return False