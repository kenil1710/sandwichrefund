"""A small multi-contract world on top of stub.py for the offline suite.

  * contracts are loaded from build/ - the exact bytes that are deployed;

  * every contract module is loaded once; instances live at fake addresses;
  * gl.contract.get_at(a).view().fn(...) calls the instance at `a` with the
    message re-pointed at it (sender = the calling contract), and returns a
    JSON round-trip of the answer, as calldata would;
  * World.call() runs one transaction: sets sender / value / datetime, and on
    a revert (UserError) or an unsettled consensus round restores EVERY
    instance to its state before the call - a reverted transaction commits
    nothing, and its value stays with the sender;
  * value: a successful payable call adds msg.value to the contract balance;
    gl.chain.Account(...).emit_transfer subtracts from it.
"""
import copy
import json
import sys
from pathlib import Path

import stub

stub._install_stub()
gl = sys.modules["genlayer"].gl
Addr = sys.modules["genlayer"].Address
ROOT = Path(__file__).resolve().parent.parent
MODULES = {}


def module(name):
    if name not in MODULES:
        MODULES[name] = stub.load_full(ROOT / "build" / (name + ".py"), name)
    return MODULES[name]


class Reverted(Exception):
    def __init__(self, msg):
        super().__init__(msg)
        self.msg = msg


class World:
    def __init__(self, now_iso="2026-10-07T12:00:00Z"):
        self.instances = {}
        self.n = 0
        self.now_iso = now_iso
        self.current = None
        self.calls = []
        self.transfers = []

    # --- time -------------------------------------------------------------
    def set_time(self, epoch):
        y, m, d = module("SandwichRefund")._civil_from_days(epoch // 86400)
        s = epoch % 86400
        self.now_iso = "%04d-%02d-%02dT%02d:%02d:%02dZ" % (y, m, d, s // 3600, (s % 3600) // 60, s % 60)

    def now(self):
        return module("SandwichRefund")._epoch_from_iso(self.now_iso)

    def advance(self, seconds):
        self.set_time(self.now() + seconds)

    # --- deploy / call ----------------------------------------------------
    def deploy(self, name, *args, sender="0x" + "d" * 40):
        self.n += 1
        address = "0x" + ("%040x" % (0xC0FFEE0000 + self.n))
        mod = module(name)
        cls = getattr(mod, name)
        inst = cls.__new__(cls)
        inst.balance = 0
        self.instances[address] = inst
        self._msg(sender, 0, address)
        cls.__init__(inst, *args)
        return address

    def _msg(self, sender, value, address):
        gl.message.sender_address = Addr(sender)
        gl.message.value = value
        gl.message.contract_address = Addr(address)
        gl.message.raw = {"datetime": self.now_iso}

    def _snapshot(self):
        return {a: copy.deepcopy(i.__dict__) for a, i in self.instances.items()}, list(stub.TRANSFERS)

    def _restore(self, snap):
        state, transfers = snap
        for a, d in state.items():
            self.instances[a].__dict__.clear()
            self.instances[a].__dict__.update(d)
        stub.TRANSFERS[:] = transfers

    def call(self, address, method, *args, sender="0x" + "a" * 40, value=0):
        inst = self.instances[address]
        fn = getattr(type(inst), method)
        if value > 0 and not getattr(fn, "_payable", False):
            raise Reverted("not payable")
        snap = self._snapshot()
        before = len(stub.TRANSFERS)
        prev = self.current
        self.current = address
        self._msg(sender, value, address)
        try:
            out = fn(inst, *args)
        except stub._UserError as e:
            self._restore(snap)
            self.current = prev
            raise Reverted(e.message)
        except stub._Rolled as e:
            self._restore(snap)
            self.current = prev
            raise Reverted("UNDETERMINED: " + str(e))
        self.current = prev
        inst.balance += value
        for to, amt in stub.TRANSFERS[before:]:
            inst.balance -= amt
            self.transfers.append((address, to, amt))
        self.calls.append((address, method, sender))
        return json.loads(json.dumps(out))

    def view(self, address, method, *args):
        inst = self.instances[address]
        self._msg("0x" + "0" * 40, 0, address)
        return json.loads(json.dumps(getattr(type(inst), method)(inst, *args)))


WORLD = None


def _get_at(a):
    key = a.as_hex if hasattr(a, "as_hex") else str(a).lower()
    w = WORLD

    class _View:
        def __getattr__(self, fn):
            def f(*args):
                inst = w.instances.get(key)
                if inst is None:
                    raise RuntimeError("no contract at " + key)
                saved = (gl.message.sender_address, gl.message.value, gl.message.contract_address)
                gl.message.sender_address = Addr(w.current or "0x" + "0" * 40)
                gl.message.value = 0
                gl.message.contract_address = Addr(key)
                try:
                    return json.loads(json.dumps(getattr(type(inst), fn)(inst, *args)))
                finally:
                    gl.message.sender_address, gl.message.value, gl.message.contract_address = saved
            return f

    class _Handle:
        def view(self):
            return _View()

    return _Handle()


gl.contract.get_at = _get_at


def new_world(**k):
    global WORLD
    WORLD = World(**k)
    return WORLD
