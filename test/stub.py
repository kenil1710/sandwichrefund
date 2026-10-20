"""Runtime stub for the SandwichRefund offline suite: the genlayer module, a web
stub serving JSON-RPC mock chains (transactions, receipts, block headers, the
finalized head). Faithful where the runner has bitten before:
  * TreeMap[key] on a missing key RAISES KeyError; `.get()` answers None for
    struct maps and the zero value for scalar maps.
  * Structs read out of a TreeMap are REFERENCES: mutating them mutates storage.
  * Only gl.evm.Account(...).emit_call (an external value message) and
    gl.chain.Account(...).emit_transfer move value.
  * A consensus round runs the leader, then a validator on gl.vm.Return. A round
    that does not settle raises _Rolled and World.call restores the contract as
    it was before the call: an UNDETERMINED transaction commits NOTHING.
"""
import ast
import builtins
import json
import sys
import types
from datetime import datetime, timezone
from pathlib import Path

_UNSET = object()

class _UserError(Exception):
    def __init__(self, message: str = ""):
        super().__init__(message)
        self.message = message


class _Return:
    """gl.vm.Return - a leader result carrying its calldata."""

    def __init__(self, calldata):
        self.calldata = calldata


class _Rollback:
    def __init__(self, message=""):
        self.message = message


class _Addr:
    """Address. Compared and keyed by its lowercase text, like the real one, and
    carrying `.as_hex`, which is the ONLY spelling the runner guarantees. A stub
    whose `str()` happened to produce the hex would hide every place the
    contract forgot `.as_hex`."""

    def __init__(self, value=""):
        v = str(value)
        if not v.startswith("0x") or len(v) != 42:
            raise ValueError("not an address: " + v[:60])
        for ch in v[2:]:
            if ch not in "0123456789abcdefABCDEF":
                raise ValueError("not an address: " + v[:60])
        self._v = v.lower()

    @property
    def as_hex(self):
        return self._v

    def __str__(self):
        return self._v

    def __repr__(self):
        return "Address(" + self._v + ")"

    def __eq__(self, other):
        return isinstance(other, _Addr) and self._v == other._v

    def __hash__(self):
        return hash(self._v)


class _TreeMap(dict):
    """Models the runtime's TreeMap, INCLUDING what it returns for a key that is
    not there."""

    _value_type = None

    @classmethod
    def __class_getitem__(cls, item):
        vt = item[1] if isinstance(item, tuple) and len(item) > 1 else None
        return type("_TreeMapOf", (cls,), {"_value_type": vt})

    def _k(self, key):
        return str(key) if isinstance(key, _Addr) else key

    def _missing(self):
        vt = type(self)._value_type
        if vt is None:
            return None
        name = getattr(vt, "__name__", str(vt))
        if name.startswith("_TreeMap") or name.startswith("_DynArray"):
            return _zero_for(vt)
        if vt is int or vt is str or vt is bool:
            return _zero_for(vt)
        if hasattr(vt, "__annotations__") and getattr(vt, "__annotations__"):
            return None
        return _zero_for(vt)

    def get(self, key, default=_UNSET):
        k = self._k(key)
        if k in self:
            return dict.__getitem__(self, k)
        if default is not _UNSET:
            return default
        return self._missing()

    def __contains__(self, key):
        return dict.__contains__(self, self._k(key))

    def __setitem__(self, key, value):
        dict.__setitem__(self, self._k(key), value)

    def __getitem__(self, key):
        """Indexing a key the map does not hold RAISES KeyError, exactly as the
        runner does. A stub that auto-created the entry would pass code that
        dies on chain; `get_or_insert_default` is the spelling that inserts."""
        return dict.__getitem__(self, self._k(key))

    def __delitem__(self, key):
        dict.__delitem__(self, self._k(key))

    def get_or_insert_default(self, key):
        k = self._k(key)
        if k not in self:
            dict.__setitem__(self, k, self._factory())
        return dict.__getitem__(self, k)

    def _factory(self):
        vt = type(self)._value_type
        if vt is None:
            return _DynArray()
        if hasattr(vt, "__annotations__") and getattr(vt, "__annotations__"):
            return _make_struct(vt)
        return _zero_for(vt)


