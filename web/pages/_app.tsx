import type { AppProps } from 'next/app';
import Head from 'next/head';
import ErrorBoundary from '../components/ErrorBoundary';
import Layout from '../components/Layout';

export default function App({ Component, pageProps }: AppProps) {
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
