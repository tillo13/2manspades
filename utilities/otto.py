"""Otto — a bot that plays Marta, headless, with Marta's own brain.

Why: the house algorithm (computer_logic) only ever ran inside a human's game, so nobody could
see how it decides across hundreds of hands. Otto sits in the player seat, runs the SAME
strategy functions on a mirrored view of the game, and drives the SAME hand_flow the web
routes use, so every rule, special card and scoring quirk is the live one. No LLM anywhere:
Marta's chat is never invoked, so a bot game costs compute and rows only.

Two consumers, one engine:
  * /cron/otto (app.py, cron.yaml every 72 min): one game, persisted to twomanspades.bot_games
    + bot_decisions. Keeps the Robot League on /stats moving and catches a deploy that changes
    behaviour.
  * `python -m utilities.otto --games 2000 --seed 1` on a laptop: the analysis run. Same engine,
    in-memory, aggregates printed and a per-hand CSV in _oneoff/. Never a decision row per trick
    into prod — the shared Cloud SQL disk is the one real cost here.

Bot games never touch the human tables: the game dict carries _no_log so logging_utils drops
every action/event, and the ledger below is its own pair of tables. (2026-09-06)
"""
import argparse
import contextlib
import csv
import io
import json
import os
import random
import time
import uuid

from .gameplay_logic import init_game, init_new_hand, is_valid_play
from .custom_rules import assign_even_odd_at_game_start, get_display_score
from .computer_logic import (computer_bidding_brain, computer_discard_strategy, computer_lead_strategy,
                             computer_follow_strategy, should_bid_blind, set_decision_sink, set_decision_seat,
                             DIFFICULTY_LEVELS, get_difficulty_params)
from .hand_flow import (process_discard_phase, process_bidding_phase, process_blind_bid_phase,
                        computer_follow_with_logging, computer_lead_with_logging, resolve_trick_with_delay,
                        process_hand_completion, process_auto_resolution)

MAX_HANDS = 60          # a 300-point game runs ~6-12 hands; this is a runaway guard, not a rule
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SEAT = {'player': 'otto', 'computer': 'marta'}

# Otto decides from Marta's point of view: swap the two seats so the strategy functions,
# which only know 'computer_*', see Otto's cards and score as their own.
_SWAP = [('player_hand', 'computer_hand'), ('player_bid', 'computer_bid'),
         ('player_tricks', 'computer_tricks'), ('player_score', 'computer_score'),
         ('player_bags', 'computer_bags'), ('player_parity', 'computer_parity'),
         ('blind_bid', 'computer_blind_bid'), ('player_discarded', 'computer_discarded'),
         ('player_trick_special_cards', 'computer_trick_special_cards')]


_SEAT_FLIP = {'player': 'computer', 'computer': 'player'}


def _mirror(game, difficulty):
    m = dict(game)
    for a, b in _SWAP:
        m[a], m[b] = game.get(b), game.get(a)
    # The table memory (trick history, leader, current trick) names seats too.
    m['first_leader'] = _SEAT_FLIP.get(game.get('first_leader'), game.get('first_leader'))
    m['trick_history'] = [dict(t, player_card=t.get('computer_card'), computer_card=t.get('player_card'),
                               winner=_SEAT_FLIP.get(t.get('winner'), t.get('winner')))
                          for t in game.get('trick_history', [])]
    m['current_trick'] = [dict(p, player=_SEAT_FLIP.get(p.get('player'), p.get('player')))
                          for p in game.get('current_trick', [])]
    m['difficulty'] = difficulty
    return m


def _app_version():
    try:
        with open(os.path.join(_ROOT, 'VERSION')) as f:
            return f.read().strip()[:40]
    except OSError:
        return None


