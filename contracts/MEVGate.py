# v0.3.0
# { "Depends": "py-genlayer:5jycge4q8k23462jtb0b9fyey1s9qz928sz2nbrd9mg4sxqg2qng" }
import genlayer as gl
from genlayer import *
from dataclasses import dataclass
import json
import typing

# MEVGate - what a consumer contract (a wallet's rebate program, a DEX
# front-end's reputation score, an insurance cover) asks about a swap or an
# address before acting on it.
#
# It reads its SandwichRefund and answers with a structured state:
#
#   per case    NO_POOL, NOT_COVERED, CLEAN, SANDWICHED_REFUNDED,
#               SANDWICHED_UNPAID, UNCLEAR, UNVERIFIABLE
#   per address the same states counted over the address's cases, the
#               refunded total, and one summary state
#
# `clean` is true only for a final CLEAN case read from a complete,
# self-consistent answer; `refunded` only for SANDWICHED_REFUNDED with a
# positive payout. A case nobody filed is UNVERIFIABLE (or NO_POOL when no
# pool covers its chain), a failed or malformed read is UNVERIFIABLE, and
# neither is ever reported as clean or refunded. An address with no cases is
# UNVERIFIABLE, never CLEAN.
#
# attest_case stores a case's state with the time it was read, so a consumer
# can point at one on-chain record. Anyone may attest; it only reads.

VERSION = "1.0.0"
CASE_STATES = ("NO_POOL", "NOT_COVERED", "CLEAN", "SANDWICHED_REFUNDED", "SANDWICHED_UNPAID", "UNCLEAR",
               "UNVERIFIABLE", "EXPIRED")
REGISTRY_STATES = ("CLEAN", "SANDWICHED_REFUNDED", "SANDWICHED_UNPAID", "UNCLEAR", "NOT_COVERED", "UNVERIFIABLE",
                   "EXPIRED")
FINAL = ("CLEAN", "SANDWICHED_REFUNDED", "SANDWICHED_UNPAID", "UNCLEAR", "EXPIRED")
# the address summary is the worst state among its cases, in this order
SEVERITY = ("SANDWICHED_UNPAID", "UNCLEAR", "UNVERIFIABLE", "EXPIRED", "SANDWICHED_REFUNDED", "NOT_COVERED", "CLEAN")
PAGE_MAX = 50
MAX_ADDRESS_CASES = 200

# INLINE:common


def _num(v: typing.Any) -> int:
    """A non-negative integer from a registry field (int or decimal string), or -1."""
    if isinstance(v, bool):
        return -1
    if isinstance(v, int):
        return v if v >= 0 else -1
    return _as_int(v, -1)


def _blank(chain: str, h: str, state: str, why: str) -> dict:
    return {"chain": chain, "tx_hash": h, "state": state, "final": False, "clean": False, "refunded": False,
            "refund_paid": "0", "loss": "0", "profit_token": "", "victim": "", "attacker": "", "pool_id": 0,
            "case_id": 0, "reason": "", "why": why}


def case_state(raw: typing.Any, chain: str, h: str) -> dict:
    """The registry's get_case answer -> the gate's structured state. Pure:
    tests call it on every malformed shape."""
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except Exception:
            return _blank(chain, h, "UNVERIFIABLE", "registry answer is not JSON")
    if not isinstance(raw, dict):
        return _blank(chain, h, "UNVERIFIABLE", "registry answer is not an object")
    if raw.get("found") is False:
        pools = _num(raw.get("pools_on_chain"))
        if pools == 0:
            return _blank(chain, h, "NO_POOL", "no pool covers this chain")
        return _blank(chain, h, "UNVERIFIABLE", "nobody has filed this case")
    if raw.get("found") is not True or raw.get("chain") != chain or raw.get("tx_hash") != h:
        return _blank(chain, h, "UNVERIFIABLE", "registry answer is not this case")
    st = raw.get("state")
    paid = _num(raw.get("refund_paid"))
    loss = _num(raw.get("loss"))
    due = _num(raw.get("refund_due"))
    cid = _num(raw.get("case_id"))
    pid = _num(raw.get("pool_id"))
    if st not in REGISTRY_STATES or min(paid, loss, due, cid, pid) < 0 or cid == 0 or pid == 0 \
            or not isinstance(raw.get("final"), bool):
        return _blank(chain, h, "UNVERIFIABLE", "registry answer is incomplete")
    if raw.get("final") != (st in FINAL):
        return _blank(chain, h, "UNVERIFIABLE", "registry finality contradicts its state")
    victim = _addr(raw.get("victim", ""))
    sandwiched = st == "SANDWICHED_REFUNDED" or st == "SANDWICHED_UNPAID"
    if sandwiched and (loss <= 0 or victim == "" or _addr(raw.get("attacker", "")) == ""):
        return _blank(chain, h, "UNVERIFIABLE", "a sandwich without a loss, victim or attacker")
    if (st == "SANDWICHED_REFUNDED" and paid <= 0) or (st != "SANDWICHED_REFUNDED" and paid != 0):
        return _blank(chain, h, "UNVERIFIABLE", "registry payout contradicts its state")
    if not sandwiched and loss != 0:
        return _blank(chain, h, "UNVERIFIABLE", "a loss on a case that is not a sandwich")
    if st in ("CLEAN", "UNCLEAR") and victim == "":
        return _blank(chain, h, "UNVERIFIABLE", "a decided case without a victim")
    return {"chain": chain, "tx_hash": h, "state": st, "final": st in FINAL, "clean": st == "CLEAN",
            "refunded": st == "SANDWICHED_REFUNDED", "refund_paid": str(paid), "loss": str(loss),
            "profit_token": _addr(raw.get("profit_token", "")), "victim": victim,
            "attacker": _addr(raw.get("attacker", "")), "pool_id": pid, "case_id": cid,
            "reason": clean_text(raw.get("reason", ""), 40), "why": "read from the registry"}


