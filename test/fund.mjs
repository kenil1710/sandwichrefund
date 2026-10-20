// Funds every test role from the Studio Dev faucet (no-op elsewhere).
import { CHAINS, accounts, fundOnStudio } from "./harness.mjs";
const acc = accounts();
for (const [role, a] of Object.entries(acc)) {
  const ok = await fundOnStudio(CHAINS.studiodev, a.address, 500n * 10n ** 18n);
  console.log(role.padEnd(10), a.address, ok ? "funded" : "not funded");
}
