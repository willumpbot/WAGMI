import React, { useState, useCallback } from 'react';
import Head from 'next/head';
import { C, R, S, F, G } from '../src/theme';

// ── Types ──
type CoursePage =
  | 'dashboard' | 'start-here' | 'start'
  | 'step1' | 'step2' | 'step3' | 'step4' | 'step5' | 'step6'
  | 'strat-trendline' | 'strat-mfi' | 'strat-macro'
  | 'bull-market' | 'backtesting'
  | 'resources' | 'alerts' | 'dictionary' | 'faq' | 'video-library' | 'videos';

// ── Shared Components ──
const card = { background: G.card, border: `1px solid ${C.border}`, borderRadius: R.lg, padding: 20, marginBottom: 16 };
const grid3 = { display: 'grid', gridTemplateColumns: 'repeat(auto-fill,minmax(260px,1fr))', gap: 16, marginBottom: 24 } as const;
const grid2 = { display: 'grid', gridTemplateColumns: 'repeat(auto-fill,minmax(320px,1fr))', gap: 16, marginBottom: 24 } as const;
const grid4 = { display: 'grid', gridTemplateColumns: 'repeat(auto-fill,minmax(180px,1fr))', gap: 12, marginBottom: 24 } as const;
const cardStyle: React.CSSProperties = { background: G.card, border: `1px solid ${C.border}`, borderRadius: R.lg, padding: 20, marginBottom: 16 };
const inputStyle: React.CSSProperties = { width: '100%', padding: '8px 12px', borderRadius: R.sm, border: `1px solid ${C.border}`, background: C.surface, color: C.text, fontSize: F.sm, outline: 'none' };
const btnStyle: React.CSSProperties = { padding: '10px 20px', borderRadius: R.md, border: 'none', background: C.brand, color: '#fff', cursor: 'pointer', fontWeight: 700, fontSize: F.sm };
const metricRow = { display: 'flex', flexWrap: 'wrap' as const, gap: 12, marginBottom: 24 };
const metricCard = { flex: '1 1 140px', background: C.surface, borderRadius: R.md, padding: '14px 16px', textAlign: 'center' as const, border: `1px solid ${C.border}` };

function PageHeader({ title, subtitle }: { title: string; subtitle: string }) {
  return <div style={{ marginBottom: 28 }}><h1 style={{ color: C.text, fontSize: F['3xl'], fontWeight: 800, margin: 0 }}>{title}</h1><p style={{ color: C.muted, fontSize: F.md, marginTop: 6 }}>{subtitle}</p></div>;
}

function InfoBox({ children, color, type }: { children: React.ReactNode; color?: string; type?: 'tip' | 'warning' | 'success' }) {
  const typeColors: Record<string, string> = { tip: '#00d4ff', warning: '#eab308', success: '#16a34a' };
  const c = color || (type ? typeColors[type] : C.info) || C.info;
  return <div style={{ padding: '14px 18px', background: c + '15', border: `1px solid ${c}33`, borderRadius: R.md, fontSize: F.sm, color: C.textSub, lineHeight: 1.7, marginBottom: 16 }}>{children}</div>;
}

function CourseCard({ icon, title, desc, tag, onClick, style: extraStyle }: { icon?: string; title: string; desc: string; tag?: string; onClick?: () => void; style?: React.CSSProperties }) {
  return (
    <div onClick={onClick} style={{ ...card, cursor: onClick ? 'pointer' : 'default', position: 'relative', ...extraStyle }}>
      {tag && <div style={{ position: 'absolute', top: 10, right: 10, fontSize: F.xs, fontWeight: 700, padding: '2px 8px', borderRadius: R.sm, background: C.brand + '22', color: C.brand }}>{tag}</div>}
      {icon && <div style={{ fontSize: 28, marginBottom: 8 }}>{icon}</div>}
      <div style={{ fontSize: F.md, fontWeight: 700, color: C.text, marginBottom: 4 }}>{title}</div>
      <div style={{ fontSize: F.sm, color: C.textSub, lineHeight: 1.5 }}>{desc}</div>
    </div>
  );
}

function MetricVal({ value, label, color }: { value: string; label: string; color?: string }) {
  return <div style={metricCard}><div style={{ fontSize: F['2xl'], fontWeight: 800, color: color || C.brand }}>{value}</div><div style={{ fontSize: F.xs, color: C.muted, marginTop: 4 }}>{label}</div></div>;
}

function Video({ id }: { id: string }) {
  return <div style={{ position: 'relative', paddingBottom: '56.25%', height: 0, margin: '16px 0 24px', borderRadius: R.md, overflow: 'hidden' }}><iframe src={`https://www.youtube.com/embed/${id}`} style={{ position: 'absolute', top: 0, left: 0, width: '100%', height: '100%', border: 'none' }} allowFullScreen /></div>;
}

function StepNav({ back, next, onNavigate }: { back?: { page: CoursePage; label: string }; next?: { page: CoursePage; label: string }; onNavigate: (p: CoursePage) => void }) {
  const btn = (primary: boolean): React.CSSProperties => ({ padding: '10px 20px', borderRadius: R.md, border: primary ? 'none' : `1px solid ${C.border}`, background: primary ? C.brand : C.card, color: primary ? '#fff' : C.text, cursor: 'pointer', fontWeight: 600, fontSize: F.sm });
  return <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 32, paddingTop: 20, borderTop: `1px solid ${C.border}` }}>{back ? <button style={btn(false)} onClick={() => onNavigate(back.page)}>{back.label}</button> : <div />}{next ? <button style={btn(true)} onClick={() => onNavigate(next.page)}>{next.label}</button> : <div />}</div>;
}

function Quiz({ questions, step }: { questions: { q: string; options: string[]; correct: number }[]; step: string }) {
  const [answers, setAnswers] = useState<Record<number, number>>({});
  const [submitted, setSubmitted] = useState(false);
  const score = submitted ? questions.filter((q, i) => answers[i] === q.correct).length : 0;
  return (
    <div style={{ ...card, borderColor: C.brand + '44' }}>
      <h3 style={{ color: C.text, marginTop: 0 }}>Knowledge Check Quiz</h3>
      {questions.map((q, qi) => (
        <div key={qi} style={{ marginBottom: 16 }}>
          <p style={{ color: C.text, fontWeight: 600, fontSize: F.sm }}>{q.q}</p>
          {q.options.map((opt, oi) => {
            const selected = answers[qi] === oi;
            const isCorrect = submitted && oi === q.correct;
            const isWrong = submitted && selected && oi !== q.correct;
            return (
              <label key={oi} style={{ display: 'block', padding: '8px 12px', marginBottom: 4, borderRadius: R.sm, background: isCorrect ? C.bull + '22' : isWrong ? C.bear + '22' : selected ? C.brand + '22' : C.surface, border: `1px solid ${isCorrect ? C.bull : isWrong ? C.bear : selected ? C.brand : C.border}`, cursor: submitted ? 'default' : 'pointer', fontSize: F.sm, color: C.textSub }}>
                <input type="radio" name={`${step}-q${qi}`} checked={selected} onChange={() => !submitted && setAnswers(a => ({ ...a, [qi]: oi }))} style={{ marginRight: 8 }} />
                {opt}
              </label>
            );
          })}
        </div>
      ))}
      {!submitted ? (
        <button onClick={() => setSubmitted(true)} style={{ padding: '10px 24px', borderRadius: R.md, border: 'none', background: C.brand, color: '#fff', cursor: 'pointer', fontWeight: 700, fontSize: F.sm }}>Check Answers</button>
      ) : (
        <div style={{ padding: '12px 16px', borderRadius: R.md, background: score === questions.length ? C.bull + '22' : C.warn + '22', color: score === questions.length ? C.bull : C.warn, fontWeight: 700, fontSize: F.sm }}>
          {score}/{questions.length} correct {score === questions.length ? '— Great job!' : '— Review the material and try again.'}
        </div>
      )}
    </div>
  );
}

// ── Sidebar ──
function Sidebar({ page, onNavigate, isOpen, onToggle }: { page: CoursePage; onNavigate: (p: CoursePage) => void; isOpen: boolean; onToggle: () => void }) {
  const sections = [
    { label: 'Overview', items: [{ id: 'dashboard' as CoursePage, icon: '◆', label: 'Dashboard' }, { id: 'start-here' as CoursePage, icon: '🚀', label: 'Start Here' }] },
    { label: 'Course Steps', items: [
      { id: 'step1' as CoursePage, icon: '1', label: 'Basics & Candlesticks' },
      { id: 'step2' as CoursePage, icon: '2', label: 'TradingView Setup' },
      { id: 'step3' as CoursePage, icon: '3', label: 'Market Structure' },
      { id: 'step4' as CoursePage, icon: '4', label: 'Risk Management' },
      { id: 'step5' as CoursePage, icon: '5', label: 'Technical Indicators' },
      { id: 'step6' as CoursePage, icon: '6', label: 'Readiness Assessment' },
    ] },
    { label: 'Strategies', items: [
      { id: 'strat-trendline' as CoursePage, icon: '📈', label: 'Trendline Breakout' },
      { id: 'strat-mfi' as CoursePage, icon: '⚡', label: 'MFI + MACD' },
      { id: 'strat-macro' as CoursePage, icon: '🌐', label: '2-Week Macro' },
    ] },
    { label: 'Analysis', items: [
      { id: 'bull-market' as CoursePage, icon: '📈', label: 'Bull Market Analysis' },
      { id: 'backtesting' as CoursePage, icon: '📊', label: 'Backtesting Lab' },
    ] },
    { label: 'Resources', items: [
      { id: 'resources' as CoursePage, icon: '📚', label: 'Resources & Templates' },
      { id: 'alerts' as CoursePage, icon: '🔔', label: 'Alerts & Signals' },
      { id: 'dictionary' as CoursePage, icon: '📖', label: 'Trading Dictionary' },
      { id: 'faq' as CoursePage, icon: '❓', label: 'FAQ' },
      { id: 'video-library' as CoursePage, icon: '🎥', label: 'Video Library' },
    ] },
  ];

  return (
    <div style={{ width: 260, minHeight: '100%', background: C.surface, borderRight: `1px solid ${C.border}`, position: 'sticky', top: 0, overflowY: 'auto', flexShrink: 0, display: isOpen ? 'block' : undefined }} className="mc-sidebar">
      <div style={{ padding: '16px 16px 12px', borderBottom: `1px solid ${C.border}` }}>
        <div style={{ fontSize: F.md, fontWeight: 800, background: 'linear-gradient(135deg, #00e6a0, #00d4ff)', WebkitBackgroundClip: 'text', WebkitTextFillColor: 'transparent' }}>Nunu's Masterclass</div>
        <div style={{ fontSize: F.xs, color: C.muted, marginTop: 2 }}>Master the art of trading</div>
      </div>
      {sections.map(s => (
        <div key={s.label} style={{ padding: '8px 0' }}>
          <div style={{ padding: '4px 16px', fontSize: 10, fontWeight: 700, color: C.muted, textTransform: 'uppercase', letterSpacing: 1 }}>{s.label}</div>
          {s.items.map(item => (
            <div key={item.id} onClick={() => { onNavigate(item.id); onToggle(); }} style={{ padding: '8px 16px', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 8, fontSize: F.sm, color: page === item.id ? '#00e6a0' : C.textSub, background: page === item.id ? '#00e6a015' : 'transparent', borderLeft: page === item.id ? '3px solid #00e6a0' : '3px solid transparent', fontWeight: page === item.id ? 700 : 400 }}>
              <span style={{ fontSize: 12, width: 20, textAlign: 'center' }}>{item.icon}</span>
              {item.label}
            </div>
          ))}
        </div>
      ))}
      <style>{`
        @media (max-width: 768px) {
          .mc-sidebar { position: fixed !important; z-index: 1000; top: 0; left: 0; height: 100vh; display: ${isOpen ? 'block' : 'none'} !important; }
        }
      `}</style>
    </div>
  );
}


// ── Dashboard Page ──
function DashboardPage({ onNavigate }: { onNavigate: (p: CoursePage) => void }) {
  const steps = [
    { id: 'step1' as CoursePage, num: 1, title: 'Basics', desc: 'Candlesticks & Timeframes', icon: '📊' },
    { id: 'step2' as CoursePage, num: 2, title: 'Setup', desc: 'TradingView Configuration', icon: '⚙️' },
    { id: 'step3' as CoursePage, num: 3, title: 'Structure', desc: 'Trends & Levels', icon: '📐' },
    { id: 'step4' as CoursePage, num: 4, title: 'Risk', desc: 'Position Sizing & Stops', icon: '🛡️' },
    { id: 'step5' as CoursePage, num: 5, title: 'Indicators', desc: 'RSI, MACD, MFI, Stoch RSI', icon: '📈' },
    { id: 'step6' as CoursePage, num: 6, title: 'Assessment', desc: 'Readiness Evaluation', icon: '🎯' },
  ];
  return (
    <>
      <PageHeader title="Welcome to Nunu's Masterclass" subtitle="Master the art of trading with our comprehensive program" />
      <h2 style={{ color: C.text, fontSize: F.xl, marginBottom: 16 }}>Your Learning Journey</h2>
      <div style={grid3}>
        {steps.map(s => (
          <CourseCard key={s.id} icon={s.icon} title={`Step ${s.num}: ${s.title}`} desc={s.desc} tag="Available" onClick={() => onNavigate(s.id)} />
        ))}
      </div>
      <h2 style={{ color: C.text, fontSize: F.xl, marginTop: 32, marginBottom: 16 }}>Bull Market Analysis</h2>
      <CourseCard icon="🐂" title="Bull Market Analysis" desc="Current Market Phase: Phase 2: Early Bull Market | Peak Probability: 15%" tag="Explore" onClick={() => onNavigate('bull-market')} style={{ maxWidth: 480 }} />
      <h2 style={{ color: C.text, fontSize: F.xl, marginTop: 32, marginBottom: 16 }}>Core Concepts</h2>
      <div style={grid3}>
        <CourseCard icon="📐" title="Trend Analysis" desc="Learn to identify trends, support & resistance on higher timeframes." onClick={() => onNavigate('step3')} />
        <CourseCard icon="📈" title="Entry Signals" desc="Master RSI, MACD, MFI, and Stochastic RSI for high-probability entries." onClick={() => onNavigate('step5')} />
        <CourseCard icon="🛡️" title="Risk Management" desc="Position sizing, stop placement, and protecting your capital." onClick={() => onNavigate('step4')} />
      </div>
      <div style={{ ...card, textAlign: 'center', marginTop: 32 }}>
        <h2 style={{ color: C.text, marginTop: 0 }}>Ready to Begin?</h2>
        <p style={{ color: C.muted, marginBottom: 16 }}>Start your journey from the very first step.</p>
        <button onClick={() => onNavigate('start-here')} style={{ padding: '12px 28px', borderRadius: R.md, border: 'none', background: C.brand, color: '#fff', cursor: 'pointer', fontWeight: 700, fontSize: F.md }}>Start Here</button>
      </div>
      <h2 style={{ color: C.text, fontSize: F.xl, marginTop: 32, marginBottom: 16 }}>Strategies</h2>
      <div style={grid3}>
        <CourseCard icon="📉" title="Trendline Breakout" desc="Win Rate: 65% | R:R 1:2.5" tag="Strategy" onClick={() => onNavigate('strat-trendline')} />
        <CourseCard icon="💧" title="MFI + MACD" desc="Win Rate: 62% | R:R 1:2.0" tag="Strategy" onClick={() => onNavigate('strat-mfi')} />
        <CourseCard icon="🔭" title="2-Week Macro" desc="Win Rate: 68% | R:R 1:3.0" tag="Strategy" onClick={() => onNavigate('strat-macro')} />
      </div>
    </>
  );
}

