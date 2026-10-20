"""Builders for the offline suite: a mock Ethereum served by both allowlisted
RPC URLs, blocks of swap transactions with receipts and Uniswap V2 / V3 Swap
logs, pools whose factory answers getPair / getPool, and a wired deployment
(a SandwichRefund in either mode and a MEVGate)."""
import hashlib
import json

import stub
import world

SR = world.module("SandwichRefund")
GT = world.module("MEVGate")

NOW_ISO = "2026-10-20T12:00:00Z"
NOW = SR._epoch_from_iso(NOW_ISO)
GEN = 10 ** 18
ETH = 10 ** 18
DEPLOYER = "0x" + "d" * 40
RPCS = list(SR.CHAINS["ethereum"][1])
V2F = SR.FACTORIES["ethereum"]["V2"][0]
V3F = SR.FACTORIES["ethereum"]["V3"][0]


def addr(n):
    return "0x" + hashlib.sha256(b"addr%d" % n).hexdigest()[:40]


def h32(seed):
    return "0x" + hashlib.sha256(str(seed).encode()).hexdigest()


SPONSOR = addr(1)
SPONSOR2 = addr(2)
KEEPER = addr(3)
STRANGER = addr(4)
VICTIM = addr(10)
VICTIM2 = addr(11)
VICTIM3 = addr(12)
ATTACKER = addr(20)          # the bot's EOA (tx.from)
BOT = addr(21)               # the bot's contract (tx.to and Swap recipient)
ATTACKER2 = addr(22)
BOT2 = addr(23)
TRADER = addr(30)
TRADER2 = addr(31)
ROUTER = addr(40)            # covered
ROUTER2 = addr(41)           # covered (a second router)
ROUTER_X = addr(42)          # NOT covered
WETH = addr(50)
USDC = addr(51)
TOKEN = addr(52)             # an unpriced token
FOT = addr(53)               # a fee-on-transfer token
POOL_V2 = addr(60)           # WETH(token0)/TOKEN(token1), Uniswap V2
POOL_V3 = addr(61)           # TOKEN(token0)/WETH(token1), Uniswap V3 fee 3000
POOL_B = addr(62)            # USDC/WETH V2, a second pool for multi-hop
POOL_FAKE = addr(63)         # a look-alike: claims the V2 factory, the factory does not know it
POOL_ALIEN = addr(64)        # a V2 pool of an unlisted factory
POOL_FOT = addr(65)          # FOT/WETH V2
ALIEN_FACTORY = addr(70)

BLOCK = 20_000_000
FINALIZED = BLOCK + 2000
START_BLOCK = BLOCK - 1000
END_BLOCK = BLOCK + 1000

_n = [0]


def word(n):
    return "%064x" % (int(n) % (1 << 256))


def topic_addr(a):
    return "0x" + "0" * 24 + a[2:].lower()


def eth_word(a):
    return "0x" + "0" * 24 + a[2:].lower()


