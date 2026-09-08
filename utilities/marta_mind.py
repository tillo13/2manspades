"""Marta's thinking at the top of the dial (2026-09-07, Andy: "use math and reasoning better
than ever before as you get closer to 100").

She never sees the other hand. She knows what is public: her cards, both discards, every
trick played, the suits the opponent has failed to follow, the opponent's bid, and how that
person has bid in the past. From that she deals the opponent a few hundred hands that fit the
evidence, solves each one to the end with both sides playing perfectly, and bids or plays
whatever does best across all of them. This is determinization, Perfect Information Monte
Carlo, the way Ginsberg's GIB plays bridge (arXiv:1106.0669) and later programs play Skat and
Hearts (arXiv:2408.02380). The solver is the lay-down referee's idea carried to a full hand:
every legal line, scored the way the hand will be scored, with bags and sets and nil.

The dial: `think` is 0 up to strength 60 and rises to 1 at 100. It is the share of hands she
thinks through (rolled once per hand, so a hand is either hers to compute or not), and it sets
how long she may spend on each decision."""
import random
import time
from .gameplay_logic import create_deck

SUITS = ('♣', '♦', '♥', '♠')
SPADE = 3
THINK_FROM = 60                 # strength at which thinking begins
THINK_FULL = 80                 # strength at which she thinks EVERY hand (and the ladder takes over)
MAX_BUDGET_MS = 150             # per decision at strength 100
MIN_WORLDS = 4
MAX_WORLDS = 400
BAG_COST = 9                    # a bag is worth about -14 by the time seven of them cost 100; she plays it as -9
# Bidding from solved worlds. Each world is solved double-dummy, which assumes she will also
# KNOW the hand while playing it; she won't, so the solved count runs high (the known PIMC
# optimism). BID_PERCENTILE is the share of worlds she must make the bid in; BID_DISCOUNT comes
# off on top. Both calibrated with Otto (_oneoff/calibrate_think.py, 2026-09-07).
BID_PERCENTILE = 0.6
BID_DISCOUNT = 1
# Which halves are on. Measured on the same 200 deals vs easy Otto, Marta thinking and Otto not
# (_oneoff/remeasure_think.py, 2026-09-07): old ruthless 65.5%, play only 78.0%, bid and play
# 80.0%, bid and play without BID_DISCOUNT 66.0% (she bids the solved count and is set 30% of
# hands), and 95.0% with the real hand in front of her, which is what perfect play is worth.
# (An earlier run said bidding this way hurt. Otto's mirror was inheriting her per-hand thinking
# flag, so that measurement was her solver against itself. See _mirror in otto.py.)
THINK_BID = True
THINK_PLAY = True
PEEK = False                    # measurement only (_oneoff/peek_think.py): she sees the real hand, one world, exact play

# The card ladder (Andy, 2026-09-08). Above PEEK_FROM she is shown some of the opponent's cards
# at the deal, one more per rung, all ten at 100 — a disclosed advantage, written on the referee
# page, not a hidden one. It rides the same machinery: a card she has been shown is simply
# evidence, so it is pinned into every world she deals and the rest is sampled as before. Ten
# cards pinned is one world, which is exact play. LADDER=False turns the whole thing off and
# leaves the thinking Marta measured at 80%.
# The ladder starts at THREE cards, not one. Measured on 200 identical deals at each count
# (_oneoff/ladder_curve.py, 2026-09-08): 0 cards 77.0%, 2 cards 78.0%, 4 cards 81.0%, 6 cards
# 87.0%, 8 cards 90.5%, 10 cards 96.0%. One or two cards out of ten barely narrow what she is
# already inferring, so rungs there would be decoration; the climb is in the back half.
LADDER = True
PEEK_FROM = 80
PEEK_MIN_CARDS = 3
PEEK_MAX_CARDS = 10


def peek_cards(strength):
    """How many of the opponent's ten cards she is shown at this strength."""
    if not LADDER:
        return 0
    try:
        s = float(strength)
    except (TypeError, ValueError):
        return 0
    if s <= PEEK_FROM:
        return 0
    span = PEEK_MAX_CARDS - PEEK_MIN_CARDS
    return min(PEEK_MAX_CARDS, PEEK_MIN_CARDS + int((s - PEEK_FROM) / (100 - PEEK_FROM) * span + 0.5))


def think_share(strength):
    """Share of hands she thinks through: 0 at THINK_FROM, 1 by THINK_FULL. The two halves of the
    top of the dial do separate work — 60 to 80 buys how OFTEN she thinks, 80 to 100 buys how much
    she is shown while doing it. (It used to ramp to 1 only at 100, which left 60-80 nearly flat:
    the sweep read 64.9% at 60 and 66.7% at 80, because at 80 she was still thinking every other
    hand. Measured 2026-09-08.)"""
    try:
        s = float(strength)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, (s - THINK_FROM) / (THINK_FULL - THINK_FROM)))


