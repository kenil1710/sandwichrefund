# ==== shared rpc helpers: contracts/shared/rpc.py, inlined by tools/build.py; edit there ====

class ReadFailed(Exception):
    """An endpoint did not answer, or answered something that is not a
    JSON-RPC result. Nothing is guessed."""


def _status(res: typing.Any) -> int:
    s = getattr(res, "status_code", None)
    if s is None:
        s = getattr(res, "status", None)
    return 0 if s is None else int(s)


def _raw(res: typing.Any) -> bytes:
    b = getattr(res, "body", None)
    if b is None:
        return b""
    if isinstance(b, bytes):
        return b
    return str(b).encode("utf-8")


def rpc_url_allowed(url: str) -> bool:
    for ch in CHAINS:
        if url in CHAINS[ch][1]:
            return True
    return False


def parse_batch(doc: typing.Any, n: int) -> list:
    """A JSON-RPC batch answer -> results in call order. Any error raises."""
    if isinstance(doc, dict):
        doc = [doc]
    if not isinstance(doc, list):
        raise ReadFailed("batch")
    by_id = {}
    for item in doc:
        if isinstance(item, dict) and isinstance(item.get("id"), int) and not isinstance(item.get("id"), bool):
            by_id[item["id"]] = item
    out = []
    for i in range(n):
        item = by_id.get(i)
        if item is None:
            raise ReadFailed("missing id")
        if "error" in item and item["error"] is not None:
            raise ReadFailed("rpc error")
        if "result" not in item:
            raise ReadFailed("no result")
        out.append(item["result"])
    return out


def rpc_send(url: str, calls: list) -> list:
    """One endpoint, every call, in batches of at most BATCH_MAX. A batch is
    retried (up to RPC_TRIES) on a transport failure, a 429 or 5xx, or an
    answer that is not a usable batch."""
    if not rpc_url_allowed(url):
        raise ReadFailed("rpc not allowed")
    out = []
    i = 0
    while i < len(calls):
        chunk = calls[i:i + BATCH_MAX]
        body = json.dumps([{"jsonrpc": "2.0", "id": j, "method": chunk[j][0], "params": chunk[j][1]}
                           for j in range(len(chunk))])
        got = None
        why = ""
        for _ in range(RPC_TRIES):
            try:
                res = gl.nondet.web.request(url, method="POST", body=body,
                                            headers={"Content-Type": "application/json"})
            except Exception:
                why = "transport"
                continue
            st = _status(res)
            if st != 200:
                why = "http " + str(st)
                if st != 429 and st < 500:
                    break
                continue
            try:
                got = parse_batch(json.loads(_raw(res).decode("utf-8", errors="replace")), len(chunk))
                break
            except ReadFailed as e:
                why = str(e)
            except Exception:
                why = "json"
        if got is None:
            raise ReadFailed(why)
        out = out + got
        i += BATCH_MAX
    return out


def decode_swap(lg: typing.Any) -> typing.Any:
    """A Uniswap V2 or V3 Swap log -> {pool, kind, n0, n1, sender, recipient,
    ti, li, tx, block}, amounts as the pool sees them (+ received, - paid,
    decimal strings). None for anything else."""
    if not isinstance(lg, dict):
        return None
    t = lg.get("topics", [])
    if not isinstance(t, list) or len(t) != 3:
        return None
    t0 = str(t[0]).lower()
    d = str(lg.get("data", "")).lower()
    sender = _word_addr(t[1])
    recipient = _word_addr(t[2])
    pool = _addr(lg.get("address", ""))
    ti = _hex_int(lg.get("transactionIndex"))
    li = _hex_int(lg.get("logIndex"))
    blk = _hex_int(lg.get("blockNumber"))
    txh = _hash32(lg.get("transactionHash", ""))
    if sender == "" or recipient == "" or pool == "" or ti < 0 or li < 0 or blk < 0 or txh == "":
        return None
    if not d.startswith("0x") or not _is_hex(d[2:]):
        return None
    w = d[2:]
    if t0 == SWAP_V2:
        if len(w) != 64 * 4:
            return None
        kind = "V2"
        n0 = int(w[0:64], 16) - int(w[128:192], 16)
        n1 = int(w[64:128], 16) - int(w[192:256], 16)
    elif t0 == SWAP_V3:
        if len(w) != 64 * 5:
            return None
        kind = "V3"
        n0 = _s256(w[0:64])
        n1 = _s256(w[64:128])
    else:
        return None
    return {"pool": pool, "kind": kind, "n0": str(n0), "n1": str(n1), "sender": sender, "recipient": recipient,
            "ti": ti, "li": li, "tx": txh, "block": blk}


