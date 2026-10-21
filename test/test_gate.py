"""MEVGate: structured states per case and per address, read from the
registry, never clean or refunded on missing or inconsistent data."""
import json
import unittest

import fixtures as F
import world
from fixtures import ETH, GEN

GT = F.GT
H = F.h32("gatecase")


def good(**over):
    c = {"found": True, "chain": "ethereum", "tx_hash": H, "state": "SANDWICHED_REFUNDED", "final": True,
         "refund_paid": "5", "loss": "10", "refund_due": "100", "case_id": 1, "pool_id": 1, "victim": F.VICTIM,
         "attacker": F.ATTACKER, "profit_token": F.WETH, "reason": "SAME_POOL_SANDWICH", "pools_on_chain": 1}
    c.update(over)
    return c


class CaseStatePure(unittest.TestCase):
    def st(self, raw):
        return GT.case_state(raw, "ethereum", H, 1, F.SPONSOR)

    def test_refunded(self):
        s = self.st(good())
        self.assertEqual(s["state"], "SANDWICHED_REFUNDED")
        self.assertTrue(s["refunded"])
        self.assertFalse(s["clean"])
        self.assertTrue(s["final"])

    def test_clean(self):
        s = self.st(good(state="CLEAN", refund_paid="0", loss="0", refund_due="0", attacker=""))
        self.assertTrue(s["clean"])
        self.assertFalse(s["refunded"])

    def test_unpaid(self):
        s = self.st(good(state="SANDWICHED_UNPAID", refund_paid="0"))
        self.assertEqual(s["state"], "SANDWICHED_UNPAID")
        self.assertFalse(s["refunded"])
        self.assertFalse(s["clean"])

    def test_unclear(self):
        s = self.st(good(state="UNCLEAR", refund_paid="0", loss="0", attacker=""))
        self.assertEqual(s["state"], "UNCLEAR")
        self.assertFalse(s["clean"] or s["refunded"])

    def test_not_covered_and_unverifiable_not_final(self):
        for st in ("NOT_COVERED", "UNVERIFIABLE"):
            s = self.st(good(state=st, final=False, refund_paid="0", loss="0", attacker=""))
            self.assertEqual(s["state"], st)
            self.assertFalse(s["final"] or s["clean"] or s["refunded"])

    def test_not_filed(self):
        s = self.st({"found": False})
        self.assertEqual(s["state"], "UNVERIFIABLE")
        self.assertIn("filed", s["why"])

    def test_another_pools_decision_is_refused(self):
        s = self.st(good(pool_id=2))
        self.assertEqual(s["state"], "UNVERIFIABLE")
        self.assertFalse(s["refunded"])

    def test_expired_is_final_not_favorable(self):
        s = self.st(good(state="EXPIRED", refund_paid="0", loss="0", attacker=""))
        self.assertEqual(s["state"], "EXPIRED")
        self.assertTrue(s["final"])
        self.assertFalse(s["clean"] or s["refunded"])


BAD = [
    ("none", None),
    ("number", 5),
    ("bad json", "{"),
    ("list", [1, 2]),
    ("found missing", {k: v for k, v in good().items() if k != "found"}),
    ("found string", good(found="true")),
    ("other hash", good(tx_hash=F.h32("x"))),
    ("other chain", good(chain="base")),
    ("unknown state", good(state="SAFE")),
    ("negative paid", good(refund_paid="-1")),
    ("paid not number", good(refund_paid="abc")),
    ("loss missing", {k: v for k, v in good().items() if k != "loss"}),
    ("case id zero", good(case_id=0)),
    ("pool id zero", good(pool_id=0)),
    ("other pool", good(pool_id=7)),
    ("final missing", {k: v for k, v in good().items() if k != "final"}),
    ("final contradicts", good(final=False)),
    ("refunded zero", good(refund_paid="0")),
    ("refunded no loss", good(loss="0")),
    ("refunded no victim", good(victim="")),
    ("refunded no attacker", good(attacker="")),
    ("clean with payout", good(state="CLEAN", refund_paid="5", loss="0", attacker="")),
    ("clean with loss", good(state="CLEAN", refund_paid="0", loss="5", attacker="")),
    ("clean without victim", good(state="CLEAN", refund_paid="0", loss="0", attacker="", victim="")),
    ("unpaid with payout", good(state="SANDWICHED_UNPAID", refund_paid="5")),
    ("unclear with payout", good(state="UNCLEAR", refund_paid="3", loss="0", attacker="")),
    ("not covered final", good(state="NOT_COVERED", final=True, refund_paid="0", loss="0")),
    ("bool paid", good(refund_paid=True)),
]


