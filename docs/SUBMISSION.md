# Submission

Plain ASCII. Lengths checked by `node tools/submission.mjs`.

## One-liner (167/180 characters)

SandwichRefund: a sponsor funds a pool; GenLayer validators read Ethereum swaps from two RPCs, code detects same-block sandwiches and refunds the victim's loss in GEN.

## Description (790/1000 characters)

Wallets and DEX front-ends route users into sandwich attacks and cannot prove or repay the loss. SandwichRefund lets a sponsor lock GEN in a pool with frozen terms: covered routers, Uniswap V2/V3 pools, block range, refund rate per profit token, caps, claim period. Anyone files a victim tx; every validator reads its receipt and the pool's Swap logs from two Ethereum RPCs and code decides: one actor's front-run and back-run on the victim's pool in the same block with positive profit is SANDWICHED and the attacker's net profit is refunded to tx.from at once. Partial patterns are UNCLEAR, never paid. Seeded with 65 real swaps of 2026-10-20: 18 sandwiched (jaredfromsubway and 8 other bots), 16 clean, 31 unclear; 18 refunds arrived. MEVGate answers consumers; a keeper scans and files.

## Review verification (493/500 characters)

Live: sandwichrefund.vercel.app (/verify: code vs GitHub). Studio Dev: SandwichRefund 0x774B1200fB05f19b057390CF1DdA1Ea2AD109917, demo 0x7f75A7166500404FB7A7590Cd9c495Eb6EEed932, MEVGate 0x2A0446ced7A4F7dA8542f6Db05a466E32B8A274d, demo 0xb74aB6983c50595396CDD48C407F52Da254811f5. Repo github.com/kenil1710/sandwichrefund: sh test/run_offline.sh (385 tests), node tools/verify_source.mjs, node tools/final_check.mjs. Deploy commit f5e60cc. docs/SEEDS.md proves 18 canonical and 13 demo payouts.

## Counts

- Real cases: 65 (SANDWICHED 18, CLEAN 16, UNCLEAR 31), read from two Ethereum RPCs on a Mac and inside GenVM, identical.
- Canonical pool: SANDWICHED_REFUNDED 18, UNCLEAR 31, CLEAN 16; 0.221 GEN refunded, 1.279 GEN returned to the sponsor at close.
- Real-world check: 18/18 SANDWICHED and 16/16 CLEAN confirmed.
- Demo: 35 steps, 13 payouts, all arrived; demo contract balance at the end 0 wei.
- Offline tests: 385.

## Evidence (pinned)

Commit `15e1d6f8c18f8051ddf5177b679ee6e5cddd3cbe`; contracts deployed from `f5e60cc6b48e9222909d0524d26f0e2385943c8c`.

- Seeds, every refund and its arrival: https://github.com/kenil1710/sandwichrefund/blob/15e1d6f8c18f8051ddf5177b679ee6e5cddd3cbe/docs/SEEDS.md
- Final check: https://github.com/kenil1710/sandwichrefund/blob/15e1d6f8c18f8051ddf5177b679ee6e5cddd3cbe/docs/FINAL_CHECK.md
- Real-world check: https://github.com/kenil1710/sandwichrefund/blob/15e1d6f8c18f8051ddf5177b679ee6e5cddd3cbe/docs/REAL_WORLD_CHECK.md
- Feasibility: https://github.com/kenil1710/sandwichrefund/blob/15e1d6f8c18f8051ddf5177b679ee6e5cddd3cbe/docs/FEASIBILITY.md
- Rules: https://github.com/kenil1710/sandwichrefund/blob/15e1d6f8c18f8051ddf5177b679ee6e5cddd3cbe/docs/RULES.md
- Attack round: https://github.com/kenil1710/sandwichrefund/blob/15e1d6f8c18f8051ddf5177b679ee6e5cddd3cbe/docs/ATTACK_REPORT.md
- Deployed source: https://github.com/kenil1710/sandwichrefund/blob/15e1d6f8c18f8051ddf5177b679ee6e5cddd3cbe/build/SandwichRefund.py, https://github.com/kenil1710/sandwichrefund/blob/15e1d6f8c18f8051ddf5177b679ee6e5cddd3cbe/build/MEVGate.py, https://github.com/kenil1710/sandwichrefund/blob/15e1d6f8c18f8051ddf5177b679ee6e5cddd3cbe/deployments.json
- Keeper, a scheduled run: https://github.com/kenil1710/sandwichrefund/actions/runs/39445834048
- Live source check: https://sandwichrefund.vercel.app/verify

## Addresses

- SandwichRefund: 0x774B1200fB05f19b057390CF1DdA1Ea2AD109917
- SandwichRefundDemo: 0x7f75A7166500404FB7A7590Cd9c495Eb6EEed932
- MEVGate: 0x2A0446ced7A4F7dA8542f6Db05a466E32B8A274d
- MEVGateDemo: 0xb74aB6983c50595396CDD48C407F52Da254811f5
