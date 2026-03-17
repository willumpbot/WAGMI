import React from 'react';
import Link from 'next/link';
import { useRouter } from 'next/router';

const NAV_ITEMS = [
  { href: '/', label: 'Dashboard' },
  { href: '/copy-trade', label: 'Copy Trade' },
  { href: '/strategies', label: 'Strategies' },
];

export default function Layout({ children }: { children: React.ReactNode }) {
  const router = useRouter();

  return (
    <div style={{ minHeight: '100vh', background: '#fafafa' }}>
      <nav
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 24,
          padding: '12px 20px',
          borderBottom: '1px solid #e0e0e0',
          background: '#fff',
          maxWidth: 1200,
          margin: '0 auto',
        }}
      >
        <Link href="/" style={{ fontWeight: 700, fontSize: 18, textDecoration: 'none', color: '#111' }}>
          WAGMI
        </Link>
        <div style={{ display: 'flex', gap: 16 }}>
          {NAV_ITEMS.map((item) => {
            const isActive = router.pathname === item.href;
            return (
              <Link
                key={item.href}
                href={item.href}
                style={{
                  fontSize: 14,
                  fontWeight: isActive ? 600 : 400,
                  color: isActive ? '#111' : '#666',
                  textDecoration: 'none',
                  padding: '4px 8px',
                  borderRadius: 6,
                  background: isActive ? '#f0f0f0' : 'transparent',
                }}
              >
                {item.label}
              </Link>
            );
          })}
        </div>
      </nav>
      <main style={{ maxWidth: 1200, margin: '0 auto', padding: '20px' }}>
        {children}
      </main>
    </div>
  );
}