// ── Start Here Page ──
function StartHerePage({ onNavigate }: { onNavigate: (p: CoursePage) => void }) {
  return (
    <>
      <PageHeader title="Start Your Trading Journey" subtitle="Welcome to Nunu's Masterclass!" />
      <InfoBox color={C.info}><strong>What you'll learn:</strong><ul style={{ margin: '8px 0 0', paddingLeft: 20 }}><li>Professional BTC trading strategies</li><li>Multi-timeframe analysis (16H → 6H → 1H)</li><li>High-probability setups with 60–70% win rates</li><li>Advanced risk management</li><li>Market psychology</li></ul></InfoBox>
      <InfoBox color={C.brand}><strong>Time Investment:</strong> 2–3 weeks to complete all modules.</InfoBox>
      <h2 style={{ color: C.text, marginBottom: 16 }}>Your Learning Path</h2>
      <div style={card}>
        {['Foundation Setup — 5 min', 'Step 1: Master the Basics — 30–45 min', 'Step 2: Trading Setup — 20–30 min', 'Step 3: HTF Structure — 45–60 min', 'Step 4: Risk Management — 30–45 min', 'Step 5: Technical Indicators — 60–90 min', 'Step 6: Practice & Assessment — 1–2 weeks', 'Advanced Strategies — Ongoing'].map((s, i) => (
          <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '10px 0', borderBottom: i < 7 ? `1px solid ${C.border}` : 'none' }}>
            <span style={{ width: 28, height: 28, borderRadius: '50%', background: i === 0 ? '#00e6a0' : C.surface, color: i === 0 ? '#000' : C.muted, display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: F.xs, fontWeight: 700, flexShrink: 0 }}>{i + 1}</span>
            <span style={{ color: C.textSub, fontSize: F.sm }}>{s}</span>
          </div>
        ))}
      </div>
      <h2 style={{ color: C.text, marginTop: 32, marginBottom: 16 }}>What Makes This Program Different</h2>
      <div style={grid3}>
        <CourseCard icon="🌍" title="Real-World Focus" desc="Every concept taught with live BTC chart examples and actionable setups." />
        <CourseCard icon="🔍" title="Multi-Timeframe Approach" desc="Learn to read charts from 16H down to 1H for confluence-based entries." />
        <CourseCard icon="🛡️" title="Risk-First Mentality" desc="Capital preservation is priority one. You learn sizing and stops before entries." />
        <CourseCard icon="🧠" title="Psychology Integration" desc="Mindset, discipline, and emotional control woven into every module." />
      </div>
      <h2 style={{ color: C.text, marginTop: 32, marginBottom: 16 }}>Prerequisites</h2>
      <div style={grid2}>
        <div style={card}><h3 style={{ color: C.bull, marginTop: 0 }}>What You Need</h3><ul style={{ paddingLeft: 20, color: C.textSub, fontSize: F.sm, lineHeight: 1.8 }}><li>A free TradingView account</li><li>2–3 hours per week to study</li><li>A demo/paper trading account</li><li>A notebook for journaling trades</li><li>Commitment to follow the process</li></ul></div>
        <div style={card}><h3 style={{ color: C.muted, marginTop: 0 }}>What You DON'T Need</h3><ul style={{ paddingLeft: 20, color: C.textSub, fontSize: F.sm, lineHeight: 1.8 }}><li>Prior trading experience</li><li>Large starting capital</li><li>Expensive software or tools</li><li>Advanced math background</li><li>Full-time availability</li></ul></div>
      </div>
      <h2 style={{ color: C.text, marginTop: 32, marginBottom: 16 }}>Success Metrics</h2>
      <div style={metricRow}><MetricVal value="60–70%" label="Target Win Rate" color={C.bull} /><MetricVal value="1:2+" label="Risk / Reward" color={C.info} /><MetricVal value="2–3%" label="Max Risk Per Trade" color={C.warn} /><MetricVal value="6–12 Mo" label="Time to Proficiency" color={C.purple} /></div>
      <InfoBox color={C.warn}><strong>Important Disclaimers:</strong><ul style={{ margin: '8px 0 0', paddingLeft: 20 }}><li>This course is for <strong>educational purposes only</strong> and is not financial advice.</li><li>Trading cryptocurrency involves <strong>significant risk of loss</strong>.</li><li>Past performance does not guarantee future results.</li><li>Always <strong>practice on a demo account</strong> before risking real capital.</li></ul></InfoBox>
      <StepNav next={{ page: 'step1', label: 'Step 1 →' }} back={{ page: 'dashboard', label: '← Dashboard' }} onNavigate={onNavigate} />
    </>
  );
}

// ── Step 1: Trading Fundamentals ──
function Step1({ onNavigate }: { onNavigate: (p: CoursePage) => void }) {
  return (<>
    <PageHeader title="Step 1: Trading Fundamentals" subtitle="Master the essential building blocks of technical analysis" />
    <Video id="JzTMlClbM84" />
    <h2 style={{ color: C.text }}>What You'll Learn</h2>
    <div style={grid3}>
      <CourseCard icon="🕯️" title="Candlestick Mastery" desc="Read price action like a professional trader through candlestick analysis" />
      <CourseCard icon="⏱️" title="Timeframe Analysis" desc="Understand how different timeframes interact and influence each other" />
      <CourseCard icon="📐" title="Pattern Recognition" desc="Identify high-probability reversal and continuation patterns" />
      <CourseCard icon="🧠" title="Market Psychology" desc="Decode the emotions behind price movements and exploit crowd behavior" />
    </div>
    <h2 style={{ color: C.text }}>Candlestick Anatomy</h2>
    <InfoBox color={C.info}>Every candlestick tells a story of battle between buyers and sellers. Learning to read them is the foundation of all technical analysis.</InfoBox>
    <h3 style={{ color: C.textSub }}>The Four Critical Price Points</h3>
    <div style={metricRow}><MetricVal value="Open" label="Price at which the candle began trading" color={C.bull} /><MetricVal value="High" label="Highest price reached — top of upper wick" color={C.info} /><MetricVal value="Low" label="Lowest price reached — bottom of lower wick" color={C.bear} /><MetricVal value="Close" label="Price at which the candle finished — determines body color" color={C.warn} /></div>
    <h3 style={{ color: C.textSub }}>Candlestick Types</h3>
    <div style={grid3}>
      <CourseCard icon="▲" title="Bullish" desc="Green body — close is higher than open. Buyers controlled the period." style={{ borderLeft: `3px solid ${C.bull}` }} />
      <CourseCard icon="▼" title="Bearish" desc="Red body — close is lower than open. Sellers controlled the period." style={{ borderLeft: `3px solid ${C.bear}` }} />
      <CourseCard icon="✚" title="Doji" desc="Tiny body — open ≈ close. Neither buyers nor sellers won the battle." style={{ borderLeft: `3px solid ${C.warn}` }} />
    </div>
    <h3 style={{ color: C.textSub }}>Wick Analysis</h3>
    <div style={grid3}>
      <CourseCard icon="┃" title="Long Lower Wick" desc="Buyers rejected lower prices — potential bullish reversal signal near support." />
      <CourseCard icon="┃" title="Long Upper Wick" desc="Sellers rejected higher prices — potential bearish reversal signal near resistance." />
      <CourseCard icon="█" title="Large Body, Small Wicks" desc="Strong directional conviction — one side completely dominated." />
    </div>
    <h2 style={{ color: C.text }}>Timeframe Mastery</h2>
    <div style={{ ...card, textAlign: 'center', padding: 24 }}>
      <p style={{ color: C.muted, marginBottom: 12 }}>Timeframe Hierarchy</p>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 12, flexWrap: 'wrap', fontSize: '1.2em', fontWeight: 700 }}>
        <span style={{ color: C.purple }}>1Y</span><span style={{ color: C.muted }}>→</span>
        <span style={{ color: C.info }}>1M</span><span style={{ color: C.muted }}>→</span>
        <span style={{ color: '#00d4ff' }}>1W</span><span style={{ color: C.muted }}>→</span>
        <span style={{ color: C.bull }}>1D</span><span style={{ color: C.muted }}>→</span>
        <span style={{ color: C.warn }}>4H</span><span style={{ color: C.muted }}>→</span>
        <span style={{ color: C.bear }}>1H</span>
      </div>
    </div>
    <div style={grid2}>
      <CourseCard title="Higher Timeframes (HTF)" desc="1W & 1D — Identify the major trend. Use 16H & 6H to confirm bias and find entry zones." style={{ borderLeft: `3px solid ${C.info}` }} />
      <CourseCard title="Entry Timeframes" desc="4H & 1H — Precise entry timing. Once HTF confirms direction, find optimal entry with tight stops." style={{ borderLeft: `3px solid ${C.warn}` }} />
    </div>
    <h2 style={{ color: C.text }}>Essential Candlestick Patterns</h2>
    <h3 style={{ color: C.bull }}>Reversal Patterns</h3>
    <div style={grid3}>
      <CourseCard icon="T" title="Hammer" desc="Bullish reversal at support. Long lower wick, small body near the top." />
      <CourseCard icon="↑" title="Shooting Star" desc="Bearish reversal at resistance. Long upper wick, small body near the bottom." />
      <CourseCard icon="▎█" title="Bullish Engulfing" desc="Large green candle completely engulfs the prior red candle. Strong shift." />
      <CourseCard icon="█▎" title="Bearish Engulfing" desc="Large red candle completely engulfs the prior green candle. Strong shift." />
    </div>
    <h3 style={{ color: C.info }}>Continuation Patterns</h3>
    <div style={grid3}>
      <CourseCard icon="▲▲▲" title="Three White Soldiers" desc="Three consecutive bullish candles with higher closes. Strong buying momentum." />
      <CourseCard icon="▼▼▼" title="Three Black Crows" desc="Three consecutive bearish candles with lower closes. Strong selling momentum." />
      <CourseCard icon="✚" title="Doji" desc="Open equals close. Signals indecision — wait for next candle to confirm." />
      <CourseCard icon="⟋" title="Piercing Pattern" desc="Green candle opens below prior red and closes above midpoint. Bullish at support." />
    </div>
    <h2 style={{ color: C.text }}>Market Psychology</h2>
    <div style={grid2}>
      <CourseCard icon="📈" title="FOMO (Fear of Missing Out)" desc="Long green candles, increasing volume. Strategy: Wait for pullbacks. FOMO entries are often the worst." style={{ borderLeft: `3px solid ${C.bull}` }} />
      <CourseCard icon="📉" title="Panic Selling" desc="Long red candles on high volume. Strategy: Look for buying opportunities at key support. Panic often marks bottoms." style={{ borderLeft: `3px solid ${C.bear}` }} />
      <CourseCard icon="⚖" title="Indecision" desc="Doji candles and small bodies. Strategy: Wait for confirmation. Let the market show its hand." style={{ borderLeft: `3px solid ${C.warn}` }} />
      <CourseCard icon="💪" title="Strong Conviction" desc="Large bodies, small wicks. Strategy: Trade in the direction of conviction. These moves follow through." style={{ borderLeft: `3px solid ${C.info}` }} />
    </div>
    <h2 style={{ color: C.text }}>Practice Exercises</h2>
    <div style={card}><ol style={{ paddingLeft: 20, color: C.textSub, lineHeight: 2, fontSize: F.sm }}><li><strong>Candlestick Identification:</strong> Open a 1D chart on BTC. Identify and label 10 candles as bullish, bearish, or doji.</li><li><strong>Wick Analysis:</strong> Find 5 candles with long lower wicks and 5 with long upper wicks. Record what happened next.</li><li><strong>Timeframe Comparison:</strong> Look at the same date on 1W, 1D, 4H, and 1H charts. How does the story change?</li><li><strong>Psychology Reading:</strong> Find recent examples of FOMO, panic selling, and indecision. What happened after each?</li></ol></div>
    <Quiz step="step1" questions={[
      { q: '1. What does a long lower wick indicate?', options: ['a) Strong buying pressure', 'b) Price was rejected at lower levels by buyers', 'c) Sellers dominated'], correct: 1 },
      { q: '2. Which timeframe should you check FIRST?', options: ['a) 1 minute', 'b) 1 hour', 'c) Daily or weekly for overall trend'], correct: 2 },
      { q: '3. A doji candle typically indicates:', options: ['a) Strong bullish momentum', 'b) Market indecision and potential reversal', 'c) Guaranteed price continuation'], correct: 1 },
      { q: '4. What psychology does a hammer pattern reveal?', options: ['a) Panic selling followed by buyer rejection', 'b) Strong seller conviction', 'c) Market consolidation'], correct: 0 },
    ]} />
    <h2 style={{ color: C.text }}>Key Takeaways</h2>
    <div style={grid3}>
      {['Candlesticks encode the battle between buyers and sellers — body size shows conviction, wicks show rejection.', 'Always start analysis on higher timeframes (Weekly/Daily) and work down to entry timeframes.', 'Reversal patterns signal potential trend changes — always confirm with context and volume.', 'Market psychology drives price — learn to recognize FOMO, panic, and indecision.', 'Practice reading candles daily until pattern recognition becomes second nature.'].map((t, i) => (
        <CourseCard key={i} icon={String(i + 1)} title="" desc={t} />
      ))}
    </div>
    <StepNav back={{ page: 'dashboard', label: '← Dashboard' }} next={{ page: 'step2', label: 'Next: Professional Setup →' }} onNavigate={onNavigate} />
  </>);
}