def play_game(seed=None, otto_difficulty='easy', marta_difficulty='easy', persist=False, source='batch',
              persona=None):
    """Play one full game, Otto (player seat) vs Marta (computer seat). Returns a result dict
    with the decision ledger; persist=True also files it in the Robot League tables.

    persona: {'email', 'name', 'google_id', 'tag'} — play AS a logged-in person. The game is
    then logged through the SAME path a human game takes (hands + game_events under their
    Google identity), so every stat counts it as theirs; the only trace is hands.played_by.
    """
    seed = random.randrange(1 << 31) if seed is None else int(seed)
    random.seed(seed)
    t0 = time.monotonic()
    decisions = []
    with contextlib.redirect_stdout(io.StringIO()):     # hand_flow prints every trick; not for bots
        player_parity, computer_parity, first_leader = assign_even_odd_at_game_start()
        game = init_game(player_parity, computer_parity, first_leader)
        game.update(difficulty=marta_difficulty, current_hand_id=str(uuid.uuid4()),
                    game_id=str(uuid.uuid4()), game_started_at=time.time(), action_sequence=0)
        if persona:
            # a human-shaped game: started a while ago, logged under the person's identity
            game['game_started_at'] = time.time() - 60 * random.uniform(8, 20)
            game['client_info'] = {'ip_address': None, 'user_agent': persona.get('tag', 'bot'),
                                   'google_auth': {'email': persona['email'], 'name': persona['name'],
                                                   'google_id': persona.get('google_id'),
                                                   'picture': None}}
            sess = {'game': game}
            _open_persona_hand(game, persona)
        else:
            game['_no_log'] = True
            sess = {}   # no 'game' key: hand_flow's logging paths see nothing to log

        def sink(kind, seat, data):
            decisions.append(dict(data, hand=game['hand_number'], seat=seat, kind=kind))
        set_decision_sink(sink)
        try:
            hands = 0
            while not game.get('game_over') and hands < MAX_HANDS:
                hands += 1
                _play_hand(game, sess, otto_difficulty, decisions)
                if game.get('game_over'):
                    break
                game['hand_number'] += 1
                init_new_hand(game)
                if persona:
                    _open_persona_hand(game, persona)
        finally:
            set_decision_sink(None)

    winner = {'player': 'otto', 'computer': 'marta'}.get(game.get('winner'), 'tie')
    result = {
        'game_id': game['game_id'], 'seed': seed, 'source': source,
        'otto_difficulty': otto_difficulty, 'marta_difficulty': marta_difficulty,
        'first_leader': SEAT[first_leader], 'winner': winner, 'hands': game['hand_number'],
        'otto_score': get_display_score(game['player_score'], game.get('player_bags', 0)),
        'marta_score': get_display_score(game['computer_score'], game.get('computer_bags', 0)),
        'otto_bags': game.get('player_bags', 0), 'marta_bags': game.get('computer_bags', 0),
        'ms': int((time.monotonic() - t0) * 1000), 'app_version': _app_version(),
        'decisions': decisions, 'decision_count': len(decisions),
    }
    if persist:
        _persist(result)
    return result


def _log(sess, action_type, data, **ctx):
    """Player-seat actions the web routes log themselves (card plays, the blind choice);
    only fires for persona games — a plain bot game has no 'game' in sess."""
    if sess.get('game'):
        from .logging_utils import log_action
        log_action(action_type=action_type, player='player', action_data=data, session=sess,
                   additional_context=ctx or None)


