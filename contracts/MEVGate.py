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
# Anyone can open a pool on the registry, under any name and terms, so every
# question names the pool AND the sponsor the consumer trusts: (pool_id,
# sponsor). The gate reads that pool and refuses to answer for it unless its
# sponsor is the named one; then it reads only that pool's decision. A copycat
# pool - same name, same routers, another sponsor or another id - is never read.
#
#   per case    NO_POOL, NOT_COVERED, CLEAN, SANDWICHED_REFUNDED,
#               SANDWICHED_UNPAID, UNCLEAR, UNVERIFIABLE, EXPIRED
#   per address the same states counted over the address's cases in that
#               pool, the refunded total, and one summary state
#
# `clean` is true only for a final CLEAN case read from a complete,
# self-consistent answer of the named pool; `refunded` only for
# SANDWICHED_REFUNDED with a positive payout. A missing pool is NO_POOL; a
# sponsor mismatch, an unfiled case, a failed or malformed read is
# UNVERIFIABLE; none is ever reported as clean or refunded. An address with no
# cases is UNVERIFIABLE, never CLEAN.
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


def _blank(chain: str, h: str, state: str, why: str, pool_id: int = 0, sponsor: str = "") -> dict:
    return {"chain": chain, "tx_hash": h, "state": state, "final": False, "clean": False, "refunded": False,
            "refund_paid": "0", "loss": "0", "profit_token": "", "victim": "", "attacker": "", "pool_id": pool_id,
            "sponsor": sponsor, "case_id": 0, "reason": "", "why": why}


def _obj(raw: typing.Any) -> typing.Any:
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except Exception:
            return None
    return raw


def pool_check(raw: typing.Any, pool_id: int, sponsor: str, chain: str) -> typing.Any:
    """The registry's get_pool answer for the pool the consumer named -> None
    when it is that sponsor's pool and covers the chain, else (state, why)."""
    raw = _obj(raw)
    if pool_id <= 0 or sponsor == "":
        return ("UNVERIFIABLE", "name a pool id and its sponsor")
    if not isinstance(raw, dict):
        return ("UNVERIFIABLE", "registry answer is not an object")
    if raw.get("found") is False:
        return ("NO_POOL", "the registry has no pool " + str(pool_id))
    if raw.get("found") is not True or _num(raw.get("pool_id")) != pool_id:
        return ("UNVERIFIABLE", "registry answer is not this pool")
    owner = _addr(raw.get("sponsor", ""))
    if owner == "" or owner != sponsor:
        return ("UNVERIFIABLE", "pool " + str(pool_id) + " is not sponsored by the named sponsor")
    chains = raw.get("chains")
    if not isinstance(chains, list):
        return ("UNVERIFIABLE", "registry answer is incomplete")
    if chain != "" and chain not in chains:
        return ("NOT_COVERED", "pool " + str(pool_id) + " does not cover " + clean_text(chain, 20))
    return None


