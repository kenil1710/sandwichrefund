# Rules

Every rule below is the code: `contracts/SandwichRefund.py`, `contracts/MEVGate.py` and the shared helpers
`contracts/shared/common.py` (the rule, `judge`) and `contracts/shared/rpc.py` (the read). `tools/build.py` inlines the
helpers into `build/*.py`, the exact bytes that are deployed. `test/test_meaning.py` checks that every reason the code
can return is named here and that every number here is the code's.

## 1. Pools

A sponsor opens a pool with `create_pool(name, chains, routers, kinds, ranges, rates, max_per_swap, max_per_victim,
claim_period_s, meta)` and sends the pool's GEN with the call. The terms freeze at creation:

| term | meaning | limits |
|---|---|---|
| chains | chains covered | each must be in `CHAINS` (Ethereum) |
| routers | `[{chain, address, name}]`: the victim transaction's `to` must be one | 1 to `MAX_ROUTERS` = 32, no zero address |
| kinds | pool types: `V2` (Uniswap V2-style Swap event) and/or `V3` (Uniswap V3-style) | at least one |
| ranges | `[{chain, start_block, end_block}]`, one per chain, inclusive | `end_block - start_block` <= `MAX_SPAN_BLOCKS` = 5000000 |
| rates | `[{chain, token, num, den, symbol, decimals}]`: refund = profit * num // den GEN wei per token wei | 1 to `MAX_RATES` = 12, num and den 1 to 10^30 |
| max_per_swap | most GEN one case pays | > 0 |
| max_per_victim | most GEN one victim address gets from this pool | >= max_per_swap |
| claim_period_s | cases are accepted until created_at + claim_period_s (the claim deadline) | mode minimum to 180 days |

The pool must hold at least `MIN_POOL` = 10^15 wei (0.001 GEN). There is no cancel and no way to change a term.
The sponsor may only:

- **top up** (`top_up`, payable, anyone): adds to an open pool before its claim deadline;
- **extend** (`extend`, sponsor only): moves the claim deadline later, at most `MAX_EXTEND_S` = 180 days past the original.

`create_pool` and `top_up` never raise. A refusal credits the value back to the sender (`withdraw_refund`) and
returns the reason: NO_CLOCK, POOL_BELOW_MINIMUM, POOL_TOO_LARGE, NAME_REQUIRED, CHAINS_BAD_JSON, CHAINS_EMPTY,
UNSUPPORTED_CHAIN, ROUTERS_BAD_JSON, ROUTERS_EMPTY, ROUTERS_TOO_MANY, ROUTERS_BAD_ENTRY, ROUTERS_CHAIN_NOT_IN_POOL,
ROUTERS_BAD_ADDRESS, KINDS_BAD_JSON, KINDS_UNKNOWN, KINDS_EMPTY, RANGES_BAD_JSON, RANGES_BAD_ENTRY,
RANGES_CHAIN_NOT_IN_POOL, RANGES_BAD_BLOCKS, RANGES_TOO_LONG, RANGES_DUPLICATE_CHAIN, RANGES_MISSING_CHAIN,
RATES_BAD_JSON, RATES_EMPTY, RATES_TOO_MANY, RATES_BAD_ENTRY, RATES_CHAIN_NOT_IN_POOL, RATES_BAD_TOKEN,
RATES_BAD_RATE, RATES_BAD_DECIMALS, RATES_DUPLICATE_TOKEN, BAD_MAX_PER_SWAP, BAD_MAX_PER_VICTIM, BAD_CLAIM_PERIOD,
META_BAD_JSON, META_NOT_OBJECT, META_TOO_LONG; for `top_up`: NO_SUCH_POOL, POOL_IS_CLOSED, CLAIM_PERIOD_OVER,
NO_VALUE, POOL_TOO_LARGE.

### Modes

| mode | min claim period (s) | filings per (pool, sender) | window (s) | sweep delay (s) |
|---|---|---|---|---|
| CANONICAL | 3600 | 200 | 3600 | 172800 |
| DEMO | 60 | 60 | 600 | 3600 |

## 2. A case: what is read

A case is (pool, chain, victim transaction hash). Anyone files it with `file_case(pool_id, chain, tx_hash)` while
the pool is open and before its claim deadline (refused: NO_SUCH_POOL, POOL_IS_CLOSED, CLAIM_PERIOD_OVER,
CHAIN_NOT_IN_POOL, BAD_HASH, ALREADY_DECIDED_<state>, RATE_LIMITED_UNTIL_<time>).

The leader and every validator read, from BOTH RPCs of the chain
(`https://rpc.mevblocker.io` and `https://eth-mainnet.public.blastapi.io`), in JSON-RPC batches of at most
`BATCH_MAX` = 12 calls:

