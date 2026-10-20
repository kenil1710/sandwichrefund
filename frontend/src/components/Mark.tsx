/** The mark: a receipt with a sandwich (two red bars around a navy one) and a mint refund tick. */
export function Mark({ size = 28 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" aria-hidden="true">
      <path d="M6 2h20v26l-2.5-2-2.5 2-2.5-2-2.5 2-2.5-2-2.5 2-2.5-2L6 28z" fill="#111214" />
      <rect x="9" y="7" width="14" height="3" fill="#e5484d" />
      <rect x="9" y="12" width="14" height="3" fill="#f1f1ec" />
      <rect x="9" y="17" width="14" height="3" fill="#e5484d" />
      <circle cx="24" cy="24" r="6" fill="#00c2a8" stroke="#f6f4ee" strokeWidth="1.5" />
      <path d="M21.3 24.2l1.8 1.8 3.6-3.8" stroke="#0e1a3a" strokeWidth="1.8" fill="none" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}
