"""Hand flow: bidding, blind bidding, discard, trick resolution (with Marta's follow/lead),
hand completion and auto-resolution. Everything here mutates the session game dict."""
from flask import session
import time
from .logging_utils import log_action, log_game_event, track_session_client, get_client_ip, IS_PRODUCTION
from .custom_rules import (
    check_special_cards_in_trick, reduce_bags_safely, assign_even_odd_at_game_start,
    calculate_discard_score_with_winner, calculate_hand_scores_with_bags,
    get_player_names_with_parity, check_special_cards_in_discard,
    check_blind_bidding_eligibility, get_display_score, apply_keep_alive
)
from .gameplay_logic import determine_trick_winner, init_game, init_new_hand, check_game_over
from .computer_logic import (
    computer_follow_strategy, computer_lead_strategy, computer_bidding_brain,
    computer_discard_strategy, autoplay_remaining_cards
)
from .logging_utils import initialize_game_logging_with_client, finalize_game_logging, flush_hand_events



def process_bidding_phase(game, session, bid, request):
    """Process player bidding with computer response and game state updates"""
    log_action(
        action_type='regular_bid',
        player='player',
        action_data={'bid_amount': bid, 'is_nil': bid == 0},
        session=session,
        request=request
    )
    
    game['player_bid'] = bid
    
    if game.get('computer_bid') is None:
        computer_bid, computer_is_blind = computer_bidding_brain(
            game['computer_hand'], 
            bid, 
            game
        )
        game['computer_bid'] = computer_bid
        
        if computer_is_blind:
            game['computer_blind_bid'] = computer_bid
            log_action(
                action_type='blind_bid',
                player='computer',
                action_data={'bid_amount': computer_bid, 'in_response_to_player': True},
                session=session
            )
        else:
            log_action(
                action_type='regular_bid',
                player='computer',
                action_data={'bid_amount': computer_bid, 'in_response_to_player': True},
                session=session
            )
            
        computer_blind_text = " (BLIND)" if computer_is_blind else ""
        player_blind_text = " (BLIND)" if game.get('blind_bid') == bid else ""
        
        message_base = f'You bid {bid}{player_blind_text}, Marta bid {computer_bid}{computer_blind_text}.'
    else:
        computer_blind_text = " (BLIND)" if game.get('computer_blind_bid') else ""
        player_blind_text = " (BLIND)" if game.get('blind_bid') == bid else ""
        
        message_base = f'You bid {bid}{player_blind_text}, Marta bid {game["computer_bid"]}{computer_blind_text}.'
    
    game['phase'] = 'playing'
    first_leader = game.get('first_leader', 'player')
    game['turn'] = first_leader
    game['trick_leader'] = first_leader
    
    log_game_event(
        event_type='bidding_complete',
        event_data={
            'player_bid': game['player_bid'],
            'computer_bid': game['computer_bid'],
            'first_leader': first_leader,
            'player_blind': game.get('blind_bid') is not None,
            'computer_blind': game.get('computer_blind_bid') is not None
        },
        session=session
    )
    
    if first_leader == 'player':
        game['message'] = f'{message_base} Your turn to lead the first trick.'
    else:
        game['message'] = f'{message_base} Marta leads the first trick.'
        computer_lead_with_logging(game, session)
        game['turn'] = 'player'
        game['message'] = f'{message_base} Marta led. Your turn to follow.'


def process_blind_bid_phase(game, session, bid, request):
    """Process blind bidding phase"""
    log_action(
        action_type='blind_bid',
        player='player',
        action_data={'bid_amount': bid},
        session=session,
        request=request
    )
    
    game['blind_bid'] = bid
    game['player_bid'] = bid
    
    computer_bid, computer_is_blind = computer_bidding_brain(
        game['computer_hand'], 
        bid, 
        game
    )
    game['computer_bid'] = computer_bid
    
    if computer_is_blind:
        game['computer_blind_bid'] = computer_bid
        log_action(
            action_type='blind_bid',
            player='computer',
            action_data={'bid_amount': computer_bid, 'in_response_to_player': True},
            session=session
        )
    else:
        log_action(
            action_type='regular_bid',
            player='computer',
            action_data={'bid_amount': computer_bid, 'in_response_to_blind': True},
            session=session
        )
    
    game['phase'] = 'discard'
    computer_blind_text = " (BLIND)" if computer_is_blind else ""
    game['message'] = f'You bid BLIND {bid}! Marta bid {computer_bid}{computer_blind_text}. Select a card to discard.'


