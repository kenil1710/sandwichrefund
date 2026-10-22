# End-to-end run (Playwright)

`e2e/flow.e2e.js` drives the site in Chrome with a throwaway wallet (`e2e/wallet.js`: a key generated in memory for
the run, never written down, funded from the Studio Dev faucet; the page's `window.ethereum` signs locally and sends
raw transactions to Studio Dev) on the demo contract:

1. connect the wallet;
2. a pool with a 5 s claim period is **rejected** (BAD_CLAIM_PERIOD; the GEN is credited back);
3. a pool is **created** (0.05 GEN, 600 s claim period);
4. a real sandwiched Ethereum swap is **filed**; the case page shows SANDWICHED_REFUNDED and the refund **arrives** at
   the victim (Studio Dev balance delta = refund);
5. the same swap filed again is **refused** (ALREADY_DECIDED_SANDWICHED_REFUNDED);
6. after the claim period the pool is **closed**; refunded + returned = funded and the GEN comes back to the wallet.

Result: [summary.json](summary.json), [run.log](run.log), screenshots `01`-`07`, the HTML report in `report/`, and the
video and trace in `artifacts/`. This run served the production build of `frontend/` locally (`next start`) because
the hosting account had reached its daily deployment limit at the time; it reads and writes the same contracts the
site uses.

    cd e2e && npm ci && SITE=https://sandwichrefund.vercel.app npx playwright test