def address_state(pages: list, address: str, pools_total: int) -> dict:
    """The registry's get_victim pages -> counts per state, the refunded
    total and one summary state. Pure. Never CLEAN on missing data: no cases,
    a page that does not add up, or more cases than were read is UNVERIFIABLE."""
    counts = {}
    for s in CASE_STATES:
        counts[s] = 0
    base = {"address": address, "state": "UNVERIFIABLE", "cases": 0, "counts": counts, "refunded": "0",
            "loss_cases": 0, "clean": False, "why": ""}
    if pools_total == 0:
        base["state"] = "NO_POOL"
        base["why"] = "the registry has no pools"
        return base
    if pools_total < 0:
        base["why"] = "registry stats unreadable"
        return base
    total = -1
    paid_sum = 0
    seen = 0
    for pg in pages:
        if not isinstance(pg, dict) or _addr(pg.get("address", "")) != address or not isinstance(pg.get("items"), list):
            base["why"] = "registry answer is not this address"
            return base
        t = _num(pg.get("total"))
        if t < 0 or (total >= 0 and t != total):
            base["why"] = "registry answer is incomplete"
            return base
        total = t
        for it in pg["items"]:
            if not isinstance(it, dict):
                base["why"] = "registry answer is incomplete"
                return base
            cs = case_state(dict(it, found=True), str(it.get("chain", "")), str(it.get("tx_hash", "")))
            if cs["state"] == "UNVERIFIABLE" and it.get("state") != "UNVERIFIABLE":
                base["why"] = "a case is inconsistent: " + cs["why"]
                return base
            if cs["victim"] != "" and cs["victim"] != address:
                base["why"] = "a case belongs to another address"
                return base
            counts[cs["state"]] += 1
            paid_sum += _num(cs["refund_paid"])
            seen += 1
    base["cases"] = seen
    base["refunded"] = str(paid_sum)
    base["loss_cases"] = counts["SANDWICHED_REFUNDED"] + counts["SANDWICHED_UNPAID"]
    if total < 0 or seen != total:
        base["why"] = "not every case was read"
        return base
    if seen == 0:
        base["why"] = "no cases on record for this address"
        return base
    for s in SEVERITY:
        if counts[s] > 0:
            base["state"] = s
            break
    base["clean"] = counts["CLEAN"] == seen
    base["why"] = "read from the registry"
    return base


@gl.storage.allow
@dataclass
class Attestation:
    attestation_id: u64
    chain: str
    tx_hash: str
    state: str
    state_json: str
    attested_at: u64
    attested_by: str