def process_discard_phase(game, session, card_index, request):
    """Process discard phase with computer response and scoring"""
    player_card = game['player_hand'].pop(card_index)
    game['player_discarded'] = player_card
    
    log_action(
        action_type='discard',
        player='player',
        action_data={
            'card_discarded': f"{player_card['rank']}{player_card['suit']}",
            'card_index': card_index
        },
        session=session,
        additional_context={'hand_size_after': len(game['player_hand'])},
        request=request
    )
    
    idx = computer_discard_strategy(game['computer_hand'], game)
    computer_card = game['computer_hand'].pop(idx)
    game['computer_discarded'] = computer_card
    
    log_action(
        action_type='discard',
        player='computer',
        action_data={
            'card_discarded': f"{computer_card['rank']}{computer_card['suit']}",
            'card_index': idx
        },
        session=session,
        additional_context={'hand_size_after': len(game['computer_hand'])}
    )
    
    discard_result = calculate_discard_score_with_winner(
        game['player_discarded'],
        game['computer_discarded'],
        game.get('player_parity', 'even'),
        game.get('computer_parity', 'odd'),
        game
    )
    
    game['pending_discard_result'] = discard_result
    
    special_discard_result = check_special_cards_in_discard(
        game['player_discarded'],
        game['computer_discarded'],
        discard_result['winner']
    )
    
    game['pending_special_discard_result'] = special_discard_result
    
    log_game_event(
        event_type='discard_scoring',
        event_data={
            'player_card': f"{player_card['rank']}{player_card['suit']}",
            'computer_card': f"{computer_card['rank']}{computer_card['suit']}",
            'winner': discard_result['winner'],
            'bonus_points': discard_result['player_bonus'] + discard_result['computer_bonus'],
            'is_double': discard_result['is_double'],
            'explanation': discard_result['explanation']
        },
        session=session
    )
    
    # Handle post-discard phase transitions
    if game.get('player_bid') is not None:
        # Bids already set, go to playing
        transition_to_playing_phase(game, session)
    else:
        # CRITICAL FIX: Check if blind decision was already made
        if not game.get('blind_decision_made', False):
            # First time - check blind eligibility or go to bidding
            transition_to_bidding_phase(game, session)
        else:
            # Already made blind decision (chose "Bid Normal"), proceed directly to bidding
            game['phase'] = 'bidding'
            first_leader = game.get('first_leader', 'player')
            
            if first_leader == 'computer':
                # Computer bids first
                computer_bid, computer_is_blind = computer_bidding_brain(
                    game['computer_hand'], 
                    None,
                    game
                )
                game['computer_bid'] = computer_bid
                
                if computer_is_blind:
                    game['computer_blind_bid'] = computer_bid
                    computer_blind_text = " (BLIND)"
                    log_action(
                        action_type='blind_bid',
                        player='computer',
                        action_data={'bid_amount': computer_bid, 'bid_first': True},
                        session=session
                    )
                else:
                    computer_blind_text = ""
                    log_action(
                        action_type='regular_bid',
                        player='computer',
                        action_data={'bid_amount': computer_bid, 'bid_first': True},
                        session=session
                    )
                
                game['message'] = f'Cards discarded. Marta bid {computer_bid}{computer_blind_text}. Your turn to bid.'
            else:
                # Player bids first
                game['message'] = f'Cards discarded. Now make your bid: How many tricks will you take? (0-10)'


def transition_to_playing_phase(game, session):
    """Transition from discard to playing phase"""
    game['phase'] = 'playing'
    first_leader = game.get('first_leader', 'player')
    game['turn'] = first_leader
    game['trick_leader'] = first_leader
    
    player_blind_text = " (BLIND)" if game.get('blind_bid') else ""
    computer_blind_text = " (BLIND)" if game.get('computer_blind_bid') else ""
    
    if first_leader == 'player':
        game['message'] = f'Cards discarded. You bid {game["player_bid"]}{player_blind_text}, Marta bid {game["computer_bid"]}{computer_blind_text}. Your turn to lead the first trick.'
    else:
        game['message'] = f'Cards discarded. You bid {game["player_bid"]}{player_blind_text}, Marta bid {game["computer_bid"]}{computer_blind_text}. Marta leads the first trick.'
        computer_lead_with_logging(game, session)
        game['turn'] = 'player'
        game['message'] = f'Cards discarded. You bid {game["player_bid"]}{player_blind_text}, Marta bid {game["computer_bid"]}{computer_blind_text}. Marta led. Your turn to follow.'


