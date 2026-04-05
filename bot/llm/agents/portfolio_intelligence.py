"""
Portfolio-level intelligence for the LLM agent network.
Computes metrics individual trade analysis misses: concentration,
directional exposure, correlation risk, risk budget usage.
"""
import logging
from typing import Any, Dict, List

logger = logging.getLogger("bot.llm.agents.portfolio_intelligence")

# Empirical correlation matrix (from our research)
_CORR = {
    ("BTC","ETH"):0.92, ("BTC","SOL"):0.85, ("BTC","HYPE"):0.63,
    ("BTC","DOGE"):0.72, ("BTC","AVAX"):0.78, ("BTC","LINK"):0.76,
    ("ETH","SOL"):0.80, ("ETH","HYPE"):0.60, ("ETH","AVAX"):0.82,
    ("SOL","HYPE"):0.58, ("SOL","AVAX"):0.70, ("SOL","DOGE"):0.65,
}
_SECTOR = {
    "BTC":"major","ETH":"major","SOL":"alt_l1","AVAX":"alt_l1","SUI":"alt_l1",
    "HYPE":"alt","DOGE":"meme","PEPE":"meme","WIF":"meme",
    "LINK":"infra","ARB":"l2","OP":"l2",
}
MAX_EXPOSURE, MAX_SINGLE, MAX_DIR, MAX_POS = 500, 200, 400, 6


def _corr(a: str, b: str) -> float:
    return _CORR.get((a,b), _CORR.get((b,a), 0.40))

def _sym(raw: str) -> str:
    return raw.split("/")[0].split(":")[0].split("-")[0].upper()


def _parse(positions: Dict) -> List[Dict[str, Any]]:
    """Extract normalized position list from Position objects or dicts."""
    if not positions:
        return []
    result = []
    items = positions.values() if isinstance(positions, dict) else positions
    for pos in items:
        if hasattr(pos, "symbol"):  # Position dataclass
            s, sd = _sym(pos.symbol), pos.side.upper()
            n = float(pos.entry) * float(pos.qty)
            result.append({"symbol":s, "side":sd, "qty":float(pos.qty),
                           "notional":n, "upnl":float(getattr(pos,"unrealized_pnl",0))})
        elif isinstance(pos, dict):
            s = _sym(pos.get("symbol", pos.get("s","")))
            sd = pos.get("side", pos.get("sd","LONG")).upper()
            e, q = float(pos.get("entry",pos.get("e",0))), float(pos.get("qty",pos.get("q",0)))
            n = float(pos.get("notional", e*q))
            upnl = float(pos.get("unrealized_pnl", pos.get("upnl",0)))
            if s and n > 0:
                result.append({"symbol":s,"side":sd,"qty":q,"notional":n,"upnl":upnl})
    return result


def compute_portfolio_state(positions: Dict, prices: Dict, equity: float) -> Dict:
    """Compute comprehensive portfolio metrics from live position data."""
    equity = max(equity, 1.0)
    parsed = _parse(positions)
    if not parsed:
        return {"total_exposure_pct":0,"directional_bias":"flat","directional_exposure_pct":0,
                "num_positions":0,"max_single_pct":0,"correlation_risk":"NONE",
                "risk_budget_used_pct":0,"risk_budget_remaining":100,
                "sector_concentration":{},"unrealized_pnl":0.0,"positions":[],"warnings":[]}

    # Update notionals with live prices
    np_ = {_sym(k):v for k,v in (prices or {}).items()}
    for p in parsed:
        if p["symbol"] in np_ and np_[p["symbol"]] > 0:
            p["notional"] = np_[p["symbol"]] * p["qty"]

    total = sum(p["notional"] for p in parsed)
    long_n = sum(p["notional"] for p in parsed if p["side"]=="LONG")
    short_n = sum(p["notional"] for p in parsed if p["side"]=="SHORT")
    net_pct = round((long_n - short_n) / equity * 100, 1)
    exp_pct = round(total / equity * 100, 1)
    bias = "flat" if abs(net_pct)<10 else ("long" if net_pct>0 else "short")

    # Per-position details + max concentration
    details, max_single = [], 0
    for p in parsed:
        w = round(p["notional"]/total*100,1) if total else 0
        pnl = round(p["upnl"]/p["notional"]*100,2) if p["notional"] else 0
        sp = round(p["notional"]/equity*100,1)
        max_single = max(max_single, sp)
        details.append({"symbol":p["symbol"],"side":p["side"],"pnl_pct":pnl,"weight":w})

    # Sector concentration
    sectors: Dict[str,int] = {}
    for p in parsed:
        sec = _SECTOR.get(p["symbol"], "other")
        sectors[sec] = sectors.get(sec,0) + 1

    # Correlation risk: count same-direction high-corr pairs
    syms = [p["symbol"] for p in parsed]
    sides = {p["symbol"]:p["side"] for p in parsed}
    hc_pairs = [(a,b,_corr(a,b)) for i,a in enumerate(syms) for b in syms[i+1:]
                if _corr(a,b)>=0.7 and sides[a]==sides[b]]
    corr_risk = "HIGH" if len(hc_pairs)>=2 else ("MEDIUM" if hc_pairs else "LOW")

    budget_used = min(round(exp_pct/MAX_EXPOSURE*100,1), 100)
    upnl = round(sum(p["upnl"] for p in parsed), 2)

    # Warnings
    w = []
    longs = sum(1 for p in parsed if p["side"]=="LONG")
    shorts = len(parsed) - longs
    if len(parsed)>=2:
        if longs==0: w.append(f"100% directional SHORT ({shorts} pos) -- squeeze vulnerable")
        elif shorts==0: w.append(f"100% directional LONG ({longs} pos) -- dump vulnerable")
    if hc_pairs:
        ps = ", ".join(f"{a}+{b}" for a,b,_ in hc_pairs[:3])
        w.append(f"{len(hc_pairs)} correlated pair(s) ({ps} r>0.7)")
    if max_single > MAX_SINGLE*0.8:
        w.append(f"Largest position {max_single:.0f}% of equity -- concentration risk")
    if budget_used > 80:
        w.append(f"Risk budget {budget_used:.0f}% used -- limited room")
    if abs(net_pct) > MAX_DIR*0.7:
        w.append(f"Net directional {net_pct:+.0f}% -- consider hedging")

    return {"total_exposure_pct":exp_pct, "directional_bias":bias,
            "directional_exposure_pct":net_pct, "num_positions":len(parsed),
            "max_single_pct":max_single, "correlation_risk":corr_risk,
            "risk_budget_used_pct":budget_used, "risk_budget_remaining":round(100-budget_used,1),
            "sector_concentration":sectors, "unrealized_pnl":upnl,
            "positions":details, "warnings":w}


