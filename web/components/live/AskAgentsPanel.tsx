'use client';

import React, { useEffect, useRef, useState } from 'react';
import { C, F, R } from '../../src/theme';
import { resolveApiBase } from '../../src/api';

/**
 * AskAgentsPanel — interactive Q&A with the LLM agents.
 * Listens for `ask-agents:prefill` window events from SynthesisColumn to
 * pre-fill suggested questions; user can also type their own.
 *
 * Phase 4e: UI shell only. Backend POST /v1/agents/ask wires later.
 * For now, sends a templated mock response after a 600ms delay so the
 * interaction feel is right.
 *
 * History persisted in localStorage per symbol.
 */

type Message = {
  role: 'user' | 'agent';
  agent?: 'trade' | 'risk' | 'critic' | 'regime' | 'all';
  text: string;
  ts: number;
};

const STORAGE_PREFIX = 'wagmi-ask-agents-';

export default function AskAgentsPanel({
  symbol,
  mode,
  replayTimestamp,
}: {
  symbol: string;
  mode: 'live' | 'replay';
  replayTimestamp?: string;
}) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState('');
  const [agentTarget, setAgentTarget] = useState<'all' | 'trade' | 'risk' | 'critic' | 'regime'>('all');
  const [busy, setBusy] = useState(false);
  const inputRef = useRef<HTMLTextAreaElement | null>(null);

  // Load history from localStorage when symbol changes
  useEffect(() => {
    try {
      const raw = localStorage.getItem(STORAGE_PREFIX + symbol);
      if (raw) setMessages(JSON.parse(raw));
      else setMessages([]);
    } catch {
      setMessages([]);
    }
  }, [symbol]);

  // Save history on change
  useEffect(() => {
    try {
      localStorage.setItem(STORAGE_PREFIX + symbol, JSON.stringify(messages.slice(-50)));
    } catch {
      /* quota? ignore */
    }
  }, [messages, symbol]);

  // Listen for prefill events from SynthesisColumn
  useEffect(() => {
    const onPrefill = (e: Event) => {
      const detail = (e as CustomEvent<string>).detail;
      if (typeof detail === 'string') {
        setInput(detail);
        inputRef.current?.focus();
      }
    };
    window.addEventListener('ask-agents:prefill', onPrefill);
    return () => window.removeEventListener('ask-agents:prefill', onPrefill);
  }, []);

  const send = async () => {
    const text = input.trim();
    if (!text || busy) return;

    const userMsg: Message = { role: 'user', text, ts: Date.now() };
    setMessages((m) => [...m, userMsg]);
    setInput('');
    setBusy(true);

    try {
      // TODO: wire to POST /v1/agents/ask once backend implemented.
      // For now, mock a templated response so the UX feel is real.
      const apiBase = resolveApiBase();
      let response: { agent: string; text: string }[] = [];
      try {
        const r = await fetch(`${apiBase}/v1/agents/ask`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            agent: agentTarget,
            question: text,
            context: {
              symbol,
              mode,
              replay_timestamp: replayTimestamp || null,
            },
          }),
        });
        if (r.ok) {
          const j = await r.json();
          response = j.responses || [];
        }
      } catch {
        // backend not yet implemented
      }

      if (response.length === 0) {
        // Fallback mock so the UX still works during development
        await new Promise((r) => setTimeout(r, 500));
        response = mockResponse(agentTarget, text, symbol);
      }

      const agentMsgs: Message[] = response.map((r) => ({
        role: 'agent',
        agent: r.agent as Message['agent'],
        text: r.text,
        ts: Date.now(),
      }));
      setMessages((m) => [...m, ...agentMsgs]);
    } finally {
      setBusy(false);
    }
  };

  const clear = () => {
    setMessages([]);
    try {
      localStorage.removeItem(STORAGE_PREFIX + symbol);
    } catch {
      /* ignore */
    }
  };

  return (
    <div
      style={{
        marginTop: 12,
        background: '#0a0a0f',
        border: `1px solid ${C.border}`,
        borderTop: `2px solid ${C.brand}`,
        borderRadius: R.sm,
        display: 'flex',
        flexDirection: 'column',
      }}
    >
      <header
        style={{
          padding: '10px 12px',
          borderBottom: `1px solid ${C.border}`,
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
        }}
      >
        <span
          style={{
            fontSize: 10,
            fontWeight: 700,
            color: C.brand,
            letterSpacing: 0.08,
            fontFamily: 'JetBrains Mono, monospace',
          }}
        >
          ASK THE AGENTS
        </span>
        <button
          onClick={clear}
          style={{
            background: 'transparent',
            border: `1px solid ${C.border}`,
            color: C.muted,
            fontSize: 10,
            padding: '2px 8px',
            borderRadius: 3,
            cursor: 'pointer',
            fontFamily: 'JetBrains Mono, monospace',
          }}
        >
          clear
        </button>
      </header>

      {/* Conversation */}
      <div
        style={{
          maxHeight: 260,
          overflowY: 'auto',
          padding: 12,
          display: 'flex',
          flexDirection: 'column',
          gap: 10,
        }}
      >
        {messages.length === 0 && (
          <div style={{ color: C.muted, fontSize: F.sm, fontStyle: 'italic' }}>
            Ask the agents anything about {symbol}. Try: "What's the strongest counter-thesis to a long here?"
          </div>
        )}
        {messages.map((m, i) => (
          <MessageBubble key={i} message={m} />
        ))}
        {busy && (
          <div style={{ color: C.muted, fontSize: F.xs, fontFamily: 'JetBrains Mono, monospace' }}>
            agents thinking…
          </div>
        )}
      </div>

      {/* Composer */}
      <div
        style={{
          padding: 10,
          borderTop: `1px solid ${C.border}`,
          display: 'flex',
          flexDirection: 'column',
          gap: 8,
        }}
      >
        <div style={{ display: 'flex', gap: 4, fontSize: F.xs, alignItems: 'center' }}>
          <span style={{ color: C.muted }}>ask:</span>
          {(['all', 'trade', 'risk', 'critic', 'regime'] as const).map((a) => {
            const active = agentTarget === a;
            return (
              <button
                key={a}
                onClick={() => setAgentTarget(a)}
                style={{
                  padding: '2px 8px',
                  fontSize: 10,
                  fontWeight: 600,
                  fontFamily: 'JetBrains Mono, monospace',
                  background: active ? C.brand + '15' : 'transparent',
                  color: active ? C.brand : C.textSub,
                  border: `1px solid ${active ? C.brand : C.border}`,
                  borderRadius: 3,
                  cursor: 'pointer',
                }}
              >
                {a}
              </button>
            );
          })}
        </div>
        <div style={{ display: 'flex', gap: 8, alignItems: 'flex-end' }}>
          <textarea
            ref={inputRef}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
                e.preventDefault();
                send();
              }
            }}
            placeholder={`Ask about ${symbol} — Ctrl/Cmd+Enter to send`}
            rows={2}
            style={{
              flex: 1,
              background: '#050508',
              border: `1px solid ${C.border}`,
              color: C.text,
              padding: '8px 10px',
              fontSize: F.sm,
              borderRadius: R.xs,
              resize: 'vertical',
              fontFamily: 'inherit',
              outline: 'none',
              minHeight: 40,
            }}
          />
          <button
            onClick={send}
            disabled={busy || !input.trim()}
            style={{
              padding: '8px 16px',
              background: input.trim() && !busy ? C.brand : C.faint,
              color: '#000',
              border: 'none',
              borderRadius: R.xs,
              fontSize: F.sm,
              fontWeight: 700,
              cursor: input.trim() && !busy ? 'pointer' : 'not-allowed',
              fontFamily: 'inherit',
              transition: 'background 120ms ease-out',
            }}
          >
            Send
          </button>
        </div>
      </div>
    </div>
  );
}