// ── Step 2: Professional Trading Setup ──
function Step2({ onNavigate }: { onNavigate: (p: CoursePage) => void }) {
  return (<>
    <PageHeader title="Step 2: Professional Trading Setup" subtitle="Build your professional trading workspace" />
    <Video id="ucR2gg8v9Uo" />
    <h2 style={{ color: C.text }}>What You'll Master</h2>
    <div style={grid3}>
      <CourseCard icon="📊" title="TradingView Mastery" desc="Set up and optimize TradingView for professional-grade charting" />
      <CourseCard icon="📈" title="Indicator Setup" desc="Configure the exact indicators used by professionals — EMAs, RSI, MACD" />
      <CourseCard icon="💻" title="Multi-Chart Layout" desc="Build multi-timeframe workspaces for complete market visibility" />
      <CourseCard icon="🔔" title="Alert Systems" desc="Set up price and indicator alerts so you never miss a setup" />
    </div>
    <h2 style={{ color: C.text }}>TradingView Account Setup</h2>
    <InfoBox color={C.info}>Go to <strong>tradingview.com</strong> and create a free account. For crypto charting, use <strong>COINBASE:BTCUSD</strong> for the cleanest data.</InfoBox>
    <h3 style={{ color: C.textSub }}>The 5-Timeframe System</h3>
    <div style={metricRow}><MetricVal value="1W" label="Weekly — Major trend direction" color={C.purple} /><MetricVal value="1D" label="Daily — Swing structure" color={C.info} /><MetricVal value="16H" label="16-Hour — Bias confirmation" color="#00d4ff" /><MetricVal value="6H" label="6-Hour — Setup alignment" color={C.bull} /><MetricVal value="1H" label="1-Hour — Precise entry timing" color={C.warn} /></div>
    <h2 style={{ color: C.text }}>Indicator Configuration</h2>
    <h3 style={{ color: C.textSub }}>Exponential Moving Averages (EMAs)</h3>
    <div style={grid3}>
      <div style={{ ...card, borderLeft: '3px solid #3B82F6' }}><div style={{ fontSize: '1.3em', fontWeight: 700, color: '#3B82F6', marginBottom: 8 }}>EMA 20</div><p style={{ color: C.textSub, fontSize: F.sm, margin: 0 }}><strong>Color:</strong> Blue — Short-term trend. Price above = bullish bias.</p></div>
      <div style={{ ...card, borderLeft: '3px solid #F59E0B' }}><div style={{ fontSize: '1.3em', fontWeight: 700, color: '#F59E0B', marginBottom: 8 }}>EMA 50</div><p style={{ color: C.textSub, fontSize: F.sm, margin: 0 }}><strong>Color:</strong> Orange — Medium-term trend. Key for swing traders.</p></div>
      <div style={{ ...card, borderLeft: '3px solid #6B7280' }}><div style={{ fontSize: '1.3em', fontWeight: 700, color: '#6B7280', marginBottom: 8 }}>EMA 200</div><p style={{ color: C.textSub, fontSize: F.sm, margin: 0 }}><strong>Color:</strong> Gray — Long-term trend. Price above = bull market.</p></div>
    </div>
    <InfoBox color={C.info}><strong>EMA Alignment Rules:</strong><br /><span style={{ color: C.bull }}>▲ Bullish:</span> EMA 20 {'>'} EMA 50 {'>'} EMA 200<br /><span style={{ color: C.bear }}>▼ Bearish:</span> EMA 20 {'<'} EMA 50 {'<'} EMA 200</InfoBox>
    <h3 style={{ color: C.textSub }}>Oscillators & Momentum</h3>
    <div style={grid2}>
      <div style={card}><div style={{ fontWeight: 700, color: '#00d4ff', marginBottom: 8 }}>RSI (Relative Strength Index)</div><p style={{ color: C.textSub, fontSize: F.sm }}><strong>Length:</strong> 14 | <strong>Overbought:</strong> 70 | <strong>Oversold:</strong> 30<br />Measures momentum. Look for divergences with price.</p></div>
      <div style={card}><div style={{ fontWeight: 700, color: C.purple, marginBottom: 8 }}>Stochastic RSI</div><p style={{ color: C.textSub, fontSize: F.sm }}><strong>K:</strong> 3 | <strong>D:</strong> 3 | <strong>RSI Length:</strong> 14<br />More sensitive than RSI. K crossing above D = bullish.</p></div>
      <div style={card}><div style={{ fontWeight: 700, color: C.bull, marginBottom: 8 }}>MACD</div><p style={{ color: C.textSub, fontSize: F.sm }}><strong>Fast:</strong> 12 | <strong>Slow:</strong> 26 | <strong>Signal:</strong> 9<br />Histogram above zero = bullish. Signal crossovers confirm entries.</p></div>
      <div style={card}><div style={{ fontWeight: 700, color: C.warn, marginBottom: 8 }}>MFI (Money Flow Index)</div><p style={{ color: C.textSub, fontSize: F.sm }}><strong>Length:</strong> 14 | <strong>Overbought:</strong> 80 | <strong>Oversold:</strong> 20<br />Volume-weighted RSI. Divergences are powerful signals.</p></div>
    </div>
    <h2 style={{ color: C.text }}>Workspace Layouts</h2>
    <div style={grid2}>
      <CourseCard title="Single Chart Pro (Recommended)" desc="Free tier. One chart: Candlesticks + EMA 20/50/200. Panel 1: RSI + Stoch RSI. Panel 2: MACD + MFI." style={{ borderLeft: `3px solid ${C.bull}` }} />
      <CourseCard title="Multi-Timeframe Pro (Advanced)" desc="Pro subscription. Chart 1: Weekly/Daily for trend. Chart 2: 16H/6H for setups. Chart 3: 1H for entries." style={{ borderLeft: `3px solid ${C.info}` }} />
    </div>
    <Quiz step="step2" questions={[
      { q: '1. What are the optimal EMA lengths?', options: ['a) 10, 30, 100', 'b) 20, 50, 200', 'c) 5, 20, 50'], correct: 1 },
      { q: '2. Which timeframes for HTF analysis?', options: ['a) 1m, 5m, 15m', 'b) 1W, 1D, 16H, 6H', 'c) 4H, 1H, 30m'], correct: 1 },
      { q: '3. What does bullish EMA alignment look like?', options: ['a) EMA 20 > EMA 50 > EMA 200', 'b) EMA 200 > EMA 50 > EMA 20', 'c) All EMAs at the same level'], correct: 0 },
      { q: '4. Recommended exchange for BTC charting?', options: ['a) BINANCE:BTCUSDT', 'b) KRAKEN:BTCUSD', 'c) COINBASE:BTCUSD'], correct: 2 },
    ]} />
    <StepNav back={{ page: 'step1', label: '← Step 1' }} next={{ page: 'step3', label: 'Next: Market Structure →' }} onNavigate={onNavigate} />
  </>);
}

// ── Step 3: Market Structure ──
function Step3({ onNavigate }: { onNavigate: (p: CoursePage) => void }) {
  return (<>
    <PageHeader title="Step 3: Strategy Fundamentals Mastery" subtitle="Master market structure analysis, trend identification, and support/resistance" />
    <Video id="XeNp9drLM9s" />
    <h2 style={{ color: C.text }}>Market Structure Analysis</h2>
    <div style={grid3}>
      <CourseCard icon="↗" title="Uptrend" desc="Higher Highs (HH) and Higher Lows (HL). Look for long entries on pullbacks to higher lows. Invalidation: Break below most recent HL." style={{ borderLeft: `3px solid ${C.bull}` }} />
      <CourseCard icon="↘" title="Downtrend" desc="Lower Highs (LH) and Lower Lows (LL). Look for short entries on rallies. Invalidation: Break above most recent LH." style={{ borderLeft: `3px solid ${C.bear}` }} />
      <CourseCard icon="↔" title="Range (Consolidation)" desc="Horizontal support/resistance. Buy at support, sell at resistance, or wait for breakout." style={{ borderLeft: `3px solid ${C.warn}` }} />
    </div>
    <h2 style={{ color: C.text }}>Professional Trendline Analysis</h2>
    <InfoBox color={C.info}><strong>Drawing Rules:</strong> Connect 2+ significant swing points. Use the ray tool. Avoid forcing through minor wicks. Focus on body closes for reliable trendlines.</InfoBox>
    <h3 style={{ color: C.textSub }}>Breakout Criteria</h3>
    <div style={grid3}>
      <CourseCard icon="✓" title="Body Closes Beyond" desc="A wick piercing the trendline is not enough. The body must close beyond." />
      <CourseCard icon="✓" title="Volume Confirmation" desc="Genuine breakouts occur on increased volume. Low volume = likely fail." />
      <CourseCard icon="✓" title="Retest of Broken Level" desc="Best breakouts pull back to retest the broken trendline before continuing." />
      <CourseCard icon="✓" title="Follow-Through" desc="Subsequent candles should continue in the breakout direction with momentum." />
    </div>
    <InfoBox color={C.warn}><strong>False Breakout Signs:</strong> Wick pierces but body stays inside. Low volume. Immediate reversal. Multiple failed attempts.</InfoBox>
    <h3 style={{ color: C.textSub }}>Trendline Strength</h3>
    <div style={metricRow}><MetricVal value="Touches" label="More touches = stronger. 3+ confirms significance." color="#00d4ff" /><MetricVal value="Timeframe" label="Longer TF = more significant. Weekly > hourly." color={C.purple} /><MetricVal value="Angle" label="Steeper = less reliable. Sustainable trends have moderate angles." color={C.warn} /></div>
    <h2 style={{ color: C.text }}>HTF Structure Analysis</h2>
    <div style={metricRow}><MetricVal value="1" label="Start High — Monthly/Weekly macro trend" color={C.purple} /><MetricVal value="2" label="Work Down — Daily to refine structure" color={C.info} /><MetricVal value="3" label="Align Bias — All TFs agree on direction" color="#00d4ff" /><MetricVal value="4" label="Find Entries — 4H/1H for precise timing" color={C.bull} /><MetricVal value="5" label="Manage Risk — Stops based on structure" color={C.warn} /></div>
    <Quiz step="step3" questions={[
      { q: '1. Which confirms bullish market structure?', options: ['a) Lower highs and lower lows', 'b) Higher highs and higher lows', 'c) Price trading sideways'], correct: 1 },
      { q: '2. Most reliable breakout confirmation?', options: ['a) Wick piercing trendline', 'b) Multiple touches', 'c) Body closes beyond trendline with volume'], correct: 2 },
      { q: '3. Correct trendline drawing approach?', options: ['a) Connect any two points', 'b) Connect 2+ significant swing points, body closes', 'c) Horizontal lines at random levels'], correct: 1 },
      { q: '4. Correct sequence for MTF analysis?', options: ['a) Monthly/Weekly down to lower TFs', 'b) Start with 1-minute and work up', 'c) Only use the 4-hour chart'], correct: 0 },
    ]} />
    <StepNav back={{ page: 'step2', label: '← Step 2' }} next={{ page: 'step4', label: 'Next: Risk Management →' }} onNavigate={onNavigate} />
  </>);
}

// ── Step 4: Risk Management ──
function Step4({ onNavigate }: { onNavigate: (p: CoursePage) => void }) {
  const [calcResult, setCalcResult] = useState<{ size: string; risk: string; rr: string; profit: string } | null>(null);
  const calc = useCallback(() => {
    const bal = parseFloat((document.getElementById('c-bal') as HTMLInputElement)?.value) || 0;
    const rp = parseFloat((document.getElementById('c-rp') as HTMLInputElement)?.value) || 1;
    const entry = parseFloat((document.getElementById('c-entry') as HTMLInputElement)?.value) || 0;
    const sl = parseFloat((document.getElementById('c-sl') as HTMLInputElement)?.value) || 0;
    const tp = parseFloat((document.getElementById('c-tp') as HTMLInputElement)?.value) || 0;
    if (!bal || !entry || !sl) return;
    const riskAmt = bal * (rp / 100);
    const perUnit = Math.abs(entry - sl);
    const size = perUnit > 0 ? riskAmt / perUnit : 0;
    const rr = tp && perUnit > 0 ? (Math.abs(tp - entry) / perUnit).toFixed(2) : 'N/A';
    const profit = tp ? (Math.abs(tp - entry) * size).toFixed(2) : 'N/A';
    setCalcResult({ size: size.toFixed(4) + ' units', risk: '$' + riskAmt.toFixed(2), rr: rr !== 'N/A' ? '1:' + rr : 'N/A', profit: profit !== 'N/A' ? '$' + profit : 'N/A' });
  }, []);

  return (<>
    <PageHeader title="Step 4: Professional Risk Management Mastery" subtitle="Master institutional-level risk management, position sizing, and capital preservation" />
    <Video id="T2D0PtADAu0" />
    <div style={metricRow}><MetricVal value="1-3%" label="Max Risk Per Trade" color="#00d4ff" /><MetricVal value="1:2+" label="Min Risk/Reward" color={C.bull} /><MetricVal value="6%" label="Max Daily Risk" color={C.bear} /><MetricVal value="Pro Level" label="Skills" color={C.purple} /></div>
    <h2 style={{ color: '#00d4ff' }}>Fundamental Principles</h2>
    <div style={grid3}>
      <CourseCard icon="📐" title="Position Sizing Formula" desc="Position Size = Risk Amount / (Entry - Stop). Risk Amount = Balance × Risk%. Never exceed your predetermined risk limit." />
      <CourseCard icon="📊" title="Risk % Guidelines" desc="Conservative: 0.5% | Standard: 1-2% | Aggressive: 2-3%. Scalping: 0.25-0.5% | Swing: 1-2% | Position: 2-3%. Never more than 6% daily." />
      <CourseCard icon="⚖️" title="Risk/Reward Ratios" desc="Minimum: 1:2 | Target: 1:3+ | Elite: 1:5+. At 1:3, you only need 25%+ win rate to be profitable." />
      <CourseCard icon="🛑" title="Stop Loss Placement" desc="Below/above key S/R. Beyond significant swing points. Outside consolidation ranges. Never move stops against your position." />
      <CourseCard icon="⏰" title="Time-Based Risk" desc="Exit if no progress in expected timeframe. Reduce size before major news. Close positions before weekends if needed." />
      <CourseCard icon="🔥" title="Portfolio Heat" desc="Max 15-20% total portfolio risk. Correlated positions = one combined risk. Scale down during drawdowns." />
    </div>
    <h2 style={{ color: '#00d4ff' }}>Position Size Calculator</h2>
    <div style={{ ...card, borderColor: C.brand + '44' }}>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, marginBottom: 12 }}>
        <div><label style={{ fontSize: F.xs, color: C.muted }}>Account Balance ($)</label><input id="c-bal" type="number" defaultValue="10000" style={{ width: '100%', padding: 8, borderRadius: R.sm, border: `1px solid ${C.border}`, background: C.surface, color: C.text, fontSize: F.sm }} /></div>
        <div><label style={{ fontSize: F.xs, color: C.muted }}>Risk %</label><input id="c-rp" type="number" defaultValue="1" step="0.25" style={{ width: '100%', padding: 8, borderRadius: R.sm, border: `1px solid ${C.border}`, background: C.surface, color: C.text, fontSize: F.sm }} /></div>
        <div><label style={{ fontSize: F.xs, color: C.muted }}>Entry Price ($)</label><input id="c-entry" type="number" placeholder="30000" style={{ width: '100%', padding: 8, borderRadius: R.sm, border: `1px solid ${C.border}`, background: C.surface, color: C.text, fontSize: F.sm }} /></div>
        <div><label style={{ fontSize: F.xs, color: C.muted }}>Stop Loss ($)</label><input id="c-sl" type="number" placeholder="29700" style={{ width: '100%', padding: 8, borderRadius: R.sm, border: `1px solid ${C.border}`, background: C.surface, color: C.text, fontSize: F.sm }} /></div>
        <div><label style={{ fontSize: F.xs, color: C.muted }}>Take Profit ($)</label><input id="c-tp" type="number" placeholder="30900" style={{ width: '100%', padding: 8, borderRadius: R.sm, border: `1px solid ${C.border}`, background: C.surface, color: C.text, fontSize: F.sm }} /></div>
        <div style={{ display: 'flex', alignItems: 'flex-end' }}><button onClick={calc} style={{ width: '100%', padding: '10px 20px', borderRadius: R.md, border: 'none', background: C.brand, color: '#fff', cursor: 'pointer', fontWeight: 700 }}>Calculate</button></div>
      </div>
      {calcResult && <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8, marginTop: 12 }}>
        <div style={{ padding: 10, background: C.surface, borderRadius: R.sm }}><span style={{ fontSize: F.xs, color: C.muted }}>Position Size</span><div style={{ color: C.bull, fontWeight: 700 }}>{calcResult.size}</div></div>
        <div style={{ padding: 10, background: C.surface, borderRadius: R.sm }}><span style={{ fontSize: F.xs, color: C.muted }}>Risk Amount</span><div style={{ color: C.warn, fontWeight: 700 }}>{calcResult.risk}</div></div>
        <div style={{ padding: 10, background: C.surface, borderRadius: R.sm }}><span style={{ fontSize: F.xs, color: C.muted }}>Risk/Reward</span><div style={{ color: '#00d4ff', fontWeight: 700 }}>{calcResult.rr}</div></div>
        <div style={{ padding: 10, background: C.surface, borderRadius: R.sm }}><span style={{ fontSize: F.xs, color: C.muted }}>Potential Profit</span><div style={{ color: C.bull, fontWeight: 700 }}>{calcResult.profit}</div></div>
      </div>}
    </div>
    <h2 style={{ color: '#00d4ff' }}>Institutional Risk Framework</h2>
    <div style={grid3}>
      <CourseCard icon="✅" title="Pre-Trade Checklist" desc="Risk % predetermined. Stop loss identified. R/R calculated (min 1:2). Position size via formula. Total portfolio risk <20%." />
      <CourseCard icon="📏" title="Risk Scaling" desc="Drawdown >10%: Reduce by 50%. 5-10%: Reduce by 25%. Profitable streak: Increase by 25%. Scale with performance, not emotion." />
      <CourseCard icon="🚨" title="Emergency Protocols" desc="Daily loss 6%: Stop for day. Weekly 10%: Stop for week. Monthly 15%: Stop, review strategy." />
    </div>
    <h2 style={{ color: '#00d4ff' }}>Trading Psychology</h2>
    <div style={grid3}>
      <CourseCard icon="🧠" title="Emotional Risk Factors" desc="Fear: Missing entries. Greed: Oversizing. Revenge: Trading to recover. Overconfidence: Ignoring risk. Solution: Mechanical rules, journaling." />
      <CourseCard icon="🛡️" title="Mental Stop Losses" desc="Stop when: Daily loss 6%. 3-4 consecutive losses. Emotional state compromised. Market unclear." />
      <CourseCard icon="💪" title="Building Discipline" desc="Start small (0.25% risk). Follow mechanical rules. Track everything. Regular reviews. Discipline is a muscle." />
    </div>
    <h2 style={{ color: '#00d4ff' }}>Practice Scenarios</h2>
    <div style={grid3}>
      <CourseCard icon="1" title="Conservative Swing" desc="Account: $5,000 | Risk: 1% | Entry: $28,000 | Stop: $27,580. Risk: $50. Per-unit: $420. Size: 0.119 units." />
      <CourseCard icon="2" title="Scalping Setup" desc="Account: $12,000 | Risk: 0.5% | Entry: $31,200 | Stop: $30,936. Risk: $60. Per-unit: $264. Size: 0.227 units." />
      <CourseCard icon="3" title="Aggressive Position" desc="Account: $20,000 | Risk: 2% | Entry: $29,500 | Stop: $28,905. Risk: $400. Per-unit: $595. Size: 0.672 units." />
    </div>
    <Quiz step="step4" questions={[
      { q: '1. $10,000 account, 1% risk — risk amount?', options: ['$10', '$100', '$1,000', '$50'], correct: 1 },
      { q: '2. Entry $30,000, SL $29,700 — per-unit risk?', options: ['$30', '$3,000', '$300', '$297'], correct: 2 },
      { q: '3. Risk $100, 1:2 R/R — target profit?', options: ['$100', '$200', '$50', '$300'], correct: 1 },
      { q: '4. Maximum recommended daily risk?', options: ['2%', '10%', '6%', '15%'], correct: 2 },
    ]} />
    <StepNav back={{ page: 'step3', label: '← Step 3' }} next={{ page: 'step5', label: 'Next: Technical Indicators →' }} onNavigate={onNavigate} />
  </>);
}

