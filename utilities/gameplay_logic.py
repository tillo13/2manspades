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

def init_game(player_parity='even', computer_parity='odd'):
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
        'turn': 'player',
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
        'discard_bonus_explanation': None,
        'pending_discard_result': None,
        'pending_special_discard_result': None,
        'blind_bidding_available': False,
        'blind_bid': None,
        'computer_blind_bid': None,  # Track computer blind bids
        'blind_multiplier': 2
    }

def init_new_hand(game):
    """Start a new hand while preserving scores, bags, and parity assignments"""
    deck = create_deck()
    random.shuffle(deck)
    
    game.update({
        'player_hand': sort_hand(deck[:11]),
        'computer_hand': sort_hand(deck[11:22]),
        'current_trick': [],
        'player_tricks': 0,
        'computer_tricks': 0,
        'spades_broken': False,
        'phase': 'discard',
        'turn': 'player',
        'trick_leader': None,
        'hand_over': False,
        'message': f'Hand #{game["hand_number"]} - Select a card to discard',
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
        'blind_bidding_available': False,
        'blind_bid': None,
        'computer_blind_bid': None  # Reset computer blind bid
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
        base_message = 'Computer won the trick!'
    
    # Add special card info to message if present
    if special_result['explanation']:
        game['message'] = f"{base_message} {special_result['explanation']} Cards will clear in 3 seconds..."
    else:
        game['message'] = f"{base_message} Cards will clear in 3 seconds..."
    
    # Mark trick as completed but don't clear yet
    game['trick_completed'] = True
    game['trick_winner'] = winner

def computer_follow(game):
    """Computer plays a card when following"""
    hand = game['computer_hand']
    trick = game['current_trick']
    
    if not trick or not hand:
        return
    
    lead_card = trick[0]['card']
    lead_suit = lead_card['suit']
    lead_value = lead_card['value']
    
    # Find valid plays
    same_suit = [(i, c) for i, c in enumerate(hand) if c['suit'] == lead_suit]
    spades = [(i, c) for i, c in enumerate(hand) if c['suit'] == '♠']
    other = [(i, c) for i, c in enumerate(hand) if c['suit'] != lead_suit and c['suit'] != '♠']
    
    if same_suit:
        # Must follow suit - try to win with lowest winning card
        winners = [(i, c) for i, c in same_suit if c['value'] > lead_value]
        if winners:
            chosen = min(winners, key=lambda x: x[1]['value'])
        else:
            # Can't win, play lowest
            chosen = min(same_suit, key=lambda x: x[1]['value'])
    elif lead_suit != '♠' and spades:
        # Can't follow suit, can trump with spade
        chosen = min(spades, key=lambda x: x[1]['value'])
    else:
        # Can't follow or trump, discard lowest
        all_cards = [(i, c) for i, c in enumerate(hand)]
        chosen = min(all_cards, key=lambda x: x[1]['value'])
    
    idx, card = chosen
    game['computer_hand'].pop(idx)
    game['current_trick'].append({'player': 'computer', 'card': card})
    
    if card['suit'] == '♠':
        game['spades_broken'] = True

def computer_lead(game):
    """Computer plays a card when leading"""
    hand = game['computer_hand']
    
    if not hand:
        return
    
    # Find valid leads
    valid = []
    for i, card in enumerate(hand):
        if card['suit'] != '♠' or game['spades_broken'] or all(c['suit'] == '♠' for c in hand):
            valid.append((i, card))
    
    if not valid:
        return
    
    # Lead lowest valid card
    chosen = min(valid, key=lambda x: (x[1]['suit'] == '♠', x[1]['value']))
    idx, card = chosen
    
    game['computer_hand'].pop(idx)
    game['current_trick'] = [{'player': 'computer', 'card': card}]
    game['trick_leader'] = 'computer'
    
    if card['suit'] == '♠':
        game['spades_broken'] = True

def check_game_over(game):
    """
    Check if the game is over (someone reached target score)
    Updates game state with winner information if game is over
    """
    if game['player_score'] >= game['target_score'] or game['computer_score'] >= game['target_score']:
        game['game_over'] = True
        if game['player_score'] > game['computer_score']:
            game['winner'] = 'player'
            game['message'] = f"GAME OVER! You WIN {game['player_score']} to {game['computer_score']}!"
        elif game['computer_score'] > game['player_score']:
            game['winner'] = 'computer'
            game['message'] = f"GAME OVER! Marta WINS {game['computer_score']} to {game['player_score']}!"
        else:
            game['winner'] = 'tie'
            game['message'] = f"GAME OVER! TIE at {game['player_score']} points each!"
        return True
    return False