def _code(card):
    return SUITS.index(card['suit']) * 16 + card['value']


def _key(card):
    return f"{card['rank']}{card['suit']}"


def _suit(code):
    return code >> 4


def _takes(led, ans):
    if _suit(led) == _suit(ans):
        return ans > led
    return _suit(ans) == SPADE


class _Budget(Exception):
    pass


def _moves(mask, live, led=None, broken=True):
    """Legal plays from a hand bitmask with equivalent cards folded: a card whose next-lower
    live card is also in this hand plays identically to it, so only the lower is tried.
    Highest first: the card most likely to be best is searched first, which cuts the most."""
    if led is not None:
        s = _suit(led)
        same = mask & (0xFFFF << (16 * s))
        pool = same or mask
    else:
        non = mask & ~(0xFFFF << (16 * SPADE))
        pool = non if (not broken and non) else mask
    out = []
    while pool:
        top = pool.bit_length() - 1
        pool &= ~(1 << top)
        below = live & ((1 << top) - 1) & ~((1 << (top & ~15)) - 1)   # live cards under it in the same suit
        if below and (mask >> (below.bit_length() - 1)) & 1:
            continue                                                  # its lower twin is in hand: same card
        out.append(top)
    return out


def _points(bid, tricks, bags, blind):
    if bid == 0:
        pts = 100 if tricks == 0 else -100
    elif tricks >= bid:
        over = tricks - bid
        pts = 10 * bid - BAG_COST * over - (100 if bags + over >= 7 else 0)
    else:
        pts = -10 * bid
    return pts * 2 if blind else pts


class _Ctx:
    __slots__ = ('mb', 'pb', 'mblind', 'pblind', 'mbags', 'pbags', 'deadline', 'nodes', 'tricks_only')

    def __init__(self, game, deadline, tricks_only=False):
        self.mb = game.get('computer_bid') or 0
        self.pb = game.get('player_bid') or 0
        self.mblind = bool(game.get('computer_blind_bid'))
        self.pblind = bool(game.get('player_blind_bid'))
        self.mbags = game.get('computer_bags', 0)
        self.pbags = game.get('player_bags', 0)
        self.deadline = deadline
        self.nodes = 0
        self.tricks_only = tricks_only

    def final(self, mt, pt):
        if self.tricks_only:
            return mt - pt
        return _points(self.mb, mt, self.mbags, self.mblind) - _points(self.pb, pt, self.pbags, self.pblind)


INF = 10 ** 6


def _solve(m, p, leader, broken, mt, pt, ctx, memo, alpha=-INF, beta=INF):
    """Best score difference (Marta minus player) from here with both sides playing perfectly:
    alpha-beta over the trick tree with a bounds table. m, p: hand bitmasks; leader 0 = Marta."""
    if not m:
        return ctx.final(mt, pt)
    key = (m, p, leader, broken, mt)
    ent = memo.get(key)
    if ent is not None:
        lo, hi = ent
        if lo == hi or lo >= beta:
            return lo
        if hi <= alpha:
            return hi
        alpha = max(alpha, lo); beta = min(beta, hi)
    else:
        lo, hi = -INF, INF
    ctx.nodes += 1
    if ctx.nodes & 255 == 0 and time.perf_counter() > ctx.deadline:
        raise _Budget()
    a0, b0 = alpha, beta
    live = m | p
    lead_hand, foll_hand = (m, p) if leader == 0 else (p, m)
    leads = _moves(lead_hand, live, broken=broken)
    if leader == 0:
        best = -INF
        for led in leads:
            worst = INF
            for ans in _moves(foll_hand, live, led=led):
                winner = 1 if _takes(led, ans) else 0
                nb = broken or _suit(led) == SPADE or _suit(ans) == SPADE
                v = _solve(m & ~(1 << led), p & ~(1 << ans), winner, nb, mt + (winner == 0), pt + (winner == 1), ctx, memo, alpha, min(beta, worst))
                if v < worst:
                    worst = v
                if worst <= alpha:
                    break
            if worst > best:
                best = worst
            if best > alpha:
                alpha = best
            if alpha >= beta:
                break
    else:
        best = INF
        for led in leads:
            worst = -INF
            for ans in _moves(foll_hand, live, led=led):
                winner = 0 if _takes(led, ans) else 1
                nb = broken or _suit(led) == SPADE or _suit(ans) == SPADE
                v = _solve(m & ~(1 << ans), p & ~(1 << led), winner, nb, mt + (winner == 0), pt + (winner == 1), ctx, memo, max(alpha, worst), beta)
                if v > worst:
                    worst = v
                if worst >= beta:
                    break
            if worst < best:
                best = worst
            if best < beta:
                beta = best
            if alpha >= beta:
                break
    if best <= a0:
        memo[key] = (lo, min(hi, best))
    elif best >= b0:
        memo[key] = (max(lo, best), hi)
    else:
        memo[key] = (best, best)
    return best