def _bad(raw):
    def t(self):
        s = GT.case_state(raw, "ethereum", H, 1, F.SPONSOR)
        self.assertEqual(s["state"], "UNVERIFIABLE", s)
        self.assertFalse(s["clean"])
        self.assertFalse(s["refunded"])
        self.assertFalse(s["final"])
    return t


for _i, (_n, _raw) in enumerate(BAD):
    setattr(CaseStatePure, "test_malformed_%02d_%s" % (_i, _n.replace(" ", "_")), _bad(_raw))


def vpage(items, total=None, address=F.VICTIM, pool_id=1):
    return {"pool_id": pool_id, "address": address, "total": len(items) if total is None else total, "items": items}


class PoolCheckPure(unittest.TestCase):
    def pool(self, **over):
        p = {"found": True, "pool_id": 1, "sponsor": F.SPONSOR, "chains": ["ethereum"]}
        p.update(over)
        return p

    def test_ok(self):
        self.assertIsNone(GT.pool_check(self.pool(), 1, F.SPONSOR, "ethereum"))

    def test_no_pool(self):
        self.assertEqual(GT.pool_check({"found": False}, 1, F.SPONSOR, "ethereum")[0], "NO_POOL")

    def test_wrong_sponsor(self):
        self.assertEqual(GT.pool_check(self.pool(sponsor=F.STRANGER), 1, F.SPONSOR, "ethereum")[0], "UNVERIFIABLE")

    def test_wrong_id(self):
        self.assertEqual(GT.pool_check(self.pool(pool_id=2), 1, F.SPONSOR, "ethereum")[0], "UNVERIFIABLE")

    def test_chain_not_covered(self):
        self.assertEqual(GT.pool_check(self.pool(), 1, F.SPONSOR, "base")[0], "NOT_COVERED")

    def test_nothing_named(self):
        self.assertEqual(GT.pool_check(self.pool(), 0, F.SPONSOR, "ethereum")[0], "UNVERIFIABLE")
        self.assertEqual(GT.pool_check(self.pool(), 1, "", "ethereum")[0], "UNVERIFIABLE")

    def test_garbage(self):
        for raw in (None, 5, "x", [], {"found": "yes"}, self.pool(chains="ethereum"), self.pool(sponsor="nope")):
            self.assertIsNotNone(GT.pool_check(raw, 1, F.SPONSOR, "ethereum"), raw)


