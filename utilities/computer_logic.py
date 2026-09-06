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
import threading

# Decision tap (2026-09-06, Otto). Every strategy function reports WHY it chose what it
# chose to a thread-local sink, so a headless bot game (utilities/otto.py) can log the
# branch that fired without duplicating any strategy code. Thread-local, not global: a
# human's game on another gunicorn thread never sees or feeds another game's sink.
# When no sink is set (every live game today) this is a no-op.
_tap = threading.local()

def set_decision_sink(fn, seat=None):
    """fn(kind, seat, data) or None. seat labels who is deciding ('marta' / 'otto')."""
    _tap.sink = fn
    _tap.seat = seat

def set_decision_seat(seat):
    _tap.seat = seat

def _note(kind, data):
    sink = getattr(_tap, 'sink', None)
    if sink:
        sink(kind, getattr(_tap, 'seat', None), data)

def _c(card):
    return f"{card['rank']}{card['suit']}" if card else None

# DIFFICULTY SYSTEM
# Marta's strength is ONE dial (0-100) that the named levels are presets on. Every knob was
# measured with Otto (utilities/otto.py, 2026-09-06, 2,000-game head-to-heads vs easy) so the
# rungs are spaced by what a player can feel, not by guesswork. Easy is pinned to the exact
# pre-dial behaviour: the family's whole record was earned against it.
#   bid_boost    flat add to the hand evaluation (the pre-dial knob)
#   bid_offset   calibration add: the evaluator underestimates by ~1.5 tricks/hand at 0
#   bag_avoid    multiplier on the bid when sitting on 5+ bags
#   max_bid      cap on a regular bid
#   nil_deficit  points behind before nil is considered (80 = the original rule)
#   nil_loose    drop the two-twos / all-low-cards gates (measured: nil still only 8% made,
#                so no preset uses it; the knob stays for experiments)
#   lead_high    probability of leading the highest safe card while tricks are still owed
#   mistake_chance  probability a follow is a random legal card (0 everywhere today)
# Measured vs easy, 2,000 games each: bid_offset peaks at +1.0 (58%), lead_high alone 57%,
# both together 65-66%; a bid cap above 6 and bag_avoid changes bought nothing. 65% is the
# ceiling of this brain, so four rungs, not five — a fifth needs a smarter follow strategy.
#   nil_hunt     probability of playing to SET an opponent's nil (duck under their card so they
#                are forced to win a trick) instead of playing her own hand
#   memory       share of the table she recalls (table_memory): 0 is a child who forgets every
#                card once it's spent, 1 remembers all of them
#   special_hold companions a 7♦/10♣ needs before she keeps it out of the middle (1 = the
#                pre-dial rule: any companion protects it). Measured on 3,937 logged tricks
#                (2026-09-06): a special she holds is cashed 30% (7♦) / 42% (10♣) of the time,
#                one she throws in the middle 50%. So short specials go to the middle as she
#                climbs, until the play that cashes them (trump drawing) exists.
_EASY = {'bid_boost': 0.3, 'bag_avoid': 0.92, 'max_bid': 6, 'mistake_chance': 0,
         'bid_offset': 0.0, 'nil_deficit': 80, 'nil_loose': False, 'lead_high': 0.0, 'nil_hunt': 0.0,
         'memory': 0.0, 'special_hold': 1}

DIFFICULTY_LEVELS = ('easy', 'medium', 'hard', 'ruthless')
# Measured vs easy (2,000 games): medium 58%, hard 62%, ruthless 64%. The top step is small
# because this brain saturates at ~65%; it widens when the follow strategy improves.
STRENGTH_PRESETS = {'easy': 0, 'medium': 30, 'hard': 60, 'ruthless': 100}
RUNG_FLOORS = {'easy': 0, 'medium': 15, 'hard': 45, 'ruthless': 80}   # a strength's rung name
LEVEL_BLURBS = {
    'easy': 'The Marta the family grew up on. Bids a trick under her hand and leads low.',
    'medium': 'Bids a little closer to her hand; sometimes leads high when she still owes tricks.',
    'hard': 'Bids near her hand and usually leads high while tricks are owed.',
    'ruthless': 'Bids to her hand and leads high whenever a trick is owed. Beats easy Marta 2 games in 3.',
}


# The ratchet (2026-09-06, Andy): for players with a track record, Marta's strength moves
# with every finished game — up when they win, down when they lose, bigger swings for bigger
# margins — so the standing flex is beating her at 100 game after game. Newcomers are exempt
# until RATCHET_MIN_GAMES completed games so learning the game never gets punished.
RATCHET_MIN_GAMES = 25


