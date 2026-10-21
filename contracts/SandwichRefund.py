# v0.3.0
# { "Depends": "py-genlayer:5jycge4q8k23462jtb0b9fyey1s9qz928sz2nbrd9mg4sxqg2qng" }
import genlayer as gl
from genlayer import *
from dataclasses import dataclass
import json
import typing

# SandwichRefund - a sponsor-funded refund pool for sandwiched swaps.
#
# A SPONSOR (a wallet, a DEX front-end, a protocol) opens a POOL and locks GEN
# in it. The pool's terms freeze at creation: chains, the covered router
# addresses (the victim transaction's `to` must be one), the pool types
# (Uniswap V2-style, V3-style), a block range per chain, the refund rate per
# profit token (GEN wei per token wei, as num/den), the maximum refund per
# swap and per victim, and the claim period. The sponsor may only top up or
# extend the claim deadline; there is no cancel.
#
# Anyone FILES A CASE: (chain, victim transaction hash) against a pool.
# Validators read the transaction, its receipt and every Swap log on its pools
# in its block (and the next) from TWO RPCs that must agree, and code applies
# the rule (contracts/shared/common.py judge):
#
#   SANDWICHED  a front-run at a lower transaction index and a back-run at a
#               higher one in the SAME block, on the SAME pool as the victim,
#               from the same EOA or paid to the same Swap recipient, the
#               front-run in the victim's direction and the back-run opposite,
#               and the attacker's net amount of the profit token positive.
#               loss = that net profit (a conservative estimate).
#   UNCLEAR     anything partial: multi-hop victim, several attackers, several
#               victims inside one pair, a back-run in the next block, no net
#               profit, an unpriced profit token, a self-sandwich.
#   CLEAN       no pattern.
#   NOT_COVERED failed victim, router not covered, block outside the range,
#               no supported swap, a pool its factory does not know.
#   UNVERIFIABLE an RPC error, a disagreement, a missing or unfinalized
#               transaction. Never a verdict; the case may be filed again.
#
#   refund = min(loss * num // den, max per swap, what is left of the
#                victim's cap in this pool, the pool's balance)
#
# A refund is pushed to the victim (the transaction's sender) in the same call:
# SANDWICHED_REFUNDED, or SANDWICHED_UNPAID when nothing could be paid. CLEAN,
# UNCLEAR and the two SANDWICHED states are final: each pool decides each case
# once. (Per pool, so a tiny pool filed first cannot lock a victim out of a
# real sponsor's refund; each sponsor pays only under its own terms and caps.)
# After the claim deadline anyone CLOSES the pool and what is left goes back
# to the sponsor. No model is asked anything; no owner can intervene.
#
# RULES
#   1. create_pool and top_up are the only payable methods and never raise:
#      a refusal credits the value back to the sender (withdraw_refund). Studio
#      keeps the value of a call that fails, so raising there would strand it.
#   2. Every check runs before the first write; counters move only after.
#   3. GEN leaves only through _send: one external value message per call,
#      posted in the call that records the payout. The caller funds it.
#   4. Ledger: received = held + refunded + returned + credits_paid + swept,
#      held = open pool balances + credits owed. Anything above held in the
#      balance arrived outside the payable methods; sweep_stray sends it to
#      the deployer.

VERSION = "1.0.0"

PS_OPEN = "OPEN"
PS_CLOSED = "CLOSED"

S_CLEAN = "CLEAN"
S_REFUNDED = "SANDWICHED_REFUNDED"
S_UNPAID = "SANDWICHED_UNPAID"
S_UNCLEAR = "UNCLEAR"
S_NOT_COVERED = "NOT_COVERED"
S_UNVERIFIABLE = "UNVERIFIABLE"
S_EXPIRED = "EXPIRED"
STATES = (S_CLEAN, S_REFUNDED, S_UNPAID, S_UNCLEAR, S_NOT_COVERED, S_UNVERIFIABLE, S_EXPIRED)
FINAL_STATES = (S_CLEAN, S_REFUNDED, S_UNPAID, S_UNCLEAR, S_EXPIRED)
# UNVERIFIABLE for a reason that can pass (an RPC failure, a disagreement, a block
# not final yet): such a case filed inside the claim period may be filed again in
# the recovery window after it; still unread when the pool closes, it is EXPIRED.
TRANSIENT = ("RPC_UNREADABLE", "RPC_DISAGREE", "NOT_FINALIZED", "TX_PENDING")
# weakest -> strongest: what get_case reports for a transaction decided by several pools
STRENGTH = (S_UNVERIFIABLE, S_EXPIRED, S_NOT_COVERED, S_CLEAN, S_UNCLEAR, S_UNPAID, S_REFUNDED)

COUNT_KEYS = ("pools", "create_refused", "top_ups", "top_up_refused", "extensions", "filings", "closes",
              "credit_withdrawals", "sweeps", "refunds", "unpaid") + tuple("state:" + s for s in STATES)

# mode -> (min_claim_period_s, rate_n, rate_window_s, sweep_delay_s, recovery_s)
#   min_claim_period_s  the shortest claim period a pool may set
#   rate_n/window       filings per (pool, sender) per window
#   sweep_delay_s       sweep_stray waits this long after the last send, so a
#                       send posted but not yet finalized is never taken for
#                       stray value
#   recovery_s          after the claim deadline, how long a case left
#                       UNVERIFIABLE for a transient reason may be filed again;
#                       fixed from the deadline, so filings cannot extend it
MODES = {
    "CANONICAL": (3600, 200, 3600, 172800, 3600),
    "DEMO": (60, 60, 600, 3600, 120),
}

MAX_CLAIM_PERIOD_S = 180 * 86400
MAX_EXTEND_S = 180 * 86400      # how far the claim deadline may move past the original
MAX_ROUTERS = 32
MAX_RATES = 12
MAX_SPAN_BLOCKS = 5000000
MAX_NAME = 80
MAX_META = 600
MIN_POOL = 10 ** 15             # 0.001 GEN
MAX_AMOUNT = 10 ** 30
MAX_RATE_PART = 10 ** 30
PAGE_MAX = 50

# INLINE:common
# INLINE:rpc


def _parse_list(raw: typing.Any) -> typing.Any:
    try:
        v = json.loads(raw) if isinstance(raw, str) else raw
    except Exception:
        return None
    return v if isinstance(v, list) else None