// ── Step 5: Technical Indicators ──
function Step5({ onNavigate }: { onNavigate: (p: CoursePage) => void }) {
  return (<>
    <PageHeader title="Step 5: Technical Indicators Mastery" subtitle="Master RSI, MACD, MFI, and Stochastic RSI for precise market timing" />
    <Video id="F8LbNp7aUsg" />
    <div style={grid4}>
      <MetricVal label="Core Indicators" value="4" color="#00d4ff" />
      <MetricVal label="Multi-Timeframe" value="MTF" color="#16a34a" />
      <MetricVal label="Signals" value="Pro Level" color="#eab308" />
      <MetricVal label="Analysis" value="Real Time" color="#a855f7" />
    </div>

    <h2 style={{ color: '#00d4ff' }}>RSI (Relative Strength Index)</h2>
    <div style={grid4}>
      <MetricVal label="Range" value="0-100" color="#00d4ff" />
      <MetricVal label="Period" value="14" color="#e2e8f0" />
      <MetricVal label="Overbought" value="70" color="#dc2626" />
      <MetricVal label="Oversold" value="30" color="#16a34a" />
    </div>
    <div style={grid3}>
      <CourseCard icon="BUY" title="Bullish Signal" desc="RSI crosses above 30 in an uptrend. Indicates oversold bounce with trend support." />
      <CourseCard icon="SELL" title="Bearish Signal" desc="RSI crosses below 70 in a downtrend. Indicates overbought reversal with trend confirmation." />
      <CourseCard icon="DIV" title="Divergence" desc="Price makes new high/low but RSI does not. Signals potential reversal or weakening momentum." />
    </div>
    <InfoBox type="warning">Don't buy just because RSI is oversold in a downtrend. Don't sell just because RSI is overbought in an uptrend. Always consider the trend context first.</InfoBox>
    <p style={{ color: '#94a3b8' }}>
      <strong style={{ color: '#00d4ff' }}>HTF (4H/Daily):</strong> Determine overall bias — is RSI trending up or down?<br/>
      <strong style={{ color: '#eab308' }}>MTF (1H):</strong> Timing — wait for RSI to reach actionable zones<br/>
      <strong style={{ color: '#16a34a' }}>LTF (15m):</strong> Precise entries — fine-tune entry on lower timeframe RSI signals
    </p>

    <h2 style={{ color: '#00d4ff' }}>MACD (Moving Average Convergence Divergence)</h2>
    <div style={grid4}>
      <MetricVal label="MACD Line" value="12 EMA - 26 EMA" color="#00d4ff" />
      <MetricVal label="Signal Line" value="9 EMA of MACD" color="#eab308" />
      <MetricVal label="Histogram" value="MACD - Signal" color="#16a34a" />
      <MetricVal label="Zero Line" value="Baseline" color="#94a3b8" />
    </div>
    <div style={grid2}>
      <CourseCard icon="BUY" title="Bullish Signals" desc="Histogram above zero and rising. Bullish crossover: MACD line crosses above signal line." />
      <CourseCard icon="SELL" title="Bearish Signals" desc="Histogram below zero and falling. Bearish crossover: MACD line crosses below signal line." />
    </div>
    <p style={{ color: '#94a3b8' }}>
      <span style={{ color: '#16a34a' }}>Rising histogram</span> = Bullish momentum building<br/>
      <span style={{ color: '#dc2626' }}>Falling histogram</span> = Bearish momentum building<br/>
      <strong>Hidden Divergence:</strong> Continuation signal — trend likely to persist<br/>
      <strong>Regular Divergence:</strong> Reversal signal — trend may be exhausting
    </p>

    <h2 style={{ color: '#00d4ff' }}>MFI (Money Flow Index)</h2>
    <div style={grid4}>
      <MetricVal label="Range" value="0-100" color="#00d4ff" />
      <MetricVal label="Period" value="14" color="#e2e8f0" />
      <MetricVal label="Overbought" value="80" color="#dc2626" />
      <MetricVal label="Oversold" value="20" color="#16a34a" />
    </div>
    <InfoBox type="tip">Key Difference from RSI: MFI incorporates volume data, making it a volume-weighted momentum indicator. This gives it an edge in detecting institutional money flow that pure price-based indicators miss.</InfoBox>
    <div style={grid3}>
      <CourseCard icon="IN" title="Capital Inflow" desc="MFI rising alongside price indicates genuine buying pressure with volume confirmation." />
      <CourseCard icon="OUT" title="Capital Outflow" desc="MFI falling alongside price indicates selling pressure with volume confirmation." />
      <CourseCard icon="DIV" title="Divergences" desc="MFI diverging from price signals that volume does not support the current move. High probability reversal signal." />
    </div>
    <p style={{ color: '#94a3b8' }}>
      <span style={{ color: '#16a34a' }}>Rising MFI + Rising Price</span> = Smart money buying (strong signal)<br/>
      <span style={{ color: '#eab308' }}>Falling MFI + Rising Price</span> = Retail buying without volume support (weak/trap)<br/>
      <span style={{ color: '#dc2626' }}>Rising MFI + Falling Price</span> = Accumulation phase (watch for reversal)<br/>
      <span style={{ color: '#dc2626' }}>Falling MFI + Falling Price</span> = Smart money selling (strong bearish)
    </p>

    <h2 style={{ color: '#00d4ff' }}>Stochastic RSI</h2>
    <div style={grid4}>
      <MetricVal label="Range" value="0-1" color="#00d4ff" />
      <MetricVal label="Lines" value="%K / %D" color="#e2e8f0" />
      <MetricVal label="Overbought" value="0.8" color="#dc2626" />
      <MetricVal label="Oversold" value="0.2" color="#16a34a" />
    </div>
    <div style={grid2}>
      <CourseCard icon="BUY" title="Bullish Crossover" desc="%K crosses above %D in the oversold zone (below 0.2). Best signal when confirmed by higher timeframe trend." />
      <CourseCard icon="SELL" title="Bearish Crossover" desc="%K crosses below %D in the overbought zone (above 0.8). Best signal when confirmed by higher timeframe trend." />
    </div>
    <InfoBox type="warning">Stochastic RSI is very noisy on lower timeframes. Best used on 1H and above. On 5m/15m charts, expect many false signals. Always combine with higher timeframe analysis.</InfoBox>

    <h2 style={{ color: '#00d4ff' }}>Multi-Timeframe Analysis Strategy</h2>
    <div style={grid3}>
      <CourseCard icon="16H" title="Overall Trend Bias" desc="Use MACD direction and MFI trend to determine the dominant market direction. This is your directional filter." />
      <CourseCard icon="6H" title="Intermediate Confirmation" desc="Confirm with RSI levels and MACD alignment. Both timeframes should agree on direction before proceeding." />
      <CourseCard icon="1H" title="Precise Entry Timing" desc="Use Stochastic RSI crossovers and MFI readings for precise entry timing once higher timeframes confirm." />
    </div>
    <InfoBox type="tip">MTF Strategy Flow: Check 16H bias (MACD + MFI) → Confirm 6H alignment (RSI + MACD) → Wait for 1H trigger signal (Stoch RSI + MFI) → Execute trade with trend</InfoBox>

    <Quiz step="step5" questions={[
      { q: '1. MACD histogram above zero and rising suggests:', options: ['Bearish reversal incoming', 'Bullish momentum building and accelerating', 'Market is range-bound', 'Volume is declining'], correct: 1 },
      { q: '2. A Stochastic RSI bullish crossover in the oversold zone indicates:', options: ['Strong sell signal', 'Market is about to crash', 'Momentum turning up, potential buy opportunity', 'Indicator is broken'], correct: 2 },
      { q: '3. MFI green and rising while price is also rising suggests:', options: ['Retail panic buying', 'Capital inflow, smart money buying', 'Market is about to reverse', 'Low volume manipulation'], correct: 1 },
      { q: '4. The correct multi-timeframe sequence for an MFI+MACD strategy is:', options: ['Start on 1H, then check higher TFs', 'Only use one timeframe for simplicity', 'Check 16H/6H for bias, trigger on 1H', 'Use 5m for all decisions'], correct: 2 },
    ]} />
    <StepNav back={{ page: 'step4', label: '← Step 4' }} next={{ page: 'step6', label: 'Next: Readiness Assessment →' }} onNavigate={onNavigate} />
  </>);
}

// ── Step 6: Readiness Assessment ──
function Step6({ onNavigate }: { onNavigate: (p: CoursePage) => void }) {
  return (<>
    <PageHeader title="Step 6: Trading Readiness Assessment" subtitle="Complete your comprehensive readiness evaluation" />
    <Video id="H7Gnh1W6VuE" />
    <div style={grid3}>
      <CourseCard icon="1" title="Knowledge Assessment" desc="Pass all 5 core quizzes from Steps 1-5. Each quiz tests critical trading knowledge — fundamentals, market structure, risk management, and technical analysis." />
      <CourseCard icon="2" title="Practical Application" desc="Submit at least 2 practice trades with detailed analysis. Each must include strategy, entry/stop/target levels, trade reasoning, and risk management plan." />
      <CourseCard icon="3" title="Overall Readiness" desc="Combined score from quizzes (70% weight) and practice trades (30% weight). You need 100% completion to be marked as ready." />
    </div>

    <h2 style={{ color: '#00d4ff' }}>Learning Journey</h2>
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(140px, 1fr))', gap: '12px' }}>
      {(['Trading Fundamentals', 'Professional Setup', 'Market Structure', 'Risk Management', 'Technical Indicators', 'Readiness Assessment'] as const).map((label, i) => (
        <div key={i} style={{ ...cardStyle, textAlign: 'center' as const, padding: '16px' }}>
          <div style={{ fontSize: '1.5rem', marginBottom: 8 }}>{i + 1}</div>
          <div style={{ fontWeight: 600, fontSize: '0.85rem' }}>{label}</div>
        </div>
      ))}
    </div>

    <InfoBox type="warning">
      <strong>Important Disclaimers</strong><br/><br/>
      <strong>Educational Purpose:</strong> This course is for educational purposes only and does not constitute financial advice.<br/>
      <strong>Risk Warning:</strong> Trading cryptocurrencies involves substantial risk of loss.<br/>
      <strong>Practice First:</strong> Always practice with paper trading before risking real capital.<br/>
      <strong>Continuous Learning:</strong> Markets evolve constantly. Commit to ongoing education.
    </InfoBox>

    <StepNav back={{ page: 'step5', label: '← Step 5' }} next={{ page: 'dashboard', label: 'Back to Dashboard →' }} onNavigate={onNavigate} />
  </>);
}