def case_state(raw: typing.Any, chain: str, h: str, pool_id: int, sponsor: str = "") -> dict:
    """The registry's get_pool_case answer for the named pool -> the gate's
    structured state. Pure: tests call it on every malformed shape."""
    raw = _obj(raw)
    if not isinstance(raw, dict):
        return _blank(chain, h, "UNVERIFIABLE", "registry answer is not an object", pool_id, sponsor)
    if raw.get("found") is False:
        return _blank(chain, h, "UNVERIFIABLE", "nobody has filed this case in pool " + str(pool_id), pool_id, sponsor)
    if raw.get("found") is not True or raw.get("chain") != chain or raw.get("tx_hash") != h:
        return _blank(chain, h, "UNVERIFIABLE", "registry answer is not this case", pool_id, sponsor)
    st = raw.get("state")
    paid = _num(raw.get("refund_paid"))
    loss = _num(raw.get("loss"))
    due = _num(raw.get("refund_due"))
    cid = _num(raw.get("case_id"))
    pid = _num(raw.get("pool_id"))
    if st not in REGISTRY_STATES or min(paid, loss, due, cid, pid) < 0 or cid == 0 \
            or not isinstance(raw.get("final"), bool):
        return _blank(chain, h, "UNVERIFIABLE", "registry answer is incomplete", pool_id, sponsor)
    if pid != pool_id:
        return _blank(chain, h, "UNVERIFIABLE", "registry answer is another pool's decision", pool_id, sponsor)
    if raw.get("final") != (st in FINAL):
        return _blank(chain, h, "UNVERIFIABLE", "registry finality contradicts its state", pool_id, sponsor)
    victim = _addr(raw.get("victim", ""))
    sandwiched = st == "SANDWICHED_REFUNDED" or st == "SANDWICHED_UNPAID"
    if sandwiched and (loss <= 0 or victim == "" or _addr(raw.get("attacker", "")) == ""):
        return _blank(chain, h, "UNVERIFIABLE", "a sandwich without a loss, victim or attacker", pool_id, sponsor)
    if (st == "SANDWICHED_REFUNDED" and paid <= 0) or (st != "SANDWICHED_REFUNDED" and paid != 0):
        return _blank(chain, h, "UNVERIFIABLE", "registry payout contradicts its state", pool_id, sponsor)
    if not sandwiched and loss != 0:
        return _blank(chain, h, "UNVERIFIABLE", "a loss on a case that is not a sandwich", pool_id, sponsor)
    if st in ("CLEAN", "UNCLEAR") and victim == "":
        return _blank(chain, h, "UNVERIFIABLE", "a decided case without a victim", pool_id, sponsor)
    return {"chain": chain, "tx_hash": h, "state": st, "final": st in FINAL, "clean": st == "CLEAN",
            "refunded": st == "SANDWICHED_REFUNDED", "refund_paid": str(paid), "loss": str(loss),
            "profit_token": _addr(raw.get("profit_token", "")), "victim": victim,
            "attacker": _addr(raw.get("attacker", "")), "pool_id": pid, "sponsor": sponsor, "case_id": cid,
            "reason": clean_text(raw.get("reason", ""), 40), "why": "read from pool " + str(pid)}


def address_state(pages: list, address: str, pool_id: int, sponsor: str = "") -> dict:
    """The registry's get_pool_victim pages for the named pool -> counts per
    state, the refunded total and one summary state. Pure. Never CLEAN on
    missing data: no cases, a page that does not add up, or more cases than
    were read is UNVERIFIABLE."""
    counts = {}
    for s in CASE_STATES:
        counts[s] = 0
    base = {"address": address, "pool_id": pool_id, "sponsor": sponsor, "state": "UNVERIFIABLE", "cases": 0,
            "counts": counts, "refunded": "0", "loss_cases": 0, "clean": False, "why": ""}
    total = -1
    paid_sum = 0
    seen = 0
    for pg in pages:
        pg = _obj(pg)
        if not isinstance(pg, dict) or _addr(pg.get("address", "")) != address or not isinstance(pg.get("items"), list) \
                or _num(pg.get("pool_id")) != pool_id:
            base["why"] = "registry answer is not this address in this pool"
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
            cs = case_state(dict(it, found=True), str(it.get("chain", "")), str(it.get("tx_hash", "")), pool_id, sponsor)
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
        base["why"] = "no cases on record for this address in pool " + str(pool_id)
        return base
    for s in SEVERITY:
        if counts[s] > 0:
            base["state"] = s
            break
    base["clean"] = counts["CLEAN"] == seen
    base["why"] = "read from pool " + str(pool_id)
    return base