def _count(m, p, leader, ctx, memo):
    """Tricks Marta can force from here: a binary search of zero-window probes, the way
    double-dummy solvers do it. Each probe answers only "at least this many?", which the
    alpha-beta cuts far faster than an exact value."""
    n = bin(m).count('1')
    lo, hi = 0, n                       # she can force at least lo; not more than hi
    while lo < hi:
        mid = (lo + hi + 1) // 2
        d = 2 * mid - n                 # mt - pt when she takes mid of n
        if _solve(m, p, leader, False, 0, 0, ctx, memo, d - 2, d) >= d:
            lo = mid
        else:
            hi = mid - 1
    return lo


def _public(game, hand):
    """What the table knows: cards out of play, the opponent's void suits, the opponent's
    possible cards (unseen minus voids)."""
    from .computer_logic import table_memory
    saved = game.get('difficulty')
    game['difficulty'] = 100            # full recall: thinking uses everything public
    try:
        mem = table_memory(hand, game)
        seen, opp_void = mem['seen'], mem['opp_void']
    finally:
        game['difficulty'] = saved
    unseen = [c for c in create_deck() if f"{c['rank']}{c['suit']}" not in seen]
    return [c for c in unseen if c['suit'] not in opp_void], opp_void


def _opp_estimate(cards, game):
    """How many tricks the opponent would think this hand is worth, bid the way this person
    bids (their measured bid bias, from the stats)."""
    from .computer_logic import analyze_hand_strength
    sure, prob, special = analyze_hand_strength(cards)
    bias = (game.get('opp_model') or {}).get('bid_bias', 0.0)
    return sure + prob + special + 1.0 - bias      # +1.0: the evaluator underestimates by about a trick


def _sample_worlds(game, hand, n, on_table=None):
    """n opponent hands that fit the evidence, each with a weight. The opponent's bid is
    evidence too: hands that person would have bid the way they did count in full, hands a
    trick off count a third, further off are dropped."""
    pool, _void = _public(game, hand)
    # Cards she was shown at the deal (the ladder) are evidence, not a guess: pin the ones still
    # in his hand into every world and sample only the rest.
    shown = set(game.get('marta_sees') or [])
    known = [c for c in (game.get('player_hand') or []) if _key(c) in shown
             and not (on_table and _key(c) == _key(on_table))]
    if known:
        pool = [c for c in pool if _key(c) not in {_key(k) for k in known}]
    need = len(hand) - (1 if on_table else 0) - len(known)
    if need < 0 or need > len(pool):
        return []
    if need == 0:                       # every card known: one world, and it is the real hand
        return [(sum(1 << _code(c) for c in known), 1.0)]
    pbid = game.get('player_bid')
    worlds, tries = [], 0
    while len(worlds) < n and tries < max(4, n * 4):
        tries += 1
        cards = random.sample(pool, need) + known
        w = 1.0
        if pbid is not None and game.get('phase') == 'playing':
            full = cards + ([on_table] if on_table else [])
            taken = game.get('player_tricks', 0)
            est = _opp_estimate(full, game) + taken
            off = abs(round(est) - pbid)
            w = 1.0 if off == 0 else 0.34 if off == 1 else 0.0
        if w:
            worlds.append((sum(1 << _code(c) for c in cards), w))
    return worlds


def _budget(game):
    share = think_share(game.get('difficulty', 0))
    return max(0.02, share) * MAX_BUDGET_MS / 1000.0


def thinks_this_hand(game):
    """Rolled once per hand at bidding; the play decisions of that hand read it."""
    return bool(game.get('marta_thinks'))


def roll_thinking(game):
    """Rolled once per hand: whether she thinks it through, and which of the opponent's cards
    she is shown for the whole hand (the same ones at the bid and at every play, so what she
    knows never jumps mid-hand)."""
    share = think_share(game.get('difficulty', 0))
    game['marta_thinks'] = share > 0 and (share >= 1 or random.random() < share)
    n = peek_cards(game.get('difficulty', 0)) if game['marta_thinks'] else 0
    opp = game.get('player_hand') or []
    game['marta_sees'] = [_key(c) for c in random.sample(opp, min(n, len(opp)))] if n else []
    return game['marta_thinks']



