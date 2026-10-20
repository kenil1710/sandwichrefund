"""Pools and money: terms frozen at creation, refund math and caps, each case
once, top up / extend / close, credits, stray value, fund conservation,
counters only after checks, and every paginated view."""
import json
import unittest

import fixtures as F
import world
from fixtures import ETH, GEN

SR = F.SR


class Base(unittest.TestCase):
    def setUp(self):
        self.d = F.Deployment()
        self.c = self.d.chain
        self.w = self.d.w

    def pool(self, **kw):
        return self.d.create(**kw)["pool_id"]

    def refused(self, fn, *args, contains="REFUSED", **kw):
        with self.assertRaises(world.Reverted) as e:
            fn(*args, **kw)
        self.assertIn(contains, e.exception.msg)
        return e.exception.msg


class RefundMath(Base):
    def test_rate_num_den(self):
        pid = self.pool(rates=((F.WETH, 7, 3),))
        _, v, _ = self.c.sandwich()
        r = self.d.file(pid, v)
        self.assertEqual(int(r["refund"]), (3 * ETH // 100) * 7 // 3)
        self.assertEqual(r["limit"], "RATE")

    def test_rate_rounds_down(self):
        pid = self.pool(rates=((F.WETH, 1, 7),))
        _, v, _ = self.c.sandwich(back=(1000 * ETH, 10 * ETH + 13))
        r = self.d.file(pid, v)
        self.assertEqual(r["refund"], "1")

    def test_rounds_to_zero_is_unpaid(self):
        pid = self.pool(rates=((F.WETH, 1, 10 ** 6),))
        _, v, _ = self.c.sandwich(back=(1000 * ETH, 10 * ETH + 5))
        r = self.d.file(pid, v)
        self.assertEqual(r["state"], "SANDWICHED_UNPAID")
        self.assertEqual(r["limit"], "REFUND_ROUNDS_TO_ZERO")
        self.assertEqual(self.d.paid_to(F.VICTIM), 0)

    def test_max_per_swap(self):
        pid = self.pool(max_swap=GEN // 10)
        _, v, _ = self.c.sandwich()
        r = self.d.file(pid, v)
        self.assertEqual(int(r["refund"]), GEN // 10)
        self.assertEqual(r["limit"], "MAX_PER_SWAP")
        c = self.d.case(v)
        self.assertEqual(int(c["refund_due"]), 3 * GEN // 10)
        self.assertEqual(int(c["refund_paid"]), GEN // 10)

    def test_max_per_victim_across_cases(self):
        pid = self.pool(max_swap=GEN // 2, max_victim=GEN // 2)
        _, v1, _ = self.c.sandwich(block=F.BLOCK)
        _, v2, _ = self.c.sandwich(block=F.BLOCK + 3)
        _, v3, _ = self.c.sandwich(block=F.BLOCK + 6)
        r1 = self.d.file(pid, v1)
        r2 = self.d.file(pid, v2)
        r3 = self.d.file(pid, v3)
        self.assertEqual(int(r1["refund"]), 3 * GEN // 10)
        self.assertEqual(int(r2["refund"]), 2 * GEN // 10)
        self.assertEqual(r2["limit"], "MAX_PER_VICTIM")
        self.assertEqual(r3["state"], "SANDWICHED_UNPAID")
        self.assertEqual(r3["limit"], "MAX_PER_VICTIM")
        self.assertEqual(self.d.paid_to(F.VICTIM), GEN // 2)

    def test_victim_cap_is_per_pool(self):
        p1 = self.pool(max_victim=GEN, max_swap=GEN)
        p2 = self.pool(max_victim=GEN, max_swap=GEN)
        _, v1, _ = self.c.sandwich(block=F.BLOCK)
        _, v2, _ = self.c.sandwich(block=F.BLOCK + 3)
        self.d.file(p1, v1)
        r = self.d.file(p2, v2)
        self.assertEqual(int(r["refund"]), 3 * GEN // 10)

    def test_other_victims_have_their_own_cap(self):
        pid = self.pool(max_swap=3 * GEN // 10, max_victim=3 * GEN // 10)
        _, v1, _ = self.c.sandwich(block=F.BLOCK)
        _, v2, _ = self.c.sandwich(block=F.BLOCK + 3, victim_from=F.VICTIM2)
        self.d.file(pid, v1)
        r = self.d.file(pid, v2)
        self.assertEqual(int(r["refund"]), 3 * GEN // 10)
        self.assertEqual(self.d.paid_to(F.VICTIM2), 3 * GEN // 10)

    def test_pool_balance_partial(self):
        pid = self.pool(value=GEN // 10)
        _, v, _ = self.c.sandwich()
        r = self.d.file(pid, v)
        self.assertEqual(int(r["refund"]), GEN // 10)
        self.assertEqual(r["limit"], "POOL_BALANCE")
        self.assertEqual(self.d.pool(pid)["balance"], "0")

    def test_pool_empty_is_unpaid(self):
        pid = self.pool(value=GEN // 10)
        _, v1, _ = self.c.sandwich(block=F.BLOCK)
        _, v2, _ = self.c.sandwich(block=F.BLOCK + 3, victim_from=F.VICTIM2)
        self.d.file(pid, v1)
        r = self.d.file(pid, v2)
        self.assertEqual(r["state"], "SANDWICHED_UNPAID")
        self.assertEqual(r["limit"], "POOL_BALANCE")
        self.assertEqual(self.d.paid_to(F.VICTIM2), 0)
        p = self.d.pool(pid)
        self.assertEqual(p["n_unpaid"], 1)
        self.assertEqual(p["n_refunded"], 1)

    def test_refund_goes_to_tx_from_not_filer(self):
        pid = self.pool()
        _, v, _ = self.c.sandwich()
        self.d.file(pid, v, sender=F.STRANGER)
        self.assertEqual(self.d.paid_to(F.STRANGER), 0)
        self.assertEqual(self.d.paid_to(F.VICTIM), 3 * GEN // 10)

    def test_refund_amount_pure(self):
        self.assertEqual(SR.refund_amount(100, 2, 1, 1000, 1000, 1000), [200, "RATE"])
        self.assertEqual(SR.refund_amount(100, 2, 1, 150, 1000, 1000), [150, "MAX_PER_SWAP"])
        self.assertEqual(SR.refund_amount(100, 2, 1, 150, 120, 1000), [120, "MAX_PER_VICTIM"])
        self.assertEqual(SR.refund_amount(100, 2, 1, 150, 120, 90), [90, "POOL_BALANCE"])
        self.assertEqual(SR.refund_amount(100, 2, 1, 150, 120, 0), [0, "POOL_BALANCE"])
        self.assertEqual(SR.refund_amount(1, 1, 3, 150, 120, 90), [0, "REFUND_ROUNDS_TO_ZERO"])
        self.assertEqual(SR.refund_amount(100, 2, 1, 150, 0, 90), [0, "MAX_PER_VICTIM"])
        self.assertEqual(SR.refund_amount(100, 2, 1, 150, -5, 90), [0, "MAX_PER_VICTIM"])


class Once(Base):
    def test_final_case_cannot_be_filed_again(self):
        pid = self.pool()
        _, v, _ = self.c.sandwich()
        self.d.file(pid, v)
        self.refused(self.d.file, pid, v, contains="ALREADY_DECIDED_SANDWICHED_REFUNDED")
        self.assertEqual(self.d.paid_to(F.VICTIM), 3 * GEN // 10)

    def test_each_pool_decides_once(self):
        p1 = self.pool()
        p2 = self.pool(sponsor=F.SPONSOR2) if False else self.pool()
        _, v, _ = self.c.sandwich()
        self.d.file(p1, v)
        self.refused(self.d.file, p1, v, contains="ALREADY_DECIDED")
        r = self.d.file(p2, v)
        self.assertEqual(r["state"], "SANDWICHED_REFUNDED")
        self.refused(self.d.file, p2, v, contains="ALREADY_DECIDED")
        c = self.d.case(v)
        self.assertEqual(c["n_decisions"], 2)
        self.assertEqual(int(c["refund_paid_all_pools"]), 6 * GEN // 10)

    def test_griefer_tiny_pool_cannot_lock_a_victim_out(self):
        real = self.pool(value=5 * GEN)
        tiny = self.d.create(value=10 ** 15, sender=F.STRANGER, max_swap=1, max_victim=1)["pool_id"]
        _, v, _ = self.c.sandwich()
        self.assertEqual(self.d.file(tiny, v, sender=F.STRANGER)["refund"], "1")
        r = self.d.file(real, v)
        self.assertEqual(r["state"], "SANDWICHED_REFUNDED")
        self.assertEqual(int(r["refund"]), 3 * GEN // 10)
        self.assertEqual(self.d.case(v)["pool_id"], real)

    def test_strongest_decision_is_reported(self):
        p1 = self.pool(routers=(F.ROUTER2,))
        p2 = self.pool()
        _, v, _ = self.c.sandwich()
        self.d.file(p1, v)
        self.assertEqual(self.d.case(v)["state"], "NOT_COVERED")
        self.d.file(p2, v)
        self.assertEqual(self.d.case(v)["state"], "SANDWICHED_REFUNDED")
        self.assertEqual(self.d.w.view(self.d.sr, "get_pool_case", p1, "ethereum", v)["state"], "NOT_COVERED")
        self.assertFalse(self.d.w.view(self.d.sr, "get_pool_case", 9, "ethereum", v)["found"])

    def test_clean_is_final(self):
        pid = self.pool()
        v = self.c.tx(F.BLOCK, F.VICTIM, F.ROUTER, [(F.POOL_V2, 5 * ETH, -450 * ETH, F.VICTIM)])
        self.d.file(pid, v)
        self.refused(self.d.file, pid, v, contains="ALREADY_DECIDED_CLEAN")

    def test_unclear_is_final(self):
        pid = self.pool()
        _, v, _ = self.c.sandwich(back=(1000 * ETH, 9 * ETH))
        self.d.file(pid, v)
        self.refused(self.d.file, pid, v, contains="ALREADY_DECIDED_UNCLEAR")

    def test_unpaid_is_final(self):
        pid = self.pool(value=GEN // 1000)
        _, v1, _ = self.c.sandwich(block=F.BLOCK)
        _, v2, _ = self.c.sandwich(block=F.BLOCK + 3, victim_from=F.VICTIM2)
        self.d.file(pid, v1)
        self.d.file(pid, v2)
        self.d.w.call(self.d.sr, "top_up", pid, sender=F.SPONSOR, value=GEN)
        self.refused(self.d.file, pid, v2, contains="ALREADY_DECIDED_SANDWICHED_UNPAID")

    def test_not_covered_may_be_filed_again(self):
        p1 = self.pool(routers=(F.ROUTER2,))
        _, v, _ = self.c.sandwich()
        self.assertEqual(self.d.file(p1, v)["state"], "NOT_COVERED")
        self.assertEqual(self.d.file(p1, v)["state"], "NOT_COVERED")
        c = self.d.case(v)
        self.assertEqual(c["attempts"], 2)
        self.assertEqual(self.d.stats()["counts"]["state:NOT_COVERED"], 1)
        self.assertEqual(self.d.w.view(self.d.sr, "get_pool_cases", p1, 0, 10)["total"], 1)

    def test_victim_listed_once_across_attempts(self):
        pid = self.pool()
        _, v, _ = self.c.sandwich()
        F.stub.WEB.down.add(F.RPCS[0])
        self.d.file(pid, v)
        F.stub.WEB.down.clear()
        self.d.file(pid, v)
        self.assertEqual(self.d.w.view(self.d.sr, "get_victim", F.VICTIM, 0, 10)["total"], 1)


CREATE_BAD = [
    ("NAME_REQUIRED", {"name": "  "}),
    ("POOL_BELOW_MINIMUM", {"value": 10 ** 15 - 1}),
    ("BAD_MAX_PER_SWAP", {"max_swap": 0}),
    ("BAD_MAX_PER_VICTIM", {"max_swap": 2 * GEN, "max_victim": GEN}),
    ("BAD_CLAIM_PERIOD", {"claim": 3599}),
    ("BAD_CLAIM_PERIOD", {"claim": 180 * 86400 + 1}),
    ("META_BAD_JSON", {"meta": "{"}),
    ("META_NOT_OBJECT", {"meta": "[1]"}),
    ("META_TOO_LONG", {"meta": json.dumps({"x": "a" * 700})}),
    ("KINDS_UNKNOWN", {"kinds": ("V4",)}),
    ("KINDS_EMPTY", {"kinds": ()}),
    ("ROUTERS_EMPTY", {"routers": ()}),
    ("ROUTERS_BAD_ADDRESS", {"routers": ("0x1234",)}),
    ("ROUTERS_BAD_ADDRESS", {"routers": ("0x" + "0" * 40,)}),
    ("ROUTERS_TOO_MANY", {"routers": tuple(F.addr(500 + i) for i in range(33))}),
    ("RANGES_BAD_BLOCKS", {"start": 100, "end": 99}),
    ("RANGES_BAD_BLOCKS", {"start": -1, "end": 99}),
    ("RANGES_TOO_LONG", {"start": 0, "end": 5000001}),
    ("RATES_EMPTY", {"rates": ()}),
    ("RATES_BAD_RATE", {"rates": ((F.WETH, 0, 1),)}),
    ("RATES_BAD_RATE", {"rates": ((F.WETH, 1, 0),)}),
    ("RATES_BAD_RATE", {"rates": ((F.WETH, 10 ** 31, 1),)}),
    ("RATES_BAD_TOKEN", {"rates": (("0xabc", 1, 1),)}),
    ("RATES_DUPLICATE_TOKEN", {"rates": ((F.WETH, 1, 1), (F.WETH, 2, 1))}),
    ("RATES_TOO_MANY", {"rates": tuple((F.addr(600 + i), 1, 1) for i in range(13))}),
]


def _create_bad(reason, kw):
    def t(self):
        before = self.d.stats()
        r = self.d.create(sender=F.SPONSOR, **kw)
        self.assertEqual(r["ok"], False)
        self.assertEqual(r["reason"], reason)
        after = self.d.stats()
        self.assertEqual(after["pools"], before["pools"])
        self.assertEqual(after["counts"]["create_refused"], before["counts"]["create_refused"] + 1)
        val = kw.get("value", 10 * GEN)
        self.assertEqual(self.d.w.view(self.d.sr, "get_credit", F.SPONSOR)["credit"], str(val))
        self.assertTrue(self.d.conserved())
    return t


class CreateRefusals(Base):
    def test_raw_terms_errors(self):
        for args, reason in (
                (("[]", "[]", "[]", "[]", "[]"), "CHAINS_EMPTY"),
                (("{", "[]", "[]", "[]", "[]"), "CHAINS_BAD_JSON"),
                (('["solana"]', "[]", "[]", "[]", "[]"), "UNSUPPORTED_CHAIN"),
                (('["ethereum"]', "x", "[]", "[]", "[]"), "ROUTERS_BAD_JSON"),
                (('["ethereum"]', '[1]', "[]", "[]", "[]"), "ROUTERS_BAD_ENTRY"),
                (('["ethereum"]', '[{"chain":"base","address":"%s"}]' % F.ROUTER, '["V2"]', "[]", "[]"),
                 "ROUTERS_CHAIN_NOT_IN_POOL"),
                (('["ethereum"]', '[{"chain":"ethereum","address":"%s"}]' % F.ROUTER, 'x', "[]", "[]"), "KINDS_BAD_JSON"),
                (('["ethereum"]', '[{"chain":"ethereum","address":"%s"}]' % F.ROUTER, '["V2"]', "x", "[]"),
                 "RANGES_BAD_JSON"),
                (('["ethereum"]', '[{"chain":"ethereum","address":"%s"}]' % F.ROUTER, '["V2"]', "[]", "[]"),
                 "RANGES_MISSING_CHAIN"),
                (('["ethereum"]', '[{"chain":"ethereum","address":"%s"}]' % F.ROUTER, '["V2"]', "[1]", "[]"),
                 "RANGES_BAD_ENTRY"),
                (('["ethereum"]', '[{"chain":"ethereum","address":"%s"}]' % F.ROUTER, '["V2"]',
                  '[{"chain":"ethereum","start_block":1,"end_block":2},{"chain":"ethereum","start_block":1,"end_block":2}]',
                  "[]"), "RANGES_DUPLICATE_CHAIN"),
                (('["ethereum"]', '[{"chain":"ethereum","address":"%s"}]' % F.ROUTER, '["V2"]',
                  '[{"chain":"base","start_block":1,"end_block":2}]', "[]"), "RANGES_CHAIN_NOT_IN_POOL"),
                (('["ethereum"]', '[{"chain":"ethereum","address":"%s"}]' % F.ROUTER, '["V2"]',
                  '[{"chain":"ethereum","start_block":1,"end_block":2}]', "x"), "RATES_BAD_JSON"),
                (('["ethereum"]', '[{"chain":"ethereum","address":"%s"}]' % F.ROUTER, '["V2"]',
                  '[{"chain":"ethereum","start_block":1,"end_block":2}]', "[1]"), "RATES_BAD_ENTRY"),
                (('["ethereum"]', '[{"chain":"ethereum","address":"%s"}]' % F.ROUTER, '["V2"]',
                  '[{"chain":"ethereum","start_block":1,"end_block":2}]',
                  '[{"chain":"base","token":"%s","num":"1","den":"1"}]' % F.WETH), "RATES_CHAIN_NOT_IN_POOL"),
                (('["ethereum"]', '[{"chain":"ethereum","address":"%s"}]' % F.ROUTER, '["V2"]',
                  '[{"chain":"ethereum","start_block":1,"end_block":2}]',
                  '[{"chain":"ethereum","token":"%s","num":"1","den":"1","decimals":99}]' % F.WETH), "RATES_BAD_DECIMALS")):
            r = self.d.w.call(self.d.sr, "create_pool", "p", *args, GEN, GEN, 3600, "", sender=F.SPONSOR, value=GEN)
            self.assertEqual(r["reason"], reason, args)
        self.assertEqual(self.d.stats()["pools"], 0)
        self.assertTrue(self.d.conserved())

    def test_no_clock_is_refused(self):
        self.d.w.now_iso = "garbage"
        r = self.d.create()
        self.assertEqual(r["reason"], "NO_CLOCK")

    def test_terms_are_frozen_and_normalized(self):
        pid = self.pool(routers=(F.ROUTER.upper().replace("0X", "0x"), F.ROUTER), kinds=("v3", "V2", "V2"))
        p = self.d.pool(pid)
        self.assertEqual([r["address"] for r in p["routers"]], [F.ROUTER])
        self.assertEqual(p["kinds"], ["V2", "V3"])
        self.assertEqual(p["chains"], ["ethereum"])
        self.assertEqual(p["status"], "OPEN")
        self.assertEqual(p["claim_deadline"], F.NOW + 7200)


for _i, (_reason, _kw) in enumerate(CREATE_BAD):
    setattr(CreateRefusals, "test_refuse_%02d_%s" % (_i, _reason.lower()), _create_bad(_reason, _kw))


class Lifecycle(Base):
    def test_top_up_adds(self):
        pid = self.pool(value=GEN)
        r = self.w.call(self.d.sr, "top_up", pid, sender=F.STRANGER, value=GEN // 2)
        self.assertTrue(r["ok"])
        p = self.d.pool(pid)
        self.assertEqual(p["balance"], str(3 * GEN // 2))
        self.assertEqual(p["funded"], str(3 * GEN // 2))
        self.assertTrue(self.d.conserved())

    def test_top_up_refusals_credit_back(self):
        pid = self.pool(value=GEN)
        for args, value, reason in (((99,), GEN, "NO_SUCH_POOL"), ((pid,), 0, "NO_VALUE")):
            r = self.w.call(self.d.sr, "top_up", *args, sender=F.STRANGER, value=value)
            self.assertEqual(r["reason"], reason)
        self.assertEqual(self.w.view(self.d.sr, "get_credit", F.STRANGER)["credit"], str(GEN))
        self.w.advance(7201)
        r = self.w.call(self.d.sr, "top_up", pid, sender=F.STRANGER, value=GEN)
        self.assertEqual(r["reason"], "CLAIM_PERIOD_OVER")
        self.w.call(self.d.sr, "close_pool", pid, sender=F.KEEPER)
        r = self.w.call(self.d.sr, "top_up", pid, sender=F.STRANGER, value=GEN)
        self.assertEqual(r["reason"], "POOL_IS_CLOSED")
        self.assertEqual(self.w.view(self.d.sr, "get_credit", F.STRANGER)["credit"], str(3 * GEN))
        self.assertTrue(self.d.conserved())

    def test_extend_only_sponsor_only_later(self):
        pid = self.pool()
        self.refused(self.w.call, self.d.sr, "extend", pid, F.NOW + 9000, sender=F.STRANGER, contains="ONLY_THE_SPONSOR")
        self.refused(self.w.call, self.d.sr, "extend", pid, F.NOW + 7200, sender=F.SPONSOR, contains="ONLY_MOVE_LATER")
        self.refused(self.w.call, self.d.sr, "extend", pid, F.NOW + 7200 + 180 * 86400 + 1, sender=F.SPONSOR,
                     contains="EXTENSION_TOO_LONG")
        self.refused(self.w.call, self.d.sr, "extend", 77, F.NOW + 9000, sender=F.SPONSOR, contains="NO_SUCH_POOL")
        r = self.w.call(self.d.sr, "extend", pid, F.NOW + 9000, sender=F.SPONSOR)
        self.assertEqual(r["claim_deadline"], F.NOW + 9000)
        self.assertEqual(self.d.pool(pid)["claim_deadline"], F.NOW + 9000)
        self.assertEqual(self.d.pool(pid)["original_deadline"], F.NOW + 7200)
        self.w.advance(9001)
        self.refused(self.w.call, self.d.sr, "extend", pid, F.NOW + 99000, sender=F.SPONSOR, contains="CLAIM_PERIOD_OVER")

    def test_no_cancel_method(self):
        for m in ("cancel", "cancel_pool", "withdraw", "withdraw_pool", "set_terms", "pause"):
            self.assertFalse(hasattr(SR.SandwichRefund, m), m)

    def test_close_before_deadline_refused(self):
        pid = self.pool()
        self.refused(self.w.call, self.d.sr, "close_pool", pid, sender=F.SPONSOR, contains="CLAIM_PERIOD_OPEN_UNTIL")
        self.w.advance(7200)
        self.refused(self.w.call, self.d.sr, "close_pool", pid, sender=F.SPONSOR, contains="CLAIM_PERIOD_OPEN_UNTIL")

    def test_close_returns_rest_to_sponsor(self):
        pid = self.pool(value=2 * GEN)
        _, v, _ = self.c.sandwich()
        self.d.file(pid, v)
        self.w.advance(7201)
        r = self.w.call(self.d.sr, "close_pool", pid, sender=F.STRANGER)
        self.assertEqual(int(r["returned"]), 2 * GEN - 3 * GEN // 10)
        self.assertEqual(self.d.paid_to(F.SPONSOR), 2 * GEN - 3 * GEN // 10)
        p = self.d.pool(pid)
        self.assertEqual(p["status"], "CLOSED")
        self.assertEqual(p["balance"], "0")
        self.assertEqual(p["closed_by"], F.STRANGER)
        self.assertEqual(int(p["refunded"]) + int(p["returned"]), int(p["funded"]))
        self.assertEqual(self.d.balance(), 0)
        self.assertTrue(self.d.conserved())
        self.refused(self.w.call, self.d.sr, "close_pool", pid, sender=F.STRANGER, contains="ALREADY_CLOSED")

    def test_close_empty_pool_sends_nothing(self):
        pid = self.pool(value=GEN // 10)
        _, v, _ = self.c.sandwich()
        self.d.file(pid, v)
        self.w.advance(7201)
        n = len(F.stub.TRANSFERS)
        r = self.w.call(self.d.sr, "close_pool", pid, sender=F.STRANGER)
        self.assertEqual(r["returned"], "0")
        self.assertEqual(len(F.stub.TRANSFERS), n)

    def test_filing_after_deadline_refused(self):
        pid = self.pool()
        _, v, _ = self.c.sandwich()
        self.w.advance(7201)
        self.refused(self.d.file, pid, v, contains="CLAIM_PERIOD_OVER")

    def test_filing_at_deadline_allowed(self):
        pid = self.pool()
        _, v, _ = self.c.sandwich()
        self.w.advance(7200)
        self.assertEqual(self.d.file(pid, v)["state"], "SANDWICHED_REFUNDED")

    def test_filing_on_closed_pool_refused(self):
        pid = self.pool()
        _, v, _ = self.c.sandwich()
        self.w.advance(7201)
        self.w.call(self.d.sr, "close_pool", pid, sender=F.STRANGER)
        self.refused(self.d.file, pid, v, contains="POOL_IS_CLOSED")

    def test_file_refusals(self):
        pid = self.pool()
        self.refused(self.d.file, 99, F.h32(1), contains="NO_SUCH_POOL")
        self.refused(self.d.file, pid, F.h32(1), chain="base", contains="CHAIN_NOT_IN_POOL")
        self.refused(self.d.file, pid, "0x1234", contains="BAD_HASH")
        self.refused(self.d.file, 0, F.h32(1), contains="NO_SUCH_POOL")
        self.assertEqual(self.d.stats()["cases"], 0)
        self.assertEqual(self.d.stats()["counts"]["filings"], 0)

    def test_extend_lets_late_cases_in(self):
        pid = self.pool()
        _, v, _ = self.c.sandwich()
        self.w.call(self.d.sr, "extend", pid, F.NOW + 10000, sender=F.SPONSOR)
        self.w.advance(9000)
        self.assertEqual(self.d.file(pid, v)["state"], "SANDWICHED_REFUNDED")

    def test_due_flag(self):
        pid = self.pool()
        self.assertEqual(self.d.pool(pid)["due"], "")
        self.w.advance(7201)
        self.assertEqual(self.d.pool(pid)["due"], "CLOSE")
        self.assertEqual(self.w.view(self.d.sr, "get_pools", 0, 10, self.w.now())["items"][0]["due"], "CLOSE")


class Credits(Base):
    def test_withdraw_refund(self):
        self.d.create(value=GEN, name="")
        r = self.w.call(self.d.sr, "withdraw_refund", sender=F.SPONSOR)
        self.assertEqual(r["withdrawn"], str(GEN))
        self.assertEqual(self.d.paid_to(F.SPONSOR), GEN)
        self.refused(self.w.call, self.d.sr, "withdraw_refund", sender=F.SPONSOR, contains="NOTHING_TO_WITHDRAW")
        self.assertTrue(self.d.conserved())
        self.assertEqual(self.d.balance(), 0)

    def test_sweep_stray(self):
        pid = self.pool(value=GEN)
        self.w.instances[self.d.sr].balance += 5      # value that arrived outside the payable methods
        r = self.w.call(self.d.sr, "sweep_stray", sender=F.STRANGER)
        self.assertEqual(r["swept"], "5")
        self.assertEqual(self.d.paid_to(F.DEPLOYER), 5)
        self.refused(self.w.call, self.d.sr, "sweep_stray", sender=F.STRANGER, contains="SENDS_MAY_BE_PENDING")

    def test_sweep_never_takes_pool_money(self):
        self.pool(value=GEN)
        self.refused(self.w.call, self.d.sr, "sweep_stray", sender=F.STRANGER, contains="NO_STRAY_BALANCE")

    def test_sweep_waits_after_a_send(self):
        pid = self.pool(value=GEN)
        _, v, _ = self.c.sandwich()
        self.d.file(pid, v)
        self.w.instances[self.d.sr].balance += 5
        self.refused(self.w.call, self.d.sr, "sweep_stray", sender=F.STRANGER, contains="SENDS_MAY_BE_PENDING")
        self.w.advance(172800)
        self.assertEqual(self.w.call(self.d.sr, "sweep_stray", sender=F.STRANGER)["swept"], "5")

    def test_non_payable_rejects_value(self):
        pid = self.pool()
        with self.assertRaises(world.Reverted):
            self.w.call(self.d.sr, "file_case", pid, "ethereum", F.h32(1), sender=F.KEEPER, value=1)


class Conservation(Base):
    def test_every_gen_has_an_exit(self):
        p1 = self.pool(value=GEN, max_swap=GEN // 5)
        p2 = self.pool(value=GEN // 10, sender=F.SPONSOR2)
        self.w.call(self.d.sr, "top_up", p1, sender=F.STRANGER, value=GEN // 3)
        self.d.create(value=GEN, name="")       # refused, credited
        vs = []
        for i in range(6):
            _, v, _ = self.c.sandwich(block=F.BLOCK + 3 * i, victim_from=F.addr(800 + i))
            vs.append(v)
        for i, v in enumerate(vs):
            self.d.file(p1 if i % 2 == 0 else p2, v)
            self.assertTrue(self.d.conserved())
        self.w.advance(7201)
        self.w.call(self.d.sr, "close_pool", p1, sender=F.KEEPER)
        self.w.call(self.d.sr, "close_pool", p2, sender=F.KEEPER)
        self.w.call(self.d.sr, "withdraw_refund", sender=F.SPONSOR)
        s = self.d.stats()
        self.assertEqual(s["held"], "0")
        self.assertEqual(self.d.balance(), 0)
        self.assertEqual(int(s["received_total"]),
                         int(s["refunded_total"]) + int(s["returned_total"]) + int(s["credit_paid_total"]))
        paid_out = sum(a for (_, a) in F.stub.TRANSFERS)
        self.assertEqual(paid_out, int(s["received_total"]))

    def test_refused_file_changes_nothing(self):
        pid = self.pool()
        _, v, _ = self.c.sandwich()
        self.d.file(pid, v)
        before = json.dumps(self.d.stats(), sort_keys=True)
        pb = json.dumps(self.d.pool(pid), sort_keys=True)
        for _ in range(3):
            try:
                self.d.file(pid, v)
            except world.Reverted:
                pass
        self.assertEqual(json.dumps(self.d.stats(), sort_keys=True), before)
        self.assertEqual(json.dumps(self.d.pool(pid), sort_keys=True), pb)

    def test_undetermined_round_commits_nothing(self):
        pid = self.pool()
        _, v, _ = self.c.sandwich()
        F.stub.FORGE["mutate"] = lambda r: (r["facts"]["swaps"][0].update({"n0": "1"}) or r)
        try:
            self.refused(self.d.file, pid, v, contains="UNDETERMINED")
        finally:
            F.stub.FORGE["mutate"] = None
        self.assertEqual(self.d.stats()["cases"], 0)
        self.assertEqual(self.d.paid_to(F.VICTIM), 0)


class RateLimit(Base):
    def test_per_sender_per_pool(self):
        pid = self.pool()
        n = SR.MODES["CANONICAL"][1]
        for i in range(n):
            self.d.file(pid, F.h32(("junk", i)))
        self.refused(self.d.file, pid, F.h32(("junk", n)), contains="RATE_LIMITED_UNTIL")
        self.d.file(pid, F.h32(("junk", n)), sender=F.STRANGER)
        self.w.advance(3600)
        self.d.file(pid, F.h32(("junk", n + 1)))


class Pagination(Base):
    def fill(self, n_pools=3, n_cases=7):
        pids = [self.pool(name="p%d" % i) for i in range(n_pools)]
        hs = []
        for i in range(n_cases):
            _, v, _ = self.c.sandwich(block=F.BLOCK + 3 * i, victim_from=F.VICTIM if i % 2 == 0 else F.VICTIM2)
            self.d.file(pids[i % n_pools], v)
            hs.append(v)
        return pids, hs

    def walk(self, fn, *args, limit=2):
        out = []
        off = 0
        pages = 0
        while off >= 0:
            pg = self.w.view(self.d.sr, fn, *args[:-1], off, limit, *args[-1:]) if fn == "get_pools" else \
                self.w.view(self.d.sr, fn, *args, off, limit)
            out += pg["items"]
            off = pg["next_offset"]
            pages += 1
            self.assertLess(pages, 100)
        return out

    def test_cases_all_pages(self):
        _, hs = self.fill()
        items = self.walk("get_cases")
        self.assertEqual([x["tx_hash"] for x in items], hs)
        self.assertEqual(items[0]["case_id"], 1)

    def test_pool_cases_pages(self):
        pids, hs = self.fill()
        got = []
        for p in pids:
            got += [x["tx_hash"] for x in self.walk("get_pool_cases", p)]
        self.assertEqual(sorted(got), sorted(hs))

    def test_victim_pages(self):
        _, hs = self.fill()
        v1 = self.walk("get_victim", F.VICTIM)
        v2 = self.walk("get_victim", F.VICTIM2)
        self.assertEqual(len(v1), 4)
        self.assertEqual(len(v2), 3)
        pg = self.w.view(self.d.sr, "get_victim", F.VICTIM, 0, 50)
        self.assertEqual(int(pg["refunded"]), sum(int(x["refund_paid"]) for x in v1))

    def test_pools_pages(self):
        pids, _ = self.fill(n_pools=5, n_cases=0)
        items = []
        off = 0
        while off >= 0:
            pg = self.w.view(self.d.sr, "get_pools", off, 2, self.w.now())
            items += pg["items"]
            off = pg["next_offset"]
        self.assertEqual([p["pool_id"] for p in items], pids)

    def test_attackers_pages(self):
        pid = self.pool()
        for i in range(5):
            _, v, _ = self.c.sandwich(block=F.BLOCK + 3 * i, attacker=F.addr(900 + i), bot=F.addr(950 + i))
            self.d.file(pid, v)
        _, v, _ = self.c.sandwich(block=F.BLOCK + 30, attacker=F.addr(900), bot=F.addr(950))
        self.d.file(pid, v)
        items = self.walk("get_attackers")
        self.assertEqual(len(items), 5)
        self.assertEqual(items[0]["n_cases"], 2)
        self.assertEqual(items[0]["address"], F.addr(900))
        self.assertEqual(items[0]["contract"], F.addr(950))

    def test_limits_clamped(self):
        self.fill(n_pools=1, n_cases=3)
        pg = self.w.view(self.d.sr, "get_cases", -5, 1000)
        self.assertEqual(pg["offset"], 0)
        self.assertEqual(pg["limit"], SR.PAGE_MAX)
        pg = self.w.view(self.d.sr, "get_cases", 0, 0)
        self.assertEqual(pg["limit"], 1)
        pg = self.w.view(self.d.sr, "get_cases", 99, 5)
        self.assertEqual(pg["items"], [])
        self.assertEqual(pg["next_offset"], -1)

    def test_missing_lookups(self):
        self.assertFalse(self.w.view(self.d.sr, "get_case", "ethereum", F.h32(5))["found"])
        self.assertFalse(self.w.view(self.d.sr, "get_case_by_id", 3)["found"])
        self.assertFalse(self.w.view(self.d.sr, "get_pool", 3, 0)["found"])
        self.assertFalse(self.w.view(self.d.sr, "get_pool_cases", 3, 0, 5)["found"])
        self.assertEqual(self.w.view(self.d.sr, "get_victim", "nope", 0, 5)["total"], 0)

    def test_case_view_has_every_field(self):
        pid = self.pool()
        _, v, _ = self.c.sandwich()
        self.d.file(pid, v)
        c = self.d.case(v)
        for k in ("case_id", "chain", "tx_hash", "pool_id", "filer", "filed_at", "attempts", "state", "final",
                  "verdict", "reason", "detail", "block", "tx_index", "victim", "router", "dex_pool", "facts",
                  "profit_token", "loss", "refund_due", "refund_paid", "limit", "attacker"):
            self.assertIn(k, c)
        p = self.d.pool(pid)
        for k in ("pool_id", "sponsor", "name", "status", "routers", "kinds", "ranges", "rates", "max_per_swap",
                  "max_per_victim", "claim_period_s", "created_at", "claim_deadline", "funded", "balance", "refunded",
                  "returned", "n_cases", "n_refunded", "n_unpaid", "history", "due"):
            self.assertIn(k, p)

    def test_stats_and_config(self):
        s = self.d.stats()
        for k in SR.COUNT_KEYS:
            self.assertIn(k, s["counts"])
        cfg = self.w.view(self.d.sr, "get_config")
        self.assertEqual(cfg["mode"], "CANONICAL")
        self.assertEqual(cfg["chains"]["ethereum"]["rpcs"], F.RPCS)


class Modes(unittest.TestCase):
    def test_demo_mode(self):
        d = F.Deployment(mode="DEMO")
        r = d.create(claim=60)
        self.assertTrue(r["ok"])
        self.assertEqual(d.w.view(d.sr, "get_config")["min_claim_period_s"], 60)

    def test_bad_mode(self):
        w = world.new_world()
        with self.assertRaises(Exception):
            w.deploy("SandwichRefund", "TEST")


if __name__ == "__main__":
    unittest.main()
