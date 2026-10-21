"""Meaning: the contract's rule and the keeper's JavaScript mirror agree on
every real case and every fixture; the gate is never favorable on missing
data; the docs state the rule exactly as the code does."""
import json
import random
import re
import subprocess
import unittest
from pathlib import Path

import fixtures as F
import test_rule
from fixtures import ETH, GEN

SR = F.SR
GT = F.GT
ROOT = Path(__file__).resolve().parent.parent
FEAS = json.loads((ROOT / "docs" / "feasibility.json").read_text())
POOL = json.loads((ROOT / "data" / "pool_canonical.json").read_text())


def canonical_terms():
    return SR.chain_terms(SR.parse_terms(json.dumps(POOL["chains"]), json.dumps(POOL["routers"]),
                                         json.dumps(POOL["kinds"]), json.dumps(POOL["ranges"]),
                                         json.dumps(POOL["rates"])), "ethereum")


def js_judge(items):
    p = subprocess.run(["node", str(ROOT / "test" / "judge_js.mjs")], input=json.dumps(items), capture_output=True,
                       text=True, cwd=str(ROOT / "test"))
    if p.returncode != 0:
        raise RuntimeError(p.stderr)
    return json.loads(p.stdout)


def same(a, b):
    keys = ("verdict", "reason", "profit", "profit_token", "attacker_eoa", "front_index", "back_index", "pool")
    return all(str(a.get(k, "")) == str(b.get(k, "")) for k in keys)


class RealCases(unittest.TestCase):
    """Every real case of docs/FEASIBILITY.md, judged by the contract's rule on
    the facts the Mac read, gives the verdict recorded there."""


def _real(case):
    def t(self):
        r = {"facts": case["facts"]} if case["facts"] else {"reason": case["reason"]}
        got = SR.judge(canonical_terms(), json.loads(json.dumps(r)))
        self.assertTrue(same(got, case), (got, {k: case.get(k) for k in ("verdict", "reason", "profit")}))
    return t


for _c in FEAS["cases"]:
    setattr(RealCases, "test_real_%s_%s" % (_c["hash"][:12], _c["verdict"].lower()), _real(_c))


class Mirror(unittest.TestCase):
    """The same facts through the JS mirror (keeper) and the Python rule (contract)."""

    def test_real_cases_in_js(self):
        t = canonical_terms()
        items = [{"terms": t, "r": {"facts": c["facts"]}} for c in FEAS["cases"] if c["facts"]]
        out = js_judge(items)
        py = [SR.judge(t, json.loads(json.dumps(i["r"]))) for i in items]
        for a, b in zip(out, py):
            self.assertTrue(same(a, b), (a, b))

    def test_fixture_scenarios_in_js(self):
        # every scenario of test_rule, read by the contract's reader, judged twice
        loader = unittest.TestLoader()
        captured = []
        orig = SR.judge

        def spy(terms, r):
            captured.append({"terms": json.loads(json.dumps(terms)), "r": json.loads(json.dumps(r))})
            return orig(terms, r)
        SR.judge = spy
        try:
            suite = loader.loadTestsFromModule(test_rule)
            unittest.TextTestRunner(stream=open("/dev/null", "w"), verbosity=0).run(suite)
        finally:
            SR.judge = orig
        self.assertGreater(len(captured), 60)
        py = [orig(c["terms"], json.loads(json.dumps(c["r"]))) for c in captured]
        js = js_judge(captured)
        for a, b, c in zip(js, py, captured):
            self.assertTrue(same(a, b), (a, b))


