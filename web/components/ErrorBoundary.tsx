import React from 'react';

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
        <div style={{ padding: 40, textAlign: 'center', color: '#f1f5f9' }}>
          <h2 style={{ color: '#fca5a5', marginBottom: 8 }}>Status: Degraded</h2>
          <p style={{ color: '#94a3b8', marginBottom: 20 }}>
            The application encountered an error. Please refresh to continue.
          </p>
          <button
            onClick={() => window.location.reload()}
            style={{
              padding: '8px 20px',
              border: '1px solid #4a5568',
              borderRadius: 6,
              background: '#1e293b',
              color: '#f1f5f9',
              cursor: 'pointer',
              fontSize: 14,
            }}
          >
            Refresh Now
          </button>
          {this.state.error && (
            <pre style={{ marginTop: 20, fontSize: 12, color: '#64748b', textAlign: 'left', maxWidth: 600, margin: '20px auto', background: '#111827', padding: '12px 16px', borderRadius: 6, overflowX: 'auto' }}>
              {this.state.error.message}
            </pre>
          )}
        </div>
      );
    }

    return this.props.children;
  }
}