function MessageBubble({ message }: { message: Message }) {
  if (message.role === 'user') {
    return (
      <div
        style={{
          alignSelf: 'flex-end',
          maxWidth: '80%',
          padding: '8px 12px',
          background: C.brand + '15',
          border: `1px solid ${C.brand + '55'}`,
          borderRadius: R.sm,
          color: C.text,
          fontSize: F.sm,
          lineHeight: 1.5,
        }}
      >
        {message.text}
      </div>
    );
  }
  const agentLabel = message.agent ? message.agent.toUpperCase() : 'AGENT';
  return (
    <div
      style={{
        alignSelf: 'flex-start',
        maxWidth: '85%',
        padding: '8px 12px',
        background: '#050508',
        border: `1px solid ${C.border}`,
        borderLeft: `3px solid ${C.purple}`,
        borderRadius: R.sm,
      }}
    >
      <div
        style={{
          fontSize: 10,
          fontWeight: 700,
          color: C.purple,
          fontFamily: 'JetBrains Mono, monospace',
          marginBottom: 4,
          letterSpacing: 0.06,
        }}
      >
        {agentLabel}
      </div>
      <div style={{ color: C.textSub, fontSize: F.sm, lineHeight: 1.5 }}>{message.text}</div>
    </div>
  );
}

function mockResponse(target: string, question: string, symbol: string): { agent: string; text: string }[] {
  // Templated stand-ins until POST /v1/agents/ask is wired.
  const note = `[mock — backend POST /v1/agents/ask not yet implemented; this is a placeholder]`;
  if (target === 'all') {
    return [
      { agent: 'trade', text: `On ${symbol}: I'd want to see confluence with the regime call before adding. ${note}` },
      { agent: 'critic', text: `Counter: have you considered the impact of the current funding rate? ${note}` },
      { agent: 'risk', text: `Sizing-wise, given current bankroll, no more than 1% risk on this idea. ${note}` },
    ];
  }
  return [
    {
      agent: target,
      text: `Re: "${question.slice(0, 80)}…" — ${target} agent thoughts on ${symbol} would go here. ${note}`,
    },
  ];
}
