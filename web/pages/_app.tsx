import type { AppProps } from 'next/app';
import Head from 'next/head';
import { useRouter } from 'next/router';
import ErrorBoundary from '../components/ErrorBoundary';
import Layout from '../components/Layout';
import { useAuth } from '../src/useAuth';
import '../styles/animations.css';

export default function App({ Component, pageProps }: AppProps) {
  const router = useRouter();
  const { isAuthenticated, isLoading } = useAuth();

  // Pages that don't require authentication
  const publicPages = ['/login', '/about'];
  const isPublicPage = publicPages.includes(router.pathname);

  // Show loading while checking auth
  if (isLoading && !isPublicPage) {
    return (
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', minHeight: '100vh', background: '#0a0f1e', color: '#64748b' }}>
        <div style={{ textAlign: 'center' }}>
          <div style={{ fontSize: '48px', marginBottom: '16px', animation: 'spin 1s linear infinite' }}>⚙️</div>
          <div>Loading...</div>
          <style>{`@keyframes spin { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }`}</style>
        </div>
      </div>
    );
  }

  // Redirect to login if not authenticated and not on public page
  if (!isAuthenticated && !isPublicPage && !isLoading) {
    if (typeof window !== 'undefined') {
      router.push('/login');
    }
    return null;
  }

  return (
    <>
      <Head>
        {/* Viewport must live in _app (not _document) per Next.js requirements */}
        <meta name="viewport" content="width=device-width, initial-scale=1" />
        {/*
          Default title template — individual pages should override this via
          their own <Head><title>Page Name | WAGMI</title></Head>.
        */}
        <title>WAGMI — AI-Powered Crypto Trading Bot</title>
        <meta name="description" content="WAGMI: AI-driven crypto trading signals, LLM decision analysis, copy-trade intelligence, and backtested proof." />
      </Head>
      <ErrorBoundary>
        <Layout>
          <Component {...pageProps} />
        </Layout>
      </ErrorBoundary>
    </>
  );
}
