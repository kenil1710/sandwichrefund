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
