// A throwaway EIP-1193 wallet for the e2e run: a fresh key made in memory for this run (never written to disk),
// funded from the Studio Dev faucet. The page's window.ethereum forwards every request here; transactions are
// signed locally and sent raw to Studio Dev.
import { generatePrivateKey, privateKeyToAccount } from "viem/accounts";

export const STUDIO = "https://studio-dev.genlayer.com/api";
export const CHAIN_ID = 61997;

export async function rpc(method, params = []) {
  for (let i = 0; i < 6; i++) {
    try {
      const r = await fetch(STUDIO, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ jsonrpc: "2.0", id: Date.now(), method, params }) });
      const j = await r.json();
      if (j.error) { if (/rate limit|-32029/i.test(JSON.stringify(j.error))) { await new Promise((s) => setTimeout(s, 12000)); continue; } throw Object.assign(new Error(j.error.message), { code: j.error.code }); }
      return j.result;
    } catch (e) { if (i === 5 || e.code) throw e; await new Promise((s) => setTimeout(s, 2000 * (i + 1))); }
  }
}

export async function throwawayWallet(page) {
  const account = privateKeyToAccount(generatePrivateKey());
  await rpc("sim_fundAccount", [account.address, 50 * 1e18]);
  const sent = [];
  await page.exposeFunction("__e2eWallet", async (method, paramsJson) => {
    const params = JSON.parse(paramsJson);
    try {
      let result;
      if (method === "eth_requestAccounts" || method === "eth_accounts") result = [account.address];
      else if (method === "eth_chainId") result = "0x" + CHAIN_ID.toString(16);
      else if (method === "wallet_switchEthereumChain" || method === "wallet_addEthereumChain") result = null;
      else if (method === "eth_sendTransaction") {
        const t = params[0];
        const raw = await account.signTransaction({ type: "legacy", chainId: CHAIN_ID, to: t.to, data: t.data, value: BigInt(t.value ?? 0),
          gas: BigInt(t.gas ?? 3_000_000), gasPrice: BigInt(t.gasPrice ?? 0), nonce: Number(BigInt(t.nonce ?? (await rpc("eth_getTransactionCount", [account.address, "pending"])))) });
        result = await rpc("eth_sendRawTransaction", [raw]);
        sent.push(result);
      } else result = await rpc(method, params);
      return JSON.stringify({ result });
    } catch (e) {
      return JSON.stringify({ error: { code: e.code ?? -32000, message: String(e.message ?? e) } });
    }
  });
  await page.addInitScript(() => {
    const listeners = {};
    window.ethereum = {
      isE2E: true,
      request: async ({ method, params }) => {
        const out = JSON.parse(await window.__e2eWallet(method, JSON.stringify(params ?? [])));
        if (out.error) throw Object.assign(new Error(out.error.message), { code: out.error.code });
        return out.result;
      },
      on: (ev, fn) => { (listeners[ev] ??= []).push(fn); },
      removeListener: () => {},
    };
  });
  return { address: account.address, sent };
}
