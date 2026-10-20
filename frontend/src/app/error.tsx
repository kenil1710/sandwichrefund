"use client";
export default function Error({ error, reset }: { error: Error; reset: () => void }) {
  return (
    <>
      <h1>Something did not load</h1>
      <p className="note warn">{String(error?.message ?? error).slice(0, 200)}. Studio Dev may be rate limiting reads; nothing is shown rather than a guess.</p>
      <button className="btn" onClick={reset}>Try again</button>
    </>
  );
}
