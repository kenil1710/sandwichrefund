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
               "UNVERIFIABLE")
REGISTRY_STATES = ("CLEAN", "SANDWICHED_REFUNDED", "SANDWICHED_UNPAID", "UNCLEAR", "NOT_COVERED", "UNVERIFIABLE")
FINAL = ("CLEAN", "SANDWICHED_REFUNDED", "SANDWICHED_UNPAID", "UNCLEAR")
# the address summary is the worst state among its cases, in this order
SEVERITY = ("SANDWICHED_UNPAID", "UNCLEAR", "UNVERIFIABLE", "SANDWICHED_REFUNDED", "NOT_COVERED", "CLEAN")
PAGE_MAX = 50
MAX_ADDRESS_CASES = 200

# ==== shared helpers: contracts/shared/common.py, inlined by tools/build.py; edit there ====
# The runner rejects the str replace method; slice around find() instead.

# chain -> (chain id, (RPC A, RPC B)). A case is read from BOTH RPCs of its
# chain and refused unless they answer identically. The two are run by
# different operators and serve old receipts, eth_getLogs filtered by pool,
# JSON-RPC batches of a dozen calls and the "finalized" tag, from GenVM with
# every validator reading at once (docs/FEASIBILITY.md). tools/lib/chains.mjs
# holds the same table.
CHAINS = {
    "ethereum": (1, ("https://rpc.mevblocker.io", "https://eth-mainnet.public.blastapi.io")),
}
SWAP_V2 = "0xd78ad95fa46c994b6551d0da85fc275fe613ce37657fb8d5e3d130840159d822"
SWAP_V3 = "0xc42079f94a6350d7e6235f29174924f928cc2ac818eb64fed8004e115fbcca67"
POOL_KINDS = ("V2", "V3")
# Pools count only if their factory() is listed here AND that factory maps the
# pool's tokens (and fee) back to the pool: getPair / getPool. A look-alike
# contract emitting the same Swap event fails the second check.
FACTORIES = {
    "ethereum": {
        "V2": ("0x5c69bee701ef814a2b6a3edd4b1652cb9cc5aa6f", "0xc0aee478e3658e2610c5f7a4a2e1777ce9e4f2ac"),
        "V3": ("0x1f98431c8ad98523631ae4a59f267346ea31f984",),
    },
}
RPC_TRIES = 4
BATCH_MAX = 12          # calls per JSON-RPC batch (both RPCs answer 12 from GenVM)
MAX_POOLS = 4           # Swap pools in one victim transaction that are read
MAX_TXS = 40            # other transactions on those pools in the victim's block
ZERO = "0x" + "0" * 40

V_CLEAN = "CLEAN"
V_SANDWICHED = "SANDWICHED"
V_UNCLEAR = "UNCLEAR"
V_NOT_COVERED = "NOT_COVERED"
V_UNVERIFIABLE = "UNVERIFIABLE"


def _as_int(v: typing.Any, default: int = -1) -> int:
    if isinstance(v, bool):
        return default
    if isinstance(v, int):
        return v
    if isinstance(v, str):
        t = v.strip()
        if t != "" and t.isdigit() and len(t) <= 78:
            return int(t)
    return default


def _is_hex(s: typing.Any, n: int = -1) -> bool:
    if not isinstance(s, str) or (n >= 0 and len(s) != n):
        return False
    for ch in s:
        if ch not in "0123456789abcdef":
            return False
    return True


def _addr(v: typing.Any) -> str:
    """A lowercase 0x address, or "" if v is not one."""
    t = str(v).strip().lower()
    if len(t) != 42 or not t.startswith("0x"):
        return ""
    return t if _is_hex(t[2:], 40) else ""


def _hash32(v: typing.Any) -> str:
    t = str(v).strip().lower()
    if len(t) != 66 or not t.startswith("0x") or not _is_hex(t[2:], 64):
        return ""
    return t


def _hex_int(v: typing.Any) -> int:
    """0x-prefixed hex quantity -> int, or -1."""
    if not isinstance(v, str):
        return -1
    t = v.strip().lower()
    if not t.startswith("0x") or len(t) < 3 or len(t) > 66 or not _is_hex(t[2:]):
        return -1
    return int(t[2:], 16)


def _word_addr(v: typing.Any) -> str:
    """A 32-byte word (a topic or an eth_call answer) holding an address -> the address, or ""."""
    t = _hash32(v)
    if t == "" or t[2:26] != "0" * 24:
        return ""
    return "0x" + t[26:]


