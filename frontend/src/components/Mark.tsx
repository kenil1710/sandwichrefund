/** The mark: a sandwich of three bars, the red bread around a mint filling with a return arrow (frontend/public/logo.svg). */
export function Mark({ size = 28 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 64 64" aria-hidden="true">
      <rect x="6" y="7" width="52" height="14" rx="7" fill="#E5484D" />
      <rect x="6" y="25" width="52" height="14" rx="7" fill="#00C2A8" />
      <path d="M42 28.2v2.6a3.2 3.2 0 0 1-3.2 3.2H24.5" fill="none" stroke="#0E1A3A" strokeWidth="3.2" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M28.6 29.9 24.5 34l4.1 4.1" fill="none" stroke="#0E1A3A" strokeWidth="3.2" strokeLinecap="round" strokeLinejoin="round" />
      <rect x="6" y="43" width="52" height="14" rx="7" fill="#E5484D" />
    </svg>
  );
}
