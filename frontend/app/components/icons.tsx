type IconProps = {
  className?: string;
};

export function BasketIcon({ className }: IconProps) {
  return (
    <svg className={className} viewBox="0 0 24 24" aria-hidden="true">
      <path d="M4 9h16l-1.3 10H5.3L4 9Z" fill="none" stroke="currentColor" strokeWidth="1.8" />
      <path d="m8 10 4-6 4 6M8 13v3m4-3v3m4-3v3" fill="none" stroke="currentColor" strokeLinecap="round" strokeWidth="1.8" />
    </svg>
  );
}

export function CheckIcon({ className }: IconProps) {
  return (
    <svg className={className} viewBox="0 0 20 20" aria-hidden="true">
      <path d="m4 10 3.5 3.5L16 5.8" fill="none" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" />
    </svg>
  );
}

export function StoreIcon({ className }: IconProps) {
  return (
    <svg className={className} viewBox="0 0 24 24" aria-hidden="true">
      <path d="M4 10v9h16v-9M3 5h18l-1 5a3 3 0 0 1-4 0 3 3 0 0 1-4 0 3 3 0 0 1-4 0 3 3 0 0 1-4 0L3 5Z" fill="none" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.7" />
      <path d="M9 19v-5h6v5" fill="none" stroke="currentColor" strokeWidth="1.7" />
    </svg>
  );
}

export function ArrowIcon({ className }: IconProps) {
  return (
    <svg className={className} viewBox="0 0 20 20" aria-hidden="true">
      <path d="M4 10h11m-4-4 4 4-4 4" fill="none" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.8" />
    </svg>
  );
}