def _play_hand(game, sess, otto_difficulty, decisions):
    hand = game['player_hand']
    # 1. Blind decision (only offered when Otto is 100+ behind) — Marta's own rule decides.
    if game['phase'] == 'blind_decision':
        set_decision_seat('otto')
        blind, amount = should_bid_blind(hand, _mirror(game, otto_difficulty))
        game['blind_decision_made'] = True
        _log(sess, 'blind_decision', {'chose_blind': bool(blind), 'chose_normal': not blind})
        if blind:
            decisions.append({'kind': 'bid', 'seat': 'otto', 'hand': game['hand_number'],
                              'branch': 'blind', 'bid': amount, 'opp_bid': None})
            game['phase'] = 'blind_bidding'
            set_decision_seat('marta')
            process_blind_bid_phase(game, sess, amount, None)
        else:
            game['phase'] = 'discard'
    # 2. Discard
    set_decision_seat('otto')
    idx = computer_discard_strategy(hand, _mirror(game, otto_difficulty))
    set_decision_seat('marta')
    process_discard_phase(game, sess, idx, None)
    # 3. Bid (unless the blind bid already set it). If Marta led the bidding her bid is known.
    if game['phase'] == 'bidding':
        set_decision_seat('otto')
        bid, _ = computer_bidding_brain(hand, game.get('computer_bid'), _mirror(game, otto_difficulty))
        set_decision_seat('marta')
        process_bidding_phase(game, sess, bid, None)
    # 4. Play out the tricks, exactly as /play + /clear_trick do.
    guard = 0
    while not game.get('hand_over') and guard < 60:
        guard += 1
        if game.get('trick_completed'):
            _clear_trick(game, sess)
            continue
        set_decision_seat('otto')
        m = _mirror(game, otto_difficulty)
        if game['current_trick']:
            idx = computer_follow_strategy(hand, game['current_trick'], m)
        else:
            idx = computer_lead_strategy(hand, game['spades_broken'], m)
        if idx is None or not is_valid_play(hand[idx], hand, game['current_trick'], game['spades_broken']):
            idx = next(i for i, c in enumerate(hand)
                       if is_valid_play(c, hand, game['current_trick'], game['spades_broken']))
        _log(sess, 'card_play', {'card_played': f"{hand[idx]['rank']}{hand[idx]['suit']}", 'card_index': idx,
                                 'trick_position': len(game['current_trick']) + 1,
                                 'leading': len(game['current_trick']) == 0},
             hand_size_before=len(hand), spades_broken_before=game['spades_broken'])
        card = hand.pop(idx)
        game['current_trick'].append({'player': 'player', 'card': card})
        if card['suit'] == '♠':
            game['spades_broken'] = True
            if sess.get('game'):
                from .logging_utils import log_game_event
                log_game_event('spades_broken', {'broken_by': 'player', 'card': f"{card['rank']}{card['suit']}"}, sess)
        set_decision_seat('marta')
        if len(game['current_trick']) == 1:
            game['trick_leader'] = 'player'
            game['turn'] = 'computer'
            computer_follow_with_logging(game, sess)
        resolve_trick_with_delay(game, sess)
        _mark_trick_outcome(decisions, game.get('trick_winner'))
    if game.get('trick_completed'):
        _clear_trick(game, sess)
    if game.get('hand_over'):
        _record_hand(game, decisions)


def _clear_trick(game, sess):
    winner = game.get('trick_winner')
    game['current_trick'] = []
    game['trick_completed'] = False
    game['trick_winner'] = None
    if not game['player_hand']:
        game['hand_over'] = True
        process_hand_completion(game, sess)
    elif game['computer_hand'] and not process_auto_resolution(game, sess):
        if winner == 'computer':
            computer_lead_with_logging(game, sess)
        game['turn'] = 'player'


def _mark_trick_outcome(decisions, winner):
    """The trick just resolved had exactly one lead and one follow; stamp both with the result."""
    left = 2
    for d in reversed(decisions):
        if left == 0:
            break
        if d['kind'] in ('lead', 'follow') and 'won' not in d:
            d['won'] = (d['seat'] == 'otto') == (winner == 'player')
            left -= 1


def _record_hand(game, decisions):
    ob, mb = game.get('player_bid') or 0, game.get('computer_bid') or 0
    ot, mt = game.get('player_tricks', 0), game.get('computer_tricks', 0)
    decisions.append({
        'kind': 'hand', 'seat': 'both', 'hand': game['hand_number'],
        'otto_bid': ob, 'otto_tricks': ot, 'otto_blind': game.get('blind_bid') is not None,
        'marta_bid': mb, 'marta_tricks': mt, 'marta_blind': game.get('computer_blind_bid') is not None,
        'otto_over': max(0, ot - ob) if ob > 0 else 0, 'marta_over': max(0, mt - mb) if mb > 0 else 0,
        'otto_score': get_display_score(game['player_score'], game.get('player_bags', 0)),
        'marta_score': get_display_score(game['computer_score'], game.get('computer_bags', 0)),
        'otto_bags': game.get('player_bags', 0), 'marta_bags': game.get('computer_bags', 0),
    })


