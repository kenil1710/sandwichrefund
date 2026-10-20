import Link from "next/link";
import { Mark } from "./Mark";
import { WalletButton } from "./WalletButton";

const LINKS: [string, string][] = [
  ["/", "Board"], ["/lookup", "Was I sandwiched?"], ["/pools", "Pools"], ["/sponsor", "Sponsor"], ["/gate", "MEVGate"],
  ["/keeper", "Keeper"], ["/verify", "Verify"], ["/docs", "Rules"],
];

export function Masthead() {
  return (
    <header className="mast">
      <a className="skip" href="#main">Skip to content</a>
      <div className="wrap">
        <Link href="/" className="brand" aria-label="SandwichRefund home"><Mark /><b>SandwichRefund</b></Link>
        <nav className="nav" aria-label="Main">
          {LINKS.map(([href, label]) => <Link key={href} href={href}>{label}</Link>)}
        </nav>
        <WalletButton />
      </div>
    </header>
  );
}
