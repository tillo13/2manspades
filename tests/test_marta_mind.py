"""Marta's thinking (utilities/marta_mind.py): the solver is exact, the dial is right, and at
strength 100 the bid and the plays come from it."""
import random
import time
import unittest
from utilities.gameplay_logic import create_deck
from utilities import marta_mind as mm


def _naive(m, p, leader, broken, mt, pt, ctx):
    """Plain minimax: no memo, no equivalence, no pruning. The oracle the solver must match."""
    if not m:
        return ctx.final(mt, pt)
    lead, foll = (m, p) if leader == 0 else (p, m)

    def legal(mask, led):
        cards = [c for c in range(64) if mask >> c & 1]
        if led is not None:
            same = [c for c in cards if mm._suit(c) == mm._suit(led)]
            return same or cards
        non = [c for c in cards if mm._suit(c) != mm.SPADE]
        return non if (not broken and non) else cards
    best = None
    for led in legal(lead, None):
        worst = None
        for ans in legal(foll, led):
            nb = broken or mm._suit(led) == mm.SPADE or mm._suit(ans) == mm.SPADE
            if leader == 0:
                w = 1 if mm._takes(led, ans) else 0
                v = _naive(m & ~(1 << led), p & ~(1 << ans), w, nb, mt + (w == 0), pt + (w == 1), ctx)
                worst = v if worst is None else min(worst, v)
            else:
                w = 0 if mm._takes(led, ans) else 1
                v = _naive(m & ~(1 << ans), p & ~(1 << led), w, nb, mt + (w == 0), pt + (w == 1), ctx)
                worst = v if worst is None else max(worst, v)
        best = worst if best is None else (max(best, worst) if leader == 0 else min(best, worst))
    return best


def _deal(seed, n):
    random.seed(seed)
    d = create_deck()
    random.shuffle(d)
    return d[:n], d[n:2 * n], d[2 * n:]


def _mask(cards):
    return sum(1 << mm._code(c) for c in cards)


