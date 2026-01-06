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
    
    game = {
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
    
    # Log initial hands dealt for first hand
    from .logging_utils import log_game_event
    
    # Log player's starting hand
    player_hand_cards = [f"{card['rank']}{card['suit']}" for card in game['player_hand']]
    log_game_event(
        event_type='hand_dealt',
        event_data={
            'hand_number': game['hand_number'],
            'player': 'player',
            'cards': player_hand_cards,
            'card_count': len(player_hand_cards)
        },
        session={'game': game}
    )
    
    # Log computer's starting hand
    computer_hand_cards = [f"{card['rank']}{card['suit']}" for card in game['computer_hand']]
    log_game_event(
        event_type='hand_dealt',
        event_data={
            'hand_number': game['hand_number'],
            'player': 'computer',
            'cards': computer_hand_cards,
            'card_count': len(computer_hand_cards)
        },
        session={'game': game}
    )
    
    return game


def init_new_hand(game):
    """Start a new hand while preserving scores, bags, and parity assignments"""
    
    # Generate new hand ID for this hand
    import uuid
    game['current_hand_id'] = str(uuid.uuid4())
    
    deck = create_deck()
    random.shuffle(deck)
    
    # Alternate who leads the first trick each hand
    current_first_leader = game.get('first_leader', 'player')
    next_first_leader = 'computer' if current_first_leader == 'player' else 'player'
    
    # Get current scores and bags for blind eligibility check
    player_base_score = game.get('player_score', 0)
    computer_base_score = game.get('computer_score', 0)
    player_bags = game.get('player_bags', 0)
    computer_bags = game.get('computer_bags', 0)
    
    from .custom_rules import check_blind_bidding_eligibility, get_display_score
    player_display_score = get_display_score(player_base_score, player_bags)
    computer_display_score = get_display_score(computer_base_score, computer_bags)
    blind_eligibility = check_blind_bidding_eligibility(player_display_score, computer_display_score)
    
    # Set initial phase and message based on blind eligibility
    if blind_eligibility['player_eligible']:
        initial_phase = 'blind_decision'
        deficit = computer_display_score - player_display_score
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
        'phase': initial_phase,
        'turn': 'player',
        'trick_leader': None,
        'hand_over': False,
        'message': initial_message,
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
    
    # Log starting hands for this new hand
    from .logging_utils import log_game_event
    
    # Log player's starting hand
    player_hand_cards = [f"{card['rank']}{card['suit']}" for card in game['player_hand']]
    log_game_event(
        event_type='hand_dealt',
        event_data={
            'hand_number': game['hand_number'],
            'player': 'player',
            'cards': player_hand_cards,
            'card_count': len(player_hand_cards)
        },
        session={'game': game}
    )
    
    # Log computer's starting hand
    computer_hand_cards = [f"{card['rank']}{card['suit']}" for card in game['computer_hand']]
    log_game_event(
        event_type='hand_dealt',
        event_data={
            'hand_number': game['hand_number'],
            'player': 'computer',
            'cards': computer_hand_cards,
            'card_count': len(computer_hand_cards)
        },
        session={'game': game}
    )

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

def check_game_over(game):
    """
    Check if the game is over (someone reached target score OR down by 300+ points)
    Updates game state with winner information if game is over
    
    SIMPLE RULE: Higher display score ALWAYS wins!
    - 302 beats 300 (regardless of bags)
    - 301 beats 300 (regardless of bags)
    - Bags only matter as tie-breaker when display scores are EXACTLY tied
    - More bags (further from 0) is always worse, whether positive or negative
    """
    player_base_score = game['player_score']
    computer_base_score = game['computer_score']
    player_bags = game.get('player_bags', 0)
    computer_bags = game.get('computer_bags', 0)
    target_score = game['target_score']
    
    from .custom_rules import get_display_score
    player_display_score = get_display_score(player_base_score, player_bags)
    computer_display_score = get_display_score(computer_base_score, computer_bags)
    
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
        
        # SIMPLE: Higher display score wins. Period.
        if player_display_score > computer_display_score:
            game['winner'] = 'player'
            game['message'] = f"GAME OVER! You WIN {player_display_score} to {computer_display_score}!"
        elif computer_display_score > player_display_score:
            game['winner'] = 'computer'
            game['message'] = f"GAME OVER! Marta WINS {computer_display_score} to {player_display_score}!"
        else:
            # Display scores are EXACTLY tied (e.g., both 300)
            # Only NOW do we look at tie-breakers
            
            # First tie-breaker: Higher base score
            if player_base_score > computer_base_score:
                game['winner'] = 'player'
                game['message'] = f"GAME OVER! You WIN {player_display_score} to {computer_display_score} (higher base score tie-breaker)!"
            elif computer_base_score > player_base_score:
                game['winner'] = 'computer'
                game['message'] = f"GAME OVER! Marta WINS {computer_display_score} to {player_display_score} (higher base score tie-breaker)!"
            else:
                # Second tie-breaker: Fewer bags (closer to 0 is better)
                # Convert to absolute values to compare distance from 0
                player_bag_distance = abs(player_bags)
                computer_bag_distance = abs(computer_bags)
                
                if player_bag_distance < computer_bag_distance:
                    # Player has fewer bags (closer to 0)
                    game['winner'] = 'player'
                    game['message'] = f"GAME OVER! You WIN {player_display_score} to {computer_display_score} (fewer bags: {player_bags} vs {computer_bags})!"
                elif computer_bag_distance < player_bag_distance:
                    # Computer has fewer bags (closer to 0)
                    game['winner'] = 'computer'
                    game['message'] = f"GAME OVER! Marta WINS {computer_display_score} to {player_display_score} (fewer bags: {computer_bags} vs {player_bags})!"
                else:
                    # Absolute tie - same everything
                    game['winner'] = 'tie'
                    game['message'] = f"GAME OVER! ABSOLUTE TIE at {player_display_score} points each!"
        
        return True
    
    return False