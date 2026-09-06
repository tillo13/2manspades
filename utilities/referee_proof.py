"""Otto Matic's proof: Otto vs Marta on seeded games, twice. Once with lay downs dealt out, once
with every hand played to the last card by the real strategies. Per-hand bids, tricks, scores and
bags must match on every game, and every call is checked against the played-out trick split.
Writes static/referee_proof.json (totals + about forty calls, varied) for the /referee page.

    venv_2man/bin/python -m utilities.referee_proof --games 10000
"""
import argparse
import json
import os
import random
import time
from contextlib import ExitStack, redirect_stdout
from io import StringIO
from unittest.mock import patch

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(_ROOT, 'static', 'referee_proof.json')
SPECIALS = ('7♦', '10♣')


def run_proof(n, quiet=True):
    from utilities import otto, hand_flow, computer_logic
    c = lambda x: f"{x['rank']}{x['suit']}"
    calls, times, seed_now = [], [], [0]
    _orig, _ld = computer_logic.autoplay_remaining_cards, computer_logic.lay_down

    def timed(game, leader=None):
        t = time.perf_counter(); r = _ld(game, leader); times.append(time.perf_counter() - t); return r

    def counting(game, sess=None, leader=None):
        pos = {'seed': seed_now[0], 'hand': game['hand_number'], 'after_trick': len(game.get('trick_history', [])),
               'leader': (game.get('lay_down_offer') or {}).get('leader', leader), 'spades_broken': bool(game.get('spades_broken')),
               'otto': [c(x) for x in game['player_hand']], 'marta': [c(x) for x in game['computer_hand']],
               'otto_tricks_before': game['player_tricks'], 'marta_tricks_before': game['computer_tricks']}
        call = dict(game.get('lay_down_offer') or {})
        ok, why = _orig(game, sess, leader)
        if ok:
            pos.update(call={'winner': call['winner'], 'tricks': call['tricks'], 'why': call['why']},
                       dealt=[(t['number'], c(t['player_card']), c(t['computer_card']), t['winner']) for t in game['trick_history'] if t.get('laid_down')])
            calls.append(pos)
        return ok, why

    def run(full):
        out = {}
        with ExitStack() as st:
            if quiet:
                st.enter_context(redirect_stdout(StringIO()))
            st.enter_context(patch.object(computer_logic, 'lay_down', timed))
            if full:
                st.enter_context(patch.object(hand_flow, 'process_auto_resolution', lambda *a, **k: False))
                st.enter_context(patch.object(otto, 'process_auto_resolution', lambda *a, **k: False))
            else:
                st.enter_context(patch.object(hand_flow, 'autoplay_remaining_cards', counting))
            for seed in range(1, n + 1):
                seed_now[0] = seed
                r = otto.play_game(seed=seed)
                out[seed] = {d['hand']: (d['otto_bid'], d['otto_tricks'], d['marta_bid'], d['marta_tricks'], d['otto_score'], d['marta_score'], d['otto_bags'], d['marta_bags'])
                             for d in r['decisions'] if d['kind'] == 'hand'}
        return out

    a = run(False); b = run(True)
    diff = [s for s in a if a[s] != b[s]]
    for call in calls:
        po = b[call['seed']].get(call['hand'])
        w = call['call']['winner']
        want = (call['otto_tricks_before'] + (call['call']['tricks'] if w == 'player' else 0),
                call['marta_tricks_before'] + (call['call']['tricks'] if w == 'computer' else 0))
        call['played_out'] = {'otto_tricks': po[1], 'marta_tricks': po[3]} if po else None
        call['held'] = bool(po) and (po[1], po[3]) == want
    by_cards = {}
    for call in calls:
        by_cards[len(call['otto'])] = by_cards.get(len(call['otto']), 0) + 1
    times.sort()
    summary = {'games': n, 'hands': sum(len(v) for v in a.values()), 'lay_downs': len(calls),
               'tricks_dealt': sum(x['call']['tricks'] for x in calls), 'from_first_card': sum(x['after_trick'] == 0 for x in calls),
               'to_otto': sum(x['call']['winner'] == 'player' for x in calls), 'to_marta': sum(x['call']['winner'] == 'computer' for x in calls),
               'by_cards_left': {str(k): v for k, v in sorted(by_cards.items())}, 'held': sum(x['held'] for x in calls),
               'games_differ': len(diff), 'referee_calls': len(times),
               'referee_ms_avg': round(1000 * sum(times) / max(1, len(times)), 3),
               'referee_ms_p99': round(1000 * times[int(0.99 * len(times))], 2) if times else 0,
               'referee_ms_max': round(1000 * (times[-1] if times else 0), 1),
               'run_at': time.strftime('%Y-%m-%d')}
    return summary, calls, diff


def curate(calls, seed=1):
    """About forty, varied: every size from 10 cards down to 2, both winners, and calls where a
    special card sits in the dealt-out tricks."""
    random.seed(seed)
    want = {10: 3, 9: 3, 8: 4, 7: 5, 6: 5, 5: 5, 4: 5, 3: 5, 2: 5}
    out = []
    for k, n in want.items():
        pool = [x for x in calls if len(x['otto']) == k]
        random.shuffle(pool)
        picked, seen_w, seen_sp = [], set(), False
        for x in pool:   # first pass: cover both winners and a special-card case
            w = x['call']['winner']; sp = any(t[1] in SPECIALS or t[2] in SPECIALS for t in x['dealt'])
            if (w not in seen_w) or (sp and not seen_sp):
                picked.append(x); seen_w.add(w); seen_sp = seen_sp or sp
            if len(picked) >= n:
                break
        for x in pool:
            if len(picked) >= n:
                break
            if x not in picked:
                picked.append(x)
        out += picked
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('--games', type=int, default=10000)
    ap.add_argument('--out', default=OUT)
    a = ap.parse_args(argv)
    summary, calls, diff = run_proof(a.games)
    json.dump({'summary': summary, 'calls': curate(calls)}, open(a.out, 'w'), ensure_ascii=False)
    print(json.dumps(summary))
    for s in diff[:3]:
        print('differs:', s)
    print(f"-> {a.out}")


if __name__ == '__main__':
    main()
