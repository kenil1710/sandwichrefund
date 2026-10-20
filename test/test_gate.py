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
        return GT.case_state(raw, "ethereum", H)

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
        s = self.st({"found": False, "pools_on_chain": 2})
        self.assertEqual(s["state"], "UNVERIFIABLE")
        self.assertIn("filed", s["why"])

    def test_no_pool(self):
        s = self.st({"found": False, "pools_on_chain": 0})
        self.assertEqual(s["state"], "NO_POOL")
        self.assertFalse(s["clean"])

    def test_found_false_without_pool_count_is_unverifiable(self):
        self.assertEqual(self.st({"found": False})["state"], "UNVERIFIABLE")


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
        s = GT.case_state(raw, "ethereum", H)
        self.assertEqual(s["state"], "UNVERIFIABLE", s)
        self.assertFalse(s["clean"])
        self.assertFalse(s["refunded"])
        self.assertFalse(s["final"])
    return t


for _i, (_n, _raw) in enumerate(BAD):
    setattr(CaseStatePure, "test_malformed_%02d_%s" % (_i, _n.replace(" ", "_")), _bad(_raw))


def vpage(items, total=None, address=F.VICTIM):
    return {"address": address, "total": len(items) if total is None else total, "items": items}


class AddressStatePure(unittest.TestCase):
    def item(self, state, paid="0", loss="0", n=0):
        it = good(state=state, final=state in GT.FINAL, refund_paid=paid, loss=loss, tx_hash=F.h32(("a", n)))
        if state not in ("SANDWICHED_REFUNDED", "SANDWICHED_UNPAID"):
            it["attacker"] = ""
        del it["found"]
        return it

    def test_no_pools(self):
        self.assertEqual(GT.address_state([], F.VICTIM, 0)["state"], "NO_POOL")

    def test_no_cases_is_unverifiable(self):
        s = GT.address_state([vpage([])], F.VICTIM, 3)
        self.assertEqual(s["state"], "UNVERIFIABLE")
        self.assertFalse(s["clean"])

    def test_all_clean(self):
        s = GT.address_state([vpage([self.item("CLEAN", n=1), self.item("CLEAN", n=2)])], F.VICTIM, 1)
        self.assertEqual(s["state"], "CLEAN")
        self.assertTrue(s["clean"])
        self.assertEqual(s["counts"]["CLEAN"], 2)

    def test_worst_state_wins(self):
        items = [self.item("CLEAN", n=1), self.item("SANDWICHED_REFUNDED", "5", "9", n=2),
                 self.item("SANDWICHED_UNPAID", "0", "9", n=3)]
        s = GT.address_state([vpage(items)], F.VICTIM, 1)
        self.assertEqual(s["state"], "SANDWICHED_UNPAID")
        self.assertEqual(s["refunded"], "5")
        self.assertEqual(s["loss_cases"], 2)
        self.assertFalse(s["clean"])

    def test_severity_order(self):
        order = list(GT.SEVERITY)
        for i, st in enumerate(order):
            items = [self.item(x, "5" if x == "SANDWICHED_REFUNDED" else "0",
                               "9" if x.startswith("SANDWICHED") else "0", n=j) for j, x in enumerate(order[i:])]
            for it in items:
                if it["state"] in ("NOT_COVERED", "UNVERIFIABLE"):
                    it["final"] = False
            self.assertEqual(GT.address_state([vpage(items)], F.VICTIM, 1)["state"], st)

    def test_not_every_case_read(self):
        s = GT.address_state([vpage([self.item("CLEAN")], total=2)], F.VICTIM, 1)
        self.assertEqual(s["state"], "UNVERIFIABLE")
        self.assertFalse(s["clean"])

    def test_pages_disagree_on_total(self):
        s = GT.address_state([vpage([self.item("CLEAN", n=1)], total=2), vpage([self.item("CLEAN", n=2)], total=3)],
                             F.VICTIM, 1)
        self.assertEqual(s["state"], "UNVERIFIABLE")

    def test_other_address_page(self):
        s = GT.address_state([vpage([self.item("CLEAN")], address=F.VICTIM2)], F.VICTIM, 1)
        self.assertEqual(s["state"], "UNVERIFIABLE")

    def test_case_of_another_victim(self):
        it = self.item("CLEAN")
        it["victim"] = F.VICTIM2
        self.assertEqual(GT.address_state([vpage([it])], F.VICTIM, 1)["state"], "UNVERIFIABLE")

    def test_inconsistent_case(self):
        it = self.item("CLEAN")
        it["refund_paid"] = "7"
        s = GT.address_state([vpage([it])], F.VICTIM, 1)
        self.assertEqual(s["state"], "UNVERIFIABLE")
        self.assertIn("inconsistent", s["why"])

    def test_stats_unreadable(self):
        self.assertEqual(GT.address_state([vpage([self.item("CLEAN")])], F.VICTIM, -1)["state"], "UNVERIFIABLE")

    def test_garbage_pages(self):
        for pg in (None, 5, "x", {"address": F.VICTIM}, {"address": F.VICTIM, "items": "x", "total": 1},
                   {"address": F.VICTIM, "items": [5], "total": 1}, {"address": F.VICTIM, "items": [], "total": -1}):
            s = GT.address_state([pg], F.VICTIM, 1)
            self.assertEqual(s["state"], "UNVERIFIABLE", pg)
            self.assertFalse(s["clean"])