def level_name(strength):
    """Nearest rung name for a strength number (or the name itself if that's what was given)."""
    if isinstance(strength, str):
        return strength if strength in DIFFICULTY_LEVELS else 'easy'
    try:
        s = float(strength)
    except (TypeError, ValueError):
        return 'easy'
    return next(lvl for lvl in reversed(DIFFICULTY_LEVELS) if s >= RUNG_FLOORS[lvl])


def strength_of(setting):
    """Strength number for a session/profile setting that may be a name or a number."""
    if isinstance(setting, str):
        return STRENGTH_PRESETS.get(setting, 0)
    try:
        return max(0, min(100, int(round(float(setting)))))
    except (TypeError, ValueError):
        return 0


def ratchet(strength, won, margin):
    """New strength after a finished game. Step 5-15 scaled by the final margin."""
    step = 5 + min(10, abs(int(margin or 0)) // 25)
    return max(0, min(100, strength_of(strength) + (step if won else -step)))


def strength_params(strength):
    """Knob values for a strength 0-100, linear between easy (0) and the measured ceiling (100)."""
    s = max(0, min(100, float(strength)))
    def lerp(a, b):
        return round(a + (b - a) * s / 100.0, 3)
    return dict(_EASY, bid_offset=lerp(0.0, 1.0), lead_high=lerp(0.0, 1.0), nil_hunt=lerp(0.0, 1.0),
                memory=lerp(0.0, 1.0), special_hold=lerp(1, 3))


def get_difficulty_params(difficulty='easy'):
    """Knobs for a level name, a numeric strength, or an explicit dict of overrides
    (Otto experiments pass dicts). Unknown names fall back to easy."""
    if isinstance(difficulty, dict):
        return dict(_EASY, **difficulty)
    if isinstance(difficulty, (int, float)) and not isinstance(difficulty, bool):
        return strength_params(difficulty)
    if difficulty == 'easy' or difficulty not in STRENGTH_PRESETS:
        return dict(_EASY)
    return strength_params(STRENGTH_PRESETS[difficulty])

# GLOBAL AI DIFFICULTY SETTINGS

# Discard Strategy Settings
SPECIAL_TOSS_PRIORITY = 1000         # A 7♦/10♣ too short to keep (see special_hold) goes to the middle
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


SPECIALS = ('7♦', '10♣')

def table_memory(hand, game_state):
    """What Marta recalls of this hand, from the computer seat. Tricks, both discards and her own
    hand are all public, so nothing here is a guess; the level's `memory` knob is the share of
    it she actually retains (a trick or discard she forgets is gone entirely). Returns
      seen         set of 'rank+suit' out of play (incl. her hand)
      specials_out specials still unaccounted for: not hers, not seen played or in the middle
      opp_void     suits the opponent has been seen failing to follow
      opp_spades   spades the opponent has been seen playing"""
    recall = get_difficulty_params(game_state.get('difficulty', 'easy'))['memory']
    remembers = lambda: recall >= 1 or (recall > 0 and random.random() < recall)
    seen = {_c(c) for c in hand}
    for key in ('player_discarded', 'computer_discarded'):
        if game_state.get(key) and remembers():
            seen.add(_c(game_state[key]))
    opp_void, opp_spades = set(), 0
    leader = game_state.get('first_leader', 'player')
    for t in game_state.get('trick_history', []):
        pc, cc = t.get('player_card'), t.get('computer_card')
        if remembers():
            seen.update(_c(c) for c in (pc, cc) if c)
            if pc and cc:
                led = cc if leader == 'computer' else pc
                if pc['suit'] != led['suit']:
                    opp_void.add(led['suit'])
            opp_spades += bool(pc and pc['suit'] == '♠')
        leader = t.get('winner', leader)
    for play in game_state.get('current_trick', []):   # on the table now: nobody forgets that
        seen.add(_c(play['card']))
        opp_spades += play.get('player') == 'player' and play['card']['suit'] == '♠'
    return {'seen': seen, 'specials_out': [x for x in SPECIALS if x not in seen],
            'opp_void': opp_void, 'opp_spades': opp_spades}

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
    
    hold = get_difficulty_params(game_state.get('difficulty', 'easy'))['special_hold']
    discard_candidates = []
    
    for i, card in enumerate(computer_hand):
        score = 0
        suit_info = suit_distribution[card['suit']]
        is_special, _ = is_special_card(card)
        
        # PRIORITY 1: A special too short to keep goes to the middle (a coin flip beats
        # holding a card that only pays if it wins its own trick)
        if is_special and suit_info['count'] - 1 < hold:
            discard_candidates.append((i, SPECIAL_TOSS_PRIORITY))
            continue
        
        # PRIORITY 2: Special card protection (a special she's keeping). (A void-creation
        # bonus for singletons used to sit here, dead since its elif chained to the branch
        # above; removed 2026-09-06 so easy stays exactly the Marta the record was earned on.)
        if is_special:
            score += SPECIAL_CARD_PROTECTION  # Negative score
        
        # PRIORITY 3: Avoid discarding spades
        if card['suit'] == '♠':
            score -= card['value'] * SPADE_DISCARD_PENALTY
        else:
            # Prefer discarding low cards from other suits
            score += (15 - card['value'])
        
        # PRIORITY 4: Light parity consideration
        discard_value = get_discard_value(card)
        if computer_parity == 'even' and discard_value % 2 == 1:
            score += PARITY_CONSIDERATION
        elif computer_parity == 'odd' and discard_value % 2 == 0:
            score += PARITY_CONSIDERATION
        
        discard_candidates.append((i, score))
    
    # Return index of card with highest discard score
    best = max(discard_candidates, key=lambda x: x[1])
    _note('discard', {'card': _c(computer_hand[best[0]]), 'score': best[1], 'hold': hold,
                      'spades': suit_distribution['♠']['count'],
                      'singleton': suit_distribution[computer_hand[best[0]]['suit']]['is_singleton']})
    return best[0]

# BIDDING STRATEGY

def should_bid_nil(hand, game_state):
    """
    Determine if computer should bid nil
    """
    player_score = game_state.get('player_score', 0)
    computer_score = game_state.get('computer_score', 0)
    player_bid = game_state.get('player_bid', 0)
    params = get_difficulty_params(game_state.get('difficulty', 'easy'))

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

    other_suits = [card for card in hand if card['suit'] != '♠']
    if not params['nil_loose']:
        # Original gates. Otto measured them at 0 nil bids in 87,000 hands (2026-09-06):
        # a deal never carries two twos AND all-low side suits AND a sub-0.8 expectation.
        # Must have at least 2 twos for safety
        twos = [card for card in hand if card['rank'] == '2']
        if len(twos) < 2:
            return False

        # Must have mostly very low cards (2-7) in other suits
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

    # Only nil when behind by the level's deficit (80 = the original rule)
    return computer_score < player_score - params['nil_deficit']

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
    # Get difficulty from game_state (defaults to 'easy')
    difficulty = game_state.get('difficulty', 'easy')
    diff_params = get_difficulty_params(difficulty)

    player_score = game_state.get('player_score', 0)
    computer_score = game_state.get('computer_score', 0)
    computer_bags = game_state.get('computer_bags', 0)

    sure_tricks, probable_tricks, special_bonus = analyze_hand_strength(computer_hand)
    why = {'sure': sure_tricks, 'probable': probable_tricks, 'special': special_bonus,
           'opp_bid': player_bid, 'score_diff': computer_score - player_score,
           'bags': computer_bags, 'difficulty': difficulty,
           'spades': sum(1 for c in computer_hand if c['suit'] == '♠')}

    # Check for nil opportunity first
    if should_bid_nil(computer_hand, game_state):
        _note('bid', dict(why, branch='nil', bid=0))
        return 0, False

    # Check for blind bidding opportunity
    should_blind, blind_amount = should_bid_blind(computer_hand, game_state)
    if should_blind:
        _note('bid', dict(why, branch='blind', bid=blind_amount))
        return blind_amount, True

    # Regular bidding logic
    base_expectation = sure_tricks + probable_tricks + special_bonus

    # Apply difficulty-based accuracy boost + the measured calibration offset
    base_expectation += diff_params['bid_boost'] + diff_params['bid_offset']

    # Score-based adjustments
    score_diff = computer_score - player_score
    if score_diff > 30:  # Ahead - be slightly conservative
        base_expectation *= (1 - SCORE_BASED_ADJUSTMENT)
    elif score_diff < -30:  # Behind - be slightly aggressive
        base_expectation *= (1 + SCORE_BASED_ADJUSTMENT)

    # Bag avoidance when close to penalty (difficulty-adjusted)
    if computer_bags >= 5:
        base_expectation *= diff_params['bag_avoid']

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
    why.update(expectation=round(base_expectation, 2), rounded=raw_bid, coin=None)

    # Apply difficulty-based maximum bid cap
    max_bid = diff_params['max_bid']
    raw_bid = min(raw_bid, max_bid)

    # Bid range preferences
    if 2.5 <= base_expectation <= 5.5:
        if raw_bid < 3:
            raw_bid = 3  # Minimum reasonable bid is 3
        elif raw_bid == 5 and random.random() < 0.4:
            raw_bid = 4  # Sometimes prefer 4 over 5
            why['coin'] = 'prefer4'

    # Avoid obvious total-10 scenarios
    if player_bid is not None and abs((raw_bid + player_bid) - 10) <= 1 and random.random() < 0.3:
        if raw_bid > 3:
            raw_bid -= 1
            why['coin'] = 'avoid10'

    # Final bounds check with difficulty max
    raw_bid = max(1, min(max_bid, raw_bid))

    _note('bid', dict(why, branch='regular', bid=raw_bid))
    return raw_bid, False

# PLAYING STRATEGY

def computer_lead_strategy(computer_hand, spades_broken, game_state=None):
    """Lead a card; see _lead_impl. Reports the choice to the decision tap."""
    idx = _lead_impl(computer_hand, spades_broken, game_state)
    if idx is not None:
        g = game_state or {}
        _note('lead', {'card': _c(computer_hand[idx]), 'hand_size': len(computer_hand),
                       'spades_broken': spades_broken, 'bid': g.get('computer_bid'),
                       'tricks': g.get('computer_tricks'), 'opp_bags': g.get('player_bags')})
    return idx


def _lead_impl(computer_hand, spades_broken, game_state=None):
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
        # Stronger levels: while tricks are still owed, lead the highest safe card (with the
        # level's probability). Leading low hands the follower the trick: the leader won
        # 32.5% of tricks (Otto, 2026-09-06). No random draw at 0 so easy stays replayable.
        if computer_tricks < computer_bid:
            lh = get_difficulty_params(game_state.get('difficulty', 'easy'))['lead_high']
            if lh and (lh >= 1 or random.random() < lh):
                return max(leads_to_consider, key=lambda x: x[1]['value'])[0]
    
    # Normal strategy: lead lowest safe card
    return min(leads_to_consider, key=lambda x: x[1]['value'])[0]

def computer_follow_strategy(computer_hand, current_trick, game_state):
    """Follow a lead; see _follow_impl. Reports the choice + its options to the decision tap."""
    idx = _follow_impl(computer_hand, current_trick, game_state)
    if idx is not None:
        lead = current_trick[0]['card']
        bid = game_state.get('computer_bid', 0)
        _note('follow', {'card': _c(computer_hand[idx]), 'lead': _c(lead), 'hand_size': len(computer_hand),
                         'could_follow': any(c['suit'] == lead['suit'] for c in computer_hand),
                         'could_trump': lead['suit'] != '♠' and any(c['suit'] == '♠' for c in computer_hand),
                         'made_bid': game_state.get('computer_tricks', 0) >= bid > 0,
                         'bid': bid, 'tricks': game_state.get('computer_tricks', 0)})
    return idx


def _follow_impl(computer_hand, current_trick, game_state):
    """
    Enhanced following strategy with special card protection and acquisition
    Returns index of best card to play
    """
    if not current_trick or not computer_hand:
        return None

    from .custom_rules import is_special_card

    computer_bid = game_state.get('computer_bid') or 0
    computer_tricks = game_state.get('computer_tricks', 0)

    # Check if computer has already made their bid. A nil bid counts as "made" from the
    # first trick: the whole point is to lose every trick. Before 2026-09-06 a nil hand fell
    # into the needs-tricks branch and played to WIN — Otto measured 0 nils made in 91 tries.
    made_bid = (computer_tricks >= computer_bid and computer_bid > 0) or computer_bid == 0

    lead_card = current_trick[0]['card']
    lead_suit = lead_card['suit']
    lead_value = lead_card['value']

    # Nil hunting (stronger levels): the opponent bid nil and is still clean, so the trick is
    # worth 100 points to THEM if they lose it. Duck: follow suit under their card, or dump
    # off-suit, so they are forced to win. Special cards are never spent on the duck.
    if game_state.get('player_bid') == 0 and game_state.get('player_tricks', 0) == 0:
        hunt = get_difficulty_params(game_state.get('difficulty', 'easy'))['nil_hunt']
        if hunt and (hunt >= 1 or random.random() < hunt):
            in_suit = [(i, c) for i, c in enumerate(computer_hand)
                       if c['suit'] == lead_suit and c['value'] < lead_value and not is_special_card(c)[0]]
            if in_suit:
                return max(in_suit, key=lambda x: x[1]['value'])[0]
            if not any(c['suit'] == lead_suit for c in computer_hand):
                dump = [(i, c) for i, c in enumerate(computer_hand)
                        if c['suit'] != '♠' and not is_special_card(c)[0]]
                if dump:
                    return max(dump, key=lambda x: x[1]['value'])[0]

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