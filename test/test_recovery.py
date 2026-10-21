"""Rule 5 and the recovery window: a case UNVERIFIABLE for a transient reason
(an RPC failure, a disagreement, a block not final) filed inside the claim
period may be filed again for a fixed window after it; close waits for it only
while such cases remain, always succeeds after it, and the leftovers are
EXPIRED. Junk (TX_NOT_FOUND) is never pending and cannot hold a pool open."""
import unittest

import fixtures as F
import world
from fixtures import ETH, GEN

SR = F.SR
REC = SR.MODES["CANONICAL"][4]
CLAIM = 7200


class Base(unittest.TestCase):
    def setUp(self):
        self.d = F.Deployment()
        self.c = self.d.chain
        self.w = self.d.w
        self.pid = self.d.create(value=2 * GEN)["pool_id"]

    def pool(self):
        return self.d.pool(self.pid)

    def refused(self, fn, *a, contains, **kw):
        with self.assertRaises(world.Reverted) as e:
            fn(*a, **kw)
        self.assertIn(contains, e.exception.msg)

    def close(self, sender=F.STRANGER):
        return self.w.call(self.d.sr, "close_pool", self.pid, sender=sender)

    def outage_case(self):
        _, v, _ = self.c.sandwich()
        F.stub.WEB.down.add(F.RPCS[1])
        r = self.d.file(self.pid, v)
        F.stub.WEB.down.clear()
        self.assertEqual((r["state"], r["reason"]), ("UNVERIFIABLE", "RPC_UNREADABLE"))
        return v


class Pending(Base):
    def test_transient_case_is_pending(self):
        self.outage_case()
        self.assertEqual(self.pool()["pending"], 1)

    def test_disagreement_is_pending(self):
        _, v, _ = self.c.sandwich()
        b = self.c.split()
        del b.txs[v]
        self.assertEqual(self.d.file(self.pid, v)["reason"], "RPC_DISAGREE")
        self.assertEqual(self.pool()["pending"], 1)

    def test_not_final_is_pending(self):
        _, v, _ = self.c.sandwich(block=F.FINALIZED - 0)
        self.d.create(value=GEN, end=F.FINALIZED + 10)
        self.assertEqual(self.d.file(2, v)["reason"], "NOT_FINALIZED")
        self.assertEqual(self.d.pool(2)["pending"], 1)

    def test_pending_tx_is_pending(self):
        self.assertEqual(self.d.file(self.pid, self.c.pending())["reason"], "TX_PENDING")
        self.assertEqual(self.pool()["pending"], 1)

    def test_junk_is_not_pending(self):
        for i in range(5):
            self.assertEqual(self.d.file(self.pid, F.h32(("junk", i)))["reason"], "TX_NOT_FOUND")
        self.assertEqual(self.pool()["pending"], 0)

    def test_resolved_retry_clears_pending(self):
        v = self.outage_case()
        self.assertEqual(self.d.file(self.pid, v)["state"], "SANDWICHED_REFUNDED")
        self.assertEqual(self.pool()["pending"], 0)

    def test_failed_retry_stays_pending_once(self):
        v = self.outage_case()
        F.stub.WEB.down.add(F.RPCS[0])
        self.d.file(self.pid, v)
        F.stub.WEB.down.clear()
        self.assertEqual(self.pool()["pending"], 1)

    def test_transient_to_junk_reason_clears_pending(self):
        v = self.outage_case()
        del self.c.c.txs[v]
        self.assertEqual(self.d.file(self.pid, v)["reason"], "TX_NOT_FOUND")
        self.assertEqual(self.pool()["pending"], 0)