def format_portfolio_for_agent(state: Dict) -> str:
    """Format portfolio state as compact text for agent context (~100 tokens)."""
    if not state or state.get("num_positions",0)==0:
        return "PORTFOLIO: 0 positions, 100% risk budget available"
    n, exp = state["num_positions"], state["total_exposure_pct"]
    bias, net = state["directional_bias"].upper(), state["directional_exposure_pct"]
    bu = state["risk_budget_used_pct"]
    hdr = f"PORTFOLIO: {n} pos, {exp:.0f}% exposed, NET {bias} {net:+.0f}% | Risk budget: {bu:.0f}% used"
    pos = " | ".join(f"{p['symbol']} {p['side']} {p['pnl_pct']:+.1f}%({p['weight']:.0f}%)"
                     for p in state.get("positions",[]))
    lines = [hdr] + ([pos] if pos else [])
    for warn in state.get("warnings",[]):
        lines.append(f"!! {warn}")
    return "\n".join(lines)


def should_new_trade_be_allowed(state: Dict, proposed_side: str,
                                proposed_symbol: str, proposed_size_pct: float) -> Dict:
    """Pre-flight check: should a new trade be allowed given portfolio state?
    Returns {allowed, reason, size_adjustment (0-1), warnings}."""
    r = {"allowed":True, "reason":"ok", "size_adjustment":1.0, "warnings":[]}
    if not state or state.get("num_positions",0)==0:
        return r
    sym, side = _sym(proposed_symbol), proposed_side.upper()

    # Position count limit
    if state["num_positions"] >= MAX_POS:
        return {"allowed":False, "reason":f"Max {MAX_POS} positions", "size_adjustment":0, "warnings":[]}
    # Duplicate check
    for p in state.get("positions",[]):
        if p["symbol"]==sym:
            return {"allowed":False, "reason":f"Already have {sym} {p['side']}", "size_adjustment":0, "warnings":[]}

    # Risk budget
    remaining = state.get("risk_budget_remaining", 100)
    if proposed_size_pct > remaining * MAX_EXPOSURE / 100:
        adj = max(0.25, remaining/100)
        r["size_adjustment"] = round(adj,2)
        r["warnings"].append(f"Risk budget {remaining:.0f}% remaining -- sizing to {adj:.0%}")

    # Directional concentration
    net = state.get("directional_exposure_pct",0)
    adds = (side=="LONG" and net>0) or (side=="SHORT" and net<0)
    if adds and abs(net) > MAX_DIR*0.6:
        r["size_adjustment"] = min(r["size_adjustment"], 0.5)
        r["warnings"].append(f"Already {net:+.0f}% directional -- {side} adds concentration")

    # Correlation with existing same-direction positions
    existing = [p["symbol"] for p in state.get("positions",[]) if p["side"]==side]
    hc = [(s,_corr(sym,s)) for s in existing if _corr(sym,s)>=0.7]
    if hc:
        r["warnings"].append(f"Correlated: {', '.join(f'{s}(r={c:.2f})' for s,c in hc)}")
        if len(hc)>=2:
            r["size_adjustment"] = min(r["size_adjustment"], 0.5)

    if r["size_adjustment"] < 1.0:
        r["reason"] = "Allowed with size reduction"
    return r
