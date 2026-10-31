/** A pallet seen from above: the product's mark. */
export function Mark() {
  return (
    <svg className="mark" viewBox="0 0 20 20" aria-hidden="true">
      <rect x="1" y="1" width="18" height="18" rx="2" fill="#17191b" />
      <rect x="4" y="4" width="5" height="5" fill="#f0b323" />
      <rect x="11" y="4" width="5" height="5" fill="#f6f6f3" />
      <rect x="4" y="11" width="5" height="5" fill="#f6f6f3" />
      <rect x="11" y="11" width="5" height="5" fill="#f6f6f3" />
    </svg>
  );
}