1. the transaction, its receipt, the `finalized` block and the chain id;
2. the receipt's Uniswap V2 / V3 `Swap` logs (topics `0xd78ad95f...` and `0xc42079f9...`), which name the victim's
   pools; if there are more than `MAX_POOLS` = 4 nothing more is read (flag TOO_MANY_POOLS);
3. `eth_getLogs` for those pools, both Swap topics, the victim's block and the next one, and each pool's `token0()`,
   `token1()`, `factory()` and (V3) `fee()`;
4. for each pool whose factory is listed in `FACTORIES` (Uniswap V2 `0x5c69bee7...`, SushiSwap V2 `0xc0aee478...`,
   Uniswap V3 `0x1f98431c...`), that factory's `getPair(token0, token1)` / `getPool(token0, token1, fee)`: the pool is
   canonical only if it answers the pool's own address; and the sender (`from`, `to`) of every other transaction with a
   swap on those pools in the block. More than `MAX_TXS` = 40 such transactions: nothing more is read (flag
   BLOCK_TOO_BUSY).

The two RPCs' answers must be identical. Read failures give a reason instead of facts: RPC_UNREADABLE (an endpoint
did not answer, answered an error or an unusable batch), RPC_DISAGREE (they answer differently, or one has the
transaction and the other does not), WRONG_CHAIN_ID, TX_NOT_FOUND, TX_PENDING, UNSUPPORTED_CHAIN.
The facts are `final` only when the victim's block AND the next are at or below both RPCs' finalized heads.

Consensus: a validator agrees with the leader when both could not read (any reasons), when the leader saw the case
unfinalized, or when its own facts are final and identical to the leader's. Anything else, or an exception, is a
disagreement: the transaction is not applied and the case can be filed again.

## 3. The verdict (`judge`)

In this order:

1. A read failure: **UNVERIFIABLE** with its reason. Facts not final: **UNVERIFIABLE** NOT_FINALIZED.
2. **NOT_COVERED**: TX_FAILED (receipt status is not 1), ROUTER_NOT_COVERED (`to` is not a covered router of this
   chain), OUTSIDE_BLOCK_RANGE, NO_SWAP_IN_TX, POOL_TYPE_NOT_COVERED (its swaps are of an uncovered kind),
   POOL_NOT_CANONICAL (its only pool fails the factory check).
3. **UNCLEAR** TOO_MANY_HOPS, BLOCK_TOO_BUSY.
4. More than one covered swap in the victim transaction (multi-hop): **UNCLEAR** MULTI_HOP_VICTIM if any of its
   canonical pools shows a front/back pair or a partial pattern; else **CLEAN** NO_PATTERN.
5. One swap on pool P in direction d (0: the pool received token0 and paid token1; 1: the reverse; neither:
   **UNCLEAR** VICTIM_DIRECTION_UNREADABLE). Other swaps on P in the block are paired:
   - a **front-run** f: a lower transaction index, direction d;
   - a **back-run** b: a higher transaction index, the opposite direction;
   - **same actor**: the same `tx.from`, or the same Swap recipient when that recipient is not the zero address, a
     covered router, the victim's `to` or one of the pools.
   No pair: **UNCLEAR** PARTIAL_PATTERN when one actor swaps on P both before and after the victim; **UNCLEAR**
   CROSS_BLOCK_PATTERN when an actor's earlier same-direction swap is answered by an opposite swap paid to the same
   recipient in the next block; else **CLEAN** NO_PATTERN.
6. Pairs that share an EOA or a recipient are one attacker. Two or more attackers: **UNCLEAR** MULTIPLE_ATTACKERS.
   One attacker with more than one front-run or back-run: **UNCLEAR** COMPLEX_PATTERN.
7. **UNCLEAR** SELF_SANDWICH when the victim's `tx.from` or its swap's recipient is any of the pair's EOAs,
   contracts (`to`) or recipients.
8. **UNCLEAR** MULTIPLE_VICTIMS when another actor's swap in direction d sits between f and b.
9. The attacker's profit, counted conservatively. With X the victim's input token and Y its output:
   `netX = X out of the back-run - X into the front-run`, `netY = Y out of the front-run - Y into the back-run`.
   - netX > 0 and netY >= 0: netX in X;
   - netY > 0 and netX >= 0: netY in Y;
   - netX > 0 > netY: only the part of the back-run that sells the front-run's Y counts: `bXout*fYout//bYin - fXin` in X;
   - netY > 0 > netX: what is left of Y after buying back the front-run's X: `fYout - ceil(bYin*fXin/bXout)` in Y;
   - otherwise, or not positive: **UNCLEAR** NO_ATTACKER_PROFIT.
   If both tokens gained, the priced one is used (X first). The profit token has no rate in this pool: **UNCLEAR**
   PROFIT_TOKEN_NOT_PRICED.
