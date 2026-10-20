"""Attack round (docs/ATTACK_REPORT.md), contract layer: fake victims,
look-alike pools, inflated profit, junk griefing, duplicate filings, forged
consensus answers, and payouts that must not leak."""
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
        self.pid = self.d.create(value=5 * GEN)["pool_id"]

    def file(self, h, **kw):
        return self.d.file(self.pid, h, **kw)


class FakeVictims(Base):
    def test_a1_attacker_is_the_victim(self):
        _, v, _ = self.c.sandwich(victim_from=F.ATTACKER)
        r = self.file(v)
        self.assertEqual(r["state"], "UNCLEAR")
        self.assertEqual(self.d.paid_to(F.ATTACKER), 0)

    def test_a1_victim_swap_pays_attacker_contract(self):
        _, v, _ = self.c.sandwich(victim_recipient=F.BOT)
        self.assertEqual(self.file(v)["reason"], "SELF_SANDWICH")

    def test_a1_attacker_swap_pays_victim_eoa(self):
        self.c.tx(F.BLOCK, F.ATTACKER, F.BOT, [(F.POOL_V2, 10 * ETH, -1000 * ETH, F.VICTIM)])
        v = self.c.tx(F.BLOCK, F.VICTIM, F.ROUTER, [(F.POOL_V2, 5 * ETH, -450 * ETH, F.TRADER)])
        self.c.tx(F.BLOCK, F.ATTACKER, F.BOT, [(F.POOL_V2, -10 * ETH - ETH // 100, 1000 * ETH, F.VICTIM)])
        self.assertEqual(self.file(v)["reason"], "SELF_SANDWICH")

    def test_a1_victim_eoa_is_the_attacker_contract(self):
        # the "victim" transaction is sent by the bot address itself
        _, v, _ = self.c.sandwich(victim_from=F.BOT)
        self.assertEqual(self.file(v)["state"], "UNCLEAR")
        self.assertEqual(self.d.paid_to(F.BOT), 0)

    def test_a1_back_run_from_victim(self):
        self.c.tx(F.BLOCK, F.ATTACKER, F.BOT, [(F.POOL_V2, 10 * ETH, -1000 * ETH, F.BOT)])
        v = self.c.tx(F.BLOCK, F.VICTIM, F.ROUTER, [(F.POOL_V2, 5 * ETH, -450 * ETH, F.VICTIM)])
        self.c.tx(F.BLOCK, F.VICTIM, F.BOT, [(F.POOL_V2, -10 * ETH - ETH // 100, 1000 * ETH, F.BOT)])
        self.assertEqual(self.file(v)["state"], "UNCLEAR")
        self.assertEqual(self.d.paid_to(F.VICTIM), 0)

    def test_a1_unlinked_wallet_is_bounded_by_caps(self):
        d = F.Deployment()
        pid = d.create(value=5 * GEN, max_swap=GEN // 10, max_victim=GEN // 10)["pool_id"]
        total = 0
        for i in range(3):
            _, v, _ = d.chain.sandwich(block=F.BLOCK + 3 * i, back=(1000 * ETH, 20 * ETH))
            total += int(d.file(pid, v)["refund"])
        self.assertEqual(total, GEN // 10)       # one address: never above max_per_victim


class LookAlikes(Base):
    def test_a2_pool_with_fake_factory_claim(self):
        _, v, _ = self.c.sandwich(pool=F.POOL_FAKE)
        r = self.file(v)
        self.assertEqual(r["reason"], "POOL_NOT_CANONICAL")
        self.assertEqual(self.d.paid_to(F.VICTIM), 0)

    def test_a2_pool_of_unlisted_factory(self):
        _, v, _ = self.c.sandwich(pool=F.POOL_ALIEN)
        self.assertEqual(self.file(v)["reason"], "POOL_NOT_CANONICAL")

    def test_a2_factory_returns_garbage(self):
        _, v, _ = self.c.sandwich()
        pad = lambda a: "0" * 24 + a[2:]
        self.c.c.calls[(F.V2F, "0xe6a43905" + pad(F.WETH) + pad(F.TOKEN))] = "0x1234"
        self.assertEqual(self.file(v)["reason"], "POOL_NOT_CANONICAL")

    def test_a2_pool_token_call_reverts(self):
        _, v, _ = self.c.sandwich()
        self.c.c.calls[(F.POOL_V2, "0x0dfe1681")] = F.stub.MockChain.REVERT
        self.assertEqual(self.file(v)["state"], "UNVERIFIABLE")

    def test_a2_lookalike_logs_inside_a_real_pool_block(self):
        # a fake pool emitting Swap events with the real pool's numbers does not count for the real pool
        self.c.tx(F.BLOCK, F.ATTACKER, F.BOT, [(F.POOL_FAKE, 10 * ETH, -1000 * ETH, F.BOT)])
        v = self.c.tx(F.BLOCK, F.VICTIM, F.ROUTER, [(F.POOL_V2, 5 * ETH, -450 * ETH, F.VICTIM)])
        self.c.tx(F.BLOCK, F.ATTACKER, F.BOT, [(F.POOL_FAKE, -10 * ETH - ETH, 1000 * ETH, F.BOT)])
        self.assertEqual(self.file(v)["state"], "CLEAN")

    def test_a2_event_with_wrong_topic_count_ignored(self):
        v = self.c.tx(F.BLOCK, F.VICTIM, F.ROUTER, [(F.POOL_V2, 5 * ETH, -450 * ETH, F.VICTIM)])
        lg = dict(self.c.c.txs[v]["receipt"]["logs"][0])
        lg["topics"] = lg["topics"][:2]
        self.c.c.txs[v]["receipt"]["logs"] = [lg]
        self.assertEqual(self.file(v)["reason"], "NO_SWAP_IN_TX")

    def test_a2_v3_event_on_a_v2_pool_ignored(self):
        self.c.tx(F.BLOCK, F.ATTACKER, F.BOT, [(F.POOL_V2, 10 * ETH, -1000 * ETH, F.BOT, F.BOT, "V3")])
        v = self.c.tx(F.BLOCK, F.VICTIM, F.ROUTER, [(F.POOL_V2, 5 * ETH, -450 * ETH, F.VICTIM)])
        self.c.tx(F.BLOCK, F.ATTACKER, F.BOT, [(F.POOL_V2, -10 * ETH - ETH, 1000 * ETH, F.BOT, F.BOT, "V3")])
        self.assertEqual(self.file(v)["state"], "CLEAN")


class Inflation(Base):
    def test_a3_fee_on_transfer_profit_token_unpriced(self):
        # FOT/WETH pool, victim sells FOT (X = FOT): profit in FOT is not priced
        _, v, _ = self.c.sandwich(pool=F.POOL_FOT, d=0, front=(1000 * ETH, 10 * ETH), victim=(400 * ETH, 3 * ETH),
                                  back=(10 * ETH, 1100 * ETH))
        r = self.file(v)
        self.assertEqual(r["reason"], "PROFIT_TOKEN_NOT_PRICED")
        self.assertEqual(self.d.paid_to(F.VICTIM), 0)

    def test_a3_fee_on_transfer_y_side_counts_only_weth(self):
        # victim pays WETH (X = WETH, token1) for FOT: profit measured in WETH as the pool paid it
        _, v, _ = self.c.sandwich(pool=F.POOL_FOT, d=1, front=(10 * ETH, 1000 * ETH), victim=(3 * ETH, 280 * ETH),
                                  back=(950 * ETH, 10 * ETH + ETH // 100))
        r = self.file(v)
        self.assertEqual(r["state"], "SANDWICHED_REFUNDED")
        self.assertEqual(r["loss"], str(ETH // 100))
        self.assertEqual(self.d.case(v)["profit_token"], F.WETH)

    def test_a3_huge_amounts_capped(self):
        _, v, _ = self.c.sandwich(front=(10 ** 30, 10 ** 30), victim=(5, 4), back=(10 ** 30, 10 ** 32))
        r = self.file(v)
        self.assertEqual(int(r["refund"]), GEN)          # max per swap
        self.assertTrue(self.d.conserved())

    def test_a3_amount_words_at_the_limit(self):
        v = self.c.tx(F.BLOCK, F.VICTIM, F.ROUTER, [(F.POOL_V3, 2 ** 255 - 1, -(2 ** 255), F.VICTIM)])
        r = self.file(v)
        self.assertIn(r["state"], ("CLEAN", "UNCLEAR"))


class Griefing(Base):
    def test_a4_junk_hashes_cost_the_pool_nothing(self):
        for i in range(20):
            self.assertEqual(self.file(F.h32(("junk", i)), sender=F.STRANGER)["state"], "UNVERIFIABLE")
        p = self.d.pool(self.pid)
        self.assertEqual(p["balance"], str(5 * GEN))
        self.assertEqual(self.d.stats()["counts"]["state:UNVERIFIABLE"], 20)

    def test_a4_junk_is_rate_limited(self):
        n = SR.MODES["CANONICAL"][1]
        for i in range(n):
            self.file(F.h32(("j", i)), sender=F.STRANGER)
        with self.assertRaises(world.Reverted) as e:
            self.file(F.h32(("j", n)), sender=F.STRANGER)
        self.assertIn("RATE_LIMITED", e.exception.msg)

    def test_a4_filing_a_real_case_unfinalized_does_not_lock_it(self):
        _, v, _ = self.c.sandwich()
        self.c.c.finalized = F.BLOCK
        self.assertEqual(self.file(v, sender=F.STRANGER)["state"], "UNVERIFIABLE")
        self.c.c.finalized = F.FINALIZED
        self.assertEqual(self.file(v)["state"], "SANDWICHED_REFUNDED")

    def test_a4_rpc_outage_does_not_lock_a_case(self):
        _, v, _ = self.c.sandwich()
        F.stub.WEB.down.add("*")
        self.assertEqual(self.file(v, sender=F.STRANGER)["state"], "UNVERIFIABLE")
        F.stub.WEB.down.clear()
        self.assertEqual(self.file(v)["state"], "SANDWICHED_REFUNDED")

    def test_a4_tiny_pool_cannot_lock_victims(self):
        tiny = self.d.create(value=10 ** 15, sender=F.STRANGER, max_swap=1, max_victim=1)["pool_id"]
        _, v, _ = self.c.sandwich()
        self.d.file(tiny, v, sender=F.STRANGER)
        self.assertEqual(self.file(v)["state"], "SANDWICHED_REFUNDED")
        self.assertEqual(self.w.view(self.d.gate, "check_case", "ethereum", v)["refund_paid"], str(3 * GEN // 10))


class Duplicates(Base):
    def test_a5_same_case_twice(self):
        _, v, _ = self.c.sandwich()
        self.file(v)
        with self.assertRaises(world.Reverted):
            self.file(v, sender=F.STRANGER)
        self.assertEqual(self.d.paid_to(F.VICTIM), 3 * GEN // 10)
        self.assertEqual(self.d.stats()["counts"]["refunds"], 1)

    def test_a5_hash_spelling_variants_are_one_case(self):
        _, v, _ = self.c.sandwich()
        self.file(v.upper().replace("0X", "0x"))
        with self.assertRaises(world.Reverted):
            self.file(" " + v + " ")
        self.assertEqual(self.d.stats()["cases"], 1)

    def test_a5_chain_spelling(self):
        _, v, _ = self.c.sandwich()
        self.d.file(self.pid, v, chain="Ethereum")
        with self.assertRaises(world.Reverted):
            self.d.file(self.pid, v, chain="ETHEREUM ")


class Forgery(Base):
    def forge(self, fn):
        F.stub.FORGE["mutate"] = fn

    def tearDown(self):
        F.stub.FORGE["mutate"] = None
        F.stub.FORGE["payload"] = None

    def test_a6_leader_inflates_profit(self):
        _, v, _ = self.c.sandwich()

        def m(r):
            for s in r["facts"]["swaps"]:
                if s["tx"] != v and int(s["n0"]) < 0:
                    s["n0"] = str(int(s["n0"]) * 100)
            return r
        self.forge(m)
        with self.assertRaises(world.Reverted) as e:
            self.file(v)
        self.assertIn("UNDETERMINED", e.exception.msg)
        self.assertEqual(self.d.paid_to(F.VICTIM), 0)

    def test_a6_leader_claims_unreadable_for_a_readable_case(self):
        _, v, _ = self.c.sandwich()
        F.stub.FORGE["payload"] = {"reason": "RPC_UNREADABLE", "detail": "x"}
        with self.assertRaises(world.Reverted):
            self.file(v)

    def test_a6_leader_swaps_the_victim(self):
        _, v, _ = self.c.sandwich()
        self.forge(lambda r: (r["facts"]["tx"].update({"from": F.STRANGER}) or r))
        with self.assertRaises(world.Reverted):
            self.file(v)
        self.assertEqual(self.d.paid_to(F.STRANGER), 0)

    def test_a6_leader_claims_unfinalized_is_harmless(self):
        _, v, _ = self.c.sandwich()
        self.forge(lambda r: (r["facts"].update({"final": False}) or r))
        self.assertEqual(self.file(v)["state"], "UNVERIFIABLE")
        self.tearDown()
        self.assertEqual(self.file(v)["state"], "SANDWICHED_REFUNDED")

    def test_a6_leader_claims_final_too_early(self):
        _, v, _ = self.c.sandwich(block=F.FINALIZED)
        self.forge(lambda r: r)
        r = self.file(v)
        self.assertEqual(r["state"], "UNVERIFIABLE")

    def test_a6_garbage_payload(self):
        _, v, _ = self.c.sandwich()
        for p in ([1], "x", 5, {"facts": 3}, {"facts": {"final": True}}):
            F.stub.FORGE["payload"] = p
            with self.assertRaises(world.Reverted):
                self.file(v)
        self.assertEqual(self.d.stats()["cases"], 0)


class Leaks(Base):
    def test_a7_only_three_exits(self):
        names = [n for n in dir(SR.SandwichRefund) if not n.startswith("_")]
        src = (F.world.ROOT / "build" / "SandwichRefund.py").read_text()
        self.assertEqual(src.count("emit_call("), 1)
        self.assertNotIn("emit_transfer", src.split("def _send")[1].split("def ")[0])
        self.assertEqual(src.count("self._send("), 4)    # refund, close, credit, stray

    def test_a7_no_model_no_owner(self):
        src = (F.world.ROOT / "build" / "SandwichRefund.py").read_text()
        for bad in ("exec_prompt", "web.render", "self.owner", "set_rate", "def pause"):
            self.assertNotIn(bad, src)

    def test_a7_payout_to_victim_only(self):
        _, v, _ = self.c.sandwich()
        self.file(v, sender=F.STRANGER)
        self.assertEqual([to for (to, _) in F.stub.TRANSFERS], [F.VICTIM])


if __name__ == "__main__":
    unittest.main()