def transition_to_bidding_phase(game, session):
    """Transition from discard to bidding phase (or blind decision) - Uses display scores for eligibility"""
    
    # CRITICAL FIX: Only check blind eligibility ONCE per hand
    # If we've already been through blind decision, skip straight to bidding
    if game.get('blind_decision_made', False):
        print(f"DEBUG: Blind decision already made this hand, proceeding to normal bidding")
        game['phase'] = 'bidding'
        first_leader = game.get('first_leader', 'player')
        
        if first_leader == 'computer':
            # Computer bids first
            computer_bid, computer_is_blind = computer_bidding_brain(
                game['computer_hand'], 
                None,
                game
            )
            game['computer_bid'] = computer_bid
            
            if computer_is_blind:
                game['computer_blind_bid'] = computer_bid
                computer_blind_text = " (BLIND)"
                log_action(
                    action_type='blind_bid',
                    player='computer',
                    action_data={'bid_amount': computer_bid, 'bid_first': True},
                    session=session
                )
            else:
                computer_blind_text = ""
                log_action(
                    action_type='regular_bid',
                    player='computer',
                    action_data={'bid_amount': computer_bid, 'bid_first': True},
                    session=session
                )
            
            game['message'] = f'Cards discarded. Marta bid {computer_bid}{computer_blind_text}. Your turn to bid.'
        else:
            # Player bids first
            game['message'] = f'Cards discarded. Now make your bid: How many tricks will you take? (0-10)'
        return
    
    # First time checking blind eligibility this hand - use DISPLAY SCORES
    player_base_score = game.get('player_score', 0)
    computer_base_score = game.get('computer_score', 0)
    player_bags = game.get('player_bags', 0)
    computer_bags = game.get('computer_bags', 0)
    
    # Calculate display scores (what players actually see)
    player_display_score = get_display_score(player_base_score, player_bags)
    computer_display_score = get_display_score(computer_base_score, computer_bags)
    
    # Check eligibility based on display scores
    blind_eligibility = check_blind_bidding_eligibility(player_display_score, computer_display_score)
    
    print(f"DEBUG BLIND CHECK: Player Display={player_display_score} (base={player_base_score}, bags={player_bags}), Computer Display={computer_display_score} (base={computer_base_score}, bags={computer_bags})")
    print(f"DEBUG BLIND CHECK: Player Eligible={blind_eligibility['player_eligible']}, Computer Eligible={blind_eligibility['computer_eligible']}")
    print(f"DEBUG BLIND CHECK: Player Deficit={blind_eligibility['player_deficit']}, Computer Deficit={blind_eligibility['computer_deficit']}")
    
    if blind_eligibility['player_eligible']:
        # Player is eligible for blind bidding - ask them to choose
        game['phase'] = 'blind_decision'
        game['blind_decision_made'] = True  # Mark that we've presented the choice
        deficit = computer_display_score - player_display_score
        game['message'] = f'Cards discarded! You are down by {deficit} points. Choose: Go BLIND for double points/penalties, or bid normally?'
        
        print(f"DEBUG: Entering blind_decision phase with deficit of {deficit}")
    else:
        # Player not eligible for blind bidding - go straight to normal bidding
        game['blind_decision_made'] = True  # Mark that we've checked (even though not eligible)
        game['phase'] = 'bidding'
        first_leader = game.get('first_leader', 'player')
        
        if first_leader == 'computer':
            # Computer bids first
            computer_bid, computer_is_blind = computer_bidding_brain(
                game['computer_hand'], 
                None,
                game
            )
            game['computer_bid'] = computer_bid
            
            if computer_is_blind:
                game['computer_blind_bid'] = computer_bid
                computer_blind_text = " (BLIND)"
                log_action(
                    action_type='blind_bid',
                    player='computer',
                    action_data={'bid_amount': computer_bid, 'bid_first': True},
                    session=session
                )
            else:
                computer_blind_text = ""
                log_action(
                    action_type='regular_bid',
                    player='computer',
                    action_data={'bid_amount': computer_bid, 'bid_first': True},
                    session=session
                )
            
            game['message'] = f'Cards discarded. Marta bid {computer_bid}{computer_blind_text}. Your turn to bid.'
        else:
            # Player bids first
            game['message'] = f'Cards discarded. Now make your bid: How many tricks will you take? (0-10)'
        
        print(f"DEBUG: Player not eligible for blind bidding (deficit only {blind_eligibility['player_deficit']}), proceeding to normal bidding")