// ── Strategy: Trendline Breakout ──
function StratTrendline({ onNavigate }: { onNavigate: (p: CoursePage) => void }) {
  const [fibLow, setFibLow] = useState('');
  const [fibHigh, setFibHigh] = useState('');
  const [fibResults, setFibResults] = useState<{name:string;val:number}[]>([]);

  const calcFib = () => {
    const low = parseFloat(fibLow), high = parseFloat(fibHigh);
    if (isNaN(low) || isNaN(high) || low >= high) return;
    const diff = high - low;
    setFibResults([
      { name: '0.236 Retracement', val: high - diff * 0.236 },
      { name: '0.382 Retracement', val: high - diff * 0.382 },
      { name: '0.500 Retracement', val: high - diff * 0.5 },
      { name: '0.618 Retracement', val: high - diff * 0.618 },
      { name: '0.786 Retracement', val: high - diff * 0.786 },
      { name: '1.272 Extension', val: high + diff * 0.272 },
      { name: '1.618 Extension', val: high + diff * 0.618 },
      { name: '2.618 Extension', val: high + diff * 1.618 },
    ]);
  };

  return (<>
    <PageHeader title="Trendline Breakout Strategy" subtitle="Master trendline breakout trading with Bitcoin's 4-year cycle analysis" />
    <div style={grid4}>
      <MetricVal label="Win Rate (Backtested)" value="78%" color="#16a34a" />
      <MetricVal label="Risk/Reward" value="3.2:1" color="#00d4ff" />
      <MetricVal label="Primary Timeframe" value="Weekly" color="#eab308" />
      <MetricVal label="Trades per Month" value="4-6" color="#a855f7" />
    </div>

    <h2>Strategy Overview</h2>
    <div style={grid2}>
      <CourseCard icon="/" title="Market Structure Focus" desc="Identify key trendlines on BTC logarithmic scale. Focus on major structural levels tested multiple times across the 4-year cycle." />
      <CourseCard icon="+" title="Multi-Indicator Confirmation" desc="Combine Stochastic RSI, RSI, and MACD for triple confirmation. Each indicator must align before entry." />
    </div>

    <h2>Breakout Patterns</h2>
    <div style={grid2}>
      <div style={{ ...cardStyle, borderLeft: '3px solid #16a34a' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 8 }}>
          <strong style={{ color: '#16a34a' }}>Bullish Breakout</strong>
          <span style={{ background: '#16a34a', color: '#000', padding: '2px 10px', borderRadius: 4, fontWeight: 'bold', fontSize: '0.85em' }}>BUY</span>
        </div>
        <p style={{ color: '#94a3b8', margin: 0, fontSize: '0.9rem' }}>Price breaks above a descending trendline with significant volume increase. Candle must close above. Look for volume 2-3x average.</p>
      </div>
      <div style={{ ...cardStyle, borderLeft: '3px solid #dc2626' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 8 }}>
          <strong style={{ color: '#dc2626' }}>Bearish Breakout</strong>
          <span style={{ background: '#dc2626', color: '#000', padding: '2px 10px', borderRadius: 4, fontWeight: 'bold', fontSize: '0.85em' }}>SELL</span>
        </div>
        <p style={{ color: '#94a3b8', margin: 0, fontSize: '0.9rem' }}>Price breaks below an ascending trendline with significant volume increase. Candle must close below. Volume should spike on the break.</p>
      </div>
    </div>

    <h2>Professional Setup Checklist</h2>
    <div style={grid2}>
      <div style={{ ...cardStyle, borderLeft: '3px solid #16a34a' }}>
        <h4 style={{ color: '#16a34a', marginBottom: 8 }}>Part I — Trendline Breakout</h4>
        <ul style={{ margin: 0, paddingLeft: 18, color: '#94a3b8', fontSize: '0.9rem' }}>
          <li>Candle breaks and closes beyond the trendline</li>
          <li>Volume spike of at least 2x average</li>
          <li>No immediate rejection or long wick back inside</li>
        </ul>
      </div>
      <div style={{ ...cardStyle, borderLeft: '3px solid #00d4ff' }}>
        <h4 style={{ color: '#00d4ff', marginBottom: 8 }}>Part II — Stochastic RSI Confirmation</h4>
        <ul style={{ margin: 0, paddingLeft: 18, color: '#94a3b8', fontSize: '0.9rem' }}>
          <li>K line crosses above D line on the daily</li>
          <li>Crossover occurs in oversold zone (&lt;20)</li>
          <li>Strong momentum shown by steep upward angle</li>
        </ul>
      </div>
      <div style={{ ...cardStyle, borderLeft: '3px solid #eab308' }}>
        <h4 style={{ color: '#eab308', marginBottom: 8 }}>Part III — RSI Momentum</h4>
        <ul style={{ margin: 0, paddingLeft: 18, color: '#94a3b8', fontSize: '0.9rem' }}>
          <li>RSI breaks above 50 with conviction</li>
          <li>No bearish divergence present</li>
          <li>Strong upward slope on the RSI line</li>
        </ul>
      </div>
      <div style={{ ...cardStyle, borderLeft: '3px solid #a855f7' }}>
        <h4 style={{ color: '#a855f7', marginBottom: 8 }}>Part IV — MACD (Optional)</h4>
        <ul style={{ margin: 0, paddingLeft: 18, color: '#94a3b8', fontSize: '0.9rem' }}>
          <li>MACD line crosses above the signal line</li>
          <li>Histogram turning positive</li>
          <li>Moving toward or above the zero line</li>
        </ul>
      </div>
    </div>
    <InfoBox type="tip">Parts I, II, and III must all align before entering a trade. Part IV (MACD) adds extra confirmation but is not strictly required. When all four align, it represents the highest probability setup.</InfoBox>

    <h2>Risk Management</h2>
    <div style={grid3}>
      <CourseCard icon="X" title="Stop Loss" desc="Place stop 2-3% below the broken trendline. Account for current volatility (ATR-based adjustment). Max 2% account risk per trade." />
      <CourseCard icon="$" title="Take Profit Targets" desc="First target: 1.618 Fibonacci extension. Second target: previous swing high/low. Trail stops on remaining runners." />
      <CourseCard icon="%" title="Position Sizing" desc="Calculate position size based on stop distance. Risk 1-2% of account max per trade. Reduce size in high volatility." />
    </div>

    <h2>Fibonacci Calculator</h2>
    <div style={cardStyle}>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, marginBottom: 12 }}>
        <div>
          <label style={{ color: '#94a3b8', fontSize: '0.85rem', display: 'block', marginBottom: 4 }}>Swing Low Price</label>
          <input type="number" value={fibLow} onChange={e => setFibLow(e.target.value)} placeholder="e.g. 25000" style={inputStyle} />
        </div>
        <div>
          <label style={{ color: '#94a3b8', fontSize: '0.85rem', display: 'block', marginBottom: 4 }}>Swing High Price</label>
          <input type="number" value={fibHigh} onChange={e => setFibHigh(e.target.value)} placeholder="e.g. 45000" style={inputStyle} />
        </div>
      </div>
      <button onClick={calcFib} style={btnStyle}>Calculate Fibonacci Levels</button>
      {fibResults.length > 0 && (
        <div style={{ marginTop: 16, display: 'flex', flexDirection: 'column' as const, gap: 6 }}>
          {fibResults.map((r, i) => (
            <div key={i} style={{ display: 'flex', justifyContent: 'space-between', padding: '8px 12px', background: '#0f172a', borderRadius: 6 }}>
              <span style={{ color: '#94a3b8' }}>{r.name}</span>
              <span style={{ color: r.name.includes('Extension') ? '#16a34a' : '#00d4ff', fontWeight: 600 }}>${r.val.toFixed(2)}</span>
            </div>
          ))}
        </div>
      )}
    </div>

    <h2>Psychology Tips</h2>
    <div style={grid2}>
      <CourseCard icon="W" title="Wait for All Confirmations" desc="Never enter until all three required parts of the checklist are satisfied. Half-confirmed setups lead to losses." />
      <CourseCard icon="T" title="Trust Your System" desc="Once confirmed and entered, trust the system. Do not second-guess mid-trade. Let stop loss or take profit do its job." />
    </div>

    <InfoBox type="warning">Disclaimer: This strategy is for educational purposes only. Past performance does not guarantee future results. Never risk more than you can afford to lose. Always practice with paper trading first.</InfoBox>
    <StepNav back={{ page: 'dashboard', label: '← Dashboard' }} onNavigate={onNavigate} />
  </>);
}

// ── Strategy: MFI + MACD ──
function StratMfi({ onNavigate }: { onNavigate: (p: CoursePage) => void }) {
  const [mfiBal, setMfiBal] = useState(''); const [mfiRisk, setMfiRisk] = useState('');
  const [mfiEntry, setMfiEntry] = useState(''); const [mfiStop, setMfiStop] = useState('');
  const [mfiRes, setMfiRes] = useState<{label:string;value:string;color:string}[]>([]);

  const calcMfi = () => {
    const bal = parseFloat(mfiBal), risk = parseFloat(mfiRisk), entry = parseFloat(mfiEntry), stop = parseFloat(mfiStop);
    if (!bal || !risk || !entry || !stop) return;
    const riskAmt = bal * (risk / 100);
    const stopDist = Math.abs(entry - stop);
    const posSize = riskAmt / stopDist;
    const posVal = posSize * entry;
    const lev = posVal / bal;
    setMfiRes([
      { label: 'Risk Amount', value: `$${riskAmt.toFixed(2)}`, color: '#eab308' },
      { label: 'Stop Distance', value: `${((stopDist / entry) * 100).toFixed(2)}%`, color: '#dc2626' },
      { label: 'Position Size', value: `${posSize.toFixed(6)} units`, color: '#16a34a' },
      { label: 'Position Value', value: `$${posVal.toFixed(2)}`, color: '#00d4ff' },
      { label: 'Effective Leverage', value: `${lev.toFixed(2)}x`, color: lev > 5 ? '#dc2626' : '#16a34a' },
    ]);
  };

  return (<>
    <PageHeader title="MFI + MACD Multi-Timeframe Strategy" subtitle="Master momentum trading with MFI and MACD convergence across multiple timeframes" />
    <div style={grid4}>
      <MetricVal label="Win Rate" value="85%" color="#16a34a" />
      <MetricVal label="Risk/Reward" value="3:1" color="#00d4ff" />
      <MetricVal label="Timeframes" value="16h/6h/1h" color="#eab308" />
      <MetricVal label="Difficulty" value="Advanced" color="#a855f7" />
    </div>

    <h2>Strategy Overview</h2>
    <div style={grid3}>
      <CourseCard icon="M" title="Primary Indicators" desc="MFI (volume-weighted RSI) for buying/selling pressure. MACD Histogram for momentum direction. Stochastic RSI for precise entry signals." />
      <CourseCard icon="T" title="Timeframe Structure" desc="16h — Primary trend direction and momentum bias. 6h — Secondary momentum confirmation. 1h — Precise entry timing with VuManChu dot signal." />
      <CourseCard icon="E" title="Entry Conditions" desc="HTF must be bullish. 16h and 6h MFI green (above 50) with MACD histogram above zero. Enter when 1h MFI turns green and VuManChu dot confirms." />
    </div>

    <h2>Signal Checklist — Full 9-Point Confirmation</h2>
    <div style={cardStyle}>
      {[
        { n: 1, text: 'Monthly structure bullish — confirm macro trend', color: '#a855f7' },
        { n: 2, text: 'Weekly structure bullish — intermediate trend aligns', color: '#a855f7' },
        { n: 3, text: 'Daily structure bullish — short-term supports setup', color: '#a855f7' },
        { n: 4, text: '16h MFI green — MFI above 50 on 16-hour chart', color: '#00d4ff' },
        { n: 5, text: '16h MACD histogram > 0 — positive momentum', color: '#00d4ff' },
        { n: 6, text: '6h MFI green — MFI above 50 on 6-hour chart', color: '#eab308' },
        { n: 7, text: '6h MACD histogram > 0 — positive momentum', color: '#eab308' },
        { n: 8, text: '1h MFI turns green — MFI crosses above 50', color: '#16a34a' },
        { n: 9, text: '1h VuManChu dot closes — Stoch RSI bullish cross confirms entry', color: '#16a34a' },
      ].map(item => (
        <div key={item.n} style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '8px 0', borderBottom: '1px solid #1e293b' }}>
          <span style={{ background: item.color, color: '#000', width: 28, height: 28, borderRadius: 6, display: 'flex', alignItems: 'center', justifyContent: 'center', fontWeight: 700, fontSize: '0.85rem', flexShrink: 0 }}>{item.n}</span>
          <span style={{ color: '#e2e8f0', fontSize: '0.9rem' }}>{item.text}</span>
        </div>
      ))}
    </div>
    <InfoBox type="tip">For additional confluence, look for the 20 EMA above the 50 EMA with price holding above both. Both EMAs should be above the 200 EMA for the strongest setups.</InfoBox>

    <h2>VuManChu Dot Explanation</h2>
    <div style={grid2}>
      <CourseCard icon="?" title="What Is the Dot?" desc="Appears when multiple momentum conditions align simultaneously. Represents a high-probability entry. Always wait for the candle to CLOSE before acting." />
      <CourseCard icon="S" title="Stoch RSI Proxy" desc="If you don't have VuManChu, use Stochastic RSI. Look for K line crossing above D line from below 20-30 as the equivalent signal." />
      <CourseCard icon="E" title="Entry Rule" desc="After the dot closes (candle completes), enter on the next candle open. No early entries allowed. Must be fully confirmed." />
      <CourseCard icon="H" title="HTF Requirement" desc="A 1h dot alone is NOT enough. You must have 16h and 6h confirmation (MFI green + MACD positive) before acting on any 1h entry." />
    </div>

    <h2>Trade Management: Fib Trailing</h2>
    <div style={cardStyle}>
      <p style={{ color: '#94a3b8', marginBottom: 12 }}>Place initial stop at previous swing low. Apply trend-based Fibonacci extension from swing low to swing high.</p>
      {[
        'Price above 1.618 → Move stop to 0.618 level',
        'Price above 2.618 → Move stop to 1.618 level',
        'Price above 3.618 → Move stop to 2.618 level',
        'Price above 4.236 → Move stop to 3.618 level',
        'Continue trailing at each subsequent Fibonacci extension level',
      ].map((rule, i) => (
        <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '6px 0', color: '#16a34a', fontSize: '0.9rem' }}>
          <span style={{ color: '#16a34a' }}>↑</span> {rule}
        </div>
      ))}
    </div>

    <h2>Position Size Calculator</h2>
    <div style={cardStyle}>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, marginBottom: 12 }}>
        <div><label style={{ color: '#94a3b8', fontSize: '0.85rem', display: 'block', marginBottom: 4 }}>Account Balance ($)</label><input type="number" value={mfiBal} onChange={e => setMfiBal(e.target.value)} placeholder="10000" style={inputStyle} /></div>
        <div><label style={{ color: '#94a3b8', fontSize: '0.85rem', display: 'block', marginBottom: 4 }}>Risk %</label><input type="number" value={mfiRisk} onChange={e => setMfiRisk(e.target.value)} placeholder="2" style={inputStyle} /></div>
        <div><label style={{ color: '#94a3b8', fontSize: '0.85rem', display: 'block', marginBottom: 4 }}>Entry Price ($)</label><input type="number" value={mfiEntry} onChange={e => setMfiEntry(e.target.value)} placeholder="65000" style={inputStyle} /></div>
        <div><label style={{ color: '#94a3b8', fontSize: '0.85rem', display: 'block', marginBottom: 4 }}>Stop Loss ($)</label><input type="number" value={mfiStop} onChange={e => setMfiStop(e.target.value)} placeholder="63000" style={inputStyle} /></div>
      </div>
      <button onClick={calcMfi} style={btnStyle}>Calculate Position Size</button>
      {mfiRes.length > 0 && (
        <div style={{ marginTop: 16, display: 'flex', flexDirection: 'column' as const, gap: 6 }}>
          {mfiRes.map((r, i) => (
            <div key={i} style={{ display: 'flex', justifyContent: 'space-between', padding: '8px 12px', background: '#0f172a', borderRadius: 6 }}>
              <span style={{ color: '#94a3b8' }}>{r.label}</span>
              <span style={{ color: r.color, fontWeight: 600 }}>{r.value}</span>
            </div>
          ))}
        </div>
      )}
    </div>

    <InfoBox type="warning">Disclaimer: This strategy is for educational purposes only. Past performance does not guarantee future results. Never risk more than you can afford to lose.</InfoBox>
    <StepNav back={{ page: 'dashboard', label: '← Dashboard' }} onNavigate={onNavigate} />
  </>);
}