class NeverFavorable(unittest.TestCase):
    def test_random_field_loss_never_favorable(self):
        rnd = random.Random(7)
        base = {"found": True, "chain": "ethereum", "tx_hash": F.h32("z"), "state": "CLEAN", "final": True,
                "refund_paid": "0", "loss": "0", "refund_due": "0", "case_id": 1, "pool_id": 1, "victim": F.VICTIM,
                "attacker": "", "profit_token": "", "reason": "NO_PATTERN", "pools_on_chain": 1}
        refunded = dict(base, state="SANDWICHED_REFUNDED", refund_paid="5", loss="9", attacker=F.ATTACKER)
        for good in (base, refunded):
            for _ in range(300):
                raw = dict(good)
                k = rnd.choice(sorted(raw.keys()))
                mode = rnd.randrange(4)
                if mode == 0:
                    del raw[k]
                elif mode == 1:
                    raw[k] = None
                elif mode == 2:
                    raw[k] = rnd.choice(["", "x", -1, True, [], {}])
                else:
                    raw[k] = "garbage"
                if k in raw and type(raw[k]) is type(good[k]) and raw[k] == good[k]:
                    continue
                s = GT.case_state(raw, "ethereum", F.h32("z"), 1, F.SPONSOR)
                if s["clean"] or s["refunded"]:
                    # only possible when the damaged field does not carry the meaning
                    self.assertIn(k, ("reason", "profit_token", "pools_on_chain", "attacker") if good is base
                                  else ("reason", "profit_token", "pools_on_chain"), (k, mode, raw))

    def test_unfiled_is_never_clean(self):
        for raw in ({"found": False}, {"found": False, "pool_id": 1}, None, "x"):
            s = GT.case_state(raw, "ethereum", F.h32("q"), 1, F.SPONSOR)
            self.assertFalse(s["clean"] or s["refunded"] or s["final"])

    def test_random_pool_corruption_never_passes(self):
        rnd = random.Random(11)
        good = {"found": True, "pool_id": 1, "sponsor": F.SPONSOR, "chains": ["ethereum"]}
        for _ in range(300):
            raw = dict(good)
            k = rnd.choice(sorted(raw.keys()))
            v = rnd.choice([None, "", "x", 2, 0, True, [], F.STRANGER, ["base"]])
            if v == good[k] and type(v) is type(good[k]):
                continue
            raw[k] = v
            self.assertIsNotNone(GT.pool_check(raw, 1, F.SPONSOR, "ethereum"), (k, v))

    def test_states_are_exactly_the_spec(self):
        self.assertEqual(set(GT.CASE_STATES), {"NO_POOL", "NOT_COVERED", "CLEAN", "SANDWICHED_REFUNDED",
                                                "SANDWICHED_UNPAID", "UNCLEAR", "UNVERIFIABLE", "EXPIRED"})
        self.assertEqual(set(GT.REGISTRY_STATES), set(SR.STATES))
        self.assertEqual(set(GT.FINAL), set(SR.FINAL_STATES))


class DocsTruth(unittest.TestCase):
    """docs/RULES.md and the site's /docs page say what the code does."""

    def setUp(self):
        self.rules = (ROOT / "docs" / "RULES.md").read_text()

    def test_every_reason_is_documented(self):
        src = (ROOT / "contracts" / "shared" / "common.py").read_text() + (ROOT / "contracts" / "shared" / "rpc.py").read_text() \
            + (ROOT / "contracts" / "SandwichRefund.py").read_text()
        reasons = set(re.findall(r'"([A-Z][A-Z_]{5,})"', src))
        skip = {"CANONICAL", "DEMO", "OPEN", "CLOSED", "RATE", "CLOSE"}
        missing = sorted(r for r in reasons - skip if r not in self.rules)
        self.assertEqual(missing, [])

    def test_constants_are_documented_with_their_values(self):
        for name, val in (("MAX_POOLS", SR.MAX_POOLS), ("MAX_TXS", SR.MAX_TXS), ("BATCH_MAX", SR.BATCH_MAX),
                          ("MAX_ROUTERS", SR.MAX_ROUTERS), ("MAX_RATES", SR.MAX_RATES), ("PAGE_MAX", SR.PAGE_MAX),
                          ("MAX_SPAN_BLOCKS", SR.MAX_SPAN_BLOCKS)):
            self.assertRegex(self.rules, r"`%s` *= *%s\b" % (name, re.escape(format(val, ","))) + "|" +
                             r"`%s` *= *%d\b" % (name, val), name)

    def test_modes_documented(self):
        for m, vals in SR.MODES.items():
            row = [l for l in self.rules.split("\n") if l.startswith("| " + m)]
            self.assertEqual(len(row), 1, m)
            for v in vals:
                self.assertIn(str(v), row[0], (m, v))

    def test_refund_formula_documented(self):
        self.assertIn("min(loss * num // den, max_per_swap, max_per_victim - paid_to_victim_by_this_pool, pool_balance)",
                      self.rules)

    def test_profit_cases_documented(self):
        for frag in ("bXout*fYout//bYin - fXin", "fYout - ceil(bYin*fXin/bXout)"):
            self.assertIn(frag, self.rules)
            self.assertIn(frag, (ROOT / "contracts" / "shared" / "common.py").read_text())

    def test_rpcs_documented(self):
        for u in SR.CHAINS["ethereum"][1]:
            self.assertIn(u, self.rules)

    def test_site_docs_page_matches(self):
        page = ROOT / "frontend" / "src" / "app" / "docs" / "rules.json"
        if not page.exists():
            self.skipTest("site not built yet")
        data = json.loads(page.read_text())
        self.assertEqual(data["rules_md_sha256"], __import__("hashlib").sha256(self.rules.encode()).hexdigest())


if __name__ == "__main__":
    unittest.main()
