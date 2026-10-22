# Superseded demo evidence (demo v2)

Demo run and Playwright e2e on the first demo pair of the 47195a1 deployment: SandwichRefundDemo
0xa71645751e3D59Eb51809e76570f367D4F14841c, MEVGateDemo 0xe4Aa8409E0EE567868be43387aDF4B497202DBCE.

Why replaced: the two e2e runs here (pools 1 and 2) were refused a pool on purpose and credited 0.001 GEN each,
but their keys lived only in memory, so 0.002 GEN stayed owed and the contract balance could never return to 0.
The demo run was also interrupted by an RPC outage after creating copycat pool 6, and stopped for good in the
recovery-window steps when the redeploy was decided.

Both demo contracts were redeployed from the same commit 47195a1 (byte-identical, tools/verify_source.mjs); the
canonical SandwichRefund and MEVGate are untouched. Every throwaway key is now saved in test/.accounts.json before
use, the e2e withdraws its credit with the site's Withdraw credit button, and the new demo ends at balance 0
(docs/demo-run.json, docs/e2e).