def parse_terms(chains_json: typing.Any, routers_json: typing.Any, kinds_json: typing.Any, ranges_json: typing.Any,
                rates_json: typing.Any) -> typing.Any:
    """The frozen coverage terms -> a dict, or a reason string.
    chains ["ethereum"]; routers [{chain, address}]; kinds ["V2", "V3"];
    ranges [{chain, start_block, end_block}]; rates [{chain, token, num, den, symbol, decimals}]."""
    ch = _parse_list(chains_json)
    if ch is None:
        return "CHAINS_BAD_JSON"
    if len(ch) == 0:
        return "CHAINS_EMPTY"
    chains = []
    for c in ch:
        cc = str(c).strip().lower()
        if cc not in CHAINS:
            return "UNSUPPORTED_CHAIN"
        if cc not in chains:
            chains.append(cc)
    chains = sorted(chains)
    ro = _parse_list(routers_json)
    if ro is None:
        return "ROUTERS_BAD_JSON"
    if len(ro) == 0:
        return "ROUTERS_EMPTY"
    if len(ro) > MAX_ROUTERS:
        return "ROUTERS_TOO_MANY"
    rmap = {}
    for it in ro:
        if not isinstance(it, dict):
            return "ROUTERS_BAD_ENTRY"
        c = str(it.get("chain", "")).strip().lower()
        a = _addr(it.get("address", ""))
        if c not in chains:
            return "ROUTERS_CHAIN_NOT_IN_POOL"
        if a == "" or a == ZERO:
            return "ROUTERS_BAD_ADDRESS"
        rmap[c + "|" + a] = {"chain": c, "address": a, "name": clean_text(it.get("name", ""), 40)}
    routers = [rmap[k] for k in sorted(rmap.keys())]
    ki = _parse_list(kinds_json)
    if ki is None:
        return "KINDS_BAD_JSON"
    kinds = []
    for k in ki:
        kk = str(k).strip().upper()
        if kk not in POOL_KINDS:
            return "KINDS_UNKNOWN"
        if kk not in kinds:
            kinds.append(kk)
    if len(kinds) == 0:
        return "KINDS_EMPTY"
    kinds = sorted(kinds)
    ra = _parse_list(ranges_json)
    if ra is None:
        return "RANGES_BAD_JSON"
    ranges = {}
    for it in ra:
        if not isinstance(it, dict):
            return "RANGES_BAD_ENTRY"
        c = str(it.get("chain", "")).strip().lower()
        if c not in chains:
            return "RANGES_CHAIN_NOT_IN_POOL"
        s = _as_int(it.get("start_block"), -1)
        e = _as_int(it.get("end_block"), -1)
        if s < 0 or e < s:
            return "RANGES_BAD_BLOCKS"
        if e - s > MAX_SPAN_BLOCKS:
            return "RANGES_TOO_LONG"
        if c in ranges:
            return "RANGES_DUPLICATE_CHAIN"
        ranges[c] = [s, e]
    for c in chains:
        if c not in ranges:
            return "RANGES_MISSING_CHAIN"
    rt = _parse_list(rates_json)
    if rt is None:
        return "RATES_BAD_JSON"
    if len(rt) == 0:
        return "RATES_EMPTY"
    if len(rt) > MAX_RATES:
        return "RATES_TOO_MANY"
    rates = {}
    for it in rt:
        if not isinstance(it, dict):
            return "RATES_BAD_ENTRY"
        c = str(it.get("chain", "")).strip().lower()
        tk = _addr(it.get("token", ""))
        num = _as_int(it.get("num"), -1)
        den = _as_int(it.get("den"), -1)
        dec = _as_int(it.get("decimals"), 18)
        if c not in chains:
            return "RATES_CHAIN_NOT_IN_POOL"
        if tk == "" or tk == ZERO:
            return "RATES_BAD_TOKEN"
        if num <= 0 or den <= 0 or num > MAX_RATE_PART or den > MAX_RATE_PART:
            return "RATES_BAD_RATE"
        if dec < 0 or dec > 36:
            return "RATES_BAD_DECIMALS"
        if (c + "|" + tk) in rates:
            return "RATES_DUPLICATE_TOKEN"
        rates[c + "|" + tk] = {"chain": c, "token": tk, "num": str(num), "den": str(den),
                               "symbol": clean_text(it.get("symbol", ""), 12), "decimals": dec}
    return {"chains": chains, "routers": routers, "kinds": kinds,
            "ranges": [{"chain": c, "start_block": ranges[c][0], "end_block": ranges[c][1]} for c in chains],
            "rates": [rates[k] for k in sorted(rates.keys())]}


def chain_terms(terms: dict, chain: str) -> dict:
    """A pool's terms for one chain, in the shape judge() reads."""
    rng = [0, -1]
    for r in terms["ranges"]:
        if r["chain"] == chain:
            rng = [int(r["start_block"]), int(r["end_block"])]
    rates = {}
    for r in terms["rates"]:
        if r["chain"] == chain:
            rates[r["token"]] = [int(r["num"]), int(r["den"])]
    return {"routers": [r["address"] for r in terms["routers"] if r["chain"] == chain], "kinds": terms["kinds"],
            "start_block": rng[0], "end_block": rng[1], "rates": rates}


def refund_amount(loss: int, num: int, den: int, max_swap: int, victim_left: int, balance: int) -> list:
    """[amount, why]: min(loss * num // den, max per swap, victim cap left,
    pool balance); why names the binding limit."""
    due = (loss * num) // den
    amt = due
    why = "RATE"
    if max_swap < amt:
        amt = max_swap
        why = "MAX_PER_SWAP"
    if victim_left < amt:
        amt = victim_left
        why = "MAX_PER_VICTIM"
    if balance < amt:
        amt = balance
        why = "POOL_BALANCE"
    if amt < 0:
        amt = 0
    if amt == 0 and why == "RATE":
        why = "REFUND_ROUNDS_TO_ZERO"
    return [amt, why]


# =============================================================================
# storage
# =============================================================================

@gl.storage.allow
@dataclass
class Pool:
    pool_id: u64
    sponsor: str
    name: str
    meta_json: str
    terms_json: str
    max_per_swap: u256
    max_per_victim: u256
    claim_period_s: u64
    created_at: u64
    claim_deadline: u64
    original_deadline: u64
    funded: u256
    balance: u256
    refunded: u256
    returned: u256
    n_cases: u64
    n_refunded: u64
    n_unpaid: u64
    status: str
    closed_at: u64
    closed_by: str
    history_json: str
    pending: u64
    n_expired: u64


