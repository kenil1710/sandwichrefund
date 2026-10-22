# Playwright e2e on the live site

`cd e2e && npx playwright test` drives https://sandwichrefund.vercel.app in Chrome with a throwaway wallet (key saved
in the gitignored test/.accounts.json before use) on SandwichRefundDemo 0x3445CA1fDaEEBe026DAaf19Da4228a96a2444F31:
connect, a refused create (BAD_CLAIM_PERIOD, 0.001 GEN credited), Withdraw credit (credit back to 0), create a pool,
file a real sandwiched swap (refund verified at the victim), the same case refused, close after the claim period
(the rest verified at the sponsor wallet). summary.json lists every step and transaction; screenshots 01-07, the
HTML report and the trace/video are in this folder.

Two earlier attempts on this contract stopped at the Withdraw credit step (the page read the credit through the CDN
cache, fixed in the sponsor page); each left 0.001 GEN credit, withdrawn afterwards with its saved key
(0x5F37528173b9401490e8afE107fcBbE175003d53, 0x5811ef7C6bC27633ac56a8663D677fA004C1c84b). After this run the demo
contract holds 0: credit owed 0, open pools 0, eth_getBalance 0.

wallet_delta_after_fee in credit_withdrawn is read right after the withdrawal is accepted, before its 0.001 GEN
lands, so it shows only the fee; the step's proof is get_credit = 0.
