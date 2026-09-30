#!/usr/bin/env python3
"""The game-playing crons, run as the twomanspades-crons Cloud Run job. Cloud Scheduler starts it
with the task name as the container arg: otto (every 30 min), andybot (hourly 09-21 PT),
prune-events (daily 03:20 PT).

Moved off the App Engine serving tier 2026-09-30. Marta's solver is pure Python, and at ruthless
one bot game took up to 27 s (7-day median 15.5 s); on the single-worker F1 that CPU competed
with every page request in the process, and the fleet isolation check graded /cron/otto critical
(worst tick 53.9 s). The /stats and bid-bias warming stays on App Engine as /cron/warm, because it
fills the web process's own memory, which this process cannot reach.

One structured log line per run; a failure logs at ERROR, which kumori's error sweeper emails
(deduped, capped), and the task exits 1. The job runs with max retries 0: the next tick is the retry.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def otto():
    from utilities.otto import play_cron_tick
    from utilities.postgres_utils.par import fill_par
    out = play_cron_tick()
    out['par_solved'] = fill_par(limit=120)
    return out


def andybot():
    from utilities.otto import play_persona_tick
    return play_persona_tick()


def prune_events():
    from utilities.postgres_utils import prune_card_plays
    return prune_card_plays()


TASKS = {'otto': otto, 'andybot': andybot, 'prune-events': prune_events}


def main(argv):
    if len(argv) != 2 or argv[1] not in TASKS:
        print(f"usage: cloud_run_crons.py {'|'.join(TASKS)}", file=sys.stderr)
        return 2
    task = argv[1]
    from utilities.postgres_utils import patient_pool
    try:
        with patient_pool():
            out = TASKS[task]()
    except Exception as e:
        print(json.dumps({'severity': 'ERROR',
                          'message': f'twomanspades {task} failed: {type(e).__name__}: {e}'[:4000]}), flush=True)
        return 1
    print(json.dumps({'severity': 'INFO', 'message': f'twomanspades {task} done', 'result': out},
                     default=str)[:8000], flush=True)
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