// ── Strategy: 2-Week Macro ──
function StratMacro({ onNavigate }: { onNavigate: (p: CoursePage) => void }) {
  return (<>
    <PageHeader title="2-Week Macro Trading Strategy" subtitle="Master institutional-level macro analysis with 2-week timeframe cycles" />
    <div style={grid4}>
      <MetricVal label="Win Rate" value="78%" color="#16a34a" />
      <MetricVal label="Risk/Reward" value="5:1" color="#00d4ff" />
      <MetricVal label="Primary Timeframe" value="2-Week" color="#eab308" />
      <MetricVal label="Approach" value="Institutional" color="#a855f7" />
    </div>

    <h2>Strategy Overview</h2>
    <div style={grid3}>
      <CourseCard icon="I" title="Core Philosophy" desc="Think like an institution. Focus on major trends with high conviction. Higher timeframes provide stronger signals with less noise." />
      <CourseCard icon="T" title="Timeframe Hierarchy" desc="Monthly — overall cycle. 2-Week — primary analysis. Weekly — confirmation. Daily — entry refinement." />
      <CourseCard icon="$" title="Position Characteristics" desc="3-5% account risk. Wider stop losses for macro volatility. Extended hold periods (weeks to months). Multiple TP levels." />
    </div>

    <h2>Timeframe Flow</h2>
    <div style={{ ...cardStyle, textAlign: 'center' as const, padding: 24 }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 12, flexWrap: 'wrap' as const, fontSize: '1.1em', fontWeight: 'bold' }}>
        {[
          { tf: '1M', label: 'Market Cycle', color: '#a855f7' },
          { tf: '2W', label: 'Primary Analysis', color: '#3b82f6' },
          { tf: '1W', label: 'Confirmation', color: '#00d4ff' },
          { tf: '3D', label: 'Structure', color: '#16a34a' },
          { tf: '1D', label: 'Entry Refinement', color: '#eab308' },
          { tf: '12H', label: 'Precise Timing', color: '#dc2626' },
        ].map((item, i) => (
          <React.Fragment key={i}>
            {i > 0 && <span style={{ color: '#475569' }}>→</span>}
            <div style={{ textAlign: 'center' as const }}>
              <div style={{ color: item.color, fontSize: '1.3em' }}>{item.tf}</div>
              <div style={{ color: '#64748b', fontSize: '0.6em', fontWeight: 'normal' }}>{item.label}</div>
            </div>
          </React.Fragment>
        ))}
      </div>
    </div>

    <h2>2-Week Candle Analysis</h2>
    <div style={grid2}>
      <CourseCard icon="G" title="Bullish Engulfing on 2W" desc="Extremely powerful reversal signal. Green 2-week candle fully engulfs prior red candle — major shift in institutional sentiment." />
      <CourseCard icon="H" title="Hammer / Doji on 2W" desc="Long lower wick or doji at key support on 2-week chart signals strong buyer interest. Wait for confirmation candle." />
      <CourseCard icon="^" title="Higher Highs / Higher Lows" desc="Consecutive 2-week candles forming HH/HL confirm macro uptrend. Most reliable directional confirmation." />
      <CourseCard icon="=" title="Key S/R Levels" desc="S/R levels held across multiple 2-week candles are extremely significant — true institutional interest zones." />
    </div>

    <h2>Macro Setup Checklist</h2>
    <div style={cardStyle}>
      {[
        { n: 1, text: 'Monthly Trend — confirm overall direction on 1M chart', color: '#a855f7' },
        { n: 2, text: '2W Structure — identify key S/R levels tested multiple times', color: '#3b82f6' },
        { n: 3, text: 'Weekly Confirmation — verify 1W aligns with 2W bias', color: '#00d4ff' },
        { n: 4, text: 'Daily Entry — wait for 1D/12H signal aligned with macro direction', color: '#16a34a' },
        { n: 5, text: 'Risk Management — size appropriately for macro timeframe', color: '#eab308' },
      ].map(item => (
        <div key={item.n} style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '8px 0', borderBottom: '1px solid #1e293b' }}>
          <span style={{ background: item.color, color: '#000', width: 28, height: 28, borderRadius: 6, display: 'flex', alignItems: 'center', justifyContent: 'center', fontWeight: 700, fontSize: '0.85rem', flexShrink: 0 }}>{item.n}</span>
          <span style={{ color: '#e2e8f0', fontSize: '0.9rem' }}>{item.text}</span>
        </div>
      ))}
    </div>

    <h2>Risk Framework</h2>
    <div style={grid2}>
      <CourseCard icon="%" title="Position Sizing" desc="3-5% risk per macro trade. Maximum 15% total portfolio exposure. Scale size with conviction level." />
      <CourseCard icon="X" title="Stop Management" desc="Previous 2W swing as initial stop. Never risk more than 15% on a single trade. Move to breakeven after 1:1 R:R." />
      <CourseCard icon="$" title="Profit Taking" desc="Scale out 25% at 2:1 R:R. Scale out 50% at Fibonacci extensions. Trail stop on final 25%." />
      <CourseCard icon="T" title="Time Management" desc="Review positions weekly, not daily. Exit if no progress after 4 weeks. Reduce size before major macro events." />
    </div>

    <h2>Setup Examples</h2>
    <div style={grid3}>
      <div style={{ ...cardStyle, borderLeft: '3px solid #16a34a' }}>
        <h4 style={{ color: '#16a34a', marginBottom: 8 }}>Bullish Macro Setup</h4>
        <ol style={{ margin: 0, paddingLeft: 18, color: '#94a3b8', fontSize: '0.85rem' }}>
          <li>Monthly chart in confirmed uptrend</li>
          <li>2W candle breaking above key resistance with 2x volume</li>
          <li>Weekly showing HH/HL</li>
          <li>Enter on daily pullback to 50-61.8% Fib</li>
          <li>Targets at 1.618/2.618/4.236 Fib extensions</li>
        </ol>
      </div>
      <div style={{ ...cardStyle, borderLeft: '3px solid #dc2626' }}>
        <h4 style={{ color: '#dc2626', marginBottom: 8 }}>Bearish Macro Setup</h4>
        <ol style={{ margin: 0, paddingLeft: 18, color: '#94a3b8', fontSize: '0.85rem' }}>
          <li>Monthly chart in confirmed downtrend</li>
          <li>2W candle breaking below key support with volume</li>
          <li>Weekly showing LH/LL</li>
          <li>Enter on daily rally to 38.2-50% Fib</li>
          <li>Target previous major lows</li>
        </ol>
      </div>
      <div style={{ ...cardStyle, borderLeft: '3px solid #eab308' }}>
        <h4 style={{ color: '#eab308', marginBottom: 8 }}>Accumulation Setup</h4>
        <ol style={{ margin: 0, paddingLeft: 18, color: '#94a3b8', fontSize: '0.85rem' }}>
          <li>Price in long-term range on 2W</li>
          <li>Multiple 2W tests of support holding</li>
          <li>Decreasing volume on retests</li>
          <li>Scale into position on each support test</li>
          <li>Exit on confirmed range breakout</li>
        </ol>
      </div>
    </div>

    <InfoBox type="warning">Disclaimer: This strategy is for educational purposes only. Macro trading involves extended holds and wider stops — ensure you are comfortable with the capital at risk.</InfoBox>
    <StepNav back={{ page: 'dashboard', label: '← Dashboard' }} onNavigate={onNavigate} />
  </>);
}

// ── Bull Market Analysis ──
function BullMarketPage({ onNavigate }: { onNavigate: (p: CoursePage) => void }) {
  return (<>
    <PageHeader title="Bull Market Analysis" subtitle="Comprehensive analysis of bull market cycles, peak indicators, and the 2025 outlook" />

    <h2>Bull Market Peak Indicators</h2>
    <div style={grid3}>
      {[
        { name: 'Pi Cycle Top Indicator', desc: '111-day MA crosses 350-day MA x 2', status: 'Not Hit', color: '#16a34a' },
        { name: 'Stock-to-Flow Model', desc: 'Price vs predicted S2F value', status: 'Below Target', color: '#16a34a' },
        { name: 'MVRV Z-Score', desc: 'Market cap vs realized cap', status: 'Approaching', color: '#eab308' },
        { name: 'Puell Multiple', desc: 'Daily issuance vs 365-day average', status: 'Normal Range', color: '#16a34a' },
        { name: '200-Week Moving Average', desc: 'Price distance from 200W MA', status: 'Below Peak Zone', color: '#16a34a' },
        { name: 'NVT Golden Cross', desc: 'Network value to transactions', status: 'Not Overvalued', color: '#16a34a' },
      ].map((ind, i) => (
        <div key={i} style={cardStyle}>
          <div style={{ fontWeight: 600, color: '#e2e8f0', marginBottom: 4 }}>{ind.name}</div>
          <div style={{ color: '#94a3b8', fontSize: '0.85rem', marginBottom: 8 }}>{ind.desc}</div>
          <span style={{ background: ind.color, color: '#000', padding: '4px 12px', borderRadius: 12, fontWeight: 600, fontSize: '0.8rem' }}>{ind.status}</span>
        </div>
      ))}
    </div>

    <h2>Market Top Probability</h2>
    <div style={{ ...cardStyle, textAlign: 'center' as const }}>
      <div style={{ color: '#16a34a', fontSize: '3rem', fontWeight: 700 }}>15%</div>
      <div style={{ color: '#94a3b8', marginBottom: 12 }}>Market Top Probability</div>
      <div style={{ width: '100%', background: '#0f172a', borderRadius: 8, height: 12, overflow: 'hidden' }}>
        <div style={{ width: '15%', height: '100%', background: '#16a34a', borderRadius: 8 }} />
      </div>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 4, color: '#64748b', fontSize: '0.8rem' }}>
        <span>Low Risk</span><span>High Risk</span>
      </div>
    </div>

    <h2>5 Phases of a Bull Run</h2>
    <div style={{ display: 'flex', flexDirection: 'column' as const, gap: 12 }}>
      {[
        { n: 1, name: 'Accumulation Phase', desc: 'Smart money accumulates, retail fearful. Key: 0.618-0.786 Fib retracement.', color: '#3b82f6', active: false },
        { n: 2, name: 'Early Bull Phase', desc: 'Breaks key resistance, institutional interest. Previous cycle high becomes support.', color: '#00d4ff', active: true },
        { n: 3, name: 'Main Bull Run', desc: 'Parabolic action, retail FOMO, media coverage. Key: 1.618-2.618 Fib extensions.', color: '#16a34a', active: false },
        { n: 4, name: 'Euphoria Phase', desc: 'Peak indicators flash, everyone talking. Key: 3.618-4.236 Fib.', color: '#eab308', active: false },
        { n: 5, name: 'Distribution / Top', desc: 'Smart money distributes. Monitor all peak indicators.', color: '#dc2626', active: false },
      ].map(phase => (
        <div key={phase.n} style={{ ...cardStyle, borderLeft: `4px solid ${phase.color}`, display: 'flex', alignItems: 'center', gap: 16, background: phase.active ? '#111827' : undefined }}>
          <span style={{ background: phase.color, color: '#000', width: 32, height: 32, borderRadius: 8, display: 'flex', alignItems: 'center', justifyContent: 'center', fontWeight: 700, flexShrink: 0 }}>{phase.n}</span>
          <div>
            <strong style={{ color: '#e2e8f0' }}>{phase.name}</strong>
            {phase.active && <span style={{ background: '#00d4ff', color: '#000', padding: '2px 8px', borderRadius: 8, fontSize: '0.7rem', marginLeft: 8, fontWeight: 600 }}>ACTIVE</span>}
            <p style={{ color: '#94a3b8', margin: '4px 0 0', fontSize: '0.85rem' }}>{phase.desc}</p>
          </div>
        </div>
      ))}
    </div>

    <h2>Key Fibonacci Levels</h2>
    <div style={{ ...cardStyle, display: 'flex', flexDirection: 'column' as const, gap: 8 }}>
      {[
        { name: '0.618 (Golden Pocket)', desc: 'Strong Support', color: '#00d4ff' },
        { name: '1.618 (First Extension)', desc: 'Take Profits', color: '#16a34a' },
        { name: '2.618 (Second Extension)', desc: 'Major Resistance', color: '#eab308' },
        { name: '3.618+ (Peak Zone)', desc: 'Distribution Zone', color: '#dc2626' },
      ].map((lev, i) => (
        <div key={i} style={{ display: 'flex', justifyContent: 'space-between', padding: '8px 12px', background: '#0f172a', borderRadius: 8 }}>
          <span style={{ color: lev.color, fontWeight: 600 }}>{lev.name}</span>
          <span style={{ color: '#94a3b8' }}>{lev.desc}</span>
        </div>
      ))}
    </div>

    <h2>Trading Strategy by Phase</h2>
    <div style={{ ...cardStyle, display: 'flex', flexDirection: 'column' as const, gap: 8 }}>
      {[
        { phase: 'Phase 1-2', action: 'Accumulate on dips to key support', color: '#3b82f6' },
        { phase: 'Phase 3', action: 'Hold and ride, add on pullbacks', color: '#16a34a' },
        { phase: 'Phase 4', action: 'Begin systematic profit-taking', color: '#eab308' },
        { phase: 'Phase 5', action: 'Complete distribution, prepare for bear', color: '#dc2626' },
      ].map((item, i) => (
        <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '8px 12px', background: '#0f172a', borderRadius: 8 }}>
          <span style={{ color: item.color, fontWeight: 700, minWidth: 80 }}>{item.phase}</span>
          <span style={{ color: '#94a3b8' }}>{item.action}</span>
        </div>
      ))}
    </div>

    <StepNav back={{ page: 'dashboard', label: '← Dashboard' }} onNavigate={onNavigate} />
  </>);
}

// ── Backtesting Lab ──
function BacktestingPage({ onNavigate }: { onNavigate: (p: CoursePage) => void }) {
  const [btTotal, setBtTotal] = useState(''); const [btWins, setBtWins] = useState('');
  const [btProfit, setBtProfit] = useState(''); const [btLoss, setBtLoss] = useState('');
  const [btRes, setBtRes] = useState<{label:string;value:string;color:string}[]>([]);

  const calcBt = () => {
    const total = parseFloat(btTotal) || 0, wins = parseFloat(btWins) || 0;
    const profit = parseFloat(btProfit) || 0, loss = Math.abs(parseFloat(btLoss) || 0);
    if (total <= 0) return;
    const winRate = (wins / total) * 100;
    const pf = loss > 0 ? profit / loss : profit > 0 ? Infinity : 0;
    const net = profit - loss;
    let grade = 'F';
    if (pf >= 2 && winRate >= 60) grade = 'A';
    else if (pf >= 1.5 && winRate >= 50) grade = 'B';
    else if (pf >= 1.2) grade = 'C';
    else if (pf >= 1) grade = 'D';
    const gc: Record<string,string> = { A: '#16a34a', B: '#00d4ff', C: '#eab308', D: '#dc2626', F: '#dc2626' };
    setBtRes([
      { label: 'Win Rate', value: `${winRate.toFixed(1)}%`, color: winRate >= 50 ? '#16a34a' : '#dc2626' },
      { label: 'Profit Factor', value: pf === Infinity ? 'Infinite' : pf.toFixed(2), color: pf >= 1.5 ? '#16a34a' : pf >= 1 ? '#eab308' : '#dc2626' },
      { label: 'Net P&L', value: `${net >= 0 ? '+' : ''}$${net.toFixed(2)}`, color: net >= 0 ? '#16a34a' : '#dc2626' },
      { label: 'Strategy Grade', value: grade, color: gc[grade] },
    ]);
  };

  return (<>
    <PageHeader title="Strategy Backtesting Lab" subtitle="Comprehensive backtesting tools and methodologies" />
    <h2>Why Backtest?</h2>
    <div style={grid4}>
      <CourseCard icon="V" title="Validate Performance" desc="Prove your strategy works before risking real capital" />
      <CourseCard icon="R" title="Risk Assessment" desc="Understand worst-case drawdowns and risk exposure" />
      <CourseCard icon="C" title="Build Confidence" desc="Trade with conviction backed by data, not hope" />
      <CourseCard icon="O" title="Optimize Parameters" desc="Fine-tune indicator settings and risk parameters" />
    </div>

    <h2>5-Step Backtesting Process</h2>
    {[
      { n: 1, title: 'Setup Environment', desc: 'BTC/USD on 4H timeframe, minimum 6+ months of data. Add all indicators your strategy uses.', color: '#00d4ff' },
      { n: 2, title: 'Initialize Bar Replay', desc: 'Go to earliest date, click Bar Replay, hide right portion. Never look at future price action.', color: '#16a34a' },
      { n: 3, title: 'Execute Strategy Rules', desc: 'Step through each bar, apply exact criteria, record every setup. Check: HTF confirmed? Entry met? R/R acceptable? SL identified? TP set?', color: '#eab308' },
      { n: 4, title: 'Record Trade Details', desc: 'Log entry details (date, time, price, size), exit details, risk management (SL, TP, R-multiple), and performance notes.', color: '#a855f7' },
      { n: 5, title: 'Calculate Metrics', desc: 'Win Rate, Avg R-Multiple, Profit Factor, Max Drawdown, Sharpe Ratio. Targets: WR ≥ 50%, Avg R ≥ 0.5, PF ≥ 1.5, MDD < 15%.', color: '#dc2626' },
    ].map(step => (
      <div key={step.n} style={{ ...cardStyle, borderLeft: `4px solid ${step.color}`, marginBottom: 12 }}>
        <h3><span style={{ background: step.color, color: '#000', padding: '2px 10px', borderRadius: 8, marginRight: 8, fontSize: '0.85rem' }}>{step.n}</span> {step.title}</h3>
        <p style={{ color: '#94a3b8', margin: '8px 0 0', fontSize: '0.9rem' }}>{step.desc}</p>
      </div>
    ))}

    <h2>Performance Calculator</h2>
    <div style={cardStyle}>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, marginBottom: 12 }}>
        <div><label style={{ color: '#94a3b8', fontSize: '0.85rem', display: 'block', marginBottom: 4 }}>Total Trades</label><input type="number" value={btTotal} onChange={e => setBtTotal(e.target.value)} placeholder="100" style={inputStyle} /></div>
        <div><label style={{ color: '#94a3b8', fontSize: '0.85rem', display: 'block', marginBottom: 4 }}>Winning Trades</label><input type="number" value={btWins} onChange={e => setBtWins(e.target.value)} placeholder="58" style={inputStyle} /></div>
        <div><label style={{ color: '#94a3b8', fontSize: '0.85rem', display: 'block', marginBottom: 4 }}>Total Profit ($)</label><input type="number" value={btProfit} onChange={e => setBtProfit(e.target.value)} placeholder="5000" style={inputStyle} /></div>
        <div><label style={{ color: '#94a3b8', fontSize: '0.85rem', display: 'block', marginBottom: 4 }}>Total Loss ($)</label><input type="number" value={btLoss} onChange={e => setBtLoss(e.target.value)} placeholder="2500" style={inputStyle} /></div>
      </div>
      <button onClick={calcBt} style={btnStyle}>Calculate Performance</button>
      {btRes.length > 0 && (
        <div style={{ marginTop: 16, display: 'flex', flexDirection: 'column' as const, gap: 6 }}>
          {btRes.map((r, i) => (
            <div key={i} style={{ display: 'flex', justifyContent: 'space-between', padding: '8px 12px', background: '#0f172a', borderRadius: 6 }}>
              <span style={{ color: '#94a3b8' }}>{r.label}</span>
              <span style={{ color: r.color, fontWeight: 600 }}>{r.value}</span>
            </div>
          ))}
        </div>
      )}
    </div>

    <h2>Best Practices</h2>
    <div style={grid2}>
      <div style={{ ...cardStyle, borderLeft: '4px solid #16a34a' }}>
        <h3 style={{ color: '#16a34a' }}>Essential Do's</h3>
        <ul style={{ margin: 0, paddingLeft: 18, color: '#94a3b8', fontSize: '0.9rem' }}>
          <li>Use sufficient data (100+ trades minimum)</li>
          <li>Test across multiple timeframes</li>
          <li>Include all trading costs and fees</li>
          <li>Be honest with your results</li>
          <li>Document every trade thoroughly</li>
          <li>Test out-of-sample data separately</li>
        </ul>
      </div>
      <div style={{ ...cardStyle, borderLeft: '4px solid #dc2626' }}>
        <h3 style={{ color: '#dc2626' }}>Critical Don'ts</h3>
        <ul style={{ margin: 0, paddingLeft: 18, color: '#94a3b8', fontSize: '0.9rem' }}>
          <li>No look-ahead bias — never peek at future price</li>
          <li>No curve fitting — don't over-optimize to past data</li>
          <li>No cherry picking — record ALL trades</li>
          <li>Don't use insufficient sample size</li>
          <li>Don't ignore drawdowns — they matter most</li>
          <li>Account for human error and slippage</li>
        </ul>
      </div>
    </div>
    <StepNav back={{ page: 'dashboard', label: '← Dashboard' }} onNavigate={onNavigate} />
  </>);
}