# ─── Persona games: a bot that plays AS a person ───────────────────────────────
# Andy, 2026-09-06: "I want andybot deployed in a cron... it looks like I'm playing and
# continuing my rabid style, undetected on the stats page, but a column shows it's a bot."
# The game rides the human logging path under his Google identity; hands.played_by is the
# only marker. Profile from his measured line (266 hands): bids a trick high, leads high,
# goes blind whenever offered, ignores Marta's bid for the total.
ANDY = {'email': 'andy.tillo@gmail.com', 'name': 'Andy Tillo', 'google_id': '103015520286665847399',
        'tag': 'andybot', 'params': {'bid_offset': 1.2, 'max_bid': 8, 'lead_high': 1.0}}
_PLAYED_BY_OK = False


def _open_persona_hand(game, persona):
    """Create the hands row the way a live game does, then mark it as the bot's."""
    global _PLAYED_BY_OK
    from utilities.postgres_utils import create_hand_with_player, get_db_connection, return_db_connection
    create_hand_with_player(game, game['client_info'])
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        if not _PLAYED_BY_OK:
            from utilities.schema_guard import add_column_if_missing
            add_column_if_missing(cur, 'twomanspades', 'hands', 'played_by', 'TEXT')
            _PLAYED_BY_OK = True
        cur.execute("UPDATE twomanspades.hands SET played_by = %s WHERE hand_id = %s",
                    (persona.get('tag', 'bot'), game['current_hand_id']))
        conn.commit()
        cur.close()
    finally:
        return_db_connection(conn)


def persona_plan(persona_tag, day=None):
    """Which hours (Pacific) the persona plays today, or [] on a day off. About three days a
    week, 1-3 games on a playing day, fixed per date so every instance agrees."""
    day = day or _dt.date.today()
    rng = random.Random(f"{persona_tag}-{day.isoformat()}")
    if rng.random() > 3 / 7:
        return []
    return sorted(rng.sample(range(9, 22), rng.randint(1, 3)))


def play_persona_tick(persona=ANDY):
    """Hourly cron: if this hour is on today's plan and not yet played, play one game as the
    persona at their current ratcheted Marta and move the ratchet like a real result would."""
    from utilities.computer_logic import ratchet, level_name
    from utilities.postgres_utils import get_user_strength, save_user_strength
    now = _dt.datetime.now()
    plan = persona_plan(persona['tag'], now.date())
    if now.hour not in plan:
        return {'plan': plan, 'played': False, 'reason': 'not this hour'}
    stamp = int(now.strftime('%Y%m%d%H'))
    if _read_state(f"{persona['tag']}_last_hour") == stamp:
        return {'plan': plan, 'played': False, 'reason': 'already played this hour'}
    _save_state(f"{persona['tag']}_last_hour", stamp)
    strength = get_user_strength(persona['email']) or 0
    r = play_game(otto_difficulty=persona['params'], marta_difficulty=strength, persona=persona, source='persona')
    after = ratchet(strength, r['winner'] == 'otto', r['otto_score'] - r['marta_score'])
    save_user_strength(persona['email'], after)
    return {'plan': plan, 'played': True, 'winner': persona['name'].split()[0] if r['winner'] == 'otto' else r['winner'],
            'score': f"{r['otto_score']}-{r['marta_score']}", 'hands': r['hands'],
            'marta_strength': f"{strength} -> {after} ({level_name(after)})"}