def _pad(a: str) -> str:
    return "0" * 24 + a[2:]


def read_facts(url: str, chain: str, h: str) -> dict:
    """Facts about one victim transaction from ONE endpoint (the shape the
    rule reads): the transaction, the Swap logs of its receipt, its pools
    (tokens, factory, fee, whether the factory maps back to the pool), and
    every Swap log on those pools in its block and the next, each with the
    sender of its transaction. -> facts, or {"reason": ...}. Any transport or
    JSON-RPC failure raises ReadFailed."""
    cid = CHAINS[chain][0]
    a = rpc_send(url, [["eth_getTransactionByHash", [h]], ["eth_getTransactionReceipt", [h]],
                       ["eth_getBlockByNumber", ["finalized", False]], ["eth_chainId", []]])
    if _hex_int(a[3]) != cid:
        return {"reason": "WRONG_CHAIN_ID"}
    fin = _hex_int(a[2].get("number")) if isinstance(a[2], dict) else -1
    if fin < 0:
        raise ReadFailed("no finalized head")
    tx = a[0]
    rc = a[1]
    if tx is None:
        return {"reason": "TX_NOT_FOUND"}
    if rc is None:
        return {"reason": "TX_PENDING"}
    if not isinstance(tx, dict) or not isinstance(rc, dict):
        return {"reason": "RPC_UNREADABLE"}
    blk = _hex_int(rc.get("blockNumber"))
    ti = _hex_int(rc.get("transactionIndex"))
    bh = _hash32(rc.get("blockHash", ""))
    frm = _addr(tx.get("from", ""))
    to = _addr(tx.get("to", "")) if tx.get("to") is not None else ""
    if blk < 0 or ti < 0 or bh == "" or frm == "" or _hash32(tx.get("blockHash", "")) != bh \
            or _hex_int(tx.get("blockNumber")) != blk:
        return {"reason": "RPC_UNREADABLE"}
    head = {"hash": h, "block": blk, "block_hash": bh, "index": ti,
            "status": 1 if str(rc.get("status", "")).lower() == "0x1" else 0, "from": frm, "to": to}
    vs = []
    raw_logs = rc.get("logs", [])
    if not isinstance(raw_logs, list):
        return {"reason": "RPC_UNREADABLE"}
    for lg in raw_logs:
        s = decode_swap(lg)
        if s is not None:
            vs.append({"pool": s["pool"], "kind": s["kind"], "li": s["li"], "n0": s["n0"], "n1": s["n1"],
                       "sender": s["sender"], "recipient": s["recipient"]})
    facts = {"tx": head, "finalized": fin, "victim_swaps": vs, "pools": [], "swaps": [], "flags": []}
    kind_of = {}
    for s in vs:
        kind_of[s["pool"]] = s["kind"]
    pools = sorted(kind_of.keys())
    if head["status"] != 1 or len(pools) == 0:
        return facts
    if len(pools) > MAX_POOLS:
        facts["flags"] = ["TOO_MANY_POOLS"]
        return facts
    if blk + 1 > fin:
        return facts            # judged NOT_FINALIZED; nothing more is read
    calls = [["eth_getLogs", [{"address": pools, "topics": [[SWAP_V2, SWAP_V3]], "fromBlock": hex(blk),
                               "toBlock": hex(blk + 1)}]]]
    for p in pools:
        calls.append(["eth_call", [{"to": p, "data": "0x0dfe1681"}, "latest"]])      # token0()
        calls.append(["eth_call", [{"to": p, "data": "0xd21220a7"}, "latest"]])      # token1()
        calls.append(["eth_call", [{"to": p, "data": "0xc45a0155"}, "latest"]])      # factory()
        if kind_of[p] == "V3":
            calls.append(["eth_call", [{"to": p, "data": "0xddca3f43"}, "latest"]])  # fee()
    b = rpc_send(url, calls)
    logs = b[0]
    if not isinstance(logs, list):
        raise ReadFailed("logs")
    k = 1
    pinfo = []
    for p in pools:
        t0 = _word_addr(b[k])
        t1 = _word_addr(b[k + 1])
        fac = _word_addr(b[k + 2])
        k += 3
        fee = 0
        if kind_of[p] == "V3":
            fee = _hex_int(b[k])
            k += 1
        if t0 == "" or t1 == "" or fac == "" or fee < 0:
            return {"reason": "RPC_UNREADABLE"}
        pinfo.append({"address": p, "kind": kind_of[p], "token0": t0, "token1": t1, "factory": fac, "fee": fee,
                      "canonical": False})
    swaps = []
    for lg in logs:
        s = decode_swap(lg)
        if s is None or s["pool"] not in kind_of or (s["block"] != blk and s["block"] != blk + 1):
            continue
        if s["kind"] != kind_of[s["pool"]]:
            continue
        s["from"] = ""
        s["to"] = ""
        swaps.append(s)
    swaps = sorted(swaps, key=lambda x: x["block"] * 1000000 + x["li"])
    others = []
    for s in swaps:
        if s["block"] == blk and s["tx"] != h and s["tx"] not in others:
            others.append(s["tx"])
    others = sorted(others)
    if len(others) > MAX_TXS:
        facts["pools"] = pinfo
        facts["flags"] = ["BLOCK_TOO_BUSY"]
        return facts
    c2 = []
    checked = []
    for p in pinfo:
        known = FACTORIES.get(chain, {}).get(p["kind"], ())
        if p["factory"] not in known:
            continue
        if p["kind"] == "V2":
            data = "0xe6a43905" + _pad(p["token0"]) + _pad(p["token1"])                     # getPair(a, b)
        else:
            fh = hex(int(p["fee"]))[2:]
            data = "0x1698ee82" + _pad(p["token0"]) + _pad(p["token1"]) + "0" * (64 - len(fh)) + fh  # getPool(a, b, fee)
        c2.append(["eth_call", [{"to": p["factory"], "data": data}, "latest"]])
        checked.append(p)
    for x in others:
        c2.append(["eth_getTransactionByHash", [x]])
    c = rpc_send(url, c2) if len(c2) > 0 else []
    for i in range(len(checked)):
        checked[i]["canonical"] = _word_addr(c[i]) == checked[i]["address"]
    who = {}
    for i in range(len(others)):
        o = c[len(checked) + i]
        if not isinstance(o, dict) or _hash32(o.get("hash", "")) != others[i]:
            raise ReadFailed("tx")
        who[others[i]] = [_addr(o.get("from", "")), _addr(o.get("to", "")) if o.get("to") is not None else ""]
    for s in swaps:
        if s["block"] != blk:
            continue
        if s["tx"] == h:
            s["from"] = frm
            s["to"] = to
        else:
            s["from"] = who[s["tx"]][0]
            s["to"] = who[s["tx"]][1]
    facts["pools"] = pinfo
    facts["swaps"] = swaps
    return facts


