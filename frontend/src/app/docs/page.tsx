import type { Metadata } from "next";
import { readFileSync } from "node:fs";
import path from "node:path";
import { marked } from "marked";
import rules from "./rules.json";
import { REPO } from "@/lib/deployments";

export const metadata: Metadata = { title: "Rules" };

export default function Docs() {
  const md = readFileSync(path.join(process.cwd(), "src/content/RULES.md"), "utf8");
  return (
    <>
      <p className="kicker" style={{ marginTop: 28 }}>docs/RULES.md, as in the repository · sha256 {rules.rules_md_sha256.slice(0, 16)}</p>
      <article className="prose" dangerouslySetInnerHTML={{ __html: marked.parse(md, { async: false }) as string }} />
      <p className="small">Every reason and number above is checked against the contract code by test/test_meaning.py. Source: <a href={`${REPO}/blob/main/docs/RULES.md`}>docs/RULES.md</a>.</p>
    </>
  );
}