class SolverTests(unittest.TestCase):
    def test_matches_plain_minimax(self):
        for seed in range(60):
            mh, ph, _ = _deal(seed, 3 + seed % 3)
            g = {'computer_bid': seed % 4, 'player_bid': (seed // 4) % 4, 'computer_bags': (0, 5, 6)[seed % 3], 'player_bags': 0}
            for tricks_only in (False, True):
                ctx = mm._Ctx(g, time.perf_counter() + 30, tricks_only)
                a = mm._solve(_mask(mh), _mask(ph), seed % 2, bool(seed % 3), 0, 0, ctx, {})
                self.assertEqual(a, _naive(_mask(mh), _mask(ph), seed % 2, bool(seed % 3), 0, 0, ctx), (seed, tricks_only))

    def test_oracle_can_fail(self):
        # the comparison above is only evidence if it can go red: break the trick rule and it must
        mh, ph, _ = _deal(5, 4)
        ctx = mm._Ctx({'computer_bid': 2, 'player_bid': 2}, time.perf_counter() + 30, True)
        truth = _naive(_mask(mh), _mask(ph), 0, False, 0, 0, ctx)
        orig = mm._takes
        mm._takes = lambda led, ans: not orig(led, ans)
        try:
            self.assertNotEqual(mm._solve(_mask(mh), _mask(ph), 0, False, 0, 0, ctx, {}), truth)
        finally:
            mm._takes = orig

    def test_ten_card_solve_is_fast(self):
        mh, ph, _ = _deal(1, 10)
        ctx = mm._Ctx({'computer_bid': 3, 'player_bid': 4}, time.perf_counter() + 30)
        t = time.perf_counter()
        mm._solve(_mask(mh), _mask(ph), 1, False, 0, 0, ctx, {})
        self.assertLess(time.perf_counter() - t, 1.0)

    def test_equivalent_cards_fold(self):
        # K and Q of a suit with no live card between them are one move
        hand = _mask([{'suit': '♥', 'value': 13}, {'suit': '♥', 'value': 12}, {'suit': '♣', 'value': 5}])
        live = hand | _mask([{'suit': '♥', 'value': 2}])
        self.assertEqual(len(mm._moves(hand, live)), 2)
        live |= _mask([{'suit': '♥', 'value': 12}]) and _mask([{'suit': '♥', 'value': 12}])
        # a live J between? no: put a live card BETWEEN Q and K is impossible; put one below Q and they still fold
        self.assertEqual(len(mm._moves(hand, live)), 2)
        # spades cannot be led while unbroken if she holds anything else
        sp = _mask([{'suit': '♠', 'value': 14}, {'suit': '♦', 'value': 3}])
        self.assertEqual([mm._suit(c) for c in mm._moves(sp, sp, broken=False)], [1])
        self.assertEqual(len(mm._moves(sp, sp, broken=True)), 2)

    def test_points(self):
        self.assertEqual(mm._points(4, 4, 0, False), 40)
        self.assertEqual(mm._points(4, 6, 0, False), 40 - 2 * mm.BAG_COST)
        self.assertEqual(mm._points(4, 6, 5, False), 40 - 2 * mm.BAG_COST - 100)   # seventh bag
        self.assertEqual(mm._points(4, 3, 0, False), -40)
        self.assertEqual(mm._points(0, 0, 0, False), 100)
        self.assertEqual(mm._points(0, 1, 0, False), -100)
        self.assertEqual(mm._points(5, 5, 0, True), 100)


class DialTests(unittest.TestCase):
    def test_share(self):
        self.assertEqual(mm.think_share(0), 0)
        self.assertEqual(mm.think_share(60), 0)
        self.assertAlmostEqual(mm.think_share(80), 0.5)
        self.assertEqual(mm.think_share(100), 1)
        self.assertEqual(mm.think_share('ruthless'), 0)   # names are resolved before this; a name is not a number

    def test_roll(self):
        self.assertFalse(mm.roll_thinking({'difficulty': 59}))
        self.assertTrue(mm.roll_thinking({'difficulty': 100}))
        g = {'difficulty': 100}
        mm.roll_thinking(g)
        self.assertTrue(mm.thinks_this_hand(g))


class ThinkTests(unittest.TestCase):
    def _game(self, seed, n=10, **kw):
        mh, ph, rest = _deal(seed, n)
        g = {'computer_hand': mh, 'player_hand': ph, 'player_discarded': rest[0], 'computer_discarded': rest[1],
             'phase': 'playing', 'difficulty': 100, 'computer_bid': 3, 'player_bid': 4, 'computer_tricks': 0,
             'player_tricks': 0, 'computer_bags': 0, 'player_bags': 0, 'spades_broken': False, 'trick_history': [],
             'first_leader': 'player', 'trick_leader': 'player'}
        g.update(kw)
        return g

    def test_bid_and_play_return_legal_choices(self):
        g = self._game(1, phase='bidding', computer_bid=None, player_bid=None)
        bid, info = mm.think_bid(g['computer_hand'], None, g)
        self.assertTrue(0 <= bid <= 10)
        self.assertGreaterEqual(info['worlds'], mm.MIN_WORLDS)
        g = self._game(2, n=6)
        idx, info = mm.think_play(g['computer_hand'], [], g)
        self.assertIn(idx, range(6))
        self.assertNotEqual(g['computer_hand'][idx]['suit'], '♠')      # spades unbroken, she holds others
        led = g['player_hand'][0]
        idx, info = mm.think_play(g['computer_hand'], [{'player': 'player', 'card': led}], g)
        if any(c['suit'] == led['suit'] for c in g['computer_hand']):
            self.assertEqual(g['computer_hand'][idx]['suit'], led['suit'])

    def test_worlds_respect_voids_and_bid(self):
        g = self._game(3, n=6)
        g['trick_history'] = [{'player_card': {'rank': '9', 'suit': '♠', 'value': 9},
                               'computer_card': {'rank': '4', 'suit': '♥', 'value': 4}, 'winner': 'player'}]
        g['first_leader'] = 'computer'   # she led the 4♥ and he answered a spade: he is void in hearts
        worlds = mm._sample_worlds(g, g['computer_hand'], 50)
        self.assertTrue(worlds)
        for mask, w in worlds:
            self.assertEqual(mask & (0xFFFF << (16 * 2)), 0, 'a sampled hand holds hearts')
            self.assertEqual(bin(mask).count('1'), 6)

    def test_brain_uses_it_at_100(self):
        from utilities import computer_logic as cl
        seen = []
        cl.set_decision_sink(lambda kind, seat, data: seen.append((kind, data)))
        try:
            g = self._game(4, phase='bidding', computer_bid=None, player_bid=None)
            bid, blind = cl.computer_bidding_brain(g['computer_hand'], None, g)
            self.assertTrue(g['marta_thinks'])
            self.assertEqual(seen[-1][1]['branch'], 'think')
            g.update(phase='playing', computer_bid=bid, player_bid=4)
            idx = cl.computer_lead_strategy(g['computer_hand'], False, g)
            self.assertEqual(seen[-2][0], 'think')
            self.assertIn(idx, range(10))
            g = self._game(4, difficulty=30, phase='bidding', computer_bid=None, player_bid=None)
            cl.computer_bidding_brain(g['computer_hand'], None, g)
            self.assertFalse(g['marta_thinks'])
            self.assertNotEqual(seen[-1][1].get('branch'), 'think')
        finally:
            cl.set_decision_sink(None)



class MirrorTests(unittest.TestCase):
    def test_otto_does_not_inherit_martas_thinking(self):
        from utilities.otto import _mirror
        g = {'player_hand': [], 'computer_hand': [], 'difficulty': 100, 'marta_thinks': True, '_thought': ((1, 0, 0), 0)}
        m = _mirror(g, 'easy')
        self.assertFalse(m['marta_thinks'])
        self.assertNotIn('_thought', m)
        self.assertTrue(_mirror(g, 100)['marta_thinks'])     # a strong Otto thinks on his own account



class LadderTests(unittest.TestCase):
    """The card ladder: above PEEK_FROM she is shown some of the opponent's cards at the deal."""

    def _game(self, seed, strength):
        mh, ph, rest = _deal(seed, 10)
        return {'computer_hand': mh, 'player_hand': ph, 'player_discarded': rest[0], 'computer_discarded': rest[1],
                'phase': 'playing', 'difficulty': strength, 'computer_bid': 3, 'player_bid': 4, 'computer_tricks': 0,
                'player_tricks': 0, 'computer_bags': 0, 'player_bags': 0, 'spades_broken': False,
                'trick_history': [], 'first_leader': 'player'}

    def test_cards_by_strength(self):
        self.assertEqual([mm.peek_cards(s) for s in (0, 60, 79, 80, 82, 90, 98, 100)], [0, 0, 0, 0, 1, 5, 9, 10])

    def test_switch_turns_it_off(self):
        mm.LADDER = False
        try:
            self.assertEqual(mm.peek_cards(100), 0)
            g = self._game(1, 100)
            mm.roll_thinking(g)
            self.assertEqual(g['marta_sees'], [])
        finally:
            mm.LADDER = True

    def test_shown_cards_are_pinned_into_every_world(self):
        g = self._game(2, 90)
        mm.roll_thinking(g)
        self.assertEqual(len(g['marta_sees']), 5)
        shown = set(g['marta_sees'])
        self.assertTrue(shown <= {mm._key(c) for c in g['player_hand']}, 'she was shown a card he does not hold')
        worlds = mm._sample_worlds(g, g['computer_hand'], 20)
        self.assertTrue(worlds)
        for mask, _w in worlds:
            self.assertEqual(bin(mask).count('1'), 10)
            for c in g['player_hand']:
                if mm._key(c) in shown:
                    self.assertTrue((mask >> mm._code(c)) & 1, 'a shown card is missing from a world')

    def test_all_ten_is_one_world_and_the_real_hand(self):
        g = self._game(3, 100)
        mm.roll_thinking(g)
        worlds = mm._sample_worlds(g, g['computer_hand'], 50)
        self.assertEqual(len(worlds), 1)
        self.assertEqual(worlds[0][0], sum(1 << mm._code(c) for c in g['player_hand']))

    def test_a_shown_card_on_the_table_is_not_pinned_back_into_his_hand(self):
        g = self._game(4, 100)
        mm.roll_thinking(g)
        led = g['player_hand'][0]
        g['player_hand'] = g['player_hand'][1:]      # he has led it
        worlds = mm._sample_worlds(g, g['computer_hand'], 10, on_table=led)
        self.assertTrue(worlds)
        for mask, _w in worlds:
            self.assertFalse((mask >> mm._code(led)) & 1, 'the led card is still in his hand')
            self.assertEqual(bin(mask).count('1'), 9)

    def test_below_the_ladder_she_is_shown_nothing(self):
        # 60-80 is the thinking band with no cards; whether she thinks a given hand is a roll
        for strength in (61, 70, 79):
            for _ in range(20):
                g = self._game(5, strength)
                mm.roll_thinking(g)
                self.assertEqual(g['marta_sees'], [], strength)


if __name__ == '__main__':
    unittest.main()
