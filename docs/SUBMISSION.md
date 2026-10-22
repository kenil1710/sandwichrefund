# Submission

Plain ASCII. Lengths checked by `node tools/submission.mjs`.

## One-liner (167/180 characters)

SandwichRefund: a sponsor funds a pool; GenLayer validators read Ethereum swaps from two RPCs, code detects same-block sandwiches and refunds the victim's loss in GEN.

## Description (943/1000 characters)

Wallets and DEX front-ends route users into sandwich attacks and cannot prove or repay the loss. SandwichRefund lets a sponsor lock GEN in a pool with frozen terms: covered routers, Uniswap V2/V3 pools, block range, refund rate per profit token, caps, claim period. Anyone files a victim tx; every validator reads its receipt and the pool's Swap logs from two Ethereum RPCs and code decides: one actor's front-run and back-run on the victim's pool in the same block with positive profit is SANDWICHED and the attacker's net profit is refunded to tx.from at once. Partial patterns are UNCLEAR, never paid. Seeded with 65 real swaps of 2026-10-20: 18 sandwiched (jaredfromsubway and 8 other bots), 16 clean, 31 unclear (17 multi-hop victims, 4 unpriced profit tokens, 4 no net attacker profit, 3 several front/back-runs, 2 bundles with several victims, 1 over 4 hops); all 18 refunds arrived. MEVGate answers consumers; a keeper scans and files.

## Review verification (493/500 characters)

Live: sandwichrefund.vercel.app (/verify: code vs GitHub). Studio Dev: SandwichRefund 0x0D1fa49E0d39Ed8a592cB1f87e21BD825a644EFA, demo 0x3445CA1fDaEEBe026DAaf19Da4228a96a2444F31, MEVGate 0x96D529d8f63EC5D742907DfaE83A02627D35E1e9, demo 0x4f5bd0ABa738cD21b58495Ed962D6bC6369D8694. Repo github.com/kenil1710/sandwichrefund: sh test/run_offline.sh (427 tests), node tools/verify_source.mjs, node tools/final_check.mjs. Deploy commit 47195a1. docs/SEEDS.md proves 18 canonical and 16 demo payouts.

## Counts

- Real cases: 65 (SANDWICHED 18, CLEAN 16, UNCLEAR 31), read from two Ethereum RPCs on a Mac and inside GenVM, identical.
- Canonical pool: SANDWICHED_REFUNDED 18, UNCLEAR 31, CLEAN 16; 0.221 GEN refunded, 1.279 GEN returned to the sponsor at close.
- UNCLEAR by reason: 17 multi-hop victims, 4 unpriced profit tokens, 4 no net attacker profit, 3 several front/back-runs, 2 bundles with several victims, 1 over 4 hops. A pair the rule cannot attribute to one swap on one pool is never paid.
- Real-world check: 18/18 SANDWICHED and 16/16 CLEAN confirmed.
- Demo: 48 steps, 16 payouts, all arrived; demo contract balance at the end 0 wei.
- Offline tests: 427.

## Evidence (pinned)

Commit `38654099c748cb295cb23a1f5d7c0b5a594bbad5`; contracts deployed from `47195a18976f2004ea5a26bd34dc1a23dccb51bd`.

- Seeds, every refund and its arrival: https://github.com/kenil1710/sandwichrefund/blob/38654099c748cb295cb23a1f5d7c0b5a594bbad5/docs/SEEDS.md
- Final check: https://github.com/kenil1710/sandwichrefund/blob/38654099c748cb295cb23a1f5d7c0b5a594bbad5/docs/FINAL_CHECK.md
- Audit A-N: https://github.com/kenil1710/sandwichrefund/blob/38654099c748cb295cb23a1f5d7c0b5a594bbad5/docs/AUDIT.md
- Real-world check: https://github.com/kenil1710/sandwichrefund/blob/38654099c748cb295cb23a1f5d7c0b5a594bbad5/docs/REAL_WORLD_CHECK.md
- Feasibility: https://github.com/kenil1710/sandwichrefund/blob/38654099c748cb295cb23a1f5d7c0b5a594bbad5/docs/FEASIBILITY.md
- Rules: https://github.com/kenil1710/sandwichrefund/blob/38654099c748cb295cb23a1f5d7c0b5a594bbad5/docs/RULES.md
- Attack round: https://github.com/kenil1710/sandwichrefund/blob/38654099c748cb295cb23a1f5d7c0b5a594bbad5/docs/ATTACK_REPORT.md
- Deployed source: https://github.com/kenil1710/sandwichrefund/blob/38654099c748cb295cb23a1f5d7c0b5a594bbad5/build/SandwichRefund.py, https://github.com/kenil1710/sandwichrefund/blob/38654099c748cb295cb23a1f5d7c0b5a594bbad5/build/MEVGate.py, https://github.com/kenil1710/sandwichrefund/blob/38654099c748cb295cb23a1f5d7c0b5a594bbad5/deployments.json
- Keeper, a scheduled run: https://github.com/kenil1710/sandwichrefund/actions/runs/39790704197
- Live source check: https://sandwichrefund.vercel.app/verify

## Addresses

- SandwichRefund: 0x0D1fa49E0d39Ed8a592cB1f87e21BD825a644EFA
- SandwichRefundDemo: 0x3445CA1fDaEEBe026DAaf19Da4228a96a2444F31
- MEVGate: 0x96D529d8f63EC5D742907DfaE83A02627D35E1e9
- MEVGateDemo: 0x4f5bd0ABa738cD21b58495Ed962D6bC6369D8694
