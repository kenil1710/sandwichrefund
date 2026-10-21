"""Direct Mode (genlayer-test) helpers: a mock Ethereum answering the
contract's JSON-RPC batches by their body, wired into the official VM through
its web handler, and one real-looking sandwich block."""
import hashlib
import json

import pytest

RPC_A = "https://rpc.mevblocker.io"
RPC_B = "https://eth-mainnet.public.blastapi.io"
SWAP_V2 = "0xd78ad95fa46c994b6551d0da85fc275fe613ce37657fb8d5e3d130840159d822"
V2F = "0x5c69bee701ef814a2b6a3edd4b1652cb9cc5aa6f"
BLOCK = 20_000_000
ETH = 10 ** 18
GEN = 10 ** 18
# genlayer-test's Direct Mode (latest release, 0.29.2) runs contracts on the genvm v0.2 SDK; the contract is written for
# Studio's v0.3 SDK and pins its runner by a hash no published release carries. So Direct Mode runs the deployed bytes
# (build/SandwichRefund.py) with only these v0.3 -> v0.2 spellings changed in a temporary copy (ADAPT); every rule,
# read and check is the deployed code:
ADAPT = [
    ('"Depends": "py-genlayer:', None),                                   # header pin -> the release's runner
    ("@gl.storage.allow\n", "@gl.storage.allow_storage\n"),            # storage decorator
    ("gl.contract.Contract", "gl.Contract"),                            # contract base class
    ("gl.message.raw", "gl.message_raw"),                               # transaction datetime
    ('gl.evm.Account(Address(who)).emit_call(u256(amount), b"")',      # the one value send
     "gl.get_contract_at(Address(who)).emit_transfer(value=u256(amount))"),
]
SDK_VERSION = "v0.2.16"


def addr(n):
    return "0x" + hashlib.sha256(b"d%d" % n).hexdigest()[:40]


def h32(x):
    return "0x" + hashlib.sha256(str(x).encode()).hexdigest()


VICTIM, ATTACKER, BOT, ROUTER, WETH, TOKEN, POOL = (addr(i) for i in range(1, 8))
W = lambda n: "%064x" % (n % (1 << 256))
T = lambda a: "0x" + "0" * 24 + a[2:]