def _host(url: str) -> str:
    rest = url[url.find("//") + 2:] if url.find("//") >= 0 else url
    cut = rest.find("/")
    return rest if cut < 0 else rest[:cut]


def read_case(chain: str, h: str) -> dict:
    """One victim transaction read from BOTH RPCs of its chain ->
    {"facts": ...} when they agree (facts["final"]: see below),
    else {"reason": ..., "detail": ...}: RPC_UNREADABLE, RPC_DISAGREE or the
    reason both gave (TX_NOT_FOUND, TX_PENDING, WRONG_CHAIN_ID)."""
    if chain not in CHAINS:
        return {"reason": "UNSUPPORTED_CHAIN", "detail": ""}
    views = []
    for url in CHAINS[chain][1]:
        try:
            views.append(read_facts(url, chain, h))
        except ReadFailed as e:
            return {"reason": "RPC_UNREADABLE", "detail": _host(url) + ": " + str(e)[:60]}
        except Exception:
            return {"reason": "RPC_UNREADABLE", "detail": _host(url) + ": unexpected answer"}
    a = views[0]
    b = views[1]
    if "reason" in a or "reason" in b:
        if "reason" in a and "reason" in b and a["reason"] == b["reason"]:
            return {"reason": a["reason"], "detail": ""}
        return {"reason": "RPC_DISAGREE", "detail": "one RPC has the transaction, the other does not"}
    fa = a["finalized"]
    fb = b["finalized"]
    del a["finalized"]
    del b["finalized"]
    if _canon(a) != _canon(b):
        return {"reason": "RPC_DISAGREE", "detail": "the two RPCs answer differently"}
    # final: the victim's block AND the next one (read for back-runs) are at
    # or below BOTH RPCs' finalized heads
    a["final"] = a["tx"]["block"] + 1 <= (fa if fa < fb else fb)
    return {"facts": a}
# ==== end shared rpc ====