def _s256(h: str) -> int:
    v = int(h, 16)
    if v >= (1 << 255):
        v -= (1 << 256)
    return v


def _canon(obj: typing.Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"))


def _days_from_civil(y: int, m: int, d: int) -> int:
    y -= 1 if m <= 2 else 0
    era = (y if y >= 0 else y - 399) // 400
    yoe = y - era * 400
    doy = (153 * (m + (-3 if m > 2 else 9)) + 2) // 5 + d - 1
    doe = yoe * 365 + yoe // 4 - yoe // 100 + doy
    return era * 146097 + doe - 719468


def _civil_from_days(z: int) -> tuple:
    z += 719468
    era = (z if z >= 0 else z - 146096) // 146097
    doe = z - era * 146097
    yoe = (doe - doe // 1460 + doe // 36524 - doe // 146096) // 365
    y = yoe + era * 400
    doy = doe - (365 * yoe + yoe // 4 - yoe // 100)
    mp = (5 * doy + 2) // 153
    d = doy - (153 * mp + 2) // 5 + 1
    m = mp + 3 if mp < 10 else mp - 9
    return (y + (1 if m <= 2 else 0), m, d)


def _epoch_from_iso(value: typing.Any) -> int:
    """Seconds since the epoch from gl.message.raw["datetime"]
    ("2026-10-07T12:00:00Z" or with fractional seconds), identical on every
    validator. 0 if unreadable."""
    if not isinstance(value, str) or len(value) < 19:
        return 0
    try:
        year = int(value[0:4])
        month = int(value[5:7])
        day = int(value[8:10])
        hour = int(value[11:13])
        minute = int(value[14:16])
        second = int(value[17:19])
    except Exception:
        return 0
    if month < 1 or month > 12 or day < 1 or day > 31 or hour > 23 or minute > 59 or second > 60:
        return 0
    return _days_from_civil(year, month, day) * 86400 + hour * 3600 + minute * 60 + second


def clean_text(text: typing.Any, n: int) -> str:
    """Printable ASCII only, no markup characters, whitespace collapsed, at most n chars."""
    out = ""
    for ch in str(text):
        if " " <= ch <= "~" and ch not in "<>\"'`\\":
            out += ch
    return " ".join(out.split())[:n]


# =============================================================================
# the rule (pure: the offline suite calls it on every shape)
# =============================================================================

def swap_dir(s: dict) -> int:
    """0: the pool received token0 and paid token1; 1: the reverse; -1: neither."""
    a = int(s["n0"])
    b = int(s["n1"])
    if a > 0 and b < 0:
        return 0
    if b > 0 and a < 0:
        return 1
    return -1


def _n(s: dict, i: int) -> int:
    return int(s["n0"]) if i == 0 else int(s["n1"])


def attacker_profit(f: dict, b: dict, d: int) -> typing.Any:
    """The attacker's net gain from front-run f and back-run b around a victim
    trading direction d (X = token d in, Y = the other token out), counted
    conservatively:
      netX = X out of the back-run - X into the front-run
      netY = Y out of the front-run - Y into the back-run
      netX > 0, netY >= 0  -> netX in X           (the classic case)
      netY > 0, netX >= 0  -> netY in Y
      netX > 0 > netY      -> only the part of the back-run that sells the
                              front-run's Y counts: bXout*fYout//bYin - fXin
      netY > 0 > netX      -> Y left after buying back the front-run's X:
                              fYout - ceil(bYin*fXin/bXout)
    -> {"token": index, "amount": n, "alt": {...} or None} or None (no gain)."""
    e = 1 - d
    fx = _n(f, d)
    fy = -_n(f, e)
    by = _n(b, e)
    bx = -_n(b, d)
    if fx <= 0 or fy <= 0 or by <= 0 or bx <= 0:
        return None
    nx = bx - fx
    ny = fy - by
    if nx > 0 and ny >= 0:
        return {"token": d, "amount": nx, "alt": {"token": e, "amount": ny} if ny > 0 else None}
    if ny > 0 and nx >= 0:
        return {"token": e, "amount": ny, "alt": None}
    if nx > 0 and ny < 0:
        px = (bx * fy) // by - fx
        return {"token": d, "amount": px, "alt": None} if px > 0 else None
    if ny > 0 and nx < 0:
        need = (by * fx + bx - 1) // bx
        py = fy - need
        return {"token": e, "amount": py, "alt": None} if py > 0 else None
    return None


def analyze_pool(facts: dict, v: dict, exclude: dict) -> dict:
    """The victim's pool in its block: front/back pairs (same actor, front
    before in the victim's direction, back after in the opposite one) and,
    when there is none, whether anything partial is there."""
    t = facts["tx"]
    d = swap_dir(v)
    same = []
    nxt = []
    for s in facts["swaps"]:
        if s["pool"] != v["pool"]:
            continue
        if s["block"] == t["block"] and s["tx"] != t["hash"]:
            same.append(s)
        elif s["block"] == t["block"] + 1:
            nxt.append(s)
    before = [s for s in same if s["ti"] < t["index"]]
    after = [s for s in same if s["ti"] > t["index"]]

    def link(x: dict, y: dict) -> bool:
        if x["from"] == y["from"]:
            return True
        return x["recipient"] == y["recipient"] and not exclude.get(x["recipient"], False)

    pairs = []
    if d >= 0:
        for x in before:
            if swap_dir(x) != d:
                continue
            for y in after:
                if swap_dir(y) == 1 - d and link(x, y):
                    pairs.append({"f": x, "b": y})
    partial = ""
    if len(pairs) == 0:
        for x in before:
            for y in after:
                if link(x, y):
                    partial = "PARTIAL_PATTERN"
        if partial == "" and d >= 0:
            for x in before:
                if swap_dir(x) != d or exclude.get(x["recipient"], False):
                    continue
                for y in nxt:
                    if y["recipient"] == x["recipient"] and swap_dir(y) == 1 - d:
                        partial = "CROSS_BLOCK_PATTERN"
    return {"pairs": pairs, "partial": partial, "same": same}


def _cluster(pairs: list, exclude: dict) -> list:
    """Pairs that share an EOA or a Swap recipient are one attacker."""
    groups = []
    for p in pairs:
        ids = []
        for x in (p["f"]["from"], p["b"]["from"], p["f"]["recipient"], p["b"]["recipient"]):
            if not exclude.get(x, False) and x not in ids:
                ids.append(x)
        merged_ids = list(ids)
        merged_pairs = [p]
        keep = []
        for g in groups:
            hit = False
            for i in g["ids"]:
                if i in ids:
                    hit = True
            if hit:
                merged_ids = merged_ids + g["ids"]
                merged_pairs = merged_pairs + g["pairs"]
            else:
                keep.append(g)
        keep.append({"ids": merged_ids, "pairs": merged_pairs})
        groups = keep
    return [g["pairs"] for g in groups]


def judge(terms: dict, r: dict) -> dict:
    """The rule, on one consensus-agreed read.
    terms: {"routers": [addr], "kinds": ["V2", "V3"], "start_block", "end_block", "rates": {token: [num, den]}}
    r: read_case() answer: {"reason", "detail"} or {"facts"}.
    -> {"verdict", "reason", ...}; verdict is UNVERIFIABLE, NOT_COVERED, CLEAN, UNCLEAR or SANDWICHED."""
    if "reason" in r:
        return {"verdict": V_UNVERIFIABLE, "reason": str(r["reason"])}
    f = r["facts"]
    t = f["tx"]

    def out(verdict: str, reason: str, extra: typing.Any = None) -> dict:
        o = {"verdict": verdict, "reason": reason, "block": t["block"], "index": t["index"], "victim": t["from"],
             "router": t["to"]}
        if extra is not None:
            for k in extra:
                o[k] = extra[k]
        return o

    if f.get("final") is not True:
        return out(V_UNVERIFIABLE, "NOT_FINALIZED")
    if int(t["status"]) != 1:
        return out(V_NOT_COVERED, "TX_FAILED")
    if t["to"] not in terms["routers"]:
        return out(V_NOT_COVERED, "ROUTER_NOT_COVERED")
    if t["block"] < int(terms["start_block"]) or t["block"] > int(terms["end_block"]):
        return out(V_NOT_COVERED, "OUTSIDE_BLOCK_RANGE")
    vs = [s for s in f["victim_swaps"] if s["kind"] in terms["kinds"]]
    if len(vs) == 0:
        return out(V_NOT_COVERED, "POOL_TYPE_NOT_COVERED" if len(f["victim_swaps"]) > 0 else "NO_SWAP_IN_TX")
    if "TOO_MANY_POOLS" in f["flags"]:
        return out(V_UNCLEAR, "TOO_MANY_HOPS")
    if "BLOCK_TOO_BUSY" in f["flags"]:
        return out(V_UNCLEAR, "BLOCK_TOO_BUSY")
    pinfo = {}
    for p in f["pools"]:
        pinfo[p["address"]] = p
    good = [s for s in vs if s["pool"] in pinfo and pinfo[s["pool"]]["canonical"] is True]
    if len(vs) == 1 and len(good) == 0:
        return out(V_NOT_COVERED, "POOL_NOT_CANONICAL", {"pool": vs[0]["pool"]})
    exclude = {ZERO: True, t["to"]: True}
    for a in terms["routers"]:
        exclude[a] = True
    for p in f["pools"]:
        exclude[p["address"]] = True
    if len(vs) > 1:
        for s in good:
            a = analyze_pool(f, s, exclude)
            if len(a["pairs"]) > 0 or a["partial"] != "":
                return out(V_UNCLEAR, "MULTI_HOP_VICTIM", {"pool": s["pool"]})
        return out(V_CLEAN, "NO_PATTERN", {"pool": good[0]["pool"] if len(good) > 0 else vs[0]["pool"], "hops": len(vs)})
    v = good[0]
    d = swap_dir(v)
    if d < 0:
        return out(V_UNCLEAR, "VICTIM_DIRECTION_UNREADABLE", {"pool": v["pool"]})
    a = analyze_pool(f, v, exclude)
    pool = pinfo[v["pool"]]
    base = {"pool": v["pool"], "kind": v["kind"], "direction": d,
            "token_in": pool["token0"] if d == 0 else pool["token1"],
            "token_out": pool["token1"] if d == 0 else pool["token0"], "victim_n0": v["n0"], "victim_n1": v["n1"]}
    if len(a["pairs"]) == 0:
        if a["partial"] != "":
            return out(V_UNCLEAR, a["partial"], base)
        return out(V_CLEAN, "NO_PATTERN", base)
    clusters = _cluster(a["pairs"], exclude)
    if len(clusters) > 1:
        base["attackers"] = len(clusters)
        return out(V_UNCLEAR, "MULTIPLE_ATTACKERS", base)
    fronts = []
    backs = []
    for p in clusters[0]:
        if p["f"]["li"] not in fronts:
            fronts.append(p["f"]["li"])
        if p["b"]["li"] not in backs:
            backs.append(p["b"]["li"])
    if len(fronts) > 1 or len(backs) > 1:
        return out(V_UNCLEAR, "COMPLEX_PATTERN", base)
    fr = clusters[0][0]["f"]
    bk = clusters[0][0]["b"]
    base["front_tx"] = fr["tx"]
    base["front_index"] = fr["ti"]
    base["back_tx"] = bk["tx"]
    base["back_index"] = bk["ti"]
    base["attacker_eoa"] = fr["from"]
    base["attacker_contract"] = fr["to"]
    base["attacker_recipient"] = fr["recipient"]
    base["front_n0"] = fr["n0"]
    base["front_n1"] = fr["n1"]
    base["back_n0"] = bk["n0"]
    base["back_n1"] = bk["n1"]
    for x in (fr["from"], bk["from"], fr["recipient"], bk["recipient"], fr["to"], bk["to"]):
        if x == t["from"] or x == v["recipient"]:
            return out(V_UNCLEAR, "SELF_SANDWICH", base)
    between = 0
    for s in a["same"]:
        if fr["ti"] < s["ti"] < bk["ti"] and s["tx"] != t["hash"] and swap_dir(s) == d \
                and s["from"] != fr["from"] and s["recipient"] != fr["recipient"]:
            between += 1
    if between > 0:
        base["others"] = between
        return out(V_UNCLEAR, "MULTIPLE_VICTIMS", base)
    pr = attacker_profit(fr, bk, d)
    if pr is None:
        return out(V_UNCLEAR, "NO_ATTACKER_PROFIT", base)
    pick = pr
    tok0 = pool["token0"]
    tok1 = pool["token1"]
    rates = terms["rates"]
    if (tok0 if pick["token"] == 0 else tok1) not in rates and pr["alt"] is not None \
            and (tok0 if pr["alt"]["token"] == 0 else tok1) in rates:
        pick = pr["alt"]
    pt = tok0 if pick["token"] == 0 else tok1
    base["profit_token"] = pt
    base["profit"] = str(pick["amount"])
    if pt not in rates:
        return out(V_UNCLEAR, "PROFIT_TOKEN_NOT_PRICED", base)
    return out(V_SANDWICHED, "SAME_POOL_SANDWICH", base)
# ==== end shared ====


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
