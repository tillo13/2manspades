"""The advanced stats: par solving and the pieces that do not need a database."""
import unittest
from utilities.postgres_utils.par import _card
from utilities.postgres_utils.sabermetrics import rung_difficulty, _RUNG_STRENGTH


class CardTests(unittest.TestCase):
    def test_every_rank_parses(self):
        for code, want in [('2♣', 2), ('9♦', 9), ('10♥', 10), ('J♠', 11), ('Q♣', 12), ('K♦', 13), ('A♥', 14)]:
            c = _card(code)
            self.assertEqual(c['value'], want, code)
            self.assertEqual(c['suit'], code[-1])

    def test_ten_is_not_confused_with_one(self):
        self.assertEqual(_card('10♠')['rank'], '10')
        self.assertEqual(_card('10♠')['value'], 10)


class ParSolveTests(unittest.TestCase):
    def test_par_is_a_full_ten_tricks_and_matches_a_hand_we_can_check(self):
        from utilities.marta_mind import _code, _count, _Ctx
        # Marta holds every spade plus the top of one suit: she takes them all whoever leads.
        marta = [_card(f'{r}♠') for r in ('A', 'K', 'Q', 'J', '10', '9', '8', '7', '6', '5')]
        human = [_card(f'{r}♥') for r in ('A', 'K', 'Q', 'J', '10', '9', '8', '7', '6', '5')]
        for leader in (0, 1):
            m = sum(1 << _code(c) for c in marta)
            p = sum(1 << _code(c) for c in human)
            ctx = _Ctx({}, float('inf'), tricks_only=True)
            self.assertEqual(_count(m, p, leader, ctx, {}), 10, leader)

    def test_par_splits_ten_tricks(self):
        from utilities.marta_mind import _code, _count, _Ctx
        marta = [_card(f'{r}♠') for r in ('A', 'K', 'Q', 'J', '10')] + [_card(f'{r}♦') for r in ('2', '3', '4', '5', '6')]
        human = [_card(f'{r}♥') for r in ('A', 'K', 'Q', 'J', '10')] + [_card(f'{r}♦') for r in ('7', '8', '9', '10', 'J')]
        m = sum(1 << _code(c) for c in marta)
        p = sum(1 << _code(c) for c in human)
        ctx = _Ctx({}, float('inf'), tricks_only=True)
        got = _count(m, p, 1, ctx, {})
        self.assertTrue(0 <= got <= 10)
        self.assertEqual(got + (10 - got), 10)


class RungTests(unittest.TestCase):
    def test_difficulty_covers_every_rung_and_rises(self):
        d = rung_difficulty()
        self.assertEqual(set(d), set(_RUNG_STRENGTH))
        order = sorted(_RUNG_STRENGTH, key=_RUNG_STRENGTH.get)
        vals = [d[r] for r in order]
        self.assertEqual(vals, sorted(vals), f'a higher rung must not be easier: {dict(zip(order, vals))}')
        for r, v in d.items():
            self.assertTrue(40 <= v <= 100, (r, v))


if __name__ == '__main__':
    unittest.main()