def _read_state(key):
    from utilities.postgres_utils import get_db_connection, return_db_connection
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        _ensure_schema(cur)
        cur.execute("SELECT value FROM twomanspades.bot_state WHERE key = %s", (key,))
        row = cur.fetchone()
        cur.close()
        return row[0] if row else None
    finally:
        return_db_connection(conn)


# ─── The daily drip (cron) ─────────────────────────────────────────────────────
# Andy, 2026-09-06: "let it pick between 1-100 games a day at random to mix it up", and
# "Otto should get ratcheted the same way when playing Marta". So: one quota per calendar
# day drawn from the date (every instance agrees), spread across the 96 cron ticks; and
# Marta's strength against Otto moves with each result like it does for a person, so it
# settles wherever Otto wins half the time — a live measure of how strong easy-Otto is.
import datetime as _dt

CRON_TICKS_PER_DAY = 96          # cron.yaml: every 15 minutes


def daily_target(day=None):
    """How many games Otto plays today, 1-100, fixed for the day."""
    day = day or _dt.date.today()
    return random.Random(f"otto-{day.isoformat()}").randint(1, 100)


def games_due(target, played_today, now=None):
    """How many games this tick should play so the day's quota lands evenly: 0, 1 or 2."""
    now = now or _dt.datetime.now()
    frac = (now.hour * 60 + now.minute + 1) / (24 * 60)
    behind = int(round(target * frac)) - played_today
    return max(0, min(2, behind))


def play_cron_tick():
    """One cron tick: draw today's quota, play what's due, ratchet Marta against Otto."""
    from utilities.computer_logic import ratchet, level_name
    from utilities.postgres_utils import get_db_connection, return_db_connection
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        _ensure_schema(cur)
        conn.commit()   # return_db_connection rolls back: without this the CREATEs vanished (1st tick, 2026-09-06)
        cur.execute("SELECT COUNT(*) FROM twomanspades.bot_games WHERE played_at::date = CURRENT_DATE")
        played = cur.fetchone()[0]
        cur.execute("SELECT value FROM twomanspades.bot_state WHERE key = 'marta_strength_vs_otto'")
        row = cur.fetchone()
        strength = row[0] if row else 0
        cur.close()
    finally:
        return_db_connection(conn)
    target = daily_target()
    due = games_due(target, played)
    results = []
    for _ in range(due):
        r = play_game(marta_difficulty=strength, source='cron')
        r['marta_strength'] = strength
        before = strength
        strength = ratchet(strength, r['winner'] == 'otto', r['otto_score'] - r['marta_score'])
        r['marta_strength_after'] = strength
        _persist(r)
        _save_state('marta_strength_vs_otto', strength)
        results.append({'winner': r['winner'], 'otto': r['otto_score'], 'marta': r['marta_score'],
                        'hands': r['hands'], 'marta_strength': f"{before} -> {strength} ({level_name(strength)})"})
    return {'target_today': target, 'played_before': played, 'played_now': played + due, 'games': results,
            'marta_strength_vs_otto': strength}