def resolve_trick_with_delay(game, session_obj=None):
    """Resolve trick and set it up to be displayed for 3 seconds with logging"""
    if len(game['current_trick']) != 2:
        return
    
    winner = determine_trick_winner(game['current_trick'])
    
    # Save trick to history
    trick_number = len(game.get('trick_history', [])) + 1
    player_card = next((play['card'] for play in game['current_trick'] if play['player'] == 'player'), None)
    computer_card = next((play['card'] for play in game['current_trick'] if play['player'] == 'computer'), None)
    
    game.setdefault('trick_history', []).append({
        'number': trick_number,
        'player_card': player_card,
        'computer_card': computer_card,
        'winner': winner
    })
    
    # Console logging
    p_text = f"{player_card['rank']}{player_card['suit']}" if player_card else "?"
    c_text = f"{computer_card['rank']}{computer_card['suit']}" if computer_card else "?"
    winner_name = "You" if winner == 'player' else "Marta"
    print(f"TRICK {trick_number}: {p_text} vs {c_text} -> {winner_name} wins")
    
    # JSON logging
    if session_obj:
        log_game_event(
            event_type='trick_completed',
            event_data={
                'trick_number': trick_number,
                'player_card': p_text,
                'computer_card': c_text,
                'winner': winner,
                'winner_name': winner_name
            },
            session=session_obj
        )
    
    # Apply special card effects immediately
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
        
        if session_obj:
            log_game_event(
                event_type='special_card_effect',
                event_data={
                    'trick_number': trick_number,
                    'bag_reduction': special_result['bag_reduction'],
                    'beneficiary': winner_name,
                    'explanation': special_result['explanation']
                },
                session=session_obj
            )
    
    # Award trick and set message
    if winner == 'player':
        game['player_tricks'] += 1
        base_message = 'You won the trick!'
    else:
        game['computer_tricks'] += 1
        base_message = 'Marta won the trick!'
    
    if special_result['explanation']:
        game['message'] = f"{base_message} {special_result['explanation']}."
    else:
        game['message'] = f"{base_message}."
    
    game['trick_completed'] = True
    game['trick_winner'] = winner


def computer_follow_with_logging(game, session_obj=None):
    """Computer plays a card when following with logging"""
    hand = game['computer_hand']
    trick = game['current_trick']
    
    if not trick or not hand:
        return
    
    # Use enhanced strategy or fallback
    chosen_idx = computer_follow_strategy(hand, trick, game)
    
    if chosen_idx is None:
        # Fallback logic
        lead_card = trick[0]['card']
        lead_suit = lead_card['suit']
        lead_value = lead_card['value']
        
        same_suit = [(i, c) for i, c in enumerate(hand) if c['suit'] == lead_suit]
        spades = [(i, c) for i, c in enumerate(hand) if c['suit'] == '♠']
        
        if same_suit:
            winners = [(i, c) for i, c in same_suit if c['value'] > lead_value]
            if winners:
                chosen_idx = min(winners, key=lambda x: x[1]['value'])[0]
            else:
                chosen_idx = min(same_suit, key=lambda x: x[1]['value'])[0]
        elif lead_suit != '♠' and spades:
            chosen_idx = min(spades, key=lambda x: x[1]['value'])[0]
        else:
            all_cards = [(i, c) for i, c in enumerate(hand)]
            chosen_idx = min(all_cards, key=lambda x: x[1]['value'])[0]
    
    # Play the card
    card = hand.pop(chosen_idx)
    game['current_trick'].append({'player': 'computer', 'card': card})
    
    # Logging
    if session_obj:
        lead_card = game['current_trick'][0]['card'] if len(game['current_trick']) >= 1 else None
        log_action(
            action_type='card_play',
            player='computer',
            action_data={
                'card_played': f"{card['rank']}{card['suit']}",
                'trick_position': 2,
                'following_suit': card['suit'] == lead_card['suit'] if lead_card else False
            },
            session=session_obj,
            additional_context={
                'responding_to': f"{lead_card['rank']}{lead_card['suit']}" if lead_card else None,
                'hand_size_after': len(hand)
            }
        )
    
    if card['suit'] == '♠':
        game['spades_broken'] = True
        if session_obj:
            log_game_event('spades_broken', {'broken_by': 'computer', 'card': f"{card['rank']}{card['suit']}"}, session_obj)