class Window(Base):
    def test_retry_inside_window_pays(self):
        v = self.outage_case()
        self.w.advance(CLAIM + REC)
        r = self.d.file(self.pid, v)
        self.assertEqual(r["state"], "SANDWICHED_REFUNDED")
        self.assertEqual(self.d.paid_to(F.VICTIM), 3 * GEN // 10)

    def test_retry_after_window_refused(self):
        v = self.outage_case()
        self.w.advance(CLAIM + REC + 1)
        self.refused(self.d.file, self.pid, v, contains="RECOVERY_WINDOW_OVER")

    def test_new_case_in_window_refused(self):
        self.outage_case()
        _, v2, _ = self.c.sandwich(block=F.BLOCK + 5, victim_from=F.VICTIM2)
        self.w.advance(CLAIM + 10)
        self.refused(self.d.file, self.pid, v2, contains="CLAIM_PERIOD_OVER")

    def test_junk_retry_in_window_refused(self):
        h = F.h32("junk")
        self.d.file(self.pid, h)
        self.w.advance(CLAIM + 10)
        self.refused(self.d.file, self.pid, h, contains="CLAIM_PERIOD_OVER")

    def test_not_covered_retry_in_window_refused(self):
        _, v, _ = self.c.sandwich(router=F.ROUTER_X)
        self.d.file(self.pid, v)
        self.w.advance(CLAIM + 10)
        self.refused(self.d.file, self.pid, v, contains="CLAIM_PERIOD_OVER")

    def test_window_is_fixed_from_the_deadline(self):
        v = self.outage_case()
        self.w.advance(CLAIM + REC - 10)
        F.stub.WEB.down.add(F.RPCS[1])
        self.d.file(self.pid, v)          # a failing retry inside the window
        F.stub.WEB.down.clear()
        self.assertEqual(self.pool()["recovery_deadline"], F.NOW + CLAIM + REC)
        self.w.advance(11)
        self.refused(self.d.file, self.pid, v, contains="RECOVERY_WINDOW_OVER")


class Close(Base):
    def test_close_waits_for_pending(self):
        self.outage_case()
        self.w.advance(CLAIM + 1)
        self.refused(self.close, contains="RECOVERY_WINDOW_OPEN_UNTIL_" + str(F.NOW + CLAIM + REC))
        self.assertEqual(self.pool()["due"], "RETRY")

    def test_close_right_away_when_none_pending(self):
        _, v, _ = self.c.sandwich()
        self.d.file(self.pid, v)
        self.d.file(self.pid, F.h32("junk"))
        self.w.advance(CLAIM + 1)
        self.assertEqual(self.pool()["due"], "CLOSE")
        self.assertTrue(self.close()["ok"])

    def test_close_after_recovery_resolved(self):
        v = self.outage_case()
        self.w.advance(CLAIM + 100)
        self.d.file(self.pid, v)
        self.assertEqual(self.pool()["due"], "CLOSE")
        r = self.close()
        self.assertEqual(r["expired"], 0)

    def test_close_after_window_always_succeeds_and_expires(self):
        v = self.outage_case()
        x = self.c.pending()
        self.d.file(self.pid, x)
        self.w.advance(CLAIM + REC + 1)
        self.assertEqual(self.pool()["due"], "CLOSE")
        r = self.close()
        self.assertEqual(r["expired"], 2)
        for h in (v, x):
            c = self.d.case(h)
            self.assertEqual(c["state"], "EXPIRED")
            self.assertTrue(c["final"])
        p = self.pool()
        self.assertEqual((p["pending"], p["n_expired"], p["status"]), (0, 2, "CLOSED"))
        s = self.d.stats()["counts"]
        self.assertEqual((s["state:EXPIRED"], s["state:UNVERIFIABLE"]), (2, 0))
        self.assertEqual(self.d.paid_to(F.SPONSOR), 2 * GEN)
        self.assertTrue(self.d.conserved())

    def test_junk_never_expires(self):
        h = F.h32("junk")
        self.d.file(self.pid, h)
        self.w.advance(CLAIM + 1)
        self.close()
        self.assertEqual(self.d.case(h)["state"], "UNVERIFIABLE")
        self.assertEqual(self.d.stats()["counts"]["state:EXPIRED"], 0)

    def test_expired_cannot_be_filed(self):
        v = self.outage_case()
        self.w.advance(CLAIM + REC + 1)
        self.close()
        self.refused(self.d.file, self.pid, v, contains="POOL_IS_CLOSED")

    def test_many_pending_cannot_hold_the_pool(self):
        for i in range(30):
            _, v, _ = self.c.sandwich(block=F.BLOCK + 3 * i, victim_from=F.addr(4000 + i))
            F.stub.WEB.down.add(F.RPCS[1])
            self.d.file(self.pid, v, sender=F.addr(5000 + i))
            F.stub.WEB.down.clear()
        self.assertEqual(self.pool()["pending"], 30)
        self.w.advance(CLAIM + REC + 1)
        self.assertEqual(self.close()["expired"], 30)

    def test_extend_moves_the_window_only_with_the_deadline(self):
        self.outage_case()
        self.w.call(self.d.sr, "extend", self.pid, F.NOW + CLAIM + 500, sender=F.SPONSOR)
        self.assertEqual(self.pool()["recovery_deadline"], F.NOW + CLAIM + 500 + REC)

    def test_gate_reads_expired_as_final_not_favorable(self):
        v = self.outage_case()
        self.w.advance(CLAIM + REC + 1)
        self.close()
        s = self.w.view(self.d.gate, "check_case", self.pid, F.SPONSOR, "ethereum", v)
        self.assertEqual(s["state"], "EXPIRED")
        self.assertFalse(s["clean"] or s["refunded"])


class DemoMode(unittest.TestCase):
    def test_demo_window(self):
        d = F.Deployment(mode="DEMO")
        d.create(claim=60)
        self.assertEqual(d.pool(1)["recovery_deadline"], F.NOW + 60 + SR.MODES["DEMO"][4])


if __name__ == "__main__":
    unittest.main()