@gl.storage.allow
@dataclass
class Attestation:
    attestation_id: u64
    pool_id: u64
    sponsor: str
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

    def _case(self, pool_id: typing.Any, sponsor: typing.Any, chain: typing.Any, tx_hash: typing.Any) -> dict:
        pid = _as_int(pool_id, 0)
        sp = _addr(sponsor)
        ch = str(chain).strip().lower()
        h = _hash32(tx_hash)
        if h == "":
            return _blank(ch, str(tx_hash)[:66], "UNVERIFIABLE", "not a transaction hash", pid, sp)
        try:
            reg = gl.contract.get_at(self.registry).view()
            bad = pool_check(reg.get_pool(pid, 0) if pid > 0 else None, pid, sp, ch)
            if bad is not None:
                return _blank(ch, h, bad[0], bad[1], pid, sp)
            raw = reg.get_pool_case(pid, ch, h)
        except Exception:
            return _blank(ch, h, "UNVERIFIABLE", "registry unreadable", pid, sp)
        return case_state(raw, ch, h, pid, sp)

    @gl.public.view
    def check_case(self, pool_id: int, sponsor: str, chain: str, tx_hash: str) -> typing.Any:
        """The named pool's decision on the case, read now. Never clean or refunded on missing data."""
        return self._case(pool_id, sponsor, chain, tx_hash)

    @gl.public.view
    def is_clean(self, pool_id: int, sponsor: str, chain: str, tx_hash: str) -> bool:
        return self._case(pool_id, sponsor, chain, tx_hash)["clean"] is True

    @gl.public.view
    def was_refunded(self, pool_id: int, sponsor: str, chain: str, tx_hash: str) -> bool:
        return self._case(pool_id, sponsor, chain, tx_hash)["refunded"] is True

    @gl.public.view
    def check_address(self, pool_id: int, sponsor: str, address: str) -> typing.Any:
        """Every case of `address` in the named pool (up to MAX_ADDRESS_CASES), counted by state."""
        pid = _as_int(pool_id, 0)
        sp = _addr(sponsor)
        a = _addr(address)
        if a == "":
            out = address_state([], "", pid, sp)
            out["why"] = "not an address"
            return out
        try:
            reg = gl.contract.get_at(self.registry).view()
            bad = pool_check(reg.get_pool(pid, 0) if pid > 0 else None, pid, sp, "")
            if bad is not None:
                out = address_state([], a, pid, sp)
                out["state"] = bad[0]
                out["why"] = bad[1]
                return out
            pages = []
            off = 0
            while off >= 0 and off < MAX_ADDRESS_CASES:
                pg = reg.get_pool_victim(pid, a, off, PAGE_MAX)
                pages.append(pg)
                nxt = pg.get("next_offset") if isinstance(pg, dict) else -1
                if not isinstance(nxt, int) or isinstance(nxt, bool) or nxt <= off:
                    break
                off = nxt
        except Exception:
            out = address_state([], a, pid, sp)
            out["why"] = "registry unreadable"
            return out
        return address_state(pages, a, pid, sp)

    @gl.public.write
    def attest_case(self, pool_id: int, sponsor: str, chain: str, tx_hash: str) -> typing.Any:
        """Store the named pool's decision as read now (anyone; it only reads the registry)."""
        now = _epoch_from_iso(gl.message.raw.get("datetime", ""))
        if now <= 0:
            raise gl.vm.UserError("REFUSED: NO_CLOCK")
        st = self._case(pool_id, sponsor, chain, tx_hash)
        # --- writes
        aid = int(self.n_attest) + 1
        self.attestations[u64(aid)] = Attestation(attestation_id=u64(aid), pool_id=u64(int(st["pool_id"])),
                                                  sponsor=st["sponsor"], chain=st["chain"], tx_hash=st["tx_hash"],
                                                  state=st["state"], state_json=_canon(st), attested_at=u64(now),
                                                  attested_by=gl.message.sender_address.as_hex.lower())
        self.n_attest = u64(aid)
        self.latest[str(int(st["pool_id"])) + ":" + st["chain"] + ":" + st["tx_hash"]] = u64(aid)
        return {"ok": True, "attestation_id": aid, "state": st["state"], "clean": st["clean"], "refunded": st["refunded"]}

    def _att_view(self, a: Attestation) -> dict:
        return {"attestation_id": int(a.attestation_id), "pool_id": int(a.pool_id), "sponsor": a.sponsor,
                "chain": a.chain, "tx_hash": a.tx_hash, "state": a.state, "read": json.loads(a.state_json),
                "attested_at": int(a.attested_at), "attested_by": a.attested_by}

    @gl.public.view
    def get_attestation(self, attestation_id: int) -> typing.Any:
        a = self.attestations.get(u64(max(_as_int(attestation_id, 0), 0)))
        if a is None:
            return {"found": False}
        out = self._att_view(a)
        out["found"] = True
        return out

    @gl.public.view
    def latest_attestation(self, pool_id: int, chain: str, tx_hash: str) -> typing.Any:
        k = str(_as_int(pool_id, 0)) + ":" + str(chain).strip().lower() + ":" + _hash32(tx_hash)
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
                "binding": "every question names (pool_id, sponsor)", "attestations": int(self.n_attest)}
