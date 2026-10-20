"""The rule, end to end through file_case: every verdict and every boundary
of rule 2 and rule 3 (docs/RULES.md), read from the mock RPCs exactly as the
contract reads them."""
import unittest

import fixtures as F
from fixtures import ETH, GEN

SR = F.SR


class Base(unittest.TestCase):
    def setUp(self):
        self.d = F.Deployment()
        self.c = self.d.chain
        self.pid = self.d.create(**self.terms())["pool_id"]

    def terms(self):
        return {}

    def state(self, txh):
        return self.d.file(self.pid, txh)

    def assertVerdict(self, txh, state, reason=None):
        r = self.state(txh)
        self.assertEqual(r["state"], state, r)
        if reason is not None:
            self.assertEqual(r["reason"], reason, r)
        return r


class Sandwiched(Base):
    def test_classic_v2_weth_in(self):
        _, v, _ = self.c.sandwich()
        r = self.assertVerdict(v, "SANDWICHED_REFUNDED", "SAME_POOL_SANDWICH")
        self.assertEqual(r["loss"], str(3 * ETH // 100))
        self.assertEqual(r["refund"], str(3 * ETH // 100 * 10))
        self.assertEqual(self.d.paid_to(F.VICTIM), 3 * ETH // 10)

    def test_case_records_every_field(self):
        f, v, b = self.c.sandwich()
        self.state(v)
        c = self.d.case(v)
        self.assertEqual(c["victim"], F.VICTIM)
        self.assertEqual(c["router"], F.ROUTER)
        self.assertEqual(c["dex_pool"], F.POOL_V2)
        self.assertEqual(c["attacker"], F.ATTACKER)
        self.assertEqual(c["facts"]["attacker_contract"], F.BOT)
        self.assertEqual(c["facts"]["front_tx"], f)
        self.assertEqual(c["facts"]["back_tx"], b)
        self.assertEqual(c["facts"]["front_index"], 0)
        self.assertEqual(c["tx_index"], 1)
        self.assertEqual(c["facts"]["back_index"], 2)
        self.assertEqual(c["block"], F.BLOCK)
        self.assertEqual(c["profit_token"], F.WETH)
        self.assertTrue(c["final"])
        self.assertEqual(c["facts"]["kind"], "V2")

    def test_v3_sign_convention_weth_is_token1(self):
        # POOL_V3: token0 = TOKEN, token1 = WETH; the victim pays WETH (d = 1)
        _, v, _ = self.c.sandwich(pool=F.POOL_V3, d=1)
        r = self.assertVerdict(v, "SANDWICHED_REFUNDED")
        self.assertEqual(r["loss"], str(3 * ETH // 100))
        self.assertEqual(self.d.case(v)["facts"]["kind"], "V3")

    def test_v3_amounts_are_signed(self):
        _, v, _ = self.c.sandwich(pool=F.POOL_V3, d=1)
        self.state(v)
        fx = self.d.case(v)["facts"]
        self.assertTrue(int(fx["front_n1"]) > 0 and int(fx["front_n0"]) < 0)
        self.assertTrue(int(fx["back_n1"]) < 0 and int(fx["back_n0"]) > 0)

    def test_profit_in_y_when_attacker_balances_x(self):
        # victim sells TOKEN for WETH on POOL_V2 (d = 1, X = TOKEN): the bot buys
        # back exactly the TOKEN it sold and keeps WETH
        _, v, _ = self.c.sandwich(d=1, front=(1000 * ETH, 10 * ETH), victim=(400 * ETH, 3 * ETH),
                                  back=(997 * ETH // 100, 1000 * ETH))
        r = self.assertVerdict(v, "SANDWICHED_REFUNDED")
        self.assertEqual(r["loss"], str(3 * ETH // 100))
        self.assertEqual(self.d.case(v)["profit_token"], F.WETH)

    def test_same_eoa_different_contracts(self):
        f = self.c.tx(F.BLOCK, F.ATTACKER, F.BOT, [(F.POOL_V2, 10 * ETH, -1000 * ETH, F.BOT, F.BOT)])
        v = self.c.tx(F.BLOCK, F.VICTIM, F.ROUTER, [(F.POOL_V2, 5 * ETH, -450 * ETH, F.VICTIM, F.ROUTER)])
        b = self.c.tx(F.BLOCK, F.ATTACKER, F.BOT2, [(F.POOL_V2, -10 * ETH - ETH // 100, 1000 * ETH, F.BOT2, F.BOT2)])
        r = self.assertVerdict(v, "SANDWICHED_REFUNDED")
        self.assertEqual(r["loss"], str(ETH // 100))

    def test_same_recipient_different_eoas(self):
        self.c.tx(F.BLOCK, F.ATTACKER, F.BOT, [(F.POOL_V2, 10 * ETH, -1000 * ETH, F.BOT, F.BOT)])
        v = self.c.tx(F.BLOCK, F.VICTIM, F.ROUTER, [(F.POOL_V2, 5 * ETH, -450 * ETH, F.VICTIM, F.ROUTER)])
        self.c.tx(F.BLOCK, F.ATTACKER2, F.BOT, [(F.POOL_V2, -10 * ETH - ETH // 100, 1000 * ETH, F.BOT, F.BOT)])
        self.assertVerdict(v, "SANDWICHED_REFUNDED")

    def test_unrelated_traders_around_victim_are_clean(self):
        self.c.tx(F.BLOCK, F.TRADER, F.ROUTER_X, [(F.POOL_V2, 10 * ETH, -1000 * ETH, F.TRADER)])
        v = self.c.tx(F.BLOCK, F.VICTIM, F.ROUTER, [(F.POOL_V2, 5 * ETH, -450 * ETH, F.VICTIM)])
        self.c.tx(F.BLOCK, F.TRADER2, F.ROUTER_X, [(F.POOL_V2, -10 * ETH - ETH // 100, 1000 * ETH, F.TRADER2)])
        self.assertVerdict(v, "CLEAN", "NO_PATTERN")

    def test_shared_router_recipient_is_not_a_link(self):
        # two strangers whose Swap recipient is the covered router itself
        self.c.tx(F.BLOCK, F.TRADER, F.ROUTER, [(F.POOL_V2, 10 * ETH, -1000 * ETH, F.ROUTER)])
        v = self.c.tx(F.BLOCK, F.VICTIM, F.ROUTER, [(F.POOL_V2, 5 * ETH, -450 * ETH, F.VICTIM)])
        self.c.tx(F.BLOCK, F.TRADER2, F.ROUTER, [(F.POOL_V2, -10 * ETH - ETH // 100, 1000 * ETH, F.ROUTER)])
        self.assertVerdict(v, "CLEAN", "NO_PATTERN")

    def test_victim_alone_in_block_is_clean(self):
        v = self.c.tx(F.BLOCK, F.VICTIM, F.ROUTER, [(F.POOL_V2, 5 * ETH, -450 * ETH, F.VICTIM)])
        self.assertVerdict(v, "CLEAN", "NO_PATTERN")
        self.assertEqual(self.d.paid_to(F.VICTIM), 0)


def _gap_test(gb, ga):
    def t(self):
        _, v, _ = self.c.sandwich(gap_before=gb, gap_after=ga)
        self.assertVerdict(v, "SANDWICHED_REFUNDED")
        c = self.d.case(v)
        self.assertEqual(c["facts"]["front_index"], 0)
        self.assertEqual(c["tx_index"], 1 + gb)
        self.assertEqual(c["facts"]["back_index"], 2 + gb + ga)
    return t


for _gb in range(4):
    for _ga in range(4):
        setattr(Sandwiched, "test_tx_index_gaps_%d_%d" % (_gb, _ga), _gap_test(_gb, _ga))


class NotSandwiched(Base):
    def test_front_in_wrong_direction_is_partial(self):
        # the same bot trades opposite the victim before it and with it after
        self.c.tx(F.BLOCK, F.ATTACKER, F.BOT, [(F.POOL_V2, -10 * ETH, 1000 * ETH, F.BOT)])
        v = self.c.tx(F.BLOCK, F.VICTIM, F.ROUTER, [(F.POOL_V2, 5 * ETH, -450 * ETH, F.VICTIM)])
        self.c.tx(F.BLOCK, F.ATTACKER, F.BOT, [(F.POOL_V2, 10 * ETH, -900 * ETH, F.BOT)])
        self.assertVerdict(v, "UNCLEAR", "PARTIAL_PATTERN")

    def test_back_in_same_direction_is_partial(self):
        self.c.tx(F.BLOCK, F.ATTACKER, F.BOT, [(F.POOL_V2, 10 * ETH, -1000 * ETH, F.BOT)])
        v = self.c.tx(F.BLOCK, F.VICTIM, F.ROUTER, [(F.POOL_V2, 5 * ETH, -450 * ETH, F.VICTIM)])
        self.c.tx(F.BLOCK, F.ATTACKER, F.BOT, [(F.POOL_V2, 10 * ETH, -900 * ETH, F.BOT)])
        self.assertVerdict(v, "UNCLEAR", "PARTIAL_PATTERN")

    def test_front_only_is_clean(self):
        self.c.tx(F.BLOCK, F.ATTACKER, F.BOT, [(F.POOL_V2, 10 * ETH, -1000 * ETH, F.BOT)])
        v = self.c.tx(F.BLOCK, F.VICTIM, F.ROUTER, [(F.POOL_V2, 5 * ETH, -450 * ETH, F.VICTIM)])
        self.assertVerdict(v, "CLEAN")

    def test_back_only_is_clean(self):
        v = self.c.tx(F.BLOCK, F.VICTIM, F.ROUTER, [(F.POOL_V2, 5 * ETH, -450 * ETH, F.VICTIM)])
        self.c.tx(F.BLOCK, F.ATTACKER, F.BOT, [(F.POOL_V2, -10 * ETH, 1000 * ETH, F.BOT)])
        self.assertVerdict(v, "CLEAN")

    def test_front_and_back_on_another_pool(self):
        self.c.tx(F.BLOCK, F.ATTACKER, F.BOT, [(F.POOL_B, 10 * ETH, -1000 * ETH, F.BOT)])
        v = self.c.tx(F.BLOCK, F.VICTIM, F.ROUTER, [(F.POOL_V2, 5 * ETH, -450 * ETH, F.VICTIM)])
        self.c.tx(F.BLOCK, F.ATTACKER, F.BOT, [(F.POOL_B, -10 * ETH - ETH // 100, 1000 * ETH, F.BOT)])
        self.assertVerdict(v, "CLEAN")

    def test_back_run_in_next_block_is_unclear(self):
        self.c.tx(F.BLOCK, F.ATTACKER, F.BOT, [(F.POOL_V2, 10 * ETH, -1000 * ETH, F.BOT)])
        v = self.c.tx(F.BLOCK, F.VICTIM, F.ROUTER, [(F.POOL_V2, 5 * ETH, -450 * ETH, F.VICTIM)])
        self.c.tx(F.BLOCK + 1, F.ATTACKER, F.BOT, [(F.POOL_V2, -10 * ETH - ETH // 100, 1000 * ETH, F.BOT)])
        self.assertVerdict(v, "UNCLEAR", "CROSS_BLOCK_PATTERN")

    def test_back_run_two_blocks_later_is_not_seen(self):
        self.c.tx(F.BLOCK, F.ATTACKER, F.BOT, [(F.POOL_V2, 10 * ETH, -1000 * ETH, F.BOT)])
        v = self.c.tx(F.BLOCK, F.VICTIM, F.ROUTER, [(F.POOL_V2, 5 * ETH, -450 * ETH, F.VICTIM)])
        self.c.tx(F.BLOCK + 2, F.ATTACKER, F.BOT, [(F.POOL_V2, -10 * ETH - ETH // 100, 1000 * ETH, F.BOT)])
        self.assertVerdict(v, "CLEAN")

    def test_zero_profit(self):
        _, v, _ = self.c.sandwich(back=(1000 * ETH, 10 * ETH))
        self.assertVerdict(v, "UNCLEAR", "NO_ATTACKER_PROFIT")

    def test_negative_profit(self):
        _, v, _ = self.c.sandwich(back=(1000 * ETH, 9 * ETH))
        self.assertVerdict(v, "UNCLEAR", "NO_ATTACKER_PROFIT")
        self.assertEqual(self.d.paid_to(F.VICTIM), 0)

    def test_one_wei_profit_is_a_sandwich(self):
        _, v, _ = self.c.sandwich(back=(1000 * ETH, 10 * ETH + 1))
        r = self.assertVerdict(v, "SANDWICHED_REFUNDED")
        self.assertEqual(r["loss"], "1")
        self.assertEqual(r["refund"], "10")

    def test_back_sells_more_than_front_bought_counts_pro_rata(self):
        # back sells 2000 TOKEN (twice what the front bought) for 20.1 WETH:
        # only half of it unwinds the front-run -> 10.05 - 10 = 0.05 WETH
        _, v, _ = self.c.sandwich(back=(2000 * ETH, 20 * ETH + ETH // 10))
        r = self.assertVerdict(v, "SANDWICHED_REFUNDED")
        self.assertEqual(r["loss"], str(5 * ETH // 100))

    def test_back_sells_more_without_gain_pro_rata(self):
        _, v, _ = self.c.sandwich(back=(2000 * ETH, 20 * ETH))
        self.assertVerdict(v, "UNCLEAR", "NO_ATTACKER_PROFIT")

    def test_back_sells_less_keeps_y_counts_x_only(self):
        _, v, _ = self.c.sandwich(back=(900 * ETH, 10 * ETH + ETH // 100))
        r = self.assertVerdict(v, "SANDWICHED_REFUNDED")
        self.assertEqual(r["loss"], str(ETH // 100))

    def test_unpriced_profit_token(self):
        # victim sells TOKEN on POOL_V2 (X = TOKEN); the bot profits in TOKEN only
        _, v, _ = self.c.sandwich(d=1, front=(1000 * ETH, 10 * ETH), victim=(400 * ETH, 3 * ETH),
                                  back=(10 * ETH, 1010 * ETH))
        r = self.assertVerdict(v, "UNCLEAR", "PROFIT_TOKEN_NOT_PRICED")
        self.assertEqual(self.d.case(v)["profit_token"], F.TOKEN)
        self.assertEqual(r["refund"], "0")

    def test_profit_in_both_tokens_prefers_the_priced_one(self):
        _, v, _ = self.c.sandwich(d=1, front=(1000 * ETH, 10 * ETH), victim=(400 * ETH, 3 * ETH),
                                  back=(9 * ETH, 1010 * ETH))
        r = self.assertVerdict(v, "SANDWICHED_REFUNDED")
        self.assertEqual(self.d.case(v)["profit_token"], F.WETH)
        self.assertEqual(r["loss"], str(ETH))

    def test_victim_direction_unreadable(self):
        v = self.c.tx(F.BLOCK, F.VICTIM, F.ROUTER, [(F.POOL_V2, 5 * ETH, 450 * ETH, F.VICTIM)])
        self.assertVerdict(v, "UNCLEAR", "VICTIM_DIRECTION_UNREADABLE")


class Coverage(Base):
    def terms(self):
        return {"end": F.FINALIZED + 10}

    def test_router_not_covered(self):
        _, v, _ = self.c.sandwich(router=F.ROUTER_X)
        self.assertVerdict(v, "NOT_COVERED", "ROUTER_NOT_COVERED")
        self.assertEqual(self.d.paid_to(F.VICTIM), 0)

    def test_second_covered_router(self):
        _, v, _ = self.c.sandwich(router=F.ROUTER2)
        self.assertVerdict(v, "SANDWICHED_REFUNDED")

    def test_failed_victim_tx(self):
        v = self.c.tx(F.BLOCK, F.VICTIM, F.ROUTER, [], status=0)
        self.assertVerdict(v, "NOT_COVERED", "TX_FAILED")

    def test_no_swap_in_tx(self):
        v = self.c.tx(F.BLOCK, F.VICTIM, F.ROUTER, [])
        self.assertVerdict(v, "NOT_COVERED", "NO_SWAP_IN_TX")

    def test_lookalike_pool(self):
        _, v, _ = self.c.sandwich(pool=F.POOL_FAKE)
        self.assertVerdict(v, "NOT_COVERED", "POOL_NOT_CANONICAL")

    def test_unlisted_factory(self):
        _, v, _ = self.c.sandwich(pool=F.POOL_ALIEN)
        self.assertVerdict(v, "NOT_COVERED", "POOL_NOT_CANONICAL")

    def test_unfinalized_block(self):
        _, v, _ = self.c.sandwich(block=F.FINALIZED)
        self.assertVerdict(v, "UNVERIFIABLE", "NOT_FINALIZED")

    def test_next_block_must_be_final_too(self):
        _, v, _ = self.c.sandwich(block=F.FINALIZED - 1)
        self.assertVerdict(v, "SANDWICHED_REFUNDED")

    def test_pending(self):
        self.assertVerdict(self.c.pending(), "UNVERIFIABLE", "TX_PENDING")

    def test_not_found(self):
        self.assertVerdict(F.h32("nothing"), "UNVERIFIABLE", "TX_NOT_FOUND")


def _range_test(offset, inside):
    def t(self):
        blk = (F.START_BLOCK + offset) if offset <= 0 else (F.END_BLOCK + offset - 1)
        _, v, _ = self.c.sandwich(block=blk)
        if inside:
            self.assertVerdict(v, "SANDWICHED_REFUNDED")
        else:
            self.assertVerdict(v, "NOT_COVERED", "OUTSIDE_BLOCK_RANGE")
    return t


class Range(Base):
    def terms(self):
        return {}


# START_BLOCK - 2, START_BLOCK - 1: outside; START_BLOCK: inside; END_BLOCK: inside; END_BLOCK + 1: outside
for _name, _off, _in in (("before_start_2", -2, False), ("before_start_1", -1, False), ("at_start", 0, True),
                         ("at_end", 1, True), ("after_end_1", 2, False), ("after_end_2", 3, False)):
    setattr(Range, "test_range_" + _name, _range_test(_off, _in))


class Kinds(Base):
    def terms(self):
        return {"kinds": ("V2",)}

    def test_v3_not_covered_by_a_v2_pool(self):
        _, v, _ = self.c.sandwich(pool=F.POOL_V3, d=1)
        self.assertVerdict(v, "NOT_COVERED", "POOL_TYPE_NOT_COVERED")

    def test_v2_covered(self):
        _, v, _ = self.c.sandwich()
        self.assertVerdict(v, "SANDWICHED_REFUNDED")


class KindsV3(Base):
    def terms(self):
        return {"kinds": ("V3",)}

    def test_v2_not_covered_by_a_v3_pool(self):
        _, v, _ = self.c.sandwich()
        self.assertVerdict(v, "NOT_COVERED", "POOL_TYPE_NOT_COVERED")


class Ambiguous(Base):
    def test_multi_hop_sandwiched(self):
        self.c.tx(F.BLOCK, F.ATTACKER, F.BOT, [(F.POOL_V2, 10 * ETH, -1000 * ETH, F.BOT)])
        v = self.c.tx(F.BLOCK, F.VICTIM, F.ROUTER, [(F.POOL_B, 9000 * 10 ** 6, -3 * ETH, F.POOL_V2),
                                                    (F.POOL_V2, 3 * ETH, -280 * ETH, F.VICTIM)])
        self.c.tx(F.BLOCK, F.ATTACKER, F.BOT, [(F.POOL_V2, -10 * ETH - ETH // 50, 1000 * ETH, F.BOT)])
        self.assertVerdict(v, "UNCLEAR", "MULTI_HOP_VICTIM")
        self.assertEqual(self.d.paid_to(F.VICTIM), 0)

    def test_multi_hop_clean(self):
        v = self.c.tx(F.BLOCK, F.VICTIM, F.ROUTER, [(F.POOL_B, 9000 * 10 ** 6, -3 * ETH, F.POOL_V2),
                                                    (F.POOL_V2, 3 * ETH, -280 * ETH, F.VICTIM)])
        r = self.assertVerdict(v, "CLEAN")
        self.assertEqual(self.d.case(v)["facts"]["hops"], 2)

    def test_two_swaps_on_the_same_pool(self):
        self.c.tx(F.BLOCK, F.ATTACKER, F.BOT, [(F.POOL_V2, 10 * ETH, -1000 * ETH, F.BOT)])
        v = self.c.tx(F.BLOCK, F.VICTIM, F.ROUTER, [(F.POOL_V2, 1 * ETH, -90 * ETH, F.VICTIM),
                                                    (F.POOL_V2, 1 * ETH, -89 * ETH, F.VICTIM)])
        self.c.tx(F.BLOCK, F.ATTACKER, F.BOT, [(F.POOL_V2, -10 * ETH - ETH // 50, 1000 * ETH, F.BOT)])
        self.assertVerdict(v, "UNCLEAR", "MULTI_HOP_VICTIM")

    def test_multiple_attackers(self):
        self.c.tx(F.BLOCK, F.ATTACKER, F.BOT, [(F.POOL_V2, 10 * ETH, -1000 * ETH, F.BOT)])
        self.c.tx(F.BLOCK, F.ATTACKER2, F.BOT2, [(F.POOL_V2, 5 * ETH, -400 * ETH, F.BOT2)])
        v = self.c.tx(F.BLOCK, F.VICTIM, F.ROUTER, [(F.POOL_V2, 5 * ETH, -350 * ETH, F.VICTIM)])
        self.c.tx(F.BLOCK, F.ATTACKER2, F.BOT2, [(F.POOL_V2, -5 * ETH - ETH // 100, 400 * ETH, F.BOT2)])
        self.c.tx(F.BLOCK, F.ATTACKER, F.BOT, [(F.POOL_V2, -10 * ETH - ETH // 50, 1000 * ETH, F.BOT)])
        r = self.assertVerdict(v, "UNCLEAR", "MULTIPLE_ATTACKERS")
        self.assertEqual(self.d.case(v)["facts"]["attackers"], 2)

    def test_two_victims_in_one_bundle(self):
        self.c.tx(F.BLOCK, F.ATTACKER, F.BOT, [(F.POOL_V2, 10 * ETH, -1000 * ETH, F.BOT)])
        v1 = self.c.tx(F.BLOCK, F.VICTIM, F.ROUTER, [(F.POOL_V2, 5 * ETH, -450 * ETH, F.VICTIM)])
        v2 = self.c.tx(F.BLOCK, F.VICTIM2, F.ROUTER, [(F.POOL_V2, 2 * ETH, -170 * ETH, F.VICTIM2)])
        self.c.tx(F.BLOCK, F.ATTACKER, F.BOT, [(F.POOL_V2, -10 * ETH - ETH // 20, 1000 * ETH, F.BOT)])
        self.assertVerdict(v1, "UNCLEAR", "MULTIPLE_VICTIMS")
        self.assertVerdict(v2, "UNCLEAR", "MULTIPLE_VICTIMS")

    def test_opposite_trade_between_is_not_another_victim(self):
        self.c.tx(F.BLOCK, F.ATTACKER, F.BOT, [(F.POOL_V2, 10 * ETH, -1000 * ETH, F.BOT)])
        v = self.c.tx(F.BLOCK, F.VICTIM, F.ROUTER, [(F.POOL_V2, 5 * ETH, -450 * ETH, F.VICTIM)])
        self.c.tx(F.BLOCK, F.TRADER, F.ROUTER_X, [(F.POOL_V2, -1 * ETH, 95 * ETH, F.TRADER)])
        self.c.tx(F.BLOCK, F.ATTACKER, F.BOT, [(F.POOL_V2, -10 * ETH - ETH // 50, 1000 * ETH, F.BOT)])
        self.assertVerdict(v, "SANDWICHED_REFUNDED")

    def test_two_fronts_one_attacker(self):
        self.c.tx(F.BLOCK, F.ATTACKER, F.BOT, [(F.POOL_V2, 5 * ETH, -500 * ETH, F.BOT)])
        self.c.tx(F.BLOCK, F.ATTACKER, F.BOT, [(F.POOL_V2, 5 * ETH, -490 * ETH, F.BOT)])
        v = self.c.tx(F.BLOCK, F.VICTIM, F.ROUTER, [(F.POOL_V2, 5 * ETH, -430 * ETH, F.VICTIM)])
        self.c.tx(F.BLOCK, F.ATTACKER, F.BOT, [(F.POOL_V2, -10 * ETH - ETH // 50, 990 * ETH, F.BOT)])
        self.assertVerdict(v, "UNCLEAR", "COMPLEX_PATTERN")

    def test_too_many_hops(self):
        v = self.c.tx(F.BLOCK, F.VICTIM, F.ROUTER, [(F.POOL_V2, 1, -1, F.VICTIM), (F.POOL_V3, -1, 1, F.VICTIM),
                                                    (F.POOL_B, 1, -1, F.VICTIM), (F.POOL_FOT, 1, -1, F.VICTIM),
                                                    (F.POOL_FAKE, 1, -1, F.VICTIM)])
        self.assertVerdict(v, "UNCLEAR", "TOO_MANY_HOPS")

    def test_block_too_busy(self):
        for i in range(SR.MAX_TXS + 1):
            self.c.tx(F.BLOCK, F.addr(1000 + i), F.ROUTER_X, [(F.POOL_V2, ETH, -90 * ETH, F.addr(1000 + i))])
        v = self.c.tx(F.BLOCK, F.VICTIM, F.ROUTER, [(F.POOL_V2, 5 * ETH, -450 * ETH, F.VICTIM)])
        self.assertVerdict(v, "UNCLEAR", "BLOCK_TOO_BUSY")

    def test_exactly_max_txs_is_read(self):
        for i in range(SR.MAX_TXS):
            self.c.tx(F.BLOCK, F.addr(1000 + i), F.ROUTER_X, [(F.POOL_V2, ETH, -90 * ETH, F.addr(1000 + i))])
        v = self.c.tx(F.BLOCK, F.VICTIM, F.ROUTER, [(F.POOL_V2, 5 * ETH, -450 * ETH, F.VICTIM)])
        self.assertVerdict(v, "CLEAN")


class SelfSandwich(Base):
    def test_victim_is_the_attacker_eoa(self):
        _, v, _ = self.c.sandwich(victim_from=F.ATTACKER)
        # the victim's own swap shares the EOA: no front/back pair is formed with itself,
        # and the bot's pair around it is linked to the victim
        r = self.state(v)
        self.assertEqual(r["state"], "UNCLEAR")
        self.assertEqual(self.d.paid_to(F.ATTACKER), 0)

    def test_victim_swap_pays_the_attacker_contract(self):
        _, v, _ = self.c.sandwich(victim_recipient=F.BOT)
        self.assertVerdict(v, "UNCLEAR", "SELF_SANDWICH")
        self.assertEqual(self.d.paid_to(F.VICTIM), 0)

    def test_victim_eoa_is_the_attacker_recipient(self):
        self.c.tx(F.BLOCK, F.ATTACKER, F.BOT, [(F.POOL_V2, 10 * ETH, -1000 * ETH, F.VICTIM)])
        v = self.c.tx(F.BLOCK, F.VICTIM, F.ROUTER, [(F.POOL_V2, 5 * ETH, -450 * ETH, F.TRADER)])
        self.c.tx(F.BLOCK, F.ATTACKER, F.BOT, [(F.POOL_V2, -10 * ETH - ETH // 100, 1000 * ETH, F.VICTIM)])
        self.assertVerdict(v, "UNCLEAR", "SELF_SANDWICH")


class Rpc(Base):
    def test_rpcs_disagree_on_amounts(self):
        _, v, _ = self.c.sandwich()
        b = self.c.split()
        for lg in b.logs:
            if lg["transactionHash"] == v:
                lg["data"] = lg["data"][:-1] + "1"
        self.assertVerdict(v, "UNVERIFIABLE", "RPC_DISAGREE")

    def test_one_rpc_lacks_the_tx(self):
        _, v, _ = self.c.sandwich()
        b = self.c.split()
        del b.txs[v]
        self.assertVerdict(v, "UNVERIFIABLE", "RPC_DISAGREE")

    def test_rpc_down(self):
        _, v, _ = self.c.sandwich()
        F.stub.WEB.down.add(F.RPCS[1])
        r = self.assertVerdict(v, "UNVERIFIABLE", "RPC_UNREADABLE")
        self.assertIn("blastapi", self.d.case(v)["detail"])

    def test_rpc_http_error(self):
        _, v, _ = self.c.sandwich()
        F.stub.WEB.rpc_status[F.RPCS[0]] = 503
        self.assertVerdict(v, "UNVERIFIABLE", "RPC_UNREADABLE")

    def test_rpc_json_error(self):
        _, v, _ = self.c.sandwich()
        self.c.c.fail = lambda m, p: {"code": -32000, "message": "boom"} if m == "eth_getLogs" else None
        self.assertVerdict(v, "UNVERIFIABLE", "RPC_UNREADABLE")

    def test_wrong_chain_id(self):
        _, v, _ = self.c.sandwich()
        self.c.c.chain_id = 5
        self.assertVerdict(v, "UNVERIFIABLE", "WRONG_CHAIN_ID")

    def test_unverifiable_can_be_filed_again(self):
        _, v, _ = self.c.sandwich()
        F.stub.WEB.down.add(F.RPCS[1])
        self.assertVerdict(v, "UNVERIFIABLE")
        F.stub.WEB.down.clear()
        r = self.assertVerdict(v, "SANDWICHED_REFUNDED")
        c = self.d.case(v)
        self.assertEqual(c["attempts"], 2)
        self.assertEqual(self.d.stats()["counts"]["state:UNVERIFIABLE"], 0)
        self.assertEqual(self.d.stats()["counts"]["state:SANDWICHED_REFUNDED"], 1)
        self.assertEqual(self.d.stats()["cases"], 1)

    def test_batches_respect_the_cap(self):
        for i in range(30):
            self.c.tx(F.BLOCK, F.addr(2000 + i), F.ROUTER_X, [(F.POOL_V2, ETH, -90 * ETH, F.addr(2000 + i))])
        v = self.c.tx(F.BLOCK, F.VICTIM, F.ROUTER, [(F.POOL_V2, 5 * ETH, -450 * ETH, F.VICTIM)])
        self.c.c.batch_cap = 12
        self.assertVerdict(v, "CLEAN")


if __name__ == "__main__":
    unittest.main()
