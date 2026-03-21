/**
 * ProtectedRoute — HOC for protecting pages with authentication
 */

import React from 'react';
import { useRouter } from 'next/router';
import { useAuth } from './useAuth';
import { C } from './theme';

export function withAuth<P extends object>(Component: React.ComponentType<P>) {
  return function ProtectedComponent(props: P) {
    const router = useRouter();
    const { isAuthenticated, isLoading } = useAuth();

    // Show loading while checking auth
    if (isLoading) {
      return (
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            minHeight: '100vh',
            background: C.bg,
            color: C.muted,
          }}
        >
          <div style={{ textAlign: 'center' }}>
            <div style={{ fontSize: '48px', marginBottom: '16px', animation: 'spin 1s linear infinite' }}>
              ⚙️
            </div>
            <div>Loading dashboard...</div>
            <style>{`
              @keyframes spin {
                from { transform: rotate(0deg); }
                to { transform: rotate(360deg); }
              }
            `}</style>
          </div>
        </div>
      );
    }

    // Redirect to login if not authenticated
    if (!isAuthenticated) {
      router.push('/login');
      return null;
    }

    // Render protected component
    return <Component {...props} />;
  };
}
