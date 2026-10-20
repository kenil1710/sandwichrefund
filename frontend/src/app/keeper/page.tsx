import type { Metadata } from "next";
import { keeperStatus } from "@/lib/server";
import { REPO, STUDIO_EXPLORER } from "@/lib/deployments";
import { short } from "@/lib/format";

export const metadata: Metadata = { title: "Keeper" };
export const revalidate = 60;

export default async function Keeper() {
  const s = await keeperStatus();
  if (!s) return <><h1>Keeper</h1><p className="note warn">The keeper&apos;s status file (keeper-state branch) is unreadable right now.</p></>;
  return (
    <>
      <p className="kicker" style={{ marginTop: 28 }}>GitHub Actions · hourly and 6-hourly · signer {short(s.keeper)}</p>
      <h1>Keeper</h1>
      <p className="lede">Scans each open pool&apos;s block range page by page (a page counts only when two Ethereum endpoints returned the same logs), files every candidate victim, waits for FINALIZED and re-reads the case, retries what did not land, and closes pools after their claim period. Nothing is skipped silently: everything not finished is listed below.</p>
      <p>Last run: {s.started_at} → {s.finished_at} ({s.trigger}){s.run_url && <> · <a href={s.run_url}>run log</a></>} · <a href={`${REPO}/tree/keeper-state`}>keeper-state branch</a> · <a href={`${REPO}/actions/workflows/keeper.yml`}>workflow</a></p>
      {Object.entries(s.contracts).map(([name, c]) => (
        <section key={name}>
          <h2>{name}</h2>
          <div className="tiles">
            {Object.entries(c.totals ?? {}).filter(([k]) => k !== "by_result").map(([k, v]) => <div key={k} className="tile"><div className="n">{String(v)}</div><div className="l">{k}</div></div>)}
          </div>
          <p className="small">Results: {Object.entries((c.totals?.by_result as Record<string, number>) ?? {}).map(([k, v]) => `${k} ${v}`).join(" · ") || "none yet"}</p>
          <h3>Scan cursors</h3>
          <div className="scroll"><table className="table"><thead><tr><th>pool</th><th>status</th><th>chain</th><th>cursor</th><th>pages ok</th><th>pages to retry</th><th>done</th></tr></thead><tbody>
            {Object.entries(c.pools ?? {}).flatMap(([pid, p]) => Object.entries(p.chains ?? {}).length ? Object.entries(p.chains).map(([ch, x]) => (
              <tr key={pid + ch}><td>#{pid} {p.name}</td><td>{p.status}</td><td>{ch}</td><td className="mono">{x.cursor}</td><td>{x.pages_ok}</td><td>{x.failed.length}</td><td>{x.done ? "yes" : "no"}</td></tr>
            )) : [<tr key={pid}><td>#{pid} {p.name}</td><td>{p.status}</td><td colSpan={5} className="small">not scanned ({name.endsWith("Demo") ? "demo cases are filed by the demo script; the keeper only closes" : "closed or past its deadline"})</td></tr>])}
          </tbody></table></div>
          <h3>Not finished ({c.unprocessed?.length ?? 0})</h3>
          {c.unprocessed?.length ? <ul className="small">{c.unprocessed.map((u) => <li key={u.key}><span className="mono">{u.key}</span>: {u.why}</li>)}</ul> : <p className="small">Nothing pending.</p>}
          <h3>Actions ({c.actions?.length ?? 0})</h3>
          <div className="scroll"><table className="table"><thead><tr><th>action</th><th>status</th><th>result</th><th>tx</th><th>attempts</th><th>found by</th></tr></thead><tbody>
            {(c.actions ?? []).map((a) => <tr key={a.key}><td className="mono small">{a.kind} {a.hash ? short(a.hash, 8) : `pool ${a.pool_id}`}</td><td>{a.status}</td><td>{a.result}</td><td>{a.tx && <a className="mono small" href={`${STUDIO_EXPLORER}/tx/${a.tx}`}>{short(a.tx, 6)}</a>}</td><td>{a.attempts}</td><td className="small">{a.why}{a.last_error && ` · ${a.last_error}`}</td></tr>)}
          </tbody></table></div>
        </section>
      ))}
      <h2>Run history</h2>
      <div className="scroll"><table className="table"><thead><tr><th>started</th><th>trigger</th><th>runs</th></tr></thead><tbody>
        {[...(s.history ?? [])].reverse().map((h) => <tr key={h.started_at}><td>{h.run_url ? <a href={h.run_url}>{h.started_at}</a> : h.started_at}</td><td>{h.trigger}</td><td className="small">{Object.entries(h.runs).map(([n, r]) => `${n}: submitted ${r.submitted}, done ${r.done}, pages ${r.pages} (failed ${r.pages_failed})`).join(" · ")}</td></tr>)}
      </tbody></table></div>
    </>
  );
}
