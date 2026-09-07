"""Factual game totals, computed only from complete recorded hands."""


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
        final = h.get('final_bids')
        if final and all(final.get(f'{seat}_bid') is not None for seat in ('player', 'computer')):
            h['bids'] = [dict(player=name, amount=final[f'{seat}_bid'], is_nil=final[f'{seat}_bid'] == 0,
                              is_blind=bool(final.get(f'{seat}_blind')))
                         for seat, name in zip(('player', 'computer'), names)]
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
    levels = list(dict.fromkeys(h['difficulty'] for h in played if h.get('difficulty')))
    return dict(comparison=rows, progression=progression, difficulties=levels)