class MEVGate(gl.contract.Contract):
    registry: Address
    n_attest: u64
    attestations: gl.storage.TreeMap[u64, Attestation]
    latest: gl.storage.TreeMap[str, u64]

    def __init__(self, registry: str) -> None:
        r = _addr(registry)
        if r == "" or r == ZERO:
            raise gl.vm.UserError("registry must be a 0x address")
        self.registry = Address(r)
        self.n_attest = u64(0)

    def _case(self, chain: typing.Any, tx_hash: typing.Any) -> dict:
        ch = str(chain).strip().lower()
        h = _hash32(tx_hash)
        if h == "":
            return _blank(ch, str(tx_hash)[:66], "UNVERIFIABLE", "not a transaction hash")
        try:
            raw = gl.contract.get_at(self.registry).view().get_case(ch, h)
        except Exception:
            raw = None
        return case_state(raw, ch, h)

    @gl.public.view
    def check_case(self, chain: str, tx_hash: str) -> typing.Any:
        """The case's state as read now. Never clean or refunded on missing data."""
        return self._case(chain, tx_hash)

    @gl.public.view
    def is_clean(self, chain: str, tx_hash: str) -> bool:
        return self._case(chain, tx_hash)["clean"] is True

    @gl.public.view
    def was_refunded(self, chain: str, tx_hash: str) -> bool:
        return self._case(chain, tx_hash)["refunded"] is True

    @gl.public.view
    def check_address(self, address: str) -> typing.Any:
        """Every case of `address` (up to MAX_ADDRESS_CASES), counted by state."""
        a = _addr(address)
        if a == "":
            out = address_state([], "", -1)
            out["why"] = "not an address"
            return out
        try:
            reg = gl.contract.get_at(self.registry).view()
            stats = reg.get_stats()
            pools = _num(stats.get("pools")) if isinstance(stats, dict) else -1
            pages = []
            off = 0
            while off >= 0 and off < MAX_ADDRESS_CASES:
                pg = reg.get_victim(a, off, PAGE_MAX)
                pages.append(pg)
                nxt = pg.get("next_offset") if isinstance(pg, dict) else -1
                if not isinstance(nxt, int) or isinstance(nxt, bool) or nxt <= off:
                    break
                off = nxt
        except Exception:
            out = address_state([], a, -1)
            out["why"] = "registry unreadable"
            return out
        return address_state(pages, a, pools)

    @gl.public.write
    def attest_case(self, chain: str, tx_hash: str) -> typing.Any:
        """Store the case's state as read now (anyone; it only reads the registry)."""
        now = _epoch_from_iso(gl.message.raw.get("datetime", ""))
        if now <= 0:
            raise gl.vm.UserError("REFUSED: NO_CLOCK")
        st = self._case(chain, tx_hash)
        # --- writes
        aid = int(self.n_attest) + 1
        self.attestations[u64(aid)] = Attestation(attestation_id=u64(aid), chain=st["chain"], tx_hash=st["tx_hash"],
                                                  state=st["state"], state_json=_canon(st), attested_at=u64(now),
                                                  attested_by=gl.message.sender_address.as_hex.lower())
        self.n_attest = u64(aid)
        self.latest[st["chain"] + ":" + st["tx_hash"]] = u64(aid)
        return {"ok": True, "attestation_id": aid, "state": st["state"], "clean": st["clean"], "refunded": st["refunded"]}

    def _att_view(self, a: Attestation) -> dict:
        return {"attestation_id": int(a.attestation_id), "chain": a.chain, "tx_hash": a.tx_hash, "state": a.state,
                "read": json.loads(a.state_json), "attested_at": int(a.attested_at), "attested_by": a.attested_by}

    @gl.public.view
    def get_attestation(self, attestation_id: int) -> typing.Any:
        a = self.attestations.get(u64(max(_as_int(attestation_id, 0), 0)))
        if a is None:
            return {"found": False}
        out = self._att_view(a)
        out["found"] = True
        return out

    @gl.public.view
    def latest_attestation(self, chain: str, tx_hash: str) -> typing.Any:
        k = str(chain).strip().lower() + ":" + _hash32(tx_hash)
        aid = int(self.latest.get(k, u64(0)))
        a = self.attestations.get(u64(aid)) if aid > 0 else None
        if a is None:
            return {"found": False}
        out = self._att_view(a)
        out["found"] = True
        return out

    @gl.public.view
    def get_attestations(self, offset: int, limit: int) -> typing.Any:
        off = max(_as_int(offset, 0), 0)
        lim = min(max(_as_int(limit, PAGE_MAX), 1), PAGE_MAX)
        n = int(self.n_attest)
        items = []
        i = off + 1
        while i <= n and len(items) < lim:
            a = self.attestations.get(u64(i))
            if a is not None:
                items.append(self._att_view(a))
            i += 1
        return {"total": n, "offset": off, "limit": lim, "items": items,
                "next_offset": off + len(items) if off + len(items) < n else -1}

    @gl.public.view
    def get_config(self) -> typing.Any:
        return {"version": VERSION, "contract": "MEVGate", "registry": self.registry.as_hex.lower(),
                "case_states": list(CASE_STATES), "severity": list(SEVERITY), "max_address_cases": MAX_ADDRESS_CASES,
                "attestations": int(self.n_attest)}
