"""The three stats that try to be honest rather than flattering (Andy, 2026-09-08).

A raw win rate says nothing about who you played, a raw exact-bid rate says nothing about what
the hand was worth, and a season average says nothing about whether you show up when the game
is close. Each of these fixes one of those, and each carries its sample size, because a 100%
split over ten games is not a fact.

  Wins Above Otto   your wins minus the wins easy Otto would expect against the same schedule
                    of Marta strengths. Otto is the replacement level: the house algorithm
                    playing itself, measured at every rung on the referee page.
  Bid vs Par        par is what the hand was worth against perfect play, solved from the cards
                    both seats were actually dealt (see par.py). Bidding your par is skill;
                    taking your bid on a hand worth three more is luck.
  Clutch            the same bidding accuracy, split by whether the game was still in reach.
"""
import json
import os
from typing import Any, Dict, List
import psycopg2.extras
from .connection import get_db_connection, return_db_connection

# Marta's measured win rate against easy Otto at each rung, from the referee proof. Read from
# the file rather than copied so the numbers can never drift from what the page shows.
_PROOF = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                      'static', 'referee_proof.json')
_RUNG_STRENGTH = {'easy': 0, 'medium': 30, 'hard': 60, 'ruthless': 100}
_FALLBACK = {'easy': 50.6, 'medium': 58.8, 'hard': 64.9, 'ruthless': 94.2}


def rung_difficulty() -> Dict[str, float]:
    """{rung: Marta's win rate vs easy Otto there}. The chance a replacement player beats her."""
    try:
        sweep = json.load(open(_PROOF))['summary']['strength_sweep']
        by_strength = {int(r['strength']): float(r['marta_pct']) for r in sweep}
        out = {}
        for rung, s in _RUNG_STRENGTH.items():
            if s in by_strength:
                out[rung] = by_strength[s]
            else:                                   # nearest measured point either side
                near = min(by_strength, key=lambda k: abs(k - s))
                out[rung] = by_strength[near]
        return out
    except Exception as e:
        print(f"[SABR] falling back to stored rung difficulty: {e}")
        return dict(_FALLBACK)


def _rows(cur, sql, args=None):
    cur.execute(sql, args or ())
    return [dict(r) for r in cur.fetchall()]