class AddressStatePure(unittest.TestCase):
    def item(self, state, paid="0", loss="0", n=0):
        it = good(state=state, final=state in GT.FINAL, refund_paid=paid, loss=loss, tx_hash=F.h32(("a", n)))
        if state not in ("SANDWICHED_REFUNDED", "SANDWICHED_UNPAID"):
            it["attacker"] = ""
        del it["found"]
        return it

    def st(self, pages):
        return GT.address_state(pages, F.VICTIM, 1, F.SPONSOR)

    def test_no_cases_is_unverifiable(self):
        s = self.st([vpage([])])
        self.assertEqual(s["state"], "UNVERIFIABLE")
        self.assertFalse(s["clean"])

    def test_all_clean(self):
        s = self.st([vpage([self.item("CLEAN", n=1), self.item("CLEAN", n=2)])])
        self.assertEqual(s["state"], "CLEAN")
        self.assertTrue(s["clean"])

    def test_worst_state_wins(self):
        items = [self.item("CLEAN", n=1), self.item("SANDWICHED_REFUNDED", "5", "9", n=2),
                 self.item("SANDWICHED_UNPAID", "0", "9", n=3)]
        s = self.st([vpage(items)])
        self.assertEqual(s["state"], "SANDWICHED_UNPAID")
        self.assertEqual(s["refunded"], "5")
        self.assertEqual(s["loss_cases"], 2)

    def test_severity_order(self):
        order = list(GT.SEVERITY)
        for i, st in enumerate(order):
            items = [self.item(x, "5" if x == "SANDWICHED_REFUNDED" else "0",
                               "9" if x.startswith("SANDWICHED") else "0", n=j) for j, x in enumerate(order[i:])]
            for it in items:
                if it["state"] in ("NOT_COVERED", "UNVERIFIABLE"):
                    it["final"] = False
            self.assertEqual(self.st([vpage(items)])["state"], st)

    def test_not_every_case_read(self):
        self.assertEqual(self.st([vpage([self.item("CLEAN")], total=2)])["state"], "UNVERIFIABLE")

    def test_page_of_another_pool(self):
        self.assertEqual(self.st([vpage([self.item("CLEAN")], pool_id=2)])["state"], "UNVERIFIABLE")

    def test_case_of_another_pool(self):
        it = self.item("CLEAN")
        it["pool_id"] = 2
        self.assertEqual(self.st([vpage([it])])["state"], "UNVERIFIABLE")

    def test_other_address_page(self):
        self.assertEqual(self.st([vpage([self.item("CLEAN")], address=F.VICTIM2)])["state"], "UNVERIFIABLE")

    def test_case_of_another_victim(self):
        it = self.item("CLEAN")
        it["victim"] = F.VICTIM2
        self.assertEqual(self.st([vpage([it])])["state"], "UNVERIFIABLE")

    def test_inconsistent_case(self):
        it = self.item("CLEAN")
        it["refund_paid"] = "7"
        s = self.st([vpage([it])])
        self.assertEqual(s["state"], "UNVERIFIABLE")
        self.assertIn("inconsistent", s["why"])

    def test_garbage_pages(self):
        for pg in (None, 5, "x", {"address": F.VICTIM}, {"pool_id": 1, "address": F.VICTIM, "items": "x", "total": 1},
                   {"pool_id": 1, "address": F.VICTIM, "items": [5], "total": 1},
                   {"pool_id": 1, "address": F.VICTIM, "items": [], "total": -1}):
            s = self.st([pg])
            self.assertEqual(s["state"], "UNVERIFIABLE", pg)
            self.assertFalse(s["clean"])