class Chain:
    """Ethereum as both RPCs see it (one MockChain served at both URLs unless
    a test splits them)."""

    def __init__(self, finalized=FINALIZED):
        self.c = stub.MockChain(1, finalized)
        stub.WEB.reset()
        for u in RPCS:
            stub.WEB.chains[u] = self.c
        self.blocks = {}         # n -> number of txs so far
        self.logi = {}           # n -> next log index
        self.pool_kind = {}
        for p, k, t0, t1, fac, fee in (
                (POOL_V2, "V2", WETH, TOKEN, V2F, 0),
                (POOL_V3, "V3", TOKEN, WETH, V3F, 3000),
                (POOL_B, "V2", USDC, WETH, V2F, 0),
                (POOL_FOT, "V2", FOT, WETH, V2F, 0)):
            self.add_pool(p, k, t0, t1, fac, fee, canonical=True)
        self.add_pool(POOL_FAKE, "V2", WETH, TOKEN, V2F, 0, canonical=False)
        self.add_pool(POOL_ALIEN, "V2", WETH, TOKEN, ALIEN_FACTORY, 0, canonical=False)

    def add_pool(self, p, kind, t0, t1, factory, fee, canonical=True):
        self.pool_kind[p] = kind
        c = self.c.calls
        c[(p, "0x0dfe1681")] = eth_word(t0)
        c[(p, "0xd21220a7")] = eth_word(t1)
        c[(p, "0xc45a0155")] = eth_word(factory)
        if kind == "V3":
            c[(p, "0xddca3f43")] = "0x" + word(fee)
        pad = lambda a: "0" * 24 + a[2:]
        if kind == "V2":
            data = "0xe6a43905" + pad(t0) + pad(t1)
        else:
            data = "0x1698ee82" + pad(t0) + pad(t1) + word(fee)
        if canonical:
            c[(factory, data)] = eth_word(p)
        elif (factory, data) not in c:
            c[(factory, data)] = eth_word("0x" + "0" * 40)

    def swap_log(self, block, ti, txh, pool, n0, n1, sender, recipient, kind=None):
        kind = kind or self.pool_kind[pool]
        li = self.logi.get(block, 0)
        self.logi[block] = li + 1
        if kind == "V2":
            in0, out0 = (n0, 0) if n0 >= 0 else (0, -n0)
            in1, out1 = (n1, 0) if n1 >= 0 else (0, -n1)
            data = "0x" + word(in0) + word(in1) + word(out0) + word(out1)
            t0 = SR.SWAP_V2
        else:
            data = "0x" + word(n0) + word(n1) + word(2 ** 96) + word(10 ** 18) + word(0)
            t0 = SR.SWAP_V3
        return {"address": pool, "topics": [t0, topic_addr(sender), topic_addr(recipient)], "data": data,
                "blockNumber": hex(block), "transactionHash": txh, "transactionIndex": hex(ti),
                "blockHash": "0x" + "%064x" % (block * 7919 + 13), "logIndex": hex(li), "removed": False}

    def tx(self, block, frm, to, swaps, status=1, index=None, extra_logs=None, tag=None):
        """One transaction at the next index of `block` (or `index`). swaps:
        [(pool, n0, n1, recipient)] or (pool, n0, n1, recipient, sender, kind)."""
        _n[0] += 1
        txh = h32(("tx", _n[0], tag))
        ti = self.blocks.get(block, 0) if index is None else index
        self.blocks[block] = max(self.blocks.get(block, 0), ti + 1)
        bh = "0x" + "%064x" % (block * 7919 + 13)
        logs = []
        for s in swaps:
            pool, n0, n1, rec = s[0], s[1], s[2], s[3]
            sender = s[4] if len(s) > 4 and s[4] else (to or frm)
            kind = s[5] if len(s) > 5 else None
            lg = self.swap_log(block, ti, txh, pool, n0, n1, sender, rec, kind)
            logs.append(lg)
            self.c.logs.append(lg)
        for lg in extra_logs or []:
            logs.append(lg)
        self.c.txs[txh] = {
            "tx": {"hash": txh, "from": frm, "to": to, "blockNumber": hex(block), "blockHash": bh,
                   "transactionIndex": hex(ti), "value": "0x0", "input": "0x"},
            "receipt": {"transactionHash": txh, "blockNumber": hex(block), "blockHash": bh,
                        "transactionIndex": hex(ti), "status": "0x1" if status == 1 else "0x0", "logs": logs,
                        "from": frm, "to": to}}
        return txh

    def pending(self, frm=VICTIM, to=ROUTER):
        _n[0] += 1
        txh = h32(("pending", _n[0]))
        self.c.txs[txh] = {"tx": {"hash": txh, "from": frm, "to": to, "blockNumber": None, "blockHash": None,
                                  "transactionIndex": None, "value": "0x0", "input": "0x"}, "receipt": None}
        return txh

    def split(self):
        """Serve RPC B from an independent copy (to make the two disagree)."""
        import copy
        b = copy.deepcopy(self.c)
        stub.WEB.chains[RPCS[1]] = b
        return b

    def sandwich(self, block=BLOCK, pool=POOL_V2, d=0, front=(10 * ETH, 1000 * ETH), victim=(5 * ETH, 450 * ETH),
                 back=(1000 * ETH, 10 * ETH + 3 * ETH // 100), attacker=ATTACKER, bot=BOT, victim_from=VICTIM,
                 router=ROUTER, gap_before=0, gap_after=0, victim_recipient=None):
        """front-run, victim, back-run on one pool. Amounts are (in, out) as the
        trader sees them: front (X in, Y out), victim (X in, Y out), back (Y in, X out).
        d=0: X is token0. Returns (front, victim, back) hashes."""
        def nn(x_in, y_out, dd):
            return (x_in, -y_out) if dd == 0 else (-y_out, x_in)
        f0, f1 = nn(front[0], front[1], d)
        fh = self.tx(block, attacker, bot, [(pool, f0, f1, bot, bot)], tag="front")
        for _ in range(gap_before):
            self.tx(block, TRADER2, ROUTER_X, [])
        v0, v1 = nn(victim[0], victim[1], d)
        vh = self.tx(block, victim_from, router, [(pool, v0, v1, victim_recipient or victim_from, router)], tag="victim")
        for _ in range(gap_after):
            self.tx(block, TRADER2, ROUTER_X, [])
        b0, b1 = (-back[1], back[0]) if d == 0 else (back[0], -back[1])
        bh = self.tx(block, attacker, bot, [(pool, b0, b1, bot, bot)], tag="back")
        return fh, vh, bh


def terms(routers=(ROUTER, ROUTER2), kinds=("V2", "V3"), start=START_BLOCK, end=END_BLOCK,
          rates=((WETH, 10, 1), (USDC, 10 ** 13, 2400))):
    return {
        "chains": json.dumps(["ethereum"]),
        "routers": json.dumps([{"chain": "ethereum", "address": r, "name": "r"} for r in routers]),
        "kinds": json.dumps(list(kinds)),
        "ranges": json.dumps([{"chain": "ethereum", "start_block": start, "end_block": end}]),
        "rates": json.dumps([{"chain": "ethereum", "token": t, "num": str(n), "den": str(d), "symbol": "T",
                              "decimals": 18} for (t, n, d) in rates]),
    }


class Deployment:
    def __init__(self, mode="CANONICAL", now_iso=NOW_ISO, finalized=FINALIZED):
        self.w = world.new_world(now_iso=now_iso)
        self.chain = Chain(finalized)
        self.sr = self.w.deploy("SandwichRefund", mode, sender=DEPLOYER)
        self.gate = self.w.deploy("MEVGate", self.sr, sender=DEPLOYER)
        stub.TRANSFERS.clear()

    def create(self, value=10 * GEN, sender=SPONSOR, max_swap=GEN, max_victim=2 * GEN, claim=7200, name="pool",
               meta="", **kw):
        t = terms(**kw)
        return self.w.call(self.sr, "create_pool", name, t["chains"], t["routers"], t["kinds"], t["ranges"],
                           t["rates"], max_swap, max_victim, claim, meta, sender=sender, value=value)

    def file(self, pid, txh, sender=KEEPER, chain="ethereum"):
        return self.w.call(self.sr, "file_case", pid, chain, txh, sender=sender)

    def case(self, txh):
        return self.w.view(self.sr, "get_case", "ethereum", txh)

    def pool(self, pid):
        return self.w.view(self.sr, "get_pool", pid, self.w.now())

    def stats(self):
        return self.w.view(self.sr, "get_stats")

    def paid_to(self, who):
        return sum(a for (to, a) in stub.TRANSFERS if to == who.lower())

    def balance(self):
        return self.w.instances[self.sr].balance

    def conserved(self):
        """received = held + refunded + returned + credits paid, and the balance covers held."""
        s = self.stats()
        recv = int(s["received_total"])
        out = int(s["refunded_total"]) + int(s["returned_total"]) + int(s["credit_paid_total"])
        return recv == int(s["held"]) + out and self.balance() >= int(s["held"])
