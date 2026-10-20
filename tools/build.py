"""contracts/<Name>.py -> build/<Name>.py, the exact bytes that are deployed.

GenVM deploys one file, so each contract marks where the shared helpers go
with "# INLINE:common" / "# INLINE:rpc" and this inlines
contracts/shared/{common,rpc}.py there. Nothing else changes. `--check`
exits 1 if any build file is stale (tests and tools/final_check.mjs run it).
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NAMES = ["SandwichRefund", "MEVGate"]


def built(name: str) -> str:
    t = (ROOT / "contracts" / (name + ".py")).read_text()
    for part in ("common", "rpc"):
        mark = "# INLINE:" + part + "\n"
        if mark in t:
            t = t.replace(mark, (ROOT / "contracts" / "shared" / (part + ".py")).read_text())
    if not t.startswith("# v0.3.0\n"):
        raise SystemExit(name + ": first line must be '# v0.3.0'")
    return t


bad = 0
(ROOT / "build").mkdir(exist_ok=True)
for n in NAMES:
    out = ROOT / "build" / (n + ".py")
    t = built(n)
    if "--check" in sys.argv:
        if not out.exists() or out.read_text() != t:
            print("STALE", out.relative_to(ROOT))
            bad += 1
    else:
        out.write_text(t)
        print("built", out.relative_to(ROOT), len(t.encode()), "bytes")
sys.exit(1 if bad else 0)