class Chain:
    """Ethereum as one RPC sees it."""

    def __init__(self, finalized=BLOCK + 100):
        self.finalized = finalized
        self.txs, self.logs, self.calls = {}, [], {}
        self.status = 200
        self.calls[(POOL, "0x0dfe1681")] = T(WETH)
        self.calls[(POOL, "0xd21220a7")] = T(TOKEN)
        self.calls[(POOL, "0xc45a0155")] = T(V2F)
        self.calls[(V2F, "0xe6a43905" + "0" * 24 + WETH[2:] + "0" * 24 + TOKEN[2:])] = T(POOL)
        self.n = 0

    def tx(self, frm, to, n0, n1, rec, idx):
        self.n += 1
        h = h32(("tx", self.n, frm, idx))
        in0, out0 = (n0, 0) if n0 >= 0 else (0, -n0)
        in1, out1 = (n1, 0) if n1 >= 0 else (0, -n1)
        bh = "0x" + "%064x" % BLOCK
        lg = {"address": POOL, "topics": [SWAP_V2, T(to), T(rec)], "data": "0x" + W(in0) + W(in1) + W(out0) + W(out1),
              "blockNumber": hex(BLOCK), "transactionHash": h, "transactionIndex": hex(idx), "logIndex": hex(self.n),
              "blockHash": bh}
        self.logs.append(lg)
        self.txs[h] = {"tx": {"hash": h, "from": frm, "to": to, "blockNumber": hex(BLOCK), "blockHash": bh},
                       "rc": {"blockNumber": hex(BLOCK), "blockHash": bh, "transactionIndex": hex(idx), "status": "0x1", "logs": [lg]}}
        return h

    def sandwich(self, profit=3 * ETH // 100):
        self.tx(ATTACKER, BOT, 10 * ETH, -1000 * ETH, BOT, 0)
        v = self.tx(VICTIM, ROUTER, 5 * ETH, -450 * ETH, VICTIM, 1)
        self.tx(ATTACKER, BOT, -(10 * ETH + profit), 1000 * ETH, BOT, 2)
        return v

    def answer(self, req):
        m, p, i = req["method"], req["params"], req["id"]
        r = None
        if m == "eth_chainId":
            r = "0x1"
        elif m == "eth_getBlockByNumber":
            r = {"number": hex(self.finalized)}
        elif m == "eth_getTransactionByHash":
            e = self.txs.get(p[0])
            r = e["tx"] if e else None
        elif m == "eth_getTransactionReceipt":
            e = self.txs.get(p[0])
            r = e["rc"] if e else None
        elif m == "eth_getLogs":
            f = p[0]
            lo, hi = int(f["fromBlock"], 16), int(f["toBlock"], 16)
            r = [l for l in self.logs if lo <= int(l["blockNumber"], 16) <= hi and l["address"] in f["address"]]
        elif m == "eth_call":
            r = self.calls.get((p[0]["to"], p[0]["data"]))
            if r is None:
                return {"jsonrpc": "2.0", "id": i, "error": {"code": 3, "message": "execution reverted"}}
        return {"jsonrpc": "2.0", "id": i, "result": r}


class Net:
    """Both RPC URLs; each can be its own chain, down, or failing."""

    def __init__(self):
        self.a = Chain()
        self.b = self.a
        self.down = set()

    def handler(self, data):
        url = data.get("url", "")
        if url in self.down:
            return {"ok": {"response": {"status": 503, "headers": {}, "body": b"down"}}}
        ch = self.a if url == RPC_A else self.b if url == RPC_B else None
        if ch is None:
            return {"ok": {"response": {"status": 404, "headers": {}, "body": b""}}}
        body = data.get("body")
        req = json.loads(body.decode() if isinstance(body, (bytes, bytearray)) else body)
        out = [ch.answer(r) for r in req] if isinstance(req, list) else ch.answer(req)
        return {"ok": {"response": {"status": ch.status, "headers": {}, "body": json.dumps(out).encode()}}}


def warp(vm, iso):
    """vm.warp, and the v0.2 SDK's message_raw (which the contract's clock reads) moved with it."""
    import sys
    vm.warp(iso)
    gl = sys.modules.get("genlayer.gl")
    if gl is not None and isinstance(getattr(gl, "message_raw", None), dict):
        gl.message_raw["datetime"] = iso


def fund_contract(vm, amount):
    """The value sent with a payable call, credited to the contract's balance the way the chain does."""
    key = vm._contract_address
    vm._balances[key] = vm._balances.get(key, 0) + amount


@pytest.fixture
def net(direct_vm):
    n = Net()
    direct_vm._live_web_handler = n.handler
    return n


@pytest.fixture
def contract(direct_vm, direct_deploy, direct_owner, tmp_path):
    text = open("build/SandwichRefund.py").read()
    lines = text.split("\n")
    assert lines[0] == "# v0.3.0" and ADAPT[0][0] in lines[1]
    lines[1] = '# { "Depends": "py-genlayer:latest" }'
    text = "\n".join(lines)
    for old, new in ADAPT[1:]:
        assert old in text, old
        text = text.replace(old, new)
    path = tmp_path / "SandwichRefund.py"
    path.write_text(text)
    direct_vm.sender = direct_owner
    direct_vm.warp("2026-10-21T00:00:00Z")
    c = direct_deploy(str(path), "CANONICAL", sdk_version=SDK_VERSION)
    warp(direct_vm, "2026-10-21T00:00:00Z")
    return c


def terms():
    return dict(
        chains_json=json.dumps(["ethereum"]),
        routers_json=json.dumps([{"chain": "ethereum", "address": ROUTER}]),
        kinds_json=json.dumps(["V2", "V3"]),
        ranges_json=json.dumps([{"chain": "ethereum", "start_block": BLOCK - 10, "end_block": BLOCK + 10}]),
        rates_json=json.dumps([{"chain": "ethereum", "token": WETH, "num": "10", "den": "1"}]),
    )


@pytest.fixture
def pool(direct_vm, contract, direct_alice):
    direct_vm.sender = direct_alice
    direct_vm.value = 2 * GEN
    t = terms()
    r = contract.create_pool("direct", t["chains_json"], t["routers_json"], t["kinds_json"], t["ranges_json"],
                             t["rates_json"], GEN, 2 * GEN, 3600, "")
    direct_vm.value = 0
    assert r["ok"] is True, r
    fund_contract(direct_vm, 2 * GEN)
    return r["pool_id"]