// ── Resources ──
function ResourcesPage({ onNavigate }: { onNavigate: (p: CoursePage) => void }) {
  return (<>
    <PageHeader title="Resources" subtitle="Professional trading resources, guides, and TradingView templates" />
    <h2>PDF Cheatsheets & Guides</h2>
    <div style={grid4}>
      <CourseCard icon="D" title="Terminology Cheatsheet" desc="Essential trading terms and definitions every trader must know" />
      <CourseCard icon="W" title="Indicator Settings Guide" desc="Optimized RSI, Stoch RSI, MACD, and MFI parameters for crypto" />
      <CourseCard icon="H" title="HTF Drill Worksheet" desc="Higher timeframe analysis practice worksheet for daily use" />
      <CourseCard icon="$" title="Risk Calculator Guide" desc="Position sizing and risk management reference guide" />
    </div>

    <h2>TradingView Templates</h2>
    <div style={cardStyle}>
      <h3>Trendline Breakout Strategy</h3>
      <p style={{ color: '#94a3b8', marginBottom: 12 }}>Complete setup guide with all required indicators.</p>
      <pre style={{ background: '#0f172a', border: '1px solid #1e293b', borderRadius: 8, padding: 16, color: '#00d4ff', overflow: 'auto', fontSize: '0.85rem', lineHeight: 1.6 }}>{`{
  "indicators": {
    "EMA 21":  { "length": 21,  "color": "#FF6B35" },
    "EMA 50":  { "length": 50,  "color": "#4ECDC4" },
    "EMA 200": { "length": 200, "color": "#45B7D1" },
    "RSI":     { "length": 14 },
    "MACD":    { "fast": 12, "slow": 26, "signal": 9 },
    "Volume":  { "type": "standard" }
  }
}`}</pre>
    </div>
    <div style={cardStyle}>
      <h3>MFI + MACD Multi-Timeframe</h3>
      <p style={{ color: '#94a3b8', marginBottom: 12 }}>16H / 6H / 1H analysis system with alert configurations.</p>
      <h4 style={{ color: '#00d4ff', marginBottom: 8 }}>6H MFI + MACD Setup Alert</h4>
      <pre style={{ background: '#0f172a', border: '1px solid #1e293b', borderRadius: 8, padding: 16, color: '#16a34a', overflow: 'auto', fontSize: '0.85rem', lineHeight: 1.6 }}>{`// Pine Script Alert Condition — 6H MFI + MACD
mfiVal = ta.mfi(hlc3, 14)
[macdLine, signalLine, hist] = ta.macd(close, 12, 26, 9)
longSetup = ta.crossover(macdLine, signalLine) and mfiVal > 50
alertcondition(longSetup, "6H MFI+MACD Long", "6H LONG setup")`}</pre>
      <h4 style={{ color: '#00d4ff', marginTop: 16, marginBottom: 8 }}>1H Stoch RSI Entry Alert</h4>
      <pre style={{ background: '#0f172a', border: '1px solid #1e293b', borderRadius: 8, padding: 16, color: '#16a34a', overflow: 'auto', fontSize: '0.85rem', lineHeight: 1.6 }}>{`// Pine Script Alert Condition — 1H Stoch RSI Entry
rsiVal = ta.rsi(close, 14)
[k, d] = ta.stoch(rsiVal, rsiVal, rsiVal, 14)
kSmooth = ta.sma(k, 3)
dSmooth = ta.sma(d, 3)
entrySignal = ta.crossover(kSmooth, dSmooth)
alertcondition(entrySignal, "1H StochRSI Entry", "1H ENTRY")`}</pre>
    </div>

    <h2>Trade Journal Template</h2>
    <div style={cardStyle}>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 2fr', gap: '4px 16px', lineHeight: 2 }}>
        {[
          ['Date', 'YYYY-MM-DD HH:MM'], ['Symbol', 'BTC/USD'], ['Timeframe', '1H / 4H / Daily'],
          ['Setup Type', 'Trendline Break / MFI+MACD / etc.'], ['Direction', 'Long / Short'],
          ['Entry', '$XX,XXX.XX'], ['Stop Loss', '$XX,XXX.XX'], ['Take Profit', '$XX,XXX.XX'],
          ['R/R Ratio', 'X.X : 1'], ['Position Size', 'X% of account'],
          ['Setup Notes', 'Why did you take this trade?'], ['Outcome', 'Win / Loss / Break-even'],
          ['Lessons', 'What did you learn?'],
        ].map(([label, val], i) => (
          <React.Fragment key={i}>
            <span style={{ color: '#00d4ff', fontWeight: 600 }}>{label}</span>
            <span style={{ color: '#94a3b8' }}>{val}</span>
          </React.Fragment>
        ))}
      </div>
    </div>
    <StepNav back={{ page: 'dashboard', label: '← Dashboard' }} onNavigate={onNavigate} />
  </>);
}

// ── Alerts & Signals ──
function AlertsPage({ onNavigate }: { onNavigate: (p: CoursePage) => void }) {
  return (<>
    <PageHeader title="Trading Alerts & Signals" subtitle="Professional alert setups for TradingView" />
    <div style={{ ...cardStyle, border: '2px solid #a855f7', position: 'relative' as const, overflow: 'hidden' }}>
      <span style={{ position: 'absolute' as const, top: 12, right: 12, background: '#a855f7', color: '#000', padding: '2px 10px', borderRadius: 8, fontSize: '0.75rem', fontWeight: 700 }}>COMING SOON</span>
      <h3 style={{ color: '#a855f7' }}>VIP Discord Community</h3>
      <div style={grid2}>
        <CourseCard icon="A" title="Live Trade Alerts" desc="Real-time entry and exit signals" />
        <CourseCard icon="M" title="Market Analysis" desc="Daily and weekly market breakdowns" />
        <CourseCard icon="S" title="Strategy Discussions" desc="Share and refine trading strategies" />
        <CourseCard icon="E" title="Elite Community" desc="Network with serious traders" />
      </div>
      <div style={{ textAlign: 'center' as const, padding: 16, background: '#0f172a', borderRadius: 8, marginTop: 12 }}>
        <p style={{ color: '#a855f7', fontWeight: 600, marginBottom: 4 }}>Premium Access Required</p>
        <p style={{ color: '#94a3b8', fontSize: '0.9rem', margin: 0 }}>Upgrade to Premium (Coming Soon)</p>
      </div>
    </div>

    <h2>Free TradingView Alert Setups</h2>
    <h3>MFI + MACD Strategy Alerts</h3>
    <div style={grid3}>
      <div style={cardStyle}>
        <h4 style={{ color: '#00d4ff' }}>HTF Bias Change (Weekly/Daily)</h4>
        <p style={{ color: '#94a3b8', fontSize: '0.85rem' }}>Switch to 1W, add MFI + MACD. Set alert when MACD Histogram crosses zero line.</p>
      </div>
      <div style={cardStyle}>
        <h4 style={{ color: '#00d4ff' }}>16H/6H Alignment Signal</h4>
        <p style={{ color: '#94a3b8', fontSize: '0.85rem' }}>Set to 16H, add MFI + MACD. Alert when MACD crosses above signal AND MFI above 50.</p>
      </div>
      <div style={cardStyle}>
        <h4 style={{ color: '#00d4ff' }}>1H Entry Trigger</h4>
        <p style={{ color: '#94a3b8', fontSize: '0.85rem' }}>Set to 1H, add Stoch RSI. Alert when K crosses above D. Always confirm HTF bias first.</p>
      </div>
    </div>

    <h3>Trendline Breakout Alerts</h3>
    <div style={cardStyle}>
      <h4 style={{ color: '#00d4ff' }}>Trendline Break Alert</h4>
      <p style={{ color: '#94a3b8', marginBottom: 8 }}>Draw trendlines on your chart, right-click and select "Add Alert". Configure the crossing condition.</p>
      <InfoBox type="warning">Always confirm breakouts with volume expansion and RSI momentum before entering a trade.</InfoBox>
    </div>

    <h2>Alert Management Best Practices</h2>
    <div style={grid4}>
      <CourseCard icon="P" title="Mobile Notifications" desc="Enable TradingView mobile app for instant push notifications on all alerts" />
      <CourseCard icon="S" title="Custom Sounds" desc="Use different alert sounds for different strategies so you know what triggered" />
      <CourseCard icon="E" title="Email Backup" desc="Set up email notifications as backup in case you miss push notifications" />
      <CourseCard icon="C" title="Regular Cleanup" desc="Review and delete old/expired alerts weekly to keep your list clean" />
    </div>

    <h2>Webhook Integration</h2>
    <InfoBox type="tip">
      Connect TradingView alerts to external services via webhooks for automated workflows: Discord Bots, Telegram, Slack, Custom APIs. Note: Requires TradingView Pro+ or Premium subscription.
    </InfoBox>
    <StepNav back={{ page: 'dashboard', label: '← Dashboard' }} onNavigate={onNavigate} />
  </>);
}

// ── Trading Dictionary ──
const DICTIONARY_DATA = [
  // Market Structure
  { term: "Support", cat: "structure", def: "Price level where buying interest consistently prevents further decline. Acts as a floor where demand exceeds supply." },
  { term: "Resistance", cat: "structure", def: "Price level where selling pressure consistently prevents further advance. Acts as a ceiling where supply exceeds demand." },
  { term: "Trend", cat: "structure", def: "General direction of price movement. Uptrends: higher highs and higher lows. Downtrends: lower highs and lower lows." },
  { term: "Breakout", cat: "structure", def: "A decisive price move beyond an established support or resistance level, typically with increased volume." },
  { term: "Retest", cat: "structure", def: "When price returns to test a recently broken level, confirming the breakout's validity." },
  { term: "Market Structure", cat: "structure", def: "Framework of swing highs and swing lows indicating current trend direction and potential reversals." },
  { term: "Liquidity", cat: "structure", def: "Areas where stop-loss and pending orders cluster. Smart money targets these pools at key S/R levels." },
  { term: "Fair Value Gap (FVG)", cat: "structure", def: "An imbalance created between candle wicks where price moved too quickly, leaving inefficient price discovery." },
  { term: "Order Block", cat: "structure", def: "Consolidation zone before a strong move where institutional orders were placed. Acts as future S/R." },
  { term: "Break of Structure (BOS)", cat: "structure", def: "When price breaks a significant swing high/low, signaling a potential trend change or continuation." },
  { term: "Inducement", cat: "structure", def: "Price move designed to trigger stop losses and trap retail traders before the real move." },
  { term: "Premium/Discount", cat: "structure", def: "Price relative to a range. Premium (upper half) = sell zone; Discount (lower half) = buy zone." },
  { term: "Swing High/Low", cat: "structure", def: "Local peaks and troughs that define market structure and trend direction." },
  { term: "Trendline", cat: "structure", def: "Line connecting 2+ price points showing trend direction. Acts as dynamic support or resistance." },
  { term: "Channel", cat: "structure", def: "Two parallel trendlines containing price action. Can be ascending, descending, or horizontal." },
  // Indicators
  { term: "EMA", cat: "indicators", def: "Exponential Moving Average — gives more weight to recent prices, more responsive than SMA." },
  { term: "RSI", cat: "indicators", def: "Relative Strength Index — momentum on 0-100 scale. Above 70 = overbought, below 30 = oversold." },
  { term: "MACD", cat: "indicators", def: "Moving Average Convergence Divergence — shows relationship between two MAs via signal line and histogram." },
  { term: "Stochastic RSI", cat: "indicators", def: "Stochastic oscillator applied to RSI for faster, more sensitive momentum signals (0 to 1)." },
  { term: "MFI", cat: "indicators", def: "Money Flow Index — volume-weighted RSI measuring buying/selling pressure using price and volume." },
  { term: "Volume", cat: "indicators", def: "Number of shares/contracts traded. Confirms price movements and signals trend strength." },
  { term: "Bollinger Bands", cat: "indicators", def: "Volatility bands placed above/below a moving average, typically 2 standard deviations. Widen with volatility." },
  { term: "ATR", cat: "indicators", def: "Average True Range — measures market volatility by averaging high-low range over a period." },
  { term: "VWAP", cat: "indicators", def: "Volume Weighted Average Price — average price weighted by volume throughout the trading session." },
  { term: "Divergence", cat: "indicators", def: "When price and indicator move in opposite directions — signals potential trend exhaustion or reversal." },
  { term: "Golden Cross", cat: "indicators", def: "Bullish signal when short-term MA crosses above long-term MA, suggesting upward momentum." },
  { term: "Death Cross", cat: "indicators", def: "Bearish signal when short-term MA crosses below long-term MA, suggesting downward momentum." },
  // Patterns
  { term: "Double Top", cat: "patterns", def: "Bearish reversal pattern with two peaks at similar levels, indicating resistance and potential trend change." },
  { term: "Double Bottom", cat: "patterns", def: "Bullish reversal pattern with two troughs at similar levels, indicating support and potential trend change." },
  { term: "Head and Shoulders", cat: "patterns", def: "Bearish reversal pattern with three peaks — middle (head) is highest. Completes on neckline break." },
  { term: "Ascending Triangle", cat: "patterns", def: "Bullish continuation with horizontal resistance and rising support. Buyers becoming more aggressive." },
  { term: "Descending Triangle", cat: "patterns", def: "Bearish continuation with horizontal support and declining resistance. Sellers becoming more aggressive." },
  { term: "Flag Pattern", cat: "patterns", def: "Rectangular consolidation after a strong move (the flagpole). Typically a continuation signal." },
  { term: "Cup and Handle", cat: "patterns", def: "Bullish continuation forming a rounded bottom (cup) then a small pullback (handle) before breakout." },
  { term: "Wedge", cat: "patterns", def: "Converging trendlines showing diminishing momentum. Rising wedges = bearish; falling wedges = bullish." },
  // Risk Management
  { term: "Stop Loss", cat: "risk", def: "Predetermined price level where a losing position is closed to limit losses. Essential for capital preservation." },
  { term: "Take Profit", cat: "risk", def: "Predetermined price level where a winning position is closed to secure gains before potential reversal." },
  { term: "Risk-Reward Ratio", cat: "risk", def: "Ratio comparing potential loss to potential gain. Higher ratios allow profitability with lower win rates." },
  { term: "Position Size", cat: "risk", def: "Capital allocated to a single trade, calculated based on account size and risk tolerance per trade." },
  { term: "Drawdown", cat: "risk", def: "Peak-to-trough decline in account value. Measures largest loss from a high point before recovery." },
  { term: "Leverage", cat: "risk", def: "Using borrowed capital to amplify position size. Amplifies both gains and losses equally." },
  { term: "Sharpe Ratio", cat: "risk", def: "Risk-adjusted return metric comparing excess returns to volatility. Higher = better risk-adjusted performance." },
  { term: "MAE", cat: "risk", def: "Maximum Adverse Excursion — largest unrealized loss during a winning trade. Helps optimize stop placement." },
  // Orders & Execution
  { term: "Market Order", cat: "orders", def: "Order to buy/sell immediately at the best available price. Guarantees execution but not price." },
  { term: "Limit Order", cat: "orders", def: "Order to buy/sell at a specific price or better. Guarantees price but not execution." },
  { term: "Stop Order", cat: "orders", def: "Order that becomes a market order once the stop price is reached. Used for losses or breakout entries." },
  { term: "OCO", cat: "orders", def: "One Cancels Other — pair of linked orders where execution of one cancels the other (common for TP and SL)." },
  { term: "Slippage", cat: "orders", def: "Difference between expected and actual fill price. Common during high volatility or low liquidity." },
  { term: "Bid-Ask Spread", cat: "orders", def: "Difference between highest buyer price (bid) and lowest seller price (ask). Tighter = better liquidity." },
  { term: "Fill or Kill", cat: "orders", def: "Order that must execute immediately in its entirety or be cancelled completely. No partial fills." },
  // Psychology
  { term: "FOMO", cat: "psychology", def: "Fear Of Missing Out — emotional urge to enter trades impulsively due to rapid price movement." },
  { term: "Revenge Trading", cat: "psychology", def: "Aggressive, poorly planned trades attempting to quickly recover losses. Usually leads to larger losses." },
  { term: "Confirmation Bias", cat: "psychology", def: "Tendency to seek confirming information while ignoring contradictory evidence." },
  { term: "Overconfidence", cat: "psychology", def: "Excessive confidence after winning streaks, leading to oversized positions and ignored risk." },
  { term: "Analysis Paralysis", cat: "psychology", def: "Overthinking to the point of being unable to make a decision, missing valid opportunities." },
  { term: "Anchoring Bias", cat: "psychology", def: "Over-relying on first information encountered even when no longer relevant." },
  { term: "Loss Aversion", cat: "psychology", def: "Preferring to avoid losses over acquiring equivalent gains — holding losers too long." },
  { term: "Recency Bias", cat: "psychology", def: "Giving disproportionate weight to recent events while undervaluing historical patterns." },
];