10. **SANDWICHED** SAME_POOL_SANDWICH. The loss estimate is the attacker's profit.

Amounts are the pool's own Swap amounts: V2 `amount0In - amount0Out`, `amount1In - amount1Out`; V3 `amount0`,
`amount1` (signed int256, positive = the pool received).

## 4. The refund

For a SANDWICHED case:

    refund = min(loss * num // den, max_per_swap, max_per_victim - paid_to_victim_by_this_pool, pool_balance)

The binding term is recorded as `limit`: RATE, MAX_PER_SWAP, MAX_PER_VICTIM, POOL_BALANCE, or REFUND_ROUNDS_TO_ZERO.
A positive refund is sent to the victim (the transaction's `tx.from`) in the same call: **SANDWICHED_REFUNDED**.
Zero: **SANDWICHED_UNPAID**. If the contract's balance is below the refund the call is refused
(CONTRACT_BALANCE_BELOW_REFUND).

States: CLEAN, SANDWICHED_REFUNDED, SANDWICHED_UNPAID and UNCLEAR are final: a pool decides each case once
(ALREADY_DECIDED_<state>). NOT_COVERED and UNVERIFIABLE may be filed again. Each pool decides for itself, so a case
can be refunded by several pools, each under its own terms and caps; a tiny pool filed first cannot lock a victim
out of a larger one. `get_case` reports a transaction's strongest decision (SANDWICHED_REFUNDED >
SANDWICHED_UNPAID > UNCLEAR > CLEAN > NOT_COVERED > UNVERIFIABLE; on a tie the larger refund).

## 5. Closing, and every GEN's exit

After the claim deadline anyone calls `close_pool`: what is left goes to the sponsor (refused before:
CLAIM_PERIOD_OPEN_UNTIL_<time>; twice: ALREADY_CLOSED; CONTRACT_BALANCE_BELOW_POOL). GEN leaves only through one
external value message per call (`gl.evm.Account(to).emit_call(amount, b"")`): a refund (`file_case`), a close
(`close_pool`), a credit (`withdraw_refund`, refused: NOTHING_TO_WITHDRAW, CONTRACT_BALANCE_BELOW_CREDIT) or stray
value (`sweep_stray`: balance above what the ledger holds, sent to the deployer, at least the mode's sweep delay
after the last send; refused: SENDS_MAY_BE_PENDING_UNTIL_<time>, NO_STRAY_BALANCE). The caller funds the message
with an External allocation naming the recipient. Ledger: `received = held + refunded + returned + credits paid`,
`held = open pool balances + credits owed`. A transaction that times out or is undetermined applies nothing; the case
is filed again (UNVERIFIABLE is never a verdict).

Counters move only after every check passed. Every list is paginated with `offset` and `limit` (at most
`PAGE_MAX` = 50): `get_pools`, `get_cases`, `get_pool_cases`, `get_victim`, `get_attackers`; plus `get_pool`,
`get_case`, `get_pool_case`, `get_case_by_id`, `get_credit`, `get_config`, `get_stats`.

## 6. MEVGate

`check_case(chain, tx_hash)` reads the registry's `get_case` and answers one of NO_POOL (nobody filed it and no pool
covers the chain), NOT_COVERED, CLEAN, SANDWICHED_REFUNDED, SANDWICHED_UNPAID, UNCLEAR, UNVERIFIABLE (not filed, a
failed or malformed read, or numbers that do not add up). `clean` is true only for a final CLEAN case;
`refunded` only for SANDWICHED_REFUNDED with a positive payout. `check_address(address)` reads every page of
`get_victim` (up to 200 cases) and counts its cases per state; its summary is the worst state in the order
SANDWICHED_UNPAID, UNCLEAR, UNVERIFIABLE, SANDWICHED_REFUNDED, NOT_COVERED, CLEAN; no cases or an incomplete read is
UNVERIFIABLE, never CLEAN. `attest_case` stores a reading with its time. The gate holds no value and makes no web
request.

## 7. Scope

SandwichRefund detects the classic same-pool sandwich within one block: a front-run and a back-run by one actor on
the victim's own pool around the victim's single swap. The refund is the attacker's net profit, a conservative
estimate of the victim's loss (the victim's worse price is at least what the attacker took). Other forms of MEV
(multi-pool and multi-hop sandwiches, bundles with several victims, back-runs in later blocks, JIT liquidity,
cross-domain arbitrage) are ruled UNCLEAR when they show in the victim's pool, and are not otherwise looked for.
Only Uniswap V2 and V3 Swap events from pools their listed factory knows are read.