def computer_lead_with_logging(game, session_obj=None):
    """Computer plays a card when leading with logging"""
    hand = game['computer_hand']
    
    if not hand:
        return
    
    # Use enhanced strategy or fallback
    chosen_idx = computer_lead_strategy(hand, game['spades_broken'], game)
    
    if chosen_idx is None:
        # Fallback logic
        valid = []
        for i, card in enumerate(hand):
            if card['suit'] != '♠' or game['spades_broken'] or all(c['suit'] == '♠' for c in hand):
                valid.append((i, card))
        
        if valid:
            chosen = min(valid, key=lambda x: (x[1]['suit'] == '♠', x[1]['value']))
            chosen_idx = chosen[0]
        else:
            return
    
    # Play the card
    card = hand.pop(chosen_idx)
    game['current_trick'] = [{'player': 'computer', 'card': card}]
    game['trick_leader'] = 'computer'
    
    # Logging
    if session_obj:
        log_action(
            action_type='card_play',
            player='computer',
            action_data={
                'card_played': f"{card['rank']}{card['suit']}",
                'trick_position': 1,
                'leading': True
            },
            session=session_obj,
            additional_context={
                'hand_size_after': len(hand)
            }
        )
    
    if card['suit'] == '♠':
        game['spades_broken'] = True
        if session_obj:
            log_game_event('spades_broken', {'broken_by': 'computer', 'card': f"{card['rank']}{card['suit']}"}, session_obj)


def process_hand_completion(game, session):
    """All ten tricks played: score the hand."""
    log_game_event(
        event_type='hand_completed',
        event_data={
            'hand_number': game['hand_number'],
            'player_tricks': game['player_tricks'],
            'computer_tricks': game['computer_tricks'],
            'player_bid': game.get('player_bid', 0),
            'computer_bid': game.get('computer_bid', 0)
        },
        session=session
    )
    _complete_hand(game, session)


def process_auto_resolution(game, session):
    """Remaining tricks are mathematically settled: play them out and score the hand."""
    auto_resolved, explanation = autoplay_remaining_cards(game, session)
    if auto_resolved:
        _complete_hand(game, session, explanation)
    return auto_resolved


def _card(c):
    return f"{c['rank']}{c['suit']}" if c else None


def _tricks_with_leaders(game):
    """The hand's tricks with who led each (the first leader, then whoever took the last one)."""
    out, leader = [], game.get('first_leader', 'player')
    for t in game.get('trick_history', []):
        out.append({'number': t['number'], 'player_card': _card(t['player_card']) or '?',
                    'computer_card': _card(t['computer_card']) or '?',
                    'leader': 'You' if leader == 'player' else 'Marta',
                    'winner': 'You' if t['winner'] == 'player' else 'Marta'})
        leader = t['winner']
    return out