class _DynArray(list):
    """Models DynArray, INCLUDING `append_new_get()`.

    On chain a DynArray of structs cannot be appended to with a constructed
    value, so the runtime allocates a zeroed element in place and hands back a
    REFERENCE to it: the returned object must be the SAME object the array
    holds, or a later mutation through the reference would be invisible."""

    _elem_type = None

    @classmethod
    def __class_getitem__(cls, item):
        return type("_DynArrayOf", (cls,), {"_elem_type": item})

    def append_new_get(self):
        elem = type(self)._elem_type
        value = _make_struct(elem) if elem is not None and \
            hasattr(elem, "__annotations__") else _zero_for(elem)
        list.append(self, value)
        return value


def _zero_for(annotation):
    """The value the runtime auto-initialises a storage field to."""
    name = getattr(annotation, "__name__", str(annotation))
    if annotation is bool or name == "bool":
        return False
    if annotation is str or name == "str":
        return ""
    if name == "_Addr" or name == "Address":
        return _Addr("0x" + "0" * 40)
    if name.startswith("_TreeMap") or name == "TreeMap":
        return annotation() if isinstance(annotation, type) else _TreeMap()
    if name.startswith("_DynArray") or name == "DynArray":
        return annotation() if isinstance(annotation, type) else _DynArray()
    if name.startswith("u") or name.startswith("i"):
        return 0
    if hasattr(annotation, "__annotations__"):
        return _make_struct(annotation)
    return 0


def _make_struct(cls):
    obj = cls.__new__(cls)
    for field, ann in getattr(cls, "__annotations__", {}).items():
        setattr(obj, field, _zero_for(ann))
    return obj


class _Contract:
    """gl.contract.Contract. Storage fields are declared as class annotations and
    never assigned before use, exactly as on chain, so they are created on
    demand."""

    balance = 0

    def __getattr__(self, name):
        anns = {}
        for klass in reversed(type(self).__mro__):
            anns.update(getattr(klass, "__annotations__", {}))
        if name in anns:
            value = _zero_for(anns[name])
            object.__setattr__(self, name, value)
            return value
        raise AttributeError(name)


TRANSFERS = []
BALANCES = {}


class _Proxy:
    """gl.contract.Proxy. `.emit()` is a METHOD GETTER, exactly like the
    runner's, and it records NOTHING. That is the whole point: on chain,
    `emit()` with no method call after it constructs a namespace and drops it,
    posting no message. A stub that treated a bare `emit(value=...)` as a
    transfer would make this suite agree with a contract that silently never
    pays - which is precisely the bug that shipped once and had to be caught on
    chain by comparing real balances."""

    def __init__(self, address):
        self.address = address

    def view(self, **_k):
        return None

    def emit(self, **_k):
        return None

    def emit_transfer(self, value, **_k):
        if int(value) <= 0:
            raise ValueError("value must be greater than 0 for emit_transfer")
        key = str(self.address)
        TRANSFERS.append((key, int(value)))
        BALANCES[key] = BALANCES.get(key, 0) + int(value)


class _Account:
    """gl.chain.Account - the wrapper the SDK documents for ANY on-chain
    account, contract or EOA.

    Its `emit_transfer` DELIVERS here. That is a deliberate difference from the
    network the contract is deployed on: Studio Dev queues an `on="finalized"`
    value transfer and never executes it, which is a property of that network
    and not of this contract. This suite models the INTENDED semantics so the
    money invariants can be proved end to end; `test/seed.mjs` asserts the other
    half on chain - that the call posts a well-formed queued transfer to the
    right address for the right amount. Neither check is sufficient alone."""

    def __init__(self, address):
        self.address = address

    @property
    def balance(self):
        return BALANCES.get(str(self.address), 0)

    def emit_transfer(self, value, **_k):
        if int(value) <= 0:
            raise ValueError("value must be greater than 0 for emit_transfer")
        key = str(self.address)
        TRANSFERS.append((key, int(value)))
        BALANCES[key] = BALANCES.get(key, 0) + int(value)


class _EvmAccount(_Account):
    """gl.evm.Account: emit_call(value, data) posts an external message (an
    EthSend). Studio Dev delivers it when the transaction finalizes (measured
    by eth_getBalance, docs/RULES.md#payouts); here it delivers at once."""

    def emit_call(self, value, data, /):
        if int(value) <= 0:
            raise ValueError("value must be greater than 0")
        if not isinstance(data, (bytes, bytearray)):
            raise TypeError("data must be bytes")
        key = str(self.address)
        TRANSFERS.append((key, int(value)))
        BALANCES[key] = BALANCES.get(key, 0) + int(value)


