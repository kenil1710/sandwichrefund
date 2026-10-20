import { ADDR, COMMIT, REPO, STUDIO_EXPLORER } from "@/lib/deployments";

export function Footer() {
  return (
    <footer className="foot">
      <div className="wrap">
        <p>
          SandwichRefund on GenLayer Studio Dev. Contract <a className="mono" href={`${STUDIO_EXPLORER}/address/${ADDR.registry}`}>{ADDR.registry}</a>,
          gate <a className="mono" href={`${STUDIO_EXPLORER}/address/${ADDR.gate}`}>{ADDR.gate}</a>, deployed from commit{" "}
          <a className="mono" href={`${REPO}/commit/${COMMIT}`}>{COMMIT.slice(0, 7)}</a>. Source: <a href={REPO}>{REPO.replace("https://", "")}</a>.
        </p>
        <p>Every verdict is decided by code from Ethereum chain data read twice; nobody approves refunds. Refunds are GEN on Studio Dev, a test network.</p>
      </div>
    </footer>
  );
}
