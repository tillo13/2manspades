"""Game-win estimates at hand boundaries; fitted offline, no database or simulation in requests."""
import json
import math
from functools import lru_cache
from pathlib import Path

MODEL_PATH = Path(__file__).with_name('win_probability_model.json')
FEATURES = ['intercept', 'player_score', 'computer_score', 'player_close', 'computer_close',
            'player_bags', 'computer_bags', 'strength', 'thinking', 'next_player', 'otto', 'persona']
PRESETS = {'easy': 0, 'medium': 30, 'hard': 60, 'ruthless': 100}


def features(p, c, pb, cb, strength, next_player, source='human'):
    s = PRESETS.get(strength, 0) if isinstance(strength, str) else strength
    s = max(0, min(100, s)) / 100
    return [1, p / 100, c / 100, max(0, p - 200) / 100, max(0, c - 200) / 100,
            pb / 7, cb / 7, s, max(0, s - .6) / .4, int(next_player),
            int(source == 'otto'), int(source == 'persona')]


def probability(values, coefficients):
    z = sum(x * w for x, w in zip(values, coefficients))
    return 1 / (1 + math.exp(-max(-35, min(35, z))))


@lru_cache(maxsize=1)
def _model():
    try:
        model = json.loads(MODEL_PATH.read_text())
        if model['features'] == FEATURES and len(model['coefficients']) == len(FEATURES):
            return model
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return None


def estimate_win(game):
    if game.get('game_over') or game.get('target_score', 300) != 300:
        return None
    model = _model()
    if not model:
        return None
    from .custom_rules import get_display_score
    from .computer_logic import strength_of, level_name
    pb, cb = game.get('player_bags', 0), game.get('computer_bags', 0)
    p = get_display_score(game['player_score'], pb)
    c = get_display_score(game['computer_score'], cb)
    # Never extrapolate outside the supported score range or present a forecast for a finished game.
    if not (-300 < p < 300 and -300 < c < 300 and abs(p - c) < 300 and -4 <= pb <= 6 and -4 <= cb <= 6):
        return None
    strength = strength_of(game.get('difficulty', 'easy'))
    values = features(p, c, pb, cb, strength, game.get('first_leader') == 'computer')
    pct = max(1, min(99, round(100 * probability(values, model['coefficients']))))
    return {'percent': pct, 'level': level_name(strength).title(), 'strength': strength,
            'model': model['version'], 'experimental': True}
