"""Read-only export of completed-game positions; output stays outside the repository."""
import argparse
import json, sys, hashlib, re
from collections import Counter
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from utilities.postgres_utils.connection import db_cursor
def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("output", help="Private JSON path for training positions (do not commit)")
    a=ap.parse_args()
    rows=[]
    with db_cursor(dict_rows=True) as c:
        c.execute('SET TRANSACTION READ ONLY')
        c.execute('''WITH ended AS (
          SELECT h.player_id,h.started_at, MAX(e.hand_number) AS last_hand,
                 MIN(e.event_data->>'winner') AS winner,
                 COUNT(DISTINCT e.event_data->>'winner') AS outcomes
          FROM twomanspades.hands h JOIN twomanspades.game_events e USING(hand_id)
          WHERE e.event_type='game_completed' AND h.player_id IS NOT NULL
          GROUP BY 1,2)
          SELECT DISTINCT ON (h.player_id,h.started_at,e.hand_number)
            h.player_id,h.started_at,e.hand_number,h.difficulty,h.played_by,
            e.event_data->'hand_results'->'win_estimate'->>'strength' AS strength,
            e.event_data->'final_scores' AS scores,
            e.event_data->>'scoring_explanation' AS scoring,
            h.first_leader,g.winner,g.last_hand
          FROM twomanspades.hands h JOIN ended g USING(player_id,started_at)
          JOIN twomanspades.game_events e USING(hand_id)
          WHERE e.event_type='hand_scoring' AND g.outcomes=1 AND g.winner IN ('player','computer')
            AND e.hand_number < g.last_hand
          ORDER BY h.player_id,h.started_at,e.hand_number,e.timestamp DESC''')
        human=c.fetchall()
        for r in human:
            bags=re.search(r'Bags: You (-?\d+)/7, Marta (-?\d+)/7',r['scoring'] or '')
            if not bags or not r['scores']: continue
            s=r['scores']; p=s.get('player_score'); m=s.get('computer_score')
            if p is None or m is None or max(p,m)>=300 or abs(p-m)>=300: continue
            key=hashlib.sha256(f"{r['player_id']}:{r['started_at']}".encode()).hexdigest()[:20]
            rows.append(dict(game=key,date=str(r['started_at']),hand=r['hand_number'],p=p,c=m,pb=int(bags[1]),cb=int(bags[2]),
                difficulty=int(r['strength']) if r['strength'] is not None else r['difficulty'] or 'easy',source='persona' if r['played_by'] else 'human',
                next_player=r['first_leader']=='computer',won=int(r['winner']=='player')))
        c.execute('''SELECT g.game_id,g.played_at,g.marta_difficulty,g.marta_strength,g.otto_difficulty,
          g.first_leader,g.winner,d.hand,d.data FROM twomanspades.bot_games g
          JOIN twomanspades.bot_decisions d USING(game_id)
          WHERE d.kind='hand' AND d.hand<g.hands AND g.winner IN ('otto','marta')''')
        for r in c.fetchall():
            s=r['data']; p=s['otto_score']; m=s['marta_score']
            if max(p,m)>=300 or abs(p-m)>=300: continue
            rows.append(dict(game=str(r['game_id']),date=str(r['played_at']),hand=r['hand'],p=p,c=m,pb=s['otto_bags'],cb=s['marta_bags'],
                difficulty=r['marta_strength'] if r['marta_strength'] is not None else r['marta_difficulty'],source='otto',
                next_player=(r['first_leader']=='otto')==(r['hand']%2==0),won=int(r['winner']=='otto')))
    Path(a.output).write_text(json.dumps(rows))
    print('positions',len(rows),'games',len({r['game'] for r in rows}))
    print('sources',Counter(r['source'] for r in rows))
    print('difficulty',Counter(str(r['difficulty']) for r in rows))
    print('dates',min(r['date'] for r in rows),max(r['date'] for r in rows))
    print('human games',Counter(str(r['difficulty']) for r in {r['game']:r for r in rows if r['source']=='human'}.values()))


if __name__ == "__main__": main()
