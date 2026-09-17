"""Factual game totals, computed only from complete recorded hands."""
import re

# custom_rules.calculate_hand_scores_with_bags writes one per seat per hand, worded this way since 2025-08-30
_BAG_PENALTY = re.compile(r'\b(You|Marta): BAG PENALTY! -(\d+)00 pts')
SPECIAL_CARDS = ('10♣', '7♦')


def _bags_and_specials(played, hands_played, player):
    """Bag penalties per seat, read from each hand's scoring line, and who took 10♣ and 7♦, from
    each hand's ten tricks plus the middle. Always shown; a hand without the record isn't counted,
    and the row says how many hands it covers."""
    seat = {'You': player, 'Marta': 'Marta', 'player': player, 'computer': 'Marta'}
    penalties, scored = {player: 0, 'Marta': 0}, 0
    taken = {card: {player: 0, 'Marta': 0} for card in SPECIAL_CARDS}
    dealt = 0
    for h in played:
        text = (h.get('scoring') or {}).get('explanation')
        if text is not None:
            scored += 1
            for who, hundreds in _BAG_PENALTY.findall(text):
                penalties[seat[who]] += int(hundreds)
        history, middle = h['trick_history'], h.get('middle') or {}
        if h.get('trick_totals') is None or middle.get('winner') not in seat:
            continue
        dealt += 1
        won = [(t['winner'], (t.get('player_card'), t.get('computer_card'))) for t in history]
        won.append((seat[middle['winner']], (middle.get('player_card'), middle.get('computer_card'))))
        for winner, cards in won:
            for card in SPECIAL_CARDS:
                if card in cards:
                    taken[card][winner] += 1

    def row(label, counts, covered):
        of = '' if covered == hands_played else f' ({covered} of {hands_played} hands recorded)'
        return dict(label=label + of, player=counts[player], computer=counts['Marta'])

    return [row('Bag penalties (-100)', penalties, scored)] + \
           [row(f'{card} taken', taken[card], dealt) for card in SPECIAL_CARDS]


def summarize_game(hands, summary):
    played = [h for h in hands if h['hand_number'] > 0]
    player = summary['player_name']
    names = (player, 'Marta')
    totals = {name: dict(tricks=0, nils=0, nil_attempts=0, blinds=0, blind_attempts=0) for name in names}
    complete = bool(played) and [h['hand_number'] for h in played] == list(range(1, (summary.get('hands_played') or 0) + 1))
    bids_complete = complete
    progression = []
    for h in played:
        history = h['trick_history']
        full = sorted(t['number'] for t in history) == list(range(1, 11)) and all(t['winner'] in names for t in history)
        complete = complete and full
        if full and isinstance(h.get('auto_tricks'), int) and 0 < h['auto_tricks'] <= 10:
            for trick in history:
                trick['auto_played'] = trick['number'] > 10 - h['auto_tricks']
        h['trick_totals'] = {name: sum(t['winner'] == name for t in history) for name in names} if full else None
        final = h.get('final_bids') or {}
        # The first leader bids first (hand_flow: computer bids first when first_leader is computer).
        leader = final.get('first_leader') or h.get('first_leader')
        seats = ('computer', 'player') if leader == 'computer' else ('player', 'computer')
        by_seat = dict(zip(('player', 'computer'), names))
        if all(final.get(f'{seat}_bid') is not None for seat in seats):
            h['bids'] = [dict(player=by_seat[seat], amount=final[f'{seat}_bid'], is_nil=final[f'{seat}_bid'] == 0,
                              is_blind=bool(final.get(f'{seat}_blind')))
                         for seat in seats]
        h['first_bidder'] = h['bids'][0]['player'] if h['bids'] else (by_seat[seats[0]] if leader else None)
        bids = {b['player']: b for b in h['bids']}
        bids_complete = bids_complete and set(bids) == set(names)
        if full:
            for name in names:
                taken = h['trick_totals'][name]
                totals[name]['tricks'] += taken
                bid = bids.get(name)
                if bid:
                    made = taken == 0 if bid['amount'] == 0 else taken >= bid['amount']
                    bid['taken'], bid['made'] = taken, made
                    for key, applies in [('nil', bid['amount'] == 0), ('blind', bid['is_blind'])]:
                        if applies:
                            totals[name][key + '_attempts'] += 1
                            totals[name][key + 's'] += int(made)
        scores = h.get('scoring') or {}
        if all(scores.get(key) is not None for key in ('player_score', 'computer_score')):
            progression.append(dict(hand=h['hand_number'], player=scores['player_score'], computer=scores['computer_score']))
    rows = []
    if complete:
        rows.append(dict(label='Tricks taken', player=totals[player]['tricks'], computer=totals['Marta']['tricks']))
        if bids_complete:
            for key, label in [('nil', 'Nils made / bid'), ('blind', 'Blinds made / bid')]:
                if any(totals[n][key + '_attempts'] for n in names):
                    values = [f"{totals[n][key + 's']} / {totals[n][key + '_attempts']}" for n in names]
                    rows.append(dict(label=label, player=values[0], computer=values[1]))
    rows += _bags_and_specials(played, summary.get('hands_played') or len(played), player)
    levels = list(dict.fromkeys(h['difficulty'] for h in played if h.get('difficulty')))
    return dict(comparison=rows, progression=progression, difficulties=levels)