def _proxy_for(address):
    return _Proxy(address)


def _contract_interface(cls):
    return _proxy_for


def _evm_contract_interface(cls):
    class _Handle:
        def __init__(self, to):
            self.to = to
    return _Handle


MESSAGE = types.SimpleNamespace(sender_address=_Addr("0x" + "a" * 40), value=0,
                                raw={"datetime": "2026-10-07T12:00:00Z"})


# ---------------------------------------------------------------------------
# the web stub: GET pages from WEB.pages, JSON-RPC (single or batch) from a
# MockChain per RPC URL. Leader and validators see the SAME web unless a test
# says otherwise (WEB.validator_hook runs before every validator).
# ---------------------------------------------------------------------------


class _Response:
    def __init__(self, status, body, headers=None):
        self.status_code = status
        self.body = body.encode("utf-8") if isinstance(body, str) else body
        self.headers = {k: (v.encode("utf-8") if isinstance(v, str) else v) for k, v in (headers or {}).items()}


class MockChain:
    """One EVM chain as an RPC sees it.

      txs[hash] = {"tx": {...}, "receipt": {...} | None}   (None receipt = pending)
      logs = [log, ...]            every log eth_getLogs may return (filtered by address, topic0, block range)
      calls[(to, data)] = hex | REVERT    eth_call answers ("latest")
      finalized                    the "finalized" head number
    """

    REVERT = object()

    def __init__(self, chain_id, finalized):
        self.chain_id = chain_id
        self.finalized = finalized
        self.txs = {}
        self.logs = []
        self.calls = {}
        self.fail = None      # fn(method, params) -> error dict | None
        self.batch_cap = 12
        self.log = []

    def answer(self, req):
        m, p = req["method"], req["params"]
        self.log.append((m, json.dumps(p)))
        rid = req["id"]
        if self.fail is not None:
            err = self.fail(m, p)
            if err is not None:
                return {"jsonrpc": "2.0", "id": rid, "error": err}
        if m == "eth_chainId":
            return {"jsonrpc": "2.0", "id": rid, "result": hex(self.chain_id)}
        if m == "eth_getBlockByNumber":
            n = self.finalized if p[0] == "finalized" else int(p[0], 16)
            return {"jsonrpc": "2.0", "id": rid, "result": {"number": hex(n), "hash": "0x" + "%064x" % (n * 7919 + 13)}}
        if m == "eth_getTransactionByHash":
            e = self.txs.get(str(p[0]).lower())
            return {"jsonrpc": "2.0", "id": rid, "result": json.loads(json.dumps(e["tx"])) if e else None}
        if m == "eth_getTransactionReceipt":
            e = self.txs.get(str(p[0]).lower())
            r = e["receipt"] if e else None
            return {"jsonrpc": "2.0", "id": rid, "result": json.loads(json.dumps(r)) if r else None}
        if m == "eth_getLogs":
            f = p[0]
            addrs = f.get("address", [])
            if isinstance(addrs, str):
                addrs = [addrs]
            addrs = [x.lower() for x in addrs]
            t0 = f.get("topics", [None])[0]
            if isinstance(t0, str):
                t0 = [t0]
            lo = int(f["fromBlock"], 16)
            hi = int(f["toBlock"], 16)
            out = []
            for lg in self.logs:
                b = int(lg["blockNumber"], 16)
                if b < lo or b > hi:
                    continue
                if len(addrs) > 0 and lg["address"].lower() not in addrs:
                    continue
                if t0 is not None and lg["topics"][0] not in t0:
                    continue
                out.append(lg)
            return {"jsonrpc": "2.0", "id": rid, "result": json.loads(json.dumps(out))}
        if m == "eth_call":
            r = self.calls.get((p[0]["to"].lower(), p[0]["data"].lower()))
            if r is None or r is MockChain.REVERT:
                return {"jsonrpc": "2.0", "id": rid, "error": {"code": 3, "message": "execution reverted"}}
            return {"jsonrpc": "2.0", "id": rid, "result": r}
        return {"jsonrpc": "2.0", "id": rid, "error": {"code": -32601, "message": "method not found"}}