class GateOnChain(unittest.TestCase):
    def setUp(self):
        self.d = F.Deployment()
        self.c = self.d.chain
        self.w = self.d.w

    def check(self, h, pid=1, sponsor=F.SPONSOR, chain="ethereum"):
        return self.w.view(self.d.gate, "check_case", pid, sponsor, chain, h)

    def test_no_pool(self):
        self.assertEqual(self.check(H)["state"], "NO_POOL")
        self.d.create()
        self.assertEqual(self.check(H)["state"], "UNVERIFIABLE")
        self.assertEqual(self.check(H, pid=2)["state"], "NO_POOL")
        self.assertEqual(self.w.view(self.d.gate, "check_address", 1, F.SPONSOR, F.VICTIM)["state"], "UNVERIFIABLE")

    def test_every_registry_state_maps(self):
        pid = self.d.create(value=GEN // 5)["pool_id"]
        _, v1, _ = self.c.sandwich(block=F.BLOCK)
        _, v2, _ = self.c.sandwich(block=F.BLOCK + 3)
        clean = self.c.tx(F.BLOCK + 6, F.VICTIM, F.ROUTER, [(F.POOL_V2, ETH, -90 * ETH, F.VICTIM)])
        _, unclear, _ = self.c.sandwich(block=F.BLOCK + 9, back=(1000 * ETH, 9 * ETH))
        _, nc, _ = self.c.sandwich(block=F.BLOCK + 12, router=F.ROUTER_X)
        for h in (v1, v2, clean, unclear, nc, F.h32("missing")):
            self.d.file(pid, h)
        want = {v1: "SANDWICHED_REFUNDED", v2: "SANDWICHED_UNPAID", clean: "CLEAN", unclear: "UNCLEAR",
                nc: "NOT_COVERED", F.h32("missing"): "UNVERIFIABLE"}
        for h, st in want.items():
            s = self.check(h, pid)
            self.assertEqual(s["state"], st)
            self.assertEqual(s["clean"], st == "CLEAN")
            self.assertEqual(s["refunded"], st == "SANDWICHED_REFUNDED")
            self.assertEqual(self.w.view(self.d.gate, "is_clean", pid, F.SPONSOR, "ethereum", h), st == "CLEAN")
            self.assertEqual(self.w.view(self.d.gate, "was_refunded", pid, F.SPONSOR, "ethereum", h), st == "SANDWICHED_REFUNDED")
        a = self.w.view(self.d.gate, "check_address", pid, F.SPONSOR, F.VICTIM)
        self.assertEqual(a["state"], "SANDWICHED_UNPAID")
        self.assertEqual(a["cases"], 5)
        self.assertEqual(int(a["refunded"]), GEN // 5)

    def test_chain_not_covered_by_the_pool(self):
        self.d.create()
        self.assertEqual(self.check(H, chain="base")["state"], "NOT_COVERED")

    def test_bad_hash(self):
        self.d.create()
        self.assertEqual(self.check("0x12")["state"], "UNVERIFIABLE")
        self.assertFalse(self.w.view(self.d.gate, "is_clean", 1, F.SPONSOR, "ethereum", "0x12"))

    def test_address_pagination_beyond_one_page(self):
        pid = self.d.create(value=100 * GEN, max_swap=GEN, max_victim=100 * GEN)["pool_id"]
        for i in range(55):
            v = self.c.tx(F.BLOCK + i, F.VICTIM, F.ROUTER, [(F.POOL_V2, ETH, -90 * ETH, F.VICTIM)])
            self.d.file(pid, v, sender=F.addr(3000 + i))
        a = self.w.view(self.d.gate, "check_address", pid, F.SPONSOR, F.VICTIM)
        self.assertEqual(a["cases"], 55)
        self.assertEqual(a["state"], "CLEAN")
        self.assertTrue(a["clean"])

    def test_registry_unreadable(self):
        g = self.w.deploy("MEVGate", "0x" + "9" * 40, sender=F.DEPLOYER)
        self.assertEqual(self.w.view(g, "check_case", 1, F.SPONSOR, "ethereum", H)["state"], "UNVERIFIABLE")
        self.assertEqual(self.w.view(g, "check_address", 1, F.SPONSOR, F.VICTIM)["state"], "UNVERIFIABLE")

    def test_attest(self):
        pid = self.d.create()["pool_id"]
        _, v, _ = self.c.sandwich()
        self.d.file(pid, v)
        r = self.w.call(self.d.gate, "attest_case", pid, F.SPONSOR, "ethereum", v, sender=F.STRANGER)
        self.assertEqual(r["state"], "SANDWICHED_REFUNDED")
        a = self.w.view(self.d.gate, "latest_attestation", pid, "ethereum", v)
        self.assertTrue(a["found"])
        self.assertEqual((a["pool_id"], a["sponsor"]), (pid, F.SPONSOR))
        self.assertEqual(a["read"]["victim"], F.VICTIM)
        self.assertEqual(self.w.view(self.d.gate, "get_attestations", 0, 10)["total"], 1)
        self.assertFalse(self.w.view(self.d.gate, "latest_attestation", pid, "ethereum", H)["found"])
        self.assertFalse(self.w.view(self.d.gate, "get_attestation", 5)["found"])

    def test_no_unbound_views(self):
        import inspect
        for name in ("check_case", "is_clean", "was_refunded", "check_address", "attest_case"):
            params = list(inspect.signature(getattr(GT.MEVGate, name)).parameters)
            self.assertEqual(params[1:3], ["pool_id", "sponsor"], name)

    def test_constructor_needs_an_address(self):
        with self.assertRaises(Exception):
            self.w.deploy("MEVGate", "nope", sender=F.DEPLOYER)

    def test_gate_never_moves_value(self):
        self.d.create()
        n = len(F.stub.TRANSFERS)
        self.w.call(self.d.gate, "attest_case", 1, F.SPONSOR, "ethereum", H, sender=F.STRANGER)
        self.assertEqual(len(F.stub.TRANSFERS), n)
        self.assertEqual(self.w.view(self.d.gate, "get_config")["registry"], self.d.sr)


class Copycat(unittest.TestCase):
    """A copycat pool (same name and terms, another sponsor) decides the same
    swap; a consumer bound to the real (pool, sponsor) never reads it."""

    def setUp(self):
        self.d = F.Deployment()
        self.c = self.d.chain
        self.w = self.d.w
        self.real = self.d.create(name="WalletCo refunds", value=GEN)["pool_id"]
        self.fake = self.d.create(name="WalletCo refunds", value=10 ** 15, sender=F.STRANGER, max_swap=1, max_victim=1)["pool_id"]

    def gate(self, fn, *a):
        return self.w.view(self.d.gate, fn, *a)

    def test_copycat_refund_is_not_the_sponsors(self):
        _, v, _ = self.c.sandwich()
        self.d.file(self.fake, v, sender=F.STRANGER)          # 1 wei "refund" from the copycat
        s = self.gate("check_case", self.real, F.SPONSOR, "ethereum", v)
        self.assertEqual(s["state"], "UNVERIFIABLE")
        self.assertFalse(s["refunded"])
        self.assertFalse(self.gate("was_refunded", self.real, F.SPONSOR, "ethereum", v))

    def test_copycat_id_with_the_real_sponsor_named(self):
        _, v, _ = self.c.sandwich()
        self.d.file(self.fake, v, sender=F.STRANGER)
        s = self.gate("check_case", self.fake, F.SPONSOR, "ethereum", v)
        self.assertEqual(s["state"], "UNVERIFIABLE")
        self.assertIn("not sponsored by the named sponsor", s["why"])
        self.assertFalse(s["refunded"])

    def test_copycat_clean_does_not_make_a_swap_clean(self):
        v = self.c.tx(F.BLOCK, F.VICTIM, F.ROUTER, [(F.POOL_V2, ETH, -90 * ETH, F.VICTIM)])
        self.d.file(self.fake, v, sender=F.STRANGER)
        self.assertFalse(self.gate("is_clean", self.real, F.SPONSOR, "ethereum", v))
        self.assertFalse(self.gate("is_clean", self.fake, F.SPONSOR, "ethereum", v))
        self.assertTrue(self.gate("is_clean", self.fake, F.STRANGER, "ethereum", v))   # only for whoever trusts the copycat

    def test_real_pool_reads_its_own_decision(self):
        _, v, _ = self.c.sandwich()
        self.d.file(self.fake, v, sender=F.STRANGER)
        self.d.file(self.real, v)
        s = self.gate("check_case", self.real, F.SPONSOR, "ethereum", v)
        self.assertEqual(s["state"], "SANDWICHED_REFUNDED")
        self.assertEqual(s["refund_paid"], str(3 * GEN // 10))
        self.assertEqual(s["pool_id"], self.real)

    def test_address_view_counts_only_the_named_pool(self):
        _, v1, _ = self.c.sandwich(block=F.BLOCK)
        _, v2, _ = self.c.sandwich(block=F.BLOCK + 3)
        self.d.file(self.fake, v1, sender=F.STRANGER)
        self.d.file(self.fake, v2, sender=F.STRANGER)
        self.d.file(self.real, v1)
        a = self.gate("check_address", self.real, F.SPONSOR, F.VICTIM)
        self.assertEqual(a["cases"], 1)
        self.assertEqual(int(a["refunded"]), 3 * GEN // 10)
        b = self.gate("check_address", self.fake, F.SPONSOR, F.VICTIM)
        self.assertEqual(b["state"], "UNVERIFIABLE")
        self.assertEqual(b["cases"], 0)

    def test_attestation_binds_pool_and_sponsor(self):
        _, v, _ = self.c.sandwich()
        self.d.file(self.fake, v, sender=F.STRANGER)
        r = self.w.call(self.d.gate, "attest_case", self.fake, F.SPONSOR, "ethereum", v, sender=F.STRANGER)
        self.assertEqual(r["state"], "UNVERIFIABLE")
        self.assertFalse(r["refunded"])


if __name__ == "__main__":
    unittest.main()