def _complete_hand(game, session, auto_explanation=None):
    """Shared tail of both completion paths (they were two 80-line copies until 2026-09-06):
    apply the middle, score with bags, keep-alive, build hand_results, log, and settle
    whether the game is over. Also appends the hand to game['hand_log'] for the final screen."""
    hand_discard = None
    if 'pending_discard_result' in game:
        discard_result = game['pending_discard_result']
        hand_discard = discard_result
        game['player_score'] += discard_result['player_bonus']
        game['computer_score'] += discard_result['computer_bonus']
        game['discard_bonus_explanation'] = discard_result['explanation']
        special = game.pop('pending_special_discard_result', None)
        if special:
            for seat in ('player', 'computer'):
                if special[f'{seat}_bag_reduction'] > 0:
                    game[f'{seat}_bags'] = reduce_bags_safely(game.get(f'{seat}_bags', 0), special[f'{seat}_bag_reduction'])
            if special['explanation']:
                game['discard_bonus_explanation'] += " | " + special['explanation']
        del game['pending_discard_result']

    scoring_result = calculate_hand_scores_with_bags(game)

    # The middle can be thrown back on a game-deciding hand (family rule, 2026-09-06)
    kept_alive = apply_keep_alive(game, hand_discard)
    if kept_alive:
        game['discard_bonus_explanation'] = (game.get('discard_bonus_explanation') or '') + ' → ' + kept_alive

    # A blind nil ends the game inside scoring; the full results still show alongside it
    blind_nil_ending = game.get('game_over', False)

    player_display_score = get_display_score(game['player_score'], game.get('player_bags', 0))
    computer_display_score = get_display_score(game['computer_score'], game.get('computer_bags', 0))
    hand_results = {
        'hand_number': game['hand_number'],
        'parity': {
            'player': game.get('player_parity', 'even').title(),
            'computer': game.get('computer_parity', 'odd').title()
        },
        'discard_info': game.get('discard_bonus_explanation', ''),
        'scoring': scoring_result['explanation'],
        'trick_history': _tricks_with_leaders(game),
        'totals': {
            'player_score': player_display_score,
            'computer_score': computer_display_score
        }
    }
    if auto_explanation:
        hand_results['auto_resolution'] = auto_explanation
    game['hand_results'] = hand_results

    # One line per hand for the game-over tally
    pb, cb = game.get('player_bid') or 0, game.get('computer_bid') or 0
    game.setdefault('hand_log', []).append({
        'hand': game['hand_number'],
        'player_bid': pb, 'player_tricks': game['player_tricks'], 'player_blind': game.get('blind_bid') is not None,
        'computer_bid': cb, 'computer_tricks': game['computer_tricks'], 'computer_blind': game.get('computer_blind_bid') is not None,
        'player_specials': game.get('player_trick_special_cards', 0),
        'computer_specials': game.get('computer_trick_special_cards', 0),
        'player_score': player_display_score, 'computer_score': computer_display_score,
        'player_bags': game.get('player_bags', 0), 'computer_bags': game.get('computer_bags', 0),
        'middle': {'player': _card(game.get('player_discarded')), 'computer': _card(game.get('computer_discarded')),
                   'winner': hand_discard.get('winner') if hand_discard else None},
    })

    flush_hand_events(session)
    log_game_event(
        event_type='hand_scoring',
        event_data={
            'scoring_explanation': scoring_result['explanation'],
            'final_scores': {
                'player_score': player_display_score,
                'computer_score': computer_display_score
            },
            'hand_results': hand_results
        },
        session=session
    )
    finalize_game_logging(game)

    if blind_nil_ending:
        # The blind nil sentence set in scoring is the record; keep it
        log_game_event(
            event_type='game_completed',
            event_data={
                'winner': game['winner'],
                'final_message': game['message'],
                'hands_played': game['hand_number'],
                'game_end_reason': 'blind_nil_auto_resolve' if auto_explanation else 'blind_nil'
            },
            session=session
        )
        return

    game['message'] = f"Hand #{game['hand_number']} complete! Click 'Next Hand' to continue"
    if auto_explanation:
        game['message'] = f"{auto_explanation}. " + game['message']
    if check_game_over(game):
        log_game_event(
            event_type='game_completed',
            event_data={
                'winner': game['winner'],
                'final_message': game['message'],
                'hands_played': game['hand_number']
            },
            session=session
        )


def _finalize_game_async(hand_id, game):
    try:
        from .postgres_utils import finalize_hand  # CHANGED from finalize_game
        success = finalize_hand(hand_id, game)
        if success:
            print(f"[DB] Hand {hand_id} finalized in database")
        else:
            print(f"[DB] Hand {hand_id} failed to finalize in database")
        return success
    except Exception as e:
        print(f"[DB] Database hand finalization failed: {e}")
        import traceback
        traceback.print_exc()  # This will show you the import error
        return False