class _Web:
    def __init__(self):
        self.reset()

    def reset(self):
        self.pages = {}         # url -> (status, body)
        self.down = set()       # urls that fail at transport level ("*" = all)
        self.log = []
        self.chains = {}        # rpc url -> MockChain
        self.rpc_status = {}    # rpc url -> forced HTTP status
        self.validator_hook = None
        self.leader_hook = None
        self.tamper = {}        # rpc url -> fn(request, answer) -> answer (one RPC lying or broken)
        self.caps = {}          # rpc url -> largest batch that endpoint accepts (overrides the chain's)

    def get(self, url):
        self.log.append(url)
        if "*" in self.down or url in self.down:
            raise RuntimeError("connection refused")
        return self.pages.get(url, (404, "not found"))


WEB = _Web()


def _web_request(url, method="GET", body=None, headers=None, **_k):
    if method == "GET":
        status, text = WEB.get(url)
        return _Response(status, text)
    if method != "POST":
        raise AssertionError("SandwichRefund only issues JSON-RPC POST requests")
    WEB.log.append(url)
    if "*" in WEB.down or url in WEB.down:
        raise RuntimeError("connection refused")
    if url in WEB.rpc_status:
        return _Response(WEB.rpc_status[url], "{}")
    ch = WEB.chains.get(url)
    if ch is None:
        return _Response(404, "no such rpc")
    req = json.loads(body)
    if isinstance(req, list):
        if len(req) > WEB.caps.get(url, ch.batch_cap):
            return _Response(413, json.dumps({"error": "batch too large"}))
        return _Response(200, json.dumps([_tampered(url, r, ch.answer(r)) for r in req]))
    return _Response(200, json.dumps(_tampered(url, req, ch.answer(req))))


def _tampered(url, req, ans):
    fn = WEB.tamper.get(url)
    return fn(req, ans) if fn is not None else ans


def _web_get(url, **_k):
    status, text = WEB.get(url)
    return _Response(status, text)


def _web_render(url, **_k):
    raise AssertionError("SandwichRefund must not use web.render")


class _Model:
    """Records every prompt. `answer` may be a dict, a list of dicts (served
    in turn) or a function(prompt, n)."""

    def __init__(self):
        self.reset()

    def reset(self):
        self.prompts = []
        self.answer = {"fields": []}
        self.raise_next = 0

    def __call__(self, prompt, **kwargs):
        raise AssertionError("SandwichRefund never asks a model")
        self.prompts.append(prompt)
        n = len(self.prompts)
        if self.raise_next > 0:
            self.raise_next -= 1
            raise RuntimeError("model unavailable")
        if callable(self.answer):
            return self.answer(prompt, n)
        if isinstance(self.answer, list):
            return json.loads(json.dumps(self.answer[(n - 1) % len(self.answer)]))
        return json.loads(json.dumps(self.answer))


MODEL = _Model()
LAST_CONSENSUS = {}
FORGE = {"payload": None, "mutate": None}


def _run_nondet(leader_fn, validator_fn):
    LAST_CONSENSUS.clear()
    if WEB.leader_hook is not None:
        WEB.leader_hook()
    try:
        result = leader_fn()
    except Exception as e:
        LAST_CONSENSUS["agreed"] = False
        LAST_CONSENSUS["leader_error"] = repr(e)
        raise _Rolled("the leader crashed: " + repr(e))
    LAST_CONSENSUS["leader"] = result
    if FORGE["payload"] is not None:
        result = FORGE["payload"]
    if FORGE["mutate"] is not None:
        result = FORGE["mutate"](json.loads(json.dumps(result)))
    result = json.loads(json.dumps(result))     # calldata round trip
    if WEB.validator_hook is not None:
        WEB.validator_hook()
    agreed = validator_fn(_Return(result))
    LAST_CONSENSUS["agreed"] = bool(agreed)
    if not agreed:
        raise _Rolled("validators disagreed")
    return result


class _Rolled(Exception):
    """A round that did not settle: the whole transaction applies nothing."""


