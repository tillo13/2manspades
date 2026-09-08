"""Par: what each hand was actually worth (2026-09-08).

The log keeps every card dealt to both seats and both discards, and the referee's solver can
play a hand out perfectly. So for any finished hand we can ask the question no card game
usually answers: how many tricks was that hand worth against best play? That number is par,
and bidding is only really measurable against it. Bidding 4 and taking 4 looks identical
whether the hand was worth 4 or worth 7; against par it is the difference between a good bid
and a lucky one.

Solving is far too slow to do on a page request, so it runs once per hand and is stored.
`fill_par()` is incremental: it solves only hands it has not seen.
"""
import json
import psycopg2.extras
from .connection import get_db_connection, return_db_connection

_TABLE_OK = False
RANKS = {'J': 11, 'Q': 12, 'K': 13, 'A': 14}


def _ensure_table(cur):
    global _TABLE_OK
    if _TABLE_OK:
        return
    cur.execute('''
        CREATE TABLE IF NOT EXISTS twomanspades.hand_par (
            hand_id TEXT NOT NULL,
            hand_number INT NOT NULL,
            player_par INT NOT NULL,
            computer_par INT NOT NULL,
            first_leader TEXT,
            solved_at TIMESTAMPTZ DEFAULT NOW(),
            PRIMARY KEY (hand_id, hand_number))
    ''')
    _TABLE_OK = True


def _card(code):
    """'10♣' / 'A♠' -> the dict shape the solver's coder expects."""
    rank, suit = code[:-1], code[-1]
    return {'rank': rank, 'suit': suit, 'value': RANKS.get(rank, 0) or int(rank)}


def _unsolved(cur, limit):
    """Hands with both seats dealt, both discards and a bid record, not yet solved."""
    cur.execute('''
        WITH dealt AS (
            SELECT hand_id, hand_number,
                   MAX(event_data->>'cards') FILTER (WHERE event_data->>'player' = 'player')   AS p_cards,
                   MAX(event_data->>'cards') FILTER (WHERE event_data->>'player' = 'computer') AS c_cards
              FROM twomanspades.game_events WHERE event_type = 'hand_dealt'
             GROUP BY 1, 2),
        thrown AS (
            SELECT hand_id, hand_number,
                   MAX(event_data->'action_data'->>'card_discarded') FILTER (WHERE player = 'player')   AS p_out,
                   MAX(event_data->'action_data'->>'card_discarded') FILTER (WHERE player = 'computer') AS c_out
              FROM twomanspades.game_events WHERE event_type = 'action_discard'
             GROUP BY 1, 2),
        bids AS (
            SELECT hand_id, hand_number, MAX(event_data->>'first_leader') AS first_leader
              FROM twomanspades.game_events WHERE event_type = 'bidding_complete'
             GROUP BY 1, 2)
        SELECT d.hand_id, d.hand_number, d.p_cards, d.c_cards, t.p_out, t.c_out, b.first_leader
          FROM dealt d
          JOIN thrown t USING (hand_id, hand_number)
          JOIN bids b USING (hand_id, hand_number)
          LEFT JOIN twomanspades.hand_par hp USING (hand_id, hand_number)
         WHERE hp.hand_id IS NULL AND d.p_cards IS NOT NULL AND d.c_cards IS NOT NULL
           AND t.p_out IS NOT NULL AND t.c_out IS NOT NULL
         LIMIT %s
    ''', (limit,))
    return cur.fetchall()


def fill_par(limit=500, verbose=True):
    """Solve up to `limit` unsolved hands and store them. Returns how many were written."""
    import time
    from utilities.marta_mind import _code, _count, _Ctx
    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        _ensure_table(cur)
        conn.commit()
        rows = _unsolved(cur, limit)
        out, t0 = [], time.time()
        for r in rows:
            try:
                pc, cc = json.loads(r['p_cards']), json.loads(r['c_cards'])
                ph = [_card(c) for c in pc if c != r['p_out']]
                ch = [_card(c) for c in cc if c != r['c_out']]
            except Exception:
                continue
            if len(ph) != 10 or len(ch) != 10:
                continue
            # the solver speaks from Marta's seat: leader 0 is her, 1 is the human
            leader = 0 if r['first_leader'] == 'computer' else 1
            m = sum(1 << _code(c) for c in ch)
            p = sum(1 << _code(c) for c in ph)
            ctx = _Ctx({}, float('inf'), tricks_only=True)
            marta_par = _count(m, p, leader, ctx, {})
            out.append((r['hand_id'], r['hand_number'], 10 - marta_par, marta_par, r['first_leader']))
        if out:
            psycopg2.extras.execute_values(cur, '''
                INSERT INTO twomanspades.hand_par (hand_id, hand_number, player_par, computer_par, first_leader)
                VALUES %s ON CONFLICT (hand_id, hand_number) DO NOTHING
            ''', out)
            conn.commit()
        if verbose:
            print(f"[PAR] solved {len(out)} of {len(rows)} candidates in {time.time() - t0:.1f}s")
        cur.close()
        return len(out)
    except Exception as e:
        print(f"[PAR] fill failed: {e}")
        return 0
    finally:
        if conn is not None:
            return_db_connection(conn)


def par_coverage():
    """(hands solved, hands solvable) — the page says how much of the record this rests on."""
    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        _ensure_table(cur)
        conn.commit()
        cur.execute('SELECT COUNT(*) FROM twomanspades.hand_par')
        solved = cur.fetchone()[0]
        cur.execute('''
            SELECT COUNT(*) FROM (
                SELECT hand_id, hand_number FROM twomanspades.game_events
                 WHERE event_type = 'hand_dealt' GROUP BY 1, 2
                HAVING COUNT(DISTINCT event_data->>'player') = 2) t
        ''')
        solvable = cur.fetchone()[0]
        cur.close()
        return solved, solvable
    except Exception as e:
        print(f"[PAR] coverage failed: {e}")
        return 0, 0
    finally:
        if conn is not None:
            return_db_connection(conn)
