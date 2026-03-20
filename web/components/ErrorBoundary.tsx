import React from 'react';
import { C, R, F } from '../src/theme';

type State = {
  hasError: boolean;
  error?: Error;
};

export default class ErrorBoundary extends React.Component<{ children: React.ReactNode }, State> {
  constructor(props: any) {
    super(props);
    this.state = { hasError: false };
  }

  static getDerivedStateFromError(error: Error) {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, info: React.ErrorInfo) {
    console.error('UI Error:', error, info);
  }

  render() {
    if (this.state.hasError) {
      return (
        <div style={{ padding: 40, textAlign: 'center', color: C.text }}>
          <h2 style={{ color: C.bear, marginBottom: 8, fontSize: F.xl, fontWeight: 700 }}>Status: Degraded</h2>
          <p style={{ color: C.muted, marginBottom: 20, fontSize: F.sm }}>
            The application encountered an error. Please refresh to continue.
          </p>
          <button
            onClick={() => window.location.reload()}
            style={{
              padding: '8px 20px',
              border: `1px solid ${C.border}`,
              borderRadius: R.md,
              background: C.surface,
              color: C.text,
              cursor: 'pointer',
              fontSize: F.sm,
              fontWeight: 600,
            }}
          >
            Refresh Now
          </button>
          {this.state.error && (
            <pre style={{ marginTop: 20, fontSize: F.xs, color: C.muted, textAlign: 'left', maxWidth: 600, margin: '20px auto', background: C.bg, padding: '12px 16px', borderRadius: R.md, overflowX: 'auto', border: `1px solid ${C.border}` }}>
              {this.state.error.message}
            </pre>
          )}
        </div>
      );
    }

    return this.props.children;
  }
}