def _install_stub():
    if "genlayer" in sys.modules:
        return
    mod = types.ModuleType("genlayer")
    vm = types.SimpleNamespace(UserError=_UserError, Return=_Return,
                               Result=object, Rollback=_Rollback,
                               run_nondet=_run_nondet,
                               run_nondet_unsafe=_run_nondet)
    web = types.SimpleNamespace(request=_web_request, render=_web_render,
                                get=_web_get)
    nondet = types.SimpleNamespace(web=web, exec_prompt=MODEL)
    public = types.SimpleNamespace()
    public.view = lambda fn: fn
    write = lambda fn: fn

    def _payable(fn):
        fn._payable = True
        return fn
    write.payable = _payable
    public.write = write
    evm = types.SimpleNamespace(contract_interface=_evm_contract_interface, Account=_EvmAccount)
    storage = types.SimpleNamespace(TreeMap=_TreeMap, DynArray=_DynArray,
                                    allow=lambda cls: cls)
    contract_ns = types.SimpleNamespace(Contract=_Contract,
                                        get_at=lambda a: _proxy_for(a),
                                        interface=_contract_interface)
    chain_ns = types.SimpleNamespace(Account=_Account, id=61997)
    mod.gl = types.SimpleNamespace(vm=vm, nondet=nondet, public=public, evm=evm,
                                   storage=storage, message=MESSAGE,
                                   contract=contract_ns, chain=chain_ns)
    mod.Address = _Addr
    mod.TreeMap = _TreeMap
    mod.DynArray = _DynArray
    for name in ("u8", "u16", "u32", "u64", "u128", "u256", "i8", "i16", "i32",
                 "i64", "bigint"):
        mod.__dict__[name] = int
    sys.modules["genlayer"] = mod
    sys.modules["genlayer.gl"] = mod.gl


def load_full(path: Path, name: str) -> types.ModuleType:
    module = types.ModuleType(name)
    module.__file__ = str(path)
    exec(compile(path.read_text(encoding="utf8"), str(path), "exec"),
         module.__dict__)
    return module


# static undefined-name check
# ---------------------------------------------------------------------------

def _own_nodes(scope):
    out = []

    def rec(node):
        for sub in ast.iter_child_nodes(node):
            if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef,
                                ast.Lambda)):
                continue
            out.append(sub)
            rec(sub)
    rec(scope)
    return out


def _child_scopes(scope):
    out = []

    def rec(node):
        for sub in ast.iter_child_nodes(node):
            if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef,
                                ast.Lambda)):
                out.append(sub)
            else:
                rec(sub)
    rec(scope)
    return out


def _bound_names(scope) -> set:
    out = set()
    args = getattr(scope, "args", None)
    if args is not None:
        for group in (args.posonlyargs, args.args, args.kwonlyargs):
            for a in group:
                out.add(a.arg)
        if args.vararg:
            out.add(args.vararg.arg)
        if args.kwarg:
            out.add(args.kwarg.arg)
    for sub in _own_nodes(scope):
        if isinstance(sub, ast.Name) and isinstance(sub.ctx, ast.Store):
            out.add(sub.id)
        elif isinstance(sub, ast.ExceptHandler) and sub.name:
            out.add(sub.name)
        elif isinstance(sub, (ast.Global, ast.Nonlocal)):
            out.update(sub.names)
        elif isinstance(sub, (ast.Import, ast.ImportFrom)):
            for al in sub.names:
                out.add((al.asname or al.name).split(".")[0])
        elif isinstance(sub, ast.comprehension):
            for nm in ast.walk(sub.target):
                if isinstance(nm, ast.Name):
                    out.add(nm.id)
    for sub in _child_scopes(scope):
        if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)):
            out.add(sub.name)
    for sub in _own_nodes(scope):
        if isinstance(sub, ast.ClassDef):
            out.add(sub.name)
    return out


def undefined_names(path: Path) -> list:
    tree = ast.parse(path.read_text(encoding="utf8"))
    module_names = _bound_names(tree) | {
        "gl", "u8", "u16", "u32", "u64", "u128", "u256", "i8", "i16", "i32",
        "i64", "Address", "bigint", "self"}
    builtin_names = set(dir(builtins))
    problems = []

    def visit(scope, enclosing, label):
        scope_names = enclosing | _bound_names(scope)
        for sub in _own_nodes(scope):
            if isinstance(sub, ast.Name) and isinstance(sub.ctx, ast.Load):
                if sub.id not in scope_names and sub.id not in builtin_names:
                    problems.append((label, sub.id, sub.lineno))
        for child in _child_scopes(scope):
            visit(child, scope_names,
                  label + "." + getattr(child, "name", "<lambda>"))

    for child in _child_scopes(tree):
        visit(child, module_names, getattr(child, "name", "<lambda>"))
    for node in _own_nodes(tree):
        if isinstance(node, ast.ClassDef):
            for child in _child_scopes(node):
                visit(child, module_names | _bound_names(node),
                      node.name + "." + getattr(child, "name", "<lambda>"))
    return problems


# ---------------------------------------------------------------------------
