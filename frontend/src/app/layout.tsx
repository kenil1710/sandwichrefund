import type { Metadata, Viewport } from "next";
import { Space_Grotesk, JetBrains_Mono } from "next/font/google";
import "./globals.css";
import { Masthead } from "@/components/Masthead";
import { Footer } from "@/components/Footer";
import { WalletProvider } from "@/components/WalletProvider";

const display = Space_Grotesk({ subsets: ["latin"], weight: ["400", "500", "700"], variable: "--font-display", display: "swap" });
const mono = JetBrains_Mono({ subsets: ["latin"], weight: ["400", "700"], variable: "--font-mono", display: "swap" });

export const metadata: Metadata = {
  title: { default: "SandwichRefund", template: "%s · SandwichRefund" },
  description: "Sponsor-funded refunds for sandwiched swaps, decided by code from Ethereum chain data on GenLayer.",
  icons: { icon: "/icon.svg" },
};
export const viewport: Viewport = { themeColor: "#f6f4ee", width: "device-width", initialScale: 1 };

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${display.variable} ${mono.variable}`} style={{ ["--font-body" as string]: "var(--font-display)" }}>
      <body>
        <WalletProvider>
          <Masthead />
          <main id="main" className="wrap">{children}</main>
          <Footer />
        </WalletProvider>
      </body>
    </html>
  );
}