def _save_state(key, value):
    from utilities.postgres_utils import get_db_connection, return_db_connection
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO twomanspades.bot_state (key, value, updated_at) VALUES (%s, %s, NOW())
            ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = NOW()
        """, (key, int(value)))
        conn.commit()
        cur.close()
    finally:
        return_db_connection(conn)


# ─── Ledger ───────────────────────────────────────────────────────────────────
_SCHEMA_OK = False


def _ensure_schema(cur):
    global _SCHEMA_OK
    if _SCHEMA_OK:
        return
    from utilities.schema_guard import table_exists, create_index_if_missing
    if not table_exists(cur, 'twomanspades', 'bot_games'):
        cur.execute("""
            CREATE TABLE IF NOT EXISTS twomanspades.bot_games (
                game_id          UUID PRIMARY KEY,
                played_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                source           TEXT,            -- cron | batch
                seed             BIGINT,
                otto_difficulty  TEXT,
                marta_difficulty TEXT,
                first_leader     TEXT,            -- otto | marta
                winner           TEXT,            -- otto | marta | tie
                hands            SMALLINT,
                otto_score       INTEGER,
                marta_score      INTEGER,
                otto_bags        INTEGER,
                marta_bags       INTEGER,
                ms               INTEGER,
                app_version      TEXT
            )
        """)
    if not table_exists(cur, 'twomanspades', 'bot_decisions'):
        cur.execute("""
            CREATE TABLE IF NOT EXISTS twomanspades.bot_decisions (
                id       BIGSERIAL PRIMARY KEY,
                game_id  UUID NOT NULL REFERENCES twomanspades.bot_games(game_id) ON DELETE CASCADE,
                hand     SMALLINT,
                seat     TEXT,                    -- otto | marta | both
                kind     TEXT,                    -- bid | discard | lead | follow | hand
                data     JSONB NOT NULL
            )
        """)
    if not table_exists(cur, 'twomanspades', 'bot_state'):
        cur.execute("""
            CREATE TABLE IF NOT EXISTS twomanspades.bot_state (
                key        TEXT PRIMARY KEY,
                value      INTEGER NOT NULL,
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """)
    from utilities.schema_guard import add_column_if_missing
    add_column_if_missing(cur, 'twomanspades', 'bot_games', 'marta_strength', 'INTEGER')
    create_index_if_missing(cur, 'twomanspades', 'idx_bot_games_played', 'bot_games', '(played_at DESC)')
    create_index_if_missing(cur, 'twomanspades', 'idx_bot_decisions_game', 'bot_decisions', '(game_id)')
    create_index_if_missing(cur, 'twomanspades', 'idx_bot_decisions_kind', 'bot_decisions', '(kind, seat)')
    cur.connection.commit()   # DDL must land before any caller trusts _SCHEMA_OK
    _SCHEMA_OK = True


def _persist(r):
    from utilities.postgres_utils import get_db_connection, return_db_connection
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        _ensure_schema(cur)
        from utilities.computer_logic import level_name
        cur.execute("""
            INSERT INTO twomanspades.bot_games
                (game_id, source, seed, otto_difficulty, marta_difficulty, first_leader, winner, hands,
                 otto_score, marta_score, otto_bags, marta_bags, ms, app_version, marta_strength)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        """, (r['game_id'], r['source'], r['seed'], level_name(r['otto_difficulty']),
              level_name(r['marta_difficulty']), r['first_leader'], r['winner'], r['hands'],
              r['otto_score'], r['marta_score'], r['otto_bags'], r['marta_bags'], r['ms'],
              r['app_version'], r.get('marta_strength')))
        cur.executemany("""
            INSERT INTO twomanspades.bot_decisions (game_id, hand, seat, kind, data)
            VALUES (%s,%s,%s,%s,%s)
        """, [(r['game_id'], d['hand'], d['seat'], d['kind'],
               json.dumps({k: v for k, v in d.items() if k not in ('hand', 'seat', 'kind')}))
              for d in r['decisions']])
        conn.commit()
        cur.close()
    finally:
        return_db_connection(conn)


# ─── Batch runner (laptop analysis; nothing hits prod unless --persist) ────────
def summarize(results):
    games = len(results)
    wins = {'otto': 0, 'marta': 0, 'tie': 0}
    first_leader_wins = 0
    seats = {s: {'hands': 0, 'exact': 0, 'nil_tried': 0, 'nil_made': 0, 'blind_tried': 0,
                 'blind_made': 0, 'over': 0, 'bid_sum': 0} for s in ('otto', 'marta')}
    for r in results:
        wins[r['winner']] += 1
        if r['winner'] == r['first_leader']:
            first_leader_wins += 1
        for d in r['decisions']:
            if d['kind'] != 'hand':
                continue
            for s in seats:
                bid, tricks, blind = d[f'{s}_bid'], d[f'{s}_tricks'], d[f'{s}_blind']
                x = seats[s]
                x['hands'] += 1
                x['exact'] += bid == tricks
                x['nil_tried'] += bid == 0
                x['nil_made'] += bid == 0 and tricks == 0
                x['blind_tried'] += blind
                x['blind_made'] += blind and tricks >= bid
                x['over'] += d[f'{s}_over']
                x['bid_sum'] += bid
    out = {'games': games, **wins,
           'first_leader_win_pct': round(100 * first_leader_wins / games, 1) if games else 0,
           'avg_margin': round(sum(r['marta_score'] - r['otto_score'] for r in results) / games, 1) if games else 0,
           'avg_hands': round(sum(r['hands'] for r in results) / games, 1) if games else 0,
           'seats': []}
    for s, x in seats.items():
        h = x['hands'] or 1
        out['seats'].append({'seat': s.title(), 'hands': x['hands'], 'exact': x['exact'],
                             'exact_pct': round(100 * x['exact'] / h, 1),
                             'nil_tried': x['nil_tried'], 'nil_made': x['nil_made'],
                             'blind_tried': x['blind_tried'], 'blind_made': x['blind_made'],
                             'avg_bags': round(x['over'] / h, 2), 'avg_bid': round(x['bid_sum'] / h, 2)})
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description='Otto vs Marta, headless.')
    ap.add_argument('--games', type=int, default=200)
    ap.add_argument('--seed', type=int, default=1, help='first seed; game i uses seed+i (replayable)')
    ap.add_argument('--otto', default='easy', choices=DIFFICULTY_LEVELS)
    ap.add_argument('--marta', default='easy', choices=DIFFICULTY_LEVELS)
    ap.add_argument('--knob', action='append', default=[], metavar='NAME=VALUE',
                    help='override one of Marta\'s knobs on top of --marta (repeatable), e.g. special_hold=3')
    ap.add_argument('--persist', action='store_true', help='ALSO file every game in the prod ledger')
    a = ap.parse_args(argv)
    marta = a.marta
    if a.knob:
        marta = dict(get_difficulty_params(a.marta))
        for k in a.knob:
            name, _, val = k.partition('=')
            if name not in marta:
                ap.error(f'unknown knob {name!r}; knobs: {", ".join(marta)}')
            marta[name] = float(val)
    t0 = time.monotonic()
    results = [play_game(seed=a.seed + i, otto_difficulty=a.otto, marta_difficulty=marta,
                         persist=a.persist, source='batch') for i in range(a.games)]
    s = summarize(results)
    print(f"{s['games']} games in {time.monotonic() - t0:.1f}s  otto {a.otto} vs marta {a.marta} {' '.join(a.knob)}")
    print(f"otto {s['otto']}  marta {s['marta']}  tie {s['tie']}   first leader won {s['first_leader_win_pct']}%"
          f"   avg {s['avg_hands']} hands   marta margin {s['avg_margin']:+}")
    for x in s['seats']:
        print(f"{x['seat']:6} exact {x['exact_pct']}% ({x['exact']}/{x['hands']})  nil {x['nil_made']}/{x['nil_tried']}"
              f"  blind {x['blind_made']}/{x['blind_tried']}  bags/hand {x['avg_bags']}  avg bid {x['avg_bid']}")
    os.makedirs(os.path.join(_ROOT, '_oneoff'), exist_ok=True)
    path = os.path.join(_ROOT, '_oneoff', f"otto_batch_{time.strftime('%Y%m%d_%H%M%S')}.csv")
    cols = ['seed', 'winner', 'first_leader', 'hand', 'otto_bid', 'otto_tricks', 'otto_blind', 'marta_bid',
            'marta_tricks', 'marta_blind', 'otto_score', 'marta_score', 'otto_bags', 'marta_bags']
    with open(path, 'w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction='ignore')
        w.writeheader()
        for r in results:
            for d in r['decisions']:
                if d['kind'] == 'hand':
                    w.writerow(dict(d, seed=r['seed'], winner=r['winner'], first_leader=r['first_leader']))
    print(f"per-hand rows -> {path}")


if __name__ == '__main__':
    main()
