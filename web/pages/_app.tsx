import type { AppProps } from 'next/app';
import Head from 'next/head';
import { useRouter } from 'next/router';
import { AnimatePresence, motion } from 'framer-motion';
import ErrorBoundary from '../components/ErrorBoundary';
import Layout from '../components/Layout';

export default function App({ Component, pageProps }: AppProps) {
  const router = useRouter();

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
          <AnimatePresence mode="wait" initial={false}>
            <motion.div
              key={router.pathname}
              initial={{ opacity: 0, y: 12, scale: 0.995, filter: 'blur(2px)' }}
              animate={{ opacity: 1, y: 0, scale: 1, filter: 'blur(0px)' }}
              exit={{ opacity: 0, y: -6, filter: 'blur(1px)' }}
              transition={{ duration: 0.3, ease: [0.22, 1, 0.36, 1] }}
            >
              <Component {...pageProps} />
            </motion.div>
          </AnimatePresence>
        </Layout>
      </ErrorBoundary>
    </>
  );
}