const CAT_COLORS: Record<string,string> = { structure: '#3b82f6', indicators: '#00d4ff', patterns: '#a855f7', risk: '#dc2626', orders: '#eab308', psychology: '#16a34a' };
const CAT_LABELS: Record<string,string> = { structure: 'Market Structure', indicators: 'Indicators', patterns: 'Patterns', risk: 'Risk Management', orders: 'Orders & Execution', psychology: 'Psychology' };

function DictionaryPage({ onNavigate }: { onNavigate: (p: CoursePage) => void }) {
  const [search, setSearch] = useState('');
  const [catFilter, setCatFilter] = useState('all');

  const filtered = DICTIONARY_DATA.filter(d => {
    const matchCat = catFilter === 'all' || d.cat === catFilter;
    const matchSearch = !search || d.term.toLowerCase().includes(search.toLowerCase()) || d.def.toLowerCase().includes(search.toLowerCase());
    return matchCat && matchSearch;
  });

  return (<>
    <PageHeader title="Trading Dictionary" subtitle="Your comprehensive reference for all trading terminology" />
    <input type="text" value={search} onChange={e => setSearch(e.target.value)} placeholder="Search terms, definitions..."
      style={{ ...inputStyle, width: '100%', marginBottom: 16, padding: '12px 16px', fontSize: '1rem' }} />

    <div style={{ display: 'flex', flexWrap: 'wrap' as const, gap: 8, marginBottom: 16 }}>
      {['all', ...Object.keys(CAT_LABELS)].map(cat => (
        <button key={cat} onClick={() => setCatFilter(cat)}
          style={{ padding: '8px 16px', borderRadius: 6, border: '1px solid #1e293b', cursor: 'pointer', fontSize: '0.85rem', fontWeight: catFilter === cat ? 600 : 400,
            background: catFilter === cat ? '#00d4ff' : '#1a2236', color: catFilter === cat ? '#000' : '#e2e8f0' }}>
          {cat === 'all' ? 'All Terms' : CAT_LABELS[cat]}
        </button>
      ))}
    </div>

    <div style={grid4}>
      <MetricVal label="Total Terms" value={String(DICTIONARY_DATA.length)} color="#00d4ff" />
      <MetricVal label="Categories" value={String(Object.keys(CAT_LABELS).length)} color="#a855f7" />
      <MetricVal label="With Examples" value={String(DICTIONARY_DATA.length)} color="#16a34a" />
      <MetricVal label="Showing" value={String(filtered.length)} color="#eab308" />
    </div>

    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(320px, 1fr))', gap: 16, marginTop: 16 }}>
      {filtered.map((d, i) => {
        const color = CAT_COLORS[d.cat] || '#94a3b8';
        return (
          <div key={i} style={cardStyle}>
            <div style={{ fontWeight: 700, color: '#e2e8f0', marginBottom: 4 }}>{d.term}</div>
            <span style={{ background: `${color}22`, color, border: `1px solid ${color}44`, padding: '2px 8px', borderRadius: 4, fontSize: '0.7rem', fontWeight: 600 }}>{CAT_LABELS[d.cat]}</span>
            <p style={{ color: '#94a3b8', margin: '10px 0 0', fontSize: '0.85rem' }}>{d.def}</p>
          </div>
        );
      })}
    </div>
    <StepNav back={{ page: 'dashboard', label: '← Dashboard' }} onNavigate={onNavigate} />
  </>);
}

// ── FAQ ──
const FAQ_DATA = [
  { q: "Signals conflict (e.g., HTF up, 1h dot appears during chop)", a: "Stay out. Always require 16H and 6H MFI+MACD alignment before acting on 1H signals. Higher timeframe takes priority. Wait for multi-timeframe confluence." },
  { q: "False VuManChu dots / Indicator signals", a: "Wait for candle close confirmation before acting. Require HTF + 16H/6H confirmations. Avoid trading during low-volume hours. Use volume as a confirmation filter." },
  { q: "Trading in choppy ranges", a: "Trade less frequently. Widen filters by requiring stronger HTF bias and higher MFI thresholds. Focus on S/R bounces instead of breakout strategies during chop." },
  { q: "How do I know if a trendline is valid?", a: "Needs at least 3 touch points with clear rejection wicks. Angle should be consistent — not too steep or too flat. Confirm across multiple timeframes." },
  { q: "What's the best risk/reward ratio?", a: "Minimum 1:2 for most setups. 1:1 only acceptable for 80%+ win rate setups. At 1:2, you only need 50%+ win rate to be profitable. For swing trades, aim for 1:3+." },
  { q: "What are the best trading hours for BTC?", a: "Best: 8AM-12PM EST (Europe/US overlap), 9:30AM-4PM EST (US market hours). Avoid late Friday through early Monday and 2AM-6AM EST (lowest liquidity)." },
  { q: "How much should I risk per trade?", a: "1-2% of account per trade. For $1k-$10k: 1% max. For $10k-$50k: 1-2%. For $50k+: 0.5-1.5%. Never more than 6% daily across all positions." },
  { q: "When should I move my stop loss?", a: "Never move against your position. Move to breakeven after TP1. Trail using previous swing points or MAs. Consider closing if no progress in 24-48 hours." },
  { q: "Should I use leverage?", a: "Beginners: No leverage for 6 months — learn risk management with spot first. Intermediate: 2-3x max with tight stops. Advanced: Up to 5x only on highest conviction setups." },
  { q: "My indicators aren't showing the same signals", a: "Check timeframes are synced. Verify exact indicator settings from templates. Wait for candle close before reading signals. Slight exchange variations are normal." },
  { q: "How often should I review performance?", a: "Daily: open positions. Weekly: detailed win rate and R-multiples analysis. Monthly: full strategy review. Quarterly: major adjustments based on accumulated data." },
  { q: "How long before I become profitable?", a: "Months 1-3: Learning, demo only. Months 4-6: Small live positions, focus on consistency. Months 7-12: Developing your edge. Year 2+: Consistent profitability becomes achievable." },
];

function FaqPage({ onNavigate }: { onNavigate: (p: CoursePage) => void }) {
  const [openIdx, setOpenIdx] = useState<number | null>(null);
  return (<>
    <PageHeader title="FAQ & Troubleshooting" subtitle="Common questions and solutions for trading strategies, indicators, and platform usage" />
    <div style={{ display: 'flex', flexDirection: 'column' as const, gap: 8, marginBottom: 24 }}>
      {FAQ_DATA.map((faq, i) => (
        <div key={i} style={{ ...cardStyle, cursor: 'pointer' }} onClick={() => setOpenIdx(openIdx === i ? null : i)}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <strong style={{ color: '#e2e8f0', fontSize: '0.95rem' }}>{faq.q}</strong>
            <span style={{ color: '#64748b', transition: 'transform 0.2s', transform: openIdx === i ? 'rotate(180deg)' : 'none' }}>▼</span>
          </div>
          {openIdx === i && <p style={{ color: '#94a3b8', marginTop: 12, fontSize: '0.9rem', lineHeight: 1.6 }}>{faq.a}</p>}
        </div>
      ))}
    </div>
    <div style={{ ...cardStyle, textAlign: 'center' as const, padding: 32 }}>
      <h3 style={{ marginBottom: 12 }}>Still have questions?</h3>
      <p style={{ color: '#94a3b8', marginBottom: 20 }}>Explore more resources to deepen your understanding.</p>
      <div style={{ display: 'flex', justifyContent: 'center', gap: 12, flexWrap: 'wrap' as const }}>
        <button onClick={() => onNavigate('dictionary')} style={{ ...btnStyle, background: 'transparent', border: '1px solid #00d4ff', color: '#00d4ff' }}>Trading Dictionary</button>
        <button onClick={() => onNavigate('bull-market')} style={{ ...btnStyle, background: 'transparent', border: '1px solid #16a34a', color: '#16a34a' }}>Bull Market Guide</button>
      </div>
    </div>
    <StepNav back={{ page: 'dashboard', label: '← Dashboard' }} onNavigate={onNavigate} />
  </>);
}

// ── Video Library ──
const VIDEOS = [
  { id: 'JzTMlClbM84', title: 'Step 1: Trading Fundamentals', desc: 'Essential building blocks of technical analysis and candlestick reading.' },
  { id: 'ucR2gg8v9Uo', title: 'Step 2: Professional Setup', desc: 'Build your professional TradingView workspace with proper indicators.' },
  { id: 'XeNp9drLM9s', title: 'Step 3: Market Structure', desc: 'Master market structure, trend identification, and support/resistance.' },
  { id: 'T2D0PtADAu0', title: 'Step 4: Risk Management', desc: 'Institutional-level position sizing, stop losses, and capital preservation.' },
  { id: 'F8LbNp7aUsg', title: 'Step 5: Technical Indicators', desc: 'RSI, MACD, MFI, and Stochastic RSI for precise market timing.' },
  { id: 'H7Gnh1W6VuE', title: 'Step 6: Trading Readiness', desc: 'Complete your comprehensive readiness evaluation.' },
];

function VideoLibraryPage({ onNavigate }: { onNavigate: (p: CoursePage) => void }) {
  return (<>
    <PageHeader title="Video Library" subtitle="All course videos in one place" />
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(400px, 1fr))', gap: 24, marginTop: 20 }}>
      {VIDEOS.map((v, i) => (
        <div key={i} style={{ ...cardStyle, padding: 0, overflow: 'hidden' }}>
          <div style={{ position: 'relative' as const, paddingBottom: '56.25%', height: 0 }}>
            <iframe src={`https://www.youtube.com/embed/${v.id}`} style={{ position: 'absolute' as const, top: 0, left: 0, width: '100%', height: '100%', border: 'none' }} allowFullScreen />
          </div>
          <div style={{ padding: 16 }}>
            <h3 style={{ fontSize: '0.95rem', marginBottom: 6 }}>{v.title}</h3>
            <p style={{ fontSize: '0.8rem', color: '#94a3b8', margin: 0 }}>{v.desc}</p>
          </div>
        </div>
      ))}
    </div>
    <StepNav back={{ page: 'dashboard', label: '← Dashboard' }} onNavigate={onNavigate} />
  </>);
}

// ── Main export ──
export default function MasterclassPage() {
  const [page, setPage] = useState<CoursePage>('dashboard');
  const [sidebarOpen, setSidebarOpen] = useState(false);

  const navigate = (p: CoursePage) => {
    setPage(p);
    setSidebarOpen(false);
    window.scrollTo(0, 0);
  };

  const renderPage = () => {
    switch (page) {
      case 'dashboard': return <DashboardPage onNavigate={navigate} />;
      case 'start-here': return <StartHerePage onNavigate={navigate} />;
      case 'start': return <StartHerePage onNavigate={navigate} />;
      case 'step1': return <Step1 onNavigate={navigate} />;
      case 'step2': return <Step2 onNavigate={navigate} />;
      case 'step3': return <Step3 onNavigate={navigate} />;
      case 'step4': return <Step4 onNavigate={navigate} />;
      case 'step5': return <Step5 onNavigate={navigate} />;
      case 'step6': return <Step6 onNavigate={navigate} />;
      case 'strat-trendline': return <StratTrendline onNavigate={navigate} />;
      case 'strat-mfi': return <StratMfi onNavigate={navigate} />;
      case 'strat-macro': return <StratMacro onNavigate={navigate} />;
      case 'bull-market': return <BullMarketPage onNavigate={navigate} />;
      case 'backtesting': return <BacktestingPage onNavigate={navigate} />;
      case 'resources': return <ResourcesPage onNavigate={navigate} />;
      case 'alerts': return <AlertsPage onNavigate={navigate} />;
      case 'dictionary': return <DictionaryPage onNavigate={navigate} />;
      case 'faq': return <FaqPage onNavigate={navigate} />;
      case 'video-library': return <VideoLibraryPage onNavigate={navigate} />;
      case 'videos': return <VideoLibraryPage onNavigate={navigate} />;
      default: return <DashboardPage onNavigate={navigate} />;
    }
  };

  return (
    <>
      <Head>
        <title>Nunu&apos;s Masterclass | WAGMI</title>
        <meta name="description" content="Complete trading education course — from fundamentals to advanced strategies" />
      </Head>
      <div style={{ display: 'flex', minHeight: '100vh', background: C.bg }}>
        <Sidebar page={page} onNavigate={navigate} isOpen={sidebarOpen} onToggle={() => setSidebarOpen(false)} />
        <main style={{ flex: 1, padding: '32px 40px', maxWidth: 1000 }}>
          {renderPage()}
        </main>
      </div>
      <button onClick={() => setSidebarOpen(!sidebarOpen)}
        className="mc-sidebar-toggle"
        style={{ position: 'fixed', top: 80, left: 12, zIndex: 1001, background: C.brand, color: '#fff', border: 'none', borderRadius: 8, width: 40, height: 40, cursor: 'pointer', fontSize: '1.2rem' }}>
        {sidebarOpen ? '\u00d7' : '\u2630'}
      </button>
      <style>{`
        .mc-sidebar-toggle { display: none; }
        @media (max-width: 768px) {
          .mc-sidebar-toggle { display: flex !important; align-items: center; justify-content: center; }
          main { padding: 24px 16px !important; }
        }
      `}</style>
    </>
  );
}