def think_bid(hand, player_bid, game):
    """Bid = the tricks she can force in BID_PERCENTILE of the worlds she dealt, less
    BID_DISCOUNT. Nil when she takes none in 70% of them. Never None once a world can be dealt."""
    if not THINK_BID:
        return None
    deadline = time.perf_counter() + _budget(game) * 6       # bidding sets the whole hand: six decisions' worth
    leader = 0 if game.get('first_leader', game.get('trick_leader')) == 'computer' else 1
    m = sum(1 << _code(c) for c in hand)
    counts = []
    ctx = _Ctx(game, INF, tricks_only=True)                  # every trick +1: how many can she force
    worlds = [(sum(1 << _code(c) for c in game['player_hand']), 1.0)] if PEEK else _sample_worlds(game, hand, MAX_WORLDS)
    for p, w in worlds:
        try:
            counts.append((_count(m, p, leader, ctx, {}), w))
        except _Budget:
            break
        if len(counts) >= MIN_WORLDS:
            ctx.deadline = deadline                          # the first few are owed; the rest are on the clock
    if len(counts) < min(MIN_WORLDS, len(worlds)):
        return None
    total = sum(w for _, w in counts)
    zero = sum(w for t, w in counts if t == 0) / total
    if zero >= 0.7:
        return 0, {'worlds': len(counts), 'p_zero': round(zero, 2)}
    counts.sort()
    acc, bid = 0.0, 0
    for t, w in sorted(counts, reverse=True):        # highest first: the count she makes in BID_PERCENTILE of worlds
        acc += w
        if acc / total >= BID_PERCENTILE:
            bid = t; break
    bid -= BID_DISCOUNT
    return max(1, bid), {'worlds': len(counts), 'p_zero': round(zero, 2),
                         'spread': f"{counts[0][0]}-{counts[-1][0]}"}


def think_play(hand, current_trick, game):
    """Index of the card that does best across the sampled worlds (None only if no world fits
    the evidence, which cannot happen with a legal game state)."""
    if not THINK_PLAY:
        return None
    deadline = time.perf_counter() + _budget(game)
    on_table = current_trick[0]['card'] if current_trick else None
    led = _code(on_table) if on_table else None
    m = sum(1 << _code(c) for c in hand)
    mt, pt = game.get('computer_tricks', 0), game.get('player_tricks', 0)
    broken = bool(game.get('spades_broken'))
    if PEEK:
        real = [c for c in game['player_hand'] if not on_table or _code(c) != _code(on_table)]
        worlds = [(sum(1 << _code(c) for c in real), 1.0)]
    else:
        worlds = _sample_worlds(game, hand, MAX_WORLDS, on_table)
    if not worlds:
        return None
    options = _moves(m, m | worlds[0][0] | ((1 << led) if led is not None else 0), led=led, broken=broken)
    if len(options) == 1:
        return _index(hand, options[0]), {'worlds': 0, 'forced': True}
    ctx = _Ctx(game, INF)                                    # the first few worlds are owed; the rest are on the clock
    score = {c: 0.0 for c in options}
    scored, total_w = 0, 0.0
    for p, w in worlds:
        memo = {}
        try:
            for c in options:
                if led is None:
                    # she leads c; the opponent answers with their best reply
                    live = m | p
                    val = None
                    for ans in _moves(p, live, led=c):
                        winner = 1 if _takes(c, ans) else 0
                        nb = broken or _suit(c) == SPADE or _suit(ans) == SPADE
                        v = _solve(m & ~(1 << c), p & ~(1 << ans), winner, nb, mt + (winner == 0), pt + (winner == 1), ctx, memo)
                        val = v if val is None else min(val, v)
                else:
                    winner = 0 if _takes(led, c) else 1
                    nb = broken or _suit(led) == SPADE or _suit(c) == SPADE
                    val = _solve(m & ~(1 << c), p, winner, nb, mt + (winner == 0), pt + (winner == 1), ctx, memo)
                score[c] += w * val
        except _Budget:
            break
        scored += 1; total_w += w
        if scored >= MIN_WORLDS:
            ctx.deadline = deadline
    if scored < min(MIN_WORLDS, len(worlds)):
        return None
    best = max(options, key=lambda c: score[c])
    return _index(hand, best), {'worlds': scored, 'ev': round(score[best] / total_w, 1),
                                'options': {_name(c): round(score[c] / total_w, 1) for c in options}}


def _index(hand, code):
    return next(i for i, c in enumerate(hand) if _code(c) == code)


def _name(code):
    v = code & 15
    rank = {11: 'J', 12: 'Q', 13: 'K', 14: 'A'}.get(v, str(v))
    return f"{rank}{SUITS[_suit(code)]}"