def advanced_stats() -> Dict[str, Any]:
    """{'wao': [...], 'par': [...], 'clutch': [...], 'coverage': {...}}."""
    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        diff = rung_difficulty()

        # ── Wins Above Otto ────────────────────────────────────────────────────
        # Every game carries the rung it was played at. Easy Otto's expected win rate there is
        # 1 - Marta's measured win rate, so summing that over someone's schedule gives the wins
        # a replacement player would have had. What is left over is theirs.
        sched = _rows(cur, '''
            SELECT v.player_name AS player, COALESCE(h.difficulty, 'easy') AS rung,
                   COUNT(*) AS games, SUM(v.won::int) AS wins
              FROM twomanspades.vw_player_games v
              JOIN twomanspades.hands h ON h.hand_id = v.hand_id
             WHERE v.player_name IS NOT NULL AND v.player_name <> 'Other'
             GROUP BY 1, 2
        ''')
        wao: Dict[str, Dict[str, Any]] = {}
        for r in sched:
            e = wao.setdefault(r['player'], {'player': r['player'], 'games': 0, 'wins': 0,
                                             'expected': 0.0, 'hardest': 'easy'})
            beat_rate = 1 - diff.get(r['rung'], _FALLBACK['easy']) / 100.0
            e['games'] += r['games']
            e['wins'] += r['wins'] or 0
            e['expected'] += beat_rate * r['games']
            if _RUNG_STRENGTH.get(r['rung'], 0) > _RUNG_STRENGTH.get(e['hardest'], 0):
                e['hardest'] = r['rung']
        for e in wao.values():
            e['expected'] = round(e['expected'], 1)
            e['wao'] = round(e['wins'] - e['expected'], 1)
            e['per_100'] = round(100.0 * e['wao'] / e['games'], 1) if e['games'] else 0.0
        wao_rows = sorted(wao.values(), key=lambda e: e['wao'], reverse=True)

        # ── Bid vs Par ─────────────────────────────────────────────────────────
        par = _rows(cur, '''
            WITH bids AS (
                SELECT ge.hand_id, ge.hand_number,
                       (ge.event_data->>'player_bid')::int    AS bid,
                       (ge.event_data->>'player_tricks')::int AS took
                  FROM (SELECT DISTINCT ON (hand_id, hand_number) hand_id, hand_number, event_data
                          FROM twomanspades.game_events WHERE event_type = 'hand_completed'
                         ORDER BY hand_id, hand_number, timestamp) ge
                 WHERE (ge.event_data->>'player_bid') IS NOT NULL)
            SELECT v.player_name AS player, COUNT(*) AS hands,
                   ROUND(AVG(ABS(b.bid - hp.player_par)), 2)          AS avg_miss,
                   ROUND(AVG(b.bid - hp.player_par), 2)               AS bias,
                   ROUND(100.0 * AVG((b.bid = hp.player_par)::int), 1) AS par_exact_pct,
                   ROUND(100.0 * AVG((b.bid = b.took)::int), 1)        AS exact_pct,
                   ROUND(AVG(hp.player_par), 2)                        AS avg_par
              FROM twomanspades.hand_par hp
              JOIN bids b USING (hand_id, hand_number)
              JOIN twomanspades.vw_player_identity v ON v.hand_id = hp.hand_id
             WHERE b.bid > 0 AND v.player_name IS NOT NULL AND v.player_name <> 'Other'
             GROUP BY 1 HAVING COUNT(*) >= 20
             ORDER BY avg_miss
        ''')

        # ── Clutch ─────────────────────────────────────────────────────────────
        # A hand is "in reach" when either side could win the game with it: within 100 of 300.
        # Bidding accuracy in those hands against the rest is the only clutch claim the log
        # can actually support.
        clutch = _rows(cur, '''
            WITH scored AS (
                SELECT ge.hand_id, ge.hand_number,
                       (ge.event_data->'final_scores'->>'player_score')::int   AS p,
                       (ge.event_data->'final_scores'->>'computer_score')::int AS c
                  FROM (SELECT DISTINCT ON (hand_id, hand_number) hand_id, hand_number, event_data
                          FROM twomanspades.game_events WHERE event_type = 'hand_scoring'
                         ORDER BY hand_id, hand_number, timestamp) ge),
            before AS (
                SELECT hand_id, hand_number + 1 AS hand_number, p, c FROM scored),
            bids AS (
                SELECT ge.hand_id, ge.hand_number,
                       (ge.event_data->>'player_bid')::int    AS bid,
                       (ge.event_data->>'player_tricks')::int AS took
                  FROM (SELECT DISTINCT ON (hand_id, hand_number) hand_id, hand_number, event_data
                          FROM twomanspades.game_events WHERE event_type = 'hand_completed'
                         ORDER BY hand_id, hand_number, timestamp) ge
                 WHERE (ge.event_data->>'player_bid') IS NOT NULL)
            SELECT v.player_name AS player,
                   COUNT(*) FILTER (WHERE tight)                                     AS tight_hands,
                   ROUND(100.0 * AVG((b.bid = b.took)::int) FILTER (WHERE tight), 1) AS tight_exact,
                   COUNT(*) FILTER (WHERE NOT tight)                                 AS rest_hands,
                   ROUND(100.0 * AVG((b.bid = b.took)::int) FILTER (WHERE NOT tight), 1) AS rest_exact
              FROM bids b
              JOIN before bf USING (hand_id, hand_number)
              JOIN twomanspades.vw_player_identity v ON v.hand_id = b.hand_id
              CROSS JOIN LATERAL (SELECT (GREATEST(bf.p, bf.c) >= 200) AS tight) t
             WHERE b.bid > 0 AND v.player_name IS NOT NULL AND v.player_name <> 'Other'
             GROUP BY 1 HAVING COUNT(*) FILTER (WHERE tight) >= 20
             ORDER BY 1
        ''')
        for r in clutch:
            r['swing'] = round((r['tight_exact'] or 0) - (r['rest_exact'] or 0), 1)
        clutch.sort(key=lambda r: r['swing'], reverse=True)

        cur.close()
        from .par import par_coverage
        solved, solvable = par_coverage()
        return {'wao': wao_rows, 'par': par, 'clutch': clutch, 'rungs': diff,
                'coverage': {'solved': solved, 'solvable': solvable}}
    except Exception as e:
        print(f"Advanced stats failed: {e}")
        return {}
    finally:
        if conn is not None:
            return_db_connection(conn)