class GateOnChain(unittest.TestCase):
    def setUp(self):
        self.d = F.Deployment()
        self.c = self.d.chain
        self.w = self.d.w

    def check(self, h):
        return self.w.view(self.d.gate, "check_case", "ethereum", h)

    def test_no_pool_then_unfiled(self):
        self.assertEqual(self.check(H)["state"], "NO_POOL")
        self.d.create()
        self.assertEqual(self.check(H)["state"], "UNVERIFIABLE")
        self.assertEqual(self.w.view(self.d.gate, "check_address", F.VICTIM)["state"], "UNVERIFIABLE")

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
            s = self.check(h)
            self.assertEqual(s["state"], st)
            self.assertEqual(s["clean"], st == "CLEAN")
            self.assertEqual(s["refunded"], st == "SANDWICHED_REFUNDED")
            self.assertEqual(self.w.view(self.d.gate, "is_clean", "ethereum", h), st == "CLEAN")
            self.assertEqual(self.w.view(self.d.gate, "was_refunded", "ethereum", h), st == "SANDWICHED_REFUNDED")
        a = self.w.view(self.d.gate, "check_address", F.VICTIM)
        self.assertEqual(a["state"], "SANDWICHED_UNPAID")
        self.assertEqual(a["cases"], 5)
        self.assertEqual(a["counts"]["CLEAN"], 1)
        self.assertEqual(int(a["refunded"]), GEN // 5)

    def test_bad_hash(self):
        self.assertEqual(self.check("0x12")["state"], "UNVERIFIABLE")
        self.assertFalse(self.w.view(self.d.gate, "is_clean", "ethereum", "0x12"))

    def test_address_pagination_beyond_one_page(self):
        pid = self.d.create(value=100 * GEN, max_swap=GEN, max_victim=100 * GEN)["pool_id"]
        for i in range(55):
            v = self.c.tx(F.BLOCK + i, F.VICTIM, F.ROUTER, [(F.POOL_V2, ETH, -90 * ETH, F.VICTIM)])
            self.d.file(pid, v, sender=F.addr(3000 + i))
        a = self.w.view(self.d.gate, "check_address", F.VICTIM)
        self.assertEqual(a["cases"], 55)
        self.assertEqual(a["state"], "CLEAN")
        self.assertTrue(a["clean"])

    def test_registry_unreadable(self):
        w = self.w
        g = w.deploy("MEVGate", "0x" + "9" * 40, sender=F.DEPLOYER)
        s = w.view(g, "check_case", "ethereum", H)
        self.assertEqual(s["state"], "UNVERIFIABLE")
        self.assertEqual(w.view(g, "check_address", F.VICTIM)["state"], "UNVERIFIABLE")

    def test_attest(self):
        pid = self.d.create()["pool_id"]
        _, v, _ = self.c.sandwich()
        self.d.file(pid, v)
        r = self.w.call(self.d.gate, "attest_case", "ethereum", v, sender=F.STRANGER)
        self.assertEqual(r["state"], "SANDWICHED_REFUNDED")
        a = self.w.view(self.d.gate, "latest_attestation", "ethereum", v)
        self.assertTrue(a["found"])
        self.assertEqual(a["read"]["victim"], F.VICTIM)
        self.assertEqual(a["attested_by"], F.STRANGER)
        self.assertEqual(self.w.view(self.d.gate, "get_attestations", 0, 10)["total"], 1)
        self.assertFalse(self.w.view(self.d.gate, "latest_attestation", "ethereum", H)["found"])
        self.assertFalse(self.w.view(self.d.gate, "get_attestation", 5)["found"])

    def test_constructor_needs_an_address(self):
        with self.assertRaises(Exception):
            self.w.deploy("MEVGate", "nope", sender=F.DEPLOYER)

    def test_gate_never_moves_value(self):
        self.d.create()
        n = len(F.stub.TRANSFERS)
        self.w.call(self.d.gate, "attest_case", "ethereum", H, sender=F.STRANGER)
        self.assertEqual(len(F.stub.TRANSFERS), n)
        self.assertEqual(self.w.view(self.d.gate, "get_config")["registry"], self.d.sr)


if __name__ == "__main__":
    unittest.main()
