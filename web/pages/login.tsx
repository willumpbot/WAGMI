/**
 * /login — WAGMI Dashboard Entry Gate
 * Beautiful passcode authentication page
 */

import React, { useState, useRef } from 'react';
import Head from 'next/head';
import { useRouter } from 'next/router';
import { C, R, F, G, S, A } from '../src/theme';
import { useAuth } from '../src/useAuth';

export default function LoginPage() {
  const router = useRouter();
  const { login, error } = useAuth();
  const [passcode, setPasscode] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setIsSubmitting(true);
    const success = await login(passcode);
    if (success) {
      router.push('/');
    }
    setIsSubmitting(false);
    setPasscode('');
    inputRef.current?.focus();
  };

  return (
    <>
      <Head>
        <title>WAGMI Dashboard — Login</title>
        <meta name="description" content="Enter the WAGMI trading intelligence dashboard" />
      </Head>

      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          minHeight: '100vh',
          background: `linear-gradient(135deg, ${C.bg} 0%, #0d1529 50%, #0f172a 100%)`,
          padding: '20px',
          fontFamily: 'system-ui, -apple-system, sans-serif',
        }}
      >
        <div style={{ animation: `slideInUp 0.6s cubic-bezier(0.34, 1.56, 0.64, 1)` }}>
          {/* Main container */}
          <div
            style={{
              width: '100%',
              maxWidth: '420px',
              background: C.card,
              border: `1px solid ${C.border}`,
              borderRadius: R.lg,
              padding: '48px 32px',
              boxShadow: S.lg,
              textAlign: 'center',
            }}
          >
            {/* Logo / Title */}
            <div style={{ marginBottom: '12px', fontSize: '48px' }}>🤖</div>
            <h1
              style={{
                fontSize: F['3xl'],
                fontWeight: 800,
                color: C.text,
                margin: '0 0 8px 0',
                letterSpacing: '-0.5px',
              }}
            >
              WAGMI Dashboard
            </h1>
            <p
              style={{
                fontSize: F.sm,
                color: C.muted,
                margin: '0 0 32px 0',
              }}
            >
              Autonomous trading intelligence
            </p>

            {/* Form */}
            <form onSubmit={handleSubmit} style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
              {/* Passcode Input */}
              <div>
                <label
                  style={{
                    display: 'block',
                    fontSize: F.xs,
                    fontWeight: 700,
                    color: C.muted,
                    marginBottom: '8px',
                    textTransform: 'uppercase',
                    letterSpacing: '1px',
                  }}
                >
                  Passcode
                </label>
                <input
                  ref={inputRef}
                  type="password"
                  value={passcode}
                  onChange={(e) => setPasscode(e.target.value)}
                  placeholder="Enter passcode"
                  style={{
                    width: '100%',
                    padding: '12px 16px',
                    fontSize: F.md,
                    background: C.surface,
                    color: C.text,
                    border: `1px solid ${error ? C.bear : C.border}`,
                    borderRadius: R.md,
                    transition: `all 0.2s ease`,
                    outline: 'none',
                    fontFamily: 'monospace',
                    letterSpacing: '2px',
                    boxSizing: 'border-box',
                  }}
                  onFocus={(e) => {
                    e.currentTarget.style.borderColor = C.brand;
                    e.currentTarget.style.boxShadow = S.glow;
                  }}
                  onBlur={(e) => {
                    e.currentTarget.style.borderColor = error ? C.bear : C.border;
                    e.currentTarget.style.boxShadow = 'none';
                  }}
                  disabled={isSubmitting}
                  autoFocus
                />
              </div>

              {/* Error message */}
              {error && (
                <div
                  style={{
                    fontSize: F.xs,
                    color: C.bear,
                    background: `rgba(220, 38, 38, 0.1)`,
                    border: `1px solid ${C.bear}`,
                    borderRadius: R.sm,
                    padding: '8px 12px',
                    animation: `slideInDown 0.3s ease`,
                  }}
                >
                  {error}
                </div>
              )}

              {/* Submit button */}
              <button
                type="submit"
                disabled={!passcode || isSubmitting}
                style={{
                  padding: '12px 20px',
                  fontSize: F.md,
                  fontWeight: 700,
                  background: C.brand,
                  color: '#fff',
                  border: 'none',
                  borderRadius: R.md,
                  cursor: passcode && !isSubmitting ? 'pointer' : 'default',
                  opacity: !passcode || isSubmitting ? 0.5 : 1,
                  transition: A.hover,
                  textTransform: 'uppercase',
                  letterSpacing: '1px',
                  boxShadow: S.md,
                }}
                onMouseEnter={(e) => {
                  if (passcode && !isSubmitting) {
                    (e.currentTarget as HTMLButtonElement).style.transform = 'translateY(-2px)';
                    (e.currentTarget as HTMLButtonElement).style.boxShadow = S.lg;
                  }
                }}
                onMouseLeave={(e) => {
                  (e.currentTarget as HTMLButtonElement).style.transform = 'translateY(0)';
                  (e.currentTarget as HTMLButtonElement).style.boxShadow = S.md;
                }}
              >
                {isSubmitting ? '🔐 Verifying...' : '✓ Enter Dashboard'}
              </button>
            </form>

            {/* Footer info */}
            <div
              style={{
                marginTop: '32px',
                paddingTop: '24px',
                borderTop: `1px solid ${C.border}`,
                fontSize: F.xs,
                color: C.muted,
              }}
            >
              <p style={{ margin: '0 0 8px 0' }}>🚀 9-agent autonomous trading intelligence</p>
              <p style={{ margin: 0 }}>Real-time decision transparency & learning</p>
            </div>
          </div>

          {/* Floating elements for visual interest */}
          <div
            style={{
              position: 'fixed',
              top: '20%',
              left: '5%',
              width: '100px',
              height: '100px',
              borderRadius: '50%',
              background: `rgba(99, 102, 241, 0.05)`,
              pointerEvents: 'none',
              animation: `float 6s ease-in-out infinite`,
            }}
          />
          <div
            style={{
              position: 'fixed',
              bottom: '10%',
              right: '5%',
              width: '80px',
              height: '80px',
              borderRadius: '50%',
              background: `rgba(168, 85, 247, 0.05)`,
              pointerEvents: 'none',
              animation: `float 8s ease-in-out infinite 1s`,
            }}
          />

          {/* Float animation */}
          <style>{`
            @keyframes float {
              0%, 100% {
                transform: translateY(0px);
              }
              50% {
                transform: translateY(20px);
              }
            }
            @keyframes slideInUp {
              from {
                opacity: 0;
                transform: translateY(20px);
              }
              to {
                opacity: 1;
                transform: translateY(0);
              }
            }
            @keyframes slideInDown {
              from {
                opacity: 0;
                transform: translateY(-10px);
              }
              to {
                opacity: 1;
                transform: translateY(0);
              }
            }
          `}</style>
        </div>
      </div>
    </>
  );
}