@gl.storage.allow
@dataclass
class Case:
    case_id: u64
    chain: str
    tx_hash: str
    pool_id: u64
    filer: str
    filed_at: u64
    attempts: u64
    state: str
    verdict: str
    reason: str
    detail: str
    block: u64
    tx_index: u64
    victim: str
    router: str
    dex_pool: str
    detail_json: str
    profit_token: str
    loss: u256
    refund_due: u256
    refund_paid: u256
    limit: str
    attacker: str


@gl.storage.allow
@dataclass
class Attacker:
    address: str
    contract: str
    n_cases: u64
    refunds: u256
    last_case: u64
    first_seen: u64


class SandwichRefund(gl.contract.Contract):
    mode: str
    deployer: str
    min_claim_period_s: u64
    rate_n: u64
    rate_window_s: u64
    sweep_delay_s: u64
    recovery_s: u64
    last_send_at: u64
    n_pools: u64
    n_cases: u64
    n_attackers: u64
    pools: gl.storage.TreeMap[u64, Pool]
    cases: gl.storage.TreeMap[u64, Case]
    case_by_key: gl.storage.TreeMap[str, u64]
    tx_n: gl.storage.TreeMap[str, u64]
    tx_cases: gl.storage.TreeMap[str, u64]
    pool_cases: gl.storage.TreeMap[str, u64]
    victim_n: gl.storage.TreeMap[str, u64]
    victim_cases: gl.storage.TreeMap[str, u64]
    victim_paid: gl.storage.TreeMap[str, u256]
    pool_victim_n: gl.storage.TreeMap[str, u64]
    pool_victim_cases: gl.storage.TreeMap[str, u64]
    victim_total: gl.storage.TreeMap[str, u256]
    attackers: gl.storage.TreeMap[str, Attacker]
    attacker_idx: gl.storage.TreeMap[u64, str]
    chain_pools: gl.storage.TreeMap[str, u64]
    rate: gl.storage.TreeMap[str, str]
    credits: gl.storage.TreeMap[str, u256]
    counts: gl.storage.TreeMap[str, u64]
    received_total: u256
    open_total: u256
    refunded_total: u256
    returned_total: u256
    credit_owed_total: u256
    credit_paid_total: u256
    stray_swept_total: u256
    loss_total_json: str

    def __init__(self, mode: str) -> None:
        m = str(mode).strip().upper()
        if m not in MODES:
            raise gl.vm.UserError("mode must be CANONICAL or DEMO")
        p = MODES[m]
        self.mode = m
        self.deployer = gl.message.sender_address.as_hex.lower()
        self.min_claim_period_s = u64(p[0])
        self.rate_n = u64(p[1])
        self.rate_window_s = u64(p[2])
        self.sweep_delay_s = u64(p[3])
        self.recovery_s = u64(p[4])
        self.n_pools = u64(0)
        self.n_cases = u64(0)
        self.n_attackers = u64(0)
        self.loss_total_json = "{}"

    # --- helpers --------------------------------------------------------------

    def _now(self) -> int:
        return _epoch_from_iso(gl.message.raw.get("datetime", ""))

    def _sender(self) -> str:
        return gl.message.sender_address.as_hex.lower()

    def _bump(self, key: str, n: int = 1) -> None:
        self.counts[key] = u64(int(self.counts.get(key, u64(0))) + n)

    def _pool(self, pool_id: typing.Any) -> typing.Any:
        pid = _as_int(pool_id, 0)
        if pid <= 0:
            return None
        return self.pools.get(u64(pid))

    def _credit(self, value: int) -> None:
        who = self._sender()
        self.credits[who] = u256(int(self.credits.get(who, u256(0))) + value)
        self.credit_owed_total = u256(int(self.credit_owed_total) + value)
        self.received_total = u256(int(self.received_total) + value)

    def _refuse(self, value: int, reason: str, counter: str) -> dict:
        """A payable refusal: the value is credited back to the sender, never kept, never raised on."""
        if value > 0:
            self._credit(value)
        self._bump(counter)
        return {"ok": False, "reason": reason, "credited": str(value)}

    def _recovery_deadline(self, p: Pool) -> int:
        return int(p.claim_deadline) + int(self.recovery_s)

    def _closable(self, p: Pool, now: int) -> bool:
        return p.status == PS_OPEN and now > int(p.claim_deadline) and (int(p.pending) == 0 or now > self._recovery_deadline(p))

    def _held(self) -> int:
        return int(self.open_total) + int(self.credit_owed_total)

    def _send(self, who: str, amount: int) -> None:
        """The only way GEN leaves: an external value message (EthSend) to
        `who`, applied when this transaction finalizes and paid for by the
        caller's message allocation. Studio Dev skips an internal
        emit_transfer (declared budget 0) and credits the value back, so it is
        never used. Posted in the same call that records the payout: if it
        cannot be posted, the call fails and nothing is recorded."""
        self.last_send_at = u64(self._now())
        gl.evm.Account(Address(who)).emit_call(u256(amount), b"")

    # --- pools ------------------------------------------------------------------

    @gl.public.write.payable
    def create_pool(self, name: str, chains_json: str, routers_json: str, kinds_json: str, ranges_json: str,
                    rates_json: str, max_per_swap: int, max_per_victim: int, claim_period_s: int,
                    meta_json: str) -> typing.Any:
        """Open a pool and lock msg.value in it. Never raises."""
        value = int(gl.message.value)
        now = self._now()
        if now <= 0:
            return self._refuse(value, "NO_CLOCK", "create_refused")
        if value < MIN_POOL:
            return self._refuse(value, "POOL_BELOW_MINIMUM", "create_refused")
        if value > MAX_AMOUNT:
            return self._refuse(value, "POOL_TOO_LARGE", "create_refused")
        nm = clean_text(name, MAX_NAME)
        if nm == "":
            return self._refuse(value, "NAME_REQUIRED", "create_refused")
        terms = parse_terms(chains_json, routers_json, kinds_json, ranges_json, rates_json)
        if isinstance(terms, str):
            return self._refuse(value, terms, "create_refused")
        mps = _as_int(max_per_swap, -1)
        mpv = _as_int(max_per_victim, -1)
        if mps <= 0 or mps > MAX_AMOUNT:
            return self._refuse(value, "BAD_MAX_PER_SWAP", "create_refused")
        if mpv < mps or mpv > MAX_AMOUNT:
            return self._refuse(value, "BAD_MAX_PER_VICTIM", "create_refused")
        cp = _as_int(claim_period_s, -1)
        if cp < int(self.min_claim_period_s) or cp > MAX_CLAIM_PERIOD_S:
            return self._refuse(value, "BAD_CLAIM_PERIOD", "create_refused")
        meta = "{}"
        if str(meta_json).strip() != "":
            try:
                mv = json.loads(meta_json)
            except Exception:
                return self._refuse(value, "META_BAD_JSON", "create_refused")
            if not isinstance(mv, dict):
                return self._refuse(value, "META_NOT_OBJECT", "create_refused")
            meta = _canon(mv)
            if len(meta) > MAX_META:
                return self._refuse(value, "META_TOO_LONG", "create_refused")
        # --- writes
        pid = int(self.n_pools) + 1
        self.pools[u64(pid)] = Pool(
            pool_id=u64(pid), sponsor=self._sender(), name=nm, meta_json=meta, terms_json=_canon(terms),
            max_per_swap=u256(mps), max_per_victim=u256(mpv), claim_period_s=u64(cp), created_at=u64(now),
            claim_deadline=u64(now + cp), original_deadline=u64(now + cp), funded=u256(value), balance=u256(value),
            refunded=u256(0), returned=u256(0), n_cases=u64(0), n_refunded=u64(0), n_unpaid=u64(0), status=PS_OPEN,
            closed_at=u64(0), closed_by="", pending=u64(0), n_expired=u64(0), history_json=_canon([{"at": now, "what": "create", "value": str(value)}]))
        self.n_pools = u64(pid)
        for c in terms["chains"]:
            self.chain_pools[c] = u64(int(self.chain_pools.get(c, u64(0))) + 1)
        self.received_total = u256(int(self.received_total) + value)
        self.open_total = u256(int(self.open_total) + value)
        self._bump("pools")
        return {"ok": True, "pool_id": pid, "funded": str(value), "claim_deadline": now + cp}

    @gl.public.write.payable
    def top_up(self, pool_id: int) -> typing.Any:
        """Add msg.value to an open pool (anyone; it only adds). Never raises."""
        value = int(gl.message.value)
        now = self._now()
        if now <= 0:
            return self._refuse(value, "NO_CLOCK", "top_up_refused")
        p = self._pool(pool_id)
        if p is None:
            return self._refuse(value, "NO_SUCH_POOL", "top_up_refused")
        if p.status != PS_OPEN:
            return self._refuse(value, "POOL_IS_" + p.status, "top_up_refused")
        if now > int(p.claim_deadline):
            return self._refuse(value, "CLAIM_PERIOD_OVER", "top_up_refused")
        if value <= 0:
            return self._refuse(value, "NO_VALUE", "top_up_refused")
        if int(p.funded) + value > MAX_AMOUNT:
            return self._refuse(value, "POOL_TOO_LARGE", "top_up_refused")
        # --- writes
        p.funded = u256(int(p.funded) + value)
        p.balance = u256(int(p.balance) + value)
        h = json.loads(p.history_json)
        h.append({"at": now, "what": "top_up", "value": str(value), "by": self._sender()})
        p.history_json = _canon(h[-40:])
        self.received_total = u256(int(self.received_total) + value)
        self.open_total = u256(int(self.open_total) + value)
        self._bump("top_ups")
        return {"ok": True, "pool_id": int(p.pool_id), "balance": str(int(p.balance))}

    @gl.public.write
    def extend(self, pool_id: int, new_claim_deadline: int) -> typing.Any:
        """The sponsor may move its claim deadline later while the pool is open."""
        now = self._now()
        p = self._pool(pool_id)
        if p is None:
            raise gl.vm.UserError("REFUSED: NO_SUCH_POOL")
        if p.sponsor != self._sender():
            raise gl.vm.UserError("REFUSED: ONLY_THE_SPONSOR")
        if p.status != PS_OPEN:
            raise gl.vm.UserError("REFUSED: POOL_IS_" + p.status)
        if now > int(p.claim_deadline):
            raise gl.vm.UserError("REFUSED: CLAIM_PERIOD_OVER")
        nd = _as_int(new_claim_deadline, -1)
        if nd <= int(p.claim_deadline):
            raise gl.vm.UserError("REFUSED: DEADLINE_CAN_ONLY_MOVE_LATER")
        if nd - int(p.original_deadline) > MAX_EXTEND_S:
            raise gl.vm.UserError("REFUSED: EXTENSION_TOO_LONG")
        # --- writes
        h = json.loads(p.history_json)
        h.append({"at": now, "what": "extend", "from": int(p.claim_deadline), "to": nd})
        p.history_json = _canon(h[-40:])
        p.claim_deadline = u64(nd)
        self._bump("extensions")
        return {"ok": True, "pool_id": int(p.pool_id), "claim_deadline": nd}

    @gl.public.write
    def close_pool(self, pool_id: int) -> typing.Any:
        """Anyone, after the claim deadline - and, while cases filed in the claim
        period are UNVERIFIABLE for a transient reason, after the recovery
        window - what is left goes back to the sponsor. Past the recovery window
        it always succeeds; those cases become EXPIRED."""
        now = self._now()
        if now <= 0:
            raise gl.vm.UserError("REFUSED: NO_CLOCK")
        p = self._pool(pool_id)
        if p is None:
            raise gl.vm.UserError("REFUSED: NO_SUCH_POOL")
        if p.status != PS_OPEN:
            raise gl.vm.UserError("REFUSED: ALREADY_" + p.status)
        if now <= int(p.claim_deadline):
            raise gl.vm.UserError("REFUSED: CLAIM_PERIOD_OPEN_UNTIL_" + str(int(p.claim_deadline)))
        if int(p.pending) > 0 and now <= self._recovery_deadline(p):
            raise gl.vm.UserError("REFUSED: RECOVERY_WINDOW_OPEN_UNTIL_" + str(self._recovery_deadline(p)))
        rest = int(p.balance)
        if int(self.balance) < rest:
            raise gl.vm.UserError("REFUSED: CONTRACT_BALANCE_BELOW_POOL")
        # --- writes
        p.status = PS_CLOSED
        p.closed_at = u64(now)
        p.closed_by = self._sender()
        p.returned = u256(rest)
        p.balance = u256(0)
        expired = int(p.pending)
        if expired > 0:
            # cases still unread for a transient reason end here: EXPIRED, final
            p.n_expired = u64(expired)
            p.pending = u64(0)
            self._bump("state:" + S_UNVERIFIABLE, -expired)
            self._bump("state:" + S_EXPIRED, expired)
        self.open_total = u256(int(self.open_total) - rest)
        self.returned_total = u256(int(self.returned_total) + rest)
        self._bump("closes")
        if rest > 0:
            self._send(p.sponsor, rest)
        return {"ok": True, "pool_id": int(p.pool_id), "returned": str(rest), "to": p.sponsor, "expired": expired}

    # --- cases ------------------------------------------------------------------

    @gl.public.write
    def file_case(self, pool_id: int, chain: str, tx_hash: str) -> typing.Any:
        """Anyone: one victim transaction against one open pool. Read by every
        validator from both RPCs of its chain, judged, recorded; a SANDWICHED
        victim is refunded in this call. The caller funds the refund's
        external message (an allocation naming the victim)."""
        now = self._now()
        if now <= 0:
            raise gl.vm.UserError("REFUSED: NO_CLOCK")
        p = self._pool(pool_id)
        if p is None:
            raise gl.vm.UserError("REFUSED: NO_SUCH_POOL")
        if p.status != PS_OPEN:
            raise gl.vm.UserError("REFUSED: POOL_IS_" + p.status)
        terms = json.loads(p.terms_json)
        ch = str(chain).strip().lower()
        if ch not in terms["chains"]:
            raise gl.vm.UserError("REFUSED: CHAIN_NOT_IN_POOL")
        h = _hash32(tx_hash)
        if h == "":
            raise gl.vm.UserError("REFUSED: BAD_HASH")
        key = str(int(p.pool_id)) + ":" + ch + ":" + h
        cid = int(self.case_by_key.get(key, u64(0)))
        old = self.cases.get(u64(cid)) if cid > 0 else None
        if old is not None and old.state in FINAL_STATES:
            raise gl.vm.UserError("REFUSED: ALREADY_DECIDED_" + old.state)
        old_pending = old is not None and old.state == S_UNVERIFIABLE and old.reason in TRANSIENT
        if now > int(p.claim_deadline):
            # the recovery window: only a case already pending for a transient reason
            if not old_pending:
                raise gl.vm.UserError("REFUSED: CLAIM_PERIOD_OVER")
            if now > self._recovery_deadline(p):
                raise gl.vm.UserError("REFUSED: RECOVERY_WINDOW_OVER")
        who = self._sender()
        rk = str(int(p.pool_id)) + "|" + who
        w = self.rate.get(rk)
        ws = 0
        wn = 0
        if w is not None and w != "":
            cut = w.find(",")
            ws = int(w[:cut])
            wn = int(w[cut + 1:])
        if now - ws >= int(self.rate_window_s):
            ws = now
            wn = 0
        if wn + 1 > int(self.rate_n):
            raise gl.vm.UserError("REFUSED: RATE_LIMITED_UNTIL_" + str(ws + int(self.rate_window_s)))

        def leader() -> dict:
            return read_case(ch, h)

        def validator(res: gl.vm.Result) -> bool:
            try:
                return agree(res)
            except Exception:
                return False

        def agree(res: gl.vm.Result) -> bool:
            if not isinstance(res, gl.vm.Return):
                return False
            got = res.calldata
            if not isinstance(got, dict):
                return False
            mine = read_case(ch, h)
            if "reason" in got and "reason" in mine:
                return True         # both unreadable: UNVERIFIABLE, resubmittable
            if "facts" in got and isinstance(got["facts"], dict) and got["facts"].get("final") is not True:
                return True         # the leader saw it unfinalized: UNVERIFIABLE, resubmittable
            if "facts" not in got or "facts" not in mine:
                return False
            a = dict(got["facts"])
            b = dict(mine["facts"])
            if b.get("final") is not True:
                return False
            a["final"] = True
            b["final"] = True
            return _canon(a) == _canon(b)

        r = gl.vm.run_nondet(leader, validator)
        if not isinstance(r, dict) or ("reason" not in r and not isinstance(r.get("facts"), dict)):
            r = {"reason": "RPC_UNREADABLE", "detail": "no answer"}
        j = judge(chain_terms(terms, ch), r)
        verdict = j["verdict"]
        state = verdict
        loss = 0
        due = 0
        paid = 0
        limit = ""
        victim = str(j.get("victim", ""))
        pk = str(int(p.pool_id)) + "|" + victim
        if verdict == V_SANDWICHED:
            loss = int(j["profit"])
            rate = chain_terms(terms, ch)["rates"][j["profit_token"]]
            due = (loss * rate[0]) // rate[1]
            left = int(p.max_per_victim) - int(self.victim_paid.get(pk, u256(0)))
            ra = refund_amount(loss, rate[0], rate[1], int(p.max_per_swap), left, int(p.balance))
            paid = ra[0]
            limit = ra[1]
            state = S_REFUNDED if paid > 0 else S_UNPAID
            if paid > 0 and int(self.balance) < paid:
                raise gl.vm.UserError("REFUSED: CONTRACT_BALANCE_BELOW_REFUND")
        detail = {}
        for k in ("pool", "kind", "direction", "token_in", "token_out", "victim_n0", "victim_n1", "front_tx",
                  "front_index", "back_tx", "back_index", "attacker_eoa", "attacker_contract", "attacker_recipient",
                  "front_n0", "front_n1", "back_n0", "back_n1", "hops", "attackers", "others"):
            if k in j:
                detail[k] = j[k]
        # --- writes
        if old is None:
            cid = int(self.n_cases) + 1
            self.n_cases = u64(cid)
            self.case_by_key[key] = u64(cid)
            tn = int(self.tx_n.get(ch + ":" + h, u64(0)))
            self.tx_cases[ch + ":" + h + ":" + str(tn)] = u64(cid)
            self.tx_n[ch + ":" + h] = u64(tn + 1)
            c = Case(case_id=u64(cid), chain=ch, tx_hash=h, pool_id=p.pool_id, filer=who, filed_at=u64(now),
                     attempts=u64(0), state="", verdict="", reason="", detail="", block=u64(0), tx_index=u64(0),
                     victim="", router="", dex_pool="", detail_json="{}", profit_token="", loss=u256(0),
                     refund_due=u256(0), refund_paid=u256(0), limit="", attacker="")
            self.cases[u64(cid)] = c
            c = self.cases[u64(cid)]
        else:
            c = old
            self._bump("state:" + c.state, -1)
        if victim != "" and c.victim != victim:
            vn = int(self.victim_n.get(victim, u64(0)))
            self.victim_cases[victim + ":" + str(vn)] = u64(cid)
            self.victim_n[victim] = u64(vn + 1)
            pv = str(int(p.pool_id)) + "|" + victim
            pvn = int(self.pool_victim_n.get(pv, u64(0)))
            self.pool_victim_cases[pv + ":" + str(pvn)] = u64(cid)
            self.pool_victim_n[pv] = u64(pvn + 1)
        if old is None:
            pn = int(p.n_cases)
            self.pool_cases[str(int(p.pool_id)) + ":" + str(pn)] = u64(cid)
            p.n_cases = u64(pn + 1)
        new_pending = state == S_UNVERIFIABLE and str(j["reason"]) in TRANSIENT
        p.pending = u64(int(p.pending) + (1 if new_pending else 0) - (1 if old_pending else 0))
        c.filer = who
        c.filed_at = u64(now)
        c.attempts = u64(int(c.attempts) + 1)
        c.state = state
        c.verdict = verdict
        c.reason = str(j["reason"])
        c.detail = clean_text(r.get("detail", ""), 100) if verdict == V_UNVERIFIABLE else ""
        c.block = u64(int(j.get("block", 0)))
        c.tx_index = u64(int(j.get("index", 0)))
        c.victim = victim
        c.router = str(j.get("router", ""))
        c.dex_pool = str(j.get("pool", ""))
        c.detail_json = _canon(detail)
        c.profit_token = str(j.get("profit_token", ""))
        c.loss = u256(loss)
        c.refund_due = u256(due)
        c.refund_paid = u256(paid)
        c.limit = limit
        c.attacker = str(j.get("attacker_eoa", "")) if verdict == V_SANDWICHED else ""
        self._bump("filings")
        self._bump("state:" + state)
        self.rate[rk] = str(ws) + "," + str(wn + 1)
        if verdict == V_SANDWICHED:
            att = str(j["attacker_eoa"])
            a = self.attackers.get(att)
            if a is None:
                ai = int(self.n_attackers)
                self.attacker_idx[u64(ai)] = att
                self.n_attackers = u64(ai + 1)
                self.attackers[att] = Attacker(address=att, contract=str(j.get("attacker_contract", "")),
                                               n_cases=u64(0), refunds=u256(0), last_case=u64(0), first_seen=u64(cid))
                a = self.attackers[att]
            a.n_cases = u64(int(a.n_cases) + 1)
            a.refunds = u256(int(a.refunds) + paid)
            a.last_case = u64(cid)
            lt = json.loads(self.loss_total_json)
            tk = ch + "|" + c.profit_token
            lt[tk] = str(int(lt.get(tk, "0")) + loss)
            self.loss_total_json = _canon(lt)
            self.victim_total[victim] = u256(int(self.victim_total.get(victim, u256(0))) + paid)
            if paid > 0:
                self.victim_paid[pk] = u256(int(self.victim_paid.get(pk, u256(0))) + paid)
                p.balance = u256(int(p.balance) - paid)
                p.refunded = u256(int(p.refunded) + paid)
                p.n_refunded = u64(int(p.n_refunded) + 1)
                self.open_total = u256(int(self.open_total) - paid)
                self.refunded_total = u256(int(self.refunded_total) + paid)
                self._bump("refunds")
                self._send(victim, paid)
            else:
                p.n_unpaid = u64(int(p.n_unpaid) + 1)
                self._bump("unpaid")
        return {"ok": True, "case_id": cid, "state": state, "reason": c.reason, "victim": victim,
                "refund": str(paid), "limit": limit, "loss": str(loss)}

    @gl.public.write
    def withdraw_refund(self) -> typing.Any:
        """Value a refused create_pool or top_up credited back to the caller."""
        who = self._sender()
        amt = int(self.credits.get(who, u256(0)))
        if amt <= 0:
            raise gl.vm.UserError("REFUSED: NOTHING_TO_WITHDRAW")
        if int(self.balance) < amt:
            raise gl.vm.UserError("REFUSED: CONTRACT_BALANCE_BELOW_CREDIT")
        # --- writes
        self.credits[who] = u256(0)
        self.credit_owed_total = u256(int(self.credit_owed_total) - amt)
        self.credit_paid_total = u256(int(self.credit_paid_total) + amt)
        self._bump("credit_withdrawals")
        self._send(who, amt)
        return {"ok": True, "withdrawn": str(amt)}

    @gl.public.write
    def sweep_stray(self) -> typing.Any:
        """GEN in the balance above what the ledger holds arrived outside the
        payable methods (the runtime keeps value sent with a failing or
        non-payable call). It belongs to no pool; anyone may send it to the
        deployer."""
        now = self._now()
        if now <= 0:
            raise gl.vm.UserError("REFUSED: NO_CLOCK")
        if now < int(self.last_send_at) + int(self.sweep_delay_s):
            raise gl.vm.UserError("REFUSED: SENDS_MAY_BE_PENDING_UNTIL_" + str(int(self.last_send_at) + int(self.sweep_delay_s)))
        stray = int(self.balance) - self._held()
        if stray <= 0:
            raise gl.vm.UserError("REFUSED: NO_STRAY_BALANCE")
        # --- writes
        self.stray_swept_total = u256(int(self.stray_swept_total) + stray)
        self._bump("sweeps")
        self._send(self.deployer, stray)
        return {"ok": True, "swept": str(stray), "to": self.deployer}

    # --- views (storage only) -------------------------------------------------

    def _pool_view(self, p: Pool, now: int) -> dict:
        t = json.loads(p.terms_json)
        return {"pool_id": int(p.pool_id), "sponsor": p.sponsor, "name": p.name, "meta": json.loads(p.meta_json),
                "status": p.status, "chains": t["chains"], "routers": t["routers"], "kinds": t["kinds"],
                "ranges": t["ranges"], "rates": t["rates"], "max_per_swap": str(int(p.max_per_swap)),
                "max_per_victim": str(int(p.max_per_victim)), "claim_period_s": int(p.claim_period_s),
                "created_at": int(p.created_at), "claim_deadline": int(p.claim_deadline),
                "original_deadline": int(p.original_deadline), "funded": str(int(p.funded)),
                "balance": str(int(p.balance)), "refunded": str(int(p.refunded)), "returned": str(int(p.returned)),
                "n_cases": int(p.n_cases), "n_refunded": int(p.n_refunded), "n_unpaid": int(p.n_unpaid),
                "closed_at": int(p.closed_at), "closed_by": p.closed_by, "history": json.loads(p.history_json),
                "recovery_deadline": self._recovery_deadline(p), "pending": int(p.pending), "n_expired": int(p.n_expired),
                "due": "CLOSE" if self._closable(p, now) else ("RETRY" if p.status == PS_OPEN and now > int(p.claim_deadline) else "")}

    def _state(self, c: Case) -> str:
        """A case left UNVERIFIABLE for a transient reason reads EXPIRED once its pool is closed."""
        if c.state == S_UNVERIFIABLE and c.reason in TRANSIENT:
            p = self.pools.get(c.pool_id)
            if p is not None and p.status == PS_CLOSED:
                return S_EXPIRED
        return c.state

    def _case_view(self, c: Case) -> dict:
        st = self._state(c)
        return {"case_id": int(c.case_id), "chain": c.chain, "tx_hash": c.tx_hash, "pool_id": int(c.pool_id),
                "filer": c.filer, "filed_at": int(c.filed_at), "attempts": int(c.attempts), "state": st,
                "final": st in FINAL_STATES, "verdict": c.verdict, "reason": c.reason, "detail": c.detail,
                "block": int(c.block), "tx_index": int(c.tx_index), "victim": c.victim, "router": c.router,
                "dex_pool": c.dex_pool, "facts": json.loads(c.detail_json), "profit_token": c.profit_token,
                "loss": str(int(c.loss)), "refund_due": str(int(c.refund_due)), "refund_paid": str(int(c.refund_paid)),
                "limit": c.limit, "attacker": c.attacker}

    @gl.public.view
    def get_pool(self, pool_id: int, now: int) -> typing.Any:
        p = self._pool(pool_id)
        if p is None:
            return {"found": False, "pool_id": _as_int(pool_id, 0)}
        out = self._pool_view(p, _as_int(now, 0))
        out["found"] = True
        return out

    def _page(self, offset: typing.Any, limit: typing.Any) -> list:
        return [max(_as_int(offset, 0), 0), min(max(_as_int(limit, PAGE_MAX), 1), PAGE_MAX)]

    @gl.public.view
    def get_pools(self, offset: int, limit: int, now: int) -> typing.Any:
        """Pools offset+1 .. offset+limit (ids are 1..n), oldest first. `due`
        is CLOSE when the claim deadline is before `now` (the caller's clock;
        close_pool re-checks with the chain's)."""
        pg = self._page(offset, limit)
        n = int(self.n_pools)
        items = []
        i = pg[0] + 1
        while i <= n and len(items) < pg[1]:
            p = self.pools.get(u64(i))
            if p is not None:
                items.append(self._pool_view(p, _as_int(now, 0)))
            i += 1
        return {"total": n, "offset": pg[0], "limit": pg[1], "items": items,
                "next_offset": pg[0] + len(items) if pg[0] + len(items) < n else -1}

    @gl.public.view
    def get_case(self, chain: str, tx_hash: str) -> typing.Any:
        """One victim transaction across every pool it was filed against. The
        top-level fields are those of its strongest decision (SANDWICHED_REFUNDED
        > SANDWICHED_UNPAID > UNCLEAR > CLEAN > NOT_COVERED > UNVERIFIABLE; on a
        tie the larger refund);
        `decisions` lists every pool's (up to PAGE_MAX)."""
        ch = str(chain).strip().lower()
        h = _hash32(tx_hash)
        k = ch + ":" + h
        n = int(self.tx_n.get(k, u64(0))) if h != "" else 0
        pools = int(self.chain_pools.get(ch, u64(0)))
        if n == 0:
            return {"found": False, "chain": ch, "tx_hash": h, "pools_on_chain": pools}
        best = None
        rank = -1
        decisions = []
        paid = 0
        for i in range(n):
            c = self.cases.get(u64(int(self.tx_cases.get(k + ":" + str(i), u64(0)))))
            if c is None:
                continue
            r = STRENGTH.index(self._state(c)) if self._state(c) in STRENGTH else -1
            if r > rank or (r == rank and best is not None and int(c.refund_paid) > int(best.refund_paid)):
                rank = r
                best = c
            paid += int(c.refund_paid)
            if len(decisions) < PAGE_MAX:
                decisions.append(self._case_view(c))
        if best is None:
            return {"found": False, "chain": ch, "tx_hash": h, "pools_on_chain": pools}
        out = self._case_view(best)
        out["found"] = True
        out["pools_on_chain"] = pools
        out["n_decisions"] = n
        out["decisions"] = decisions
        out["refund_paid_all_pools"] = str(paid)
        return out

    @gl.public.view
    def get_pool_case(self, pool_id: int, chain: str, tx_hash: str) -> typing.Any:
        """The decision of one pool on one victim transaction."""
        ch = str(chain).strip().lower()
        h = _hash32(tx_hash)
        cid = int(self.case_by_key.get(str(_as_int(pool_id, 0)) + ":" + ch + ":" + h, u64(0))) if h != "" else 0
        c = self.cases.get(u64(cid)) if cid > 0 else None
        if c is None:
            return {"found": False, "pool_id": _as_int(pool_id, 0), "chain": ch, "tx_hash": h}
        out = self._case_view(c)
        out["found"] = True
        return out

    @gl.public.view
    def get_case_by_id(self, case_id: int) -> typing.Any:
        c = self.cases.get(u64(max(_as_int(case_id, 0), 0)))
        if c is None:
            return {"found": False}
        out = self._case_view(c)
        out["found"] = True
        return out

    @gl.public.view
    def get_cases(self, offset: int, limit: int) -> typing.Any:
        """Every case, by id (1..n), oldest first."""
        pg = self._page(offset, limit)
        n = int(self.n_cases)
        items = []
        i = pg[0] + 1
        while i <= n and len(items) < pg[1]:
            c = self.cases.get(u64(i))
            if c is not None:
                items.append(self._case_view(c))
            i += 1
        return {"total": n, "offset": pg[0], "limit": pg[1], "items": items,
                "next_offset": pg[0] + len(items) if pg[0] + len(items) < n else -1}

    @gl.public.view
    def get_pool_cases(self, pool_id: int, offset: int, limit: int) -> typing.Any:
        p = self._pool(pool_id)
        if p is None:
            return {"found": False, "total": 0, "items": [], "next_offset": -1}
        pg = self._page(offset, limit)
        n = int(p.n_cases)
        items = []
        i = pg[0]
        while i < n and len(items) < pg[1]:
            cid = int(self.pool_cases.get(str(int(p.pool_id)) + ":" + str(i), u64(0)))
            c = self.cases.get(u64(cid)) if cid > 0 else None
            if c is not None:
                items.append(self._case_view(c))
            i += 1
        return {"found": True, "pool_id": int(p.pool_id), "total": n, "offset": pg[0], "limit": pg[1],
                "items": items, "next_offset": pg[0] + len(items) if pg[0] + len(items) < n else -1}

    @gl.public.view
    def get_victim(self, address: str, offset: int, limit: int) -> typing.Any:
        """An address's cases (as the victim, i.e. the swap's sender) and its
        refund total across pools."""
        a = _addr(address)
        pg = self._page(offset, limit)
        n = int(self.victim_n.get(a, u64(0))) if a != "" else 0
        items = []
        i = pg[0]
        while i < n and len(items) < pg[1]:
            cid = int(self.victim_cases.get(a + ":" + str(i), u64(0)))
            c = self.cases.get(u64(cid)) if cid > 0 else None
            if c is not None:
                items.append(self._case_view(c))
            i += 1
        return {"address": a, "total": n, "offset": pg[0], "limit": pg[1], "items": items,
                "refunded": str(int(self.victim_total.get(a, u256(0)))) if a != "" else "0",
                "next_offset": pg[0] + len(items) if pg[0] + len(items) < n else -1}

    @gl.public.view
    def get_pool_victim(self, pool_id: int, address: str, offset: int, limit: int) -> typing.Any:
        """One pool's cases of one address (as the victim) and what that pool paid it."""
        pid = _as_int(pool_id, 0)
        a = _addr(address)
        pv = str(pid) + "|" + a
        pg = self._page(offset, limit)
        n = int(self.pool_victim_n.get(pv, u64(0))) if a != "" else 0
        items = []
        i = pg[0]
        while i < n and len(items) < pg[1]:
            cid = int(self.pool_victim_cases.get(pv + ":" + str(i), u64(0)))
            c = self.cases.get(u64(cid)) if cid > 0 else None
            if c is not None:
                items.append(self._case_view(c))
            i += 1
        return {"pool_id": pid, "address": a, "total": n, "offset": pg[0], "limit": pg[1], "items": items,
                "refunded": str(int(self.victim_paid.get(pv, u256(0)))) if a != "" else "0",
                "next_offset": pg[0] + len(items) if pg[0] + len(items) < n else -1}

    @gl.public.view
    def get_attackers(self, offset: int, limit: int) -> typing.Any:
        """Attacker EOAs of SANDWICHED cases, in the order first seen."""
        pg = self._page(offset, limit)
        n = int(self.n_attackers)
        items = []
        i = pg[0]
        while i < n and len(items) < pg[1]:
            k = self.attacker_idx.get(u64(i), "")
            a = self.attackers.get(k) if k != "" else None
            if a is not None:
                items.append({"address": a.address, "contract": a.contract, "n_cases": int(a.n_cases),
                              "refunds": str(int(a.refunds)), "last_case": int(a.last_case),
                              "first_case": int(a.first_seen)})
            i += 1
        return {"total": n, "offset": pg[0], "limit": pg[1], "items": items,
                "next_offset": pg[0] + len(items) if pg[0] + len(items) < n else -1}

    @gl.public.view
    def get_credit(self, who: str) -> typing.Any:
        return {"address": _addr(who), "credit": str(int(self.credits.get(_addr(who), u256(0))))}

    @gl.public.view
    def get_config(self) -> typing.Any:
        return {"version": VERSION, "contract": "SandwichRefund", "mode": self.mode, "deployer": self.deployer,
                "min_claim_period_s": int(self.min_claim_period_s), "max_claim_period_s": MAX_CLAIM_PERIOD_S,
                "max_extend_s": MAX_EXTEND_S, "rate_n": int(self.rate_n), "rate_window_s": int(self.rate_window_s),
                "sweep_delay_s": int(self.sweep_delay_s), "recovery_s": int(self.recovery_s), "transient": list(TRANSIENT), "last_send_at": int(self.last_send_at),
                "max_routers": MAX_ROUTERS, "max_rates": MAX_RATES, "max_span_blocks": MAX_SPAN_BLOCKS,
                "max_pools_per_case": MAX_POOLS, "max_txs_per_block": MAX_TXS, "min_pool": str(MIN_POOL),
                "page_max": PAGE_MAX, "states": list(STATES), "final_states": list(FINAL_STATES),
                "kinds": list(POOL_KINDS), "swap_topics": {"V2": SWAP_V2, "V3": SWAP_V3},
                "chains": {k: {"chain_id": CHAINS[k][0], "rpcs": list(CHAINS[k][1]),
                               "factories": {kk: list(FACTORIES[k][kk]) for kk in FACTORIES[k]}} for k in CHAINS}}

    @gl.public.view
    def get_stats(self) -> typing.Any:
        c = {}
        for k in COUNT_KEYS:
            c[k] = int(self.counts.get(k, u64(0)))
        return {"pools": int(self.n_pools), "cases": int(self.n_cases), "attackers": int(self.n_attackers),
                "counts": c, "received_total": str(int(self.received_total)), "open_total": str(int(self.open_total)),
                "refunded_total": str(int(self.refunded_total)), "returned_total": str(int(self.returned_total)),
                "credit_owed_total": str(int(self.credit_owed_total)),
                "credit_paid_total": str(int(self.credit_paid_total)),
                "stray_swept_total": str(int(self.stray_swept_total)), "loss_total": json.loads(self.loss_total_json),
                "held": str(self._held()), "balance": str(int(self.balance))}
