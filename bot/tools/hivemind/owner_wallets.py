"""The owner's OWN wallets as graded data (owner 10-15: "i relayed addresses ... both of you go hard"; his real trades are
the labels for the M28 policy map). Public, read-only chain data; addresses are PUBLIC keys only - never keys/seeds.

Config: data/hivemind/owner_wallets/wallets.json  {"solana": ["<pubkey>", ...], "hyperliquid": ["0x...", ...]}
(data/hivemind/ is gitignored: the addresses never reach the public repo).

Solana (public RPC, paced): every transaction signature for the wallet, newest-first, incremental via the newest
signature already stored. Each transaction is reduced to the wallet's balance changes: SOL (native + wSOL), USDC/USDT,
and every other mint. A row with one non-quote mint moving opposite to SOL/USD is a swap:
  swaps.jsonl  {sig, ts, wallet, mint, token_delta, sol_delta, usd_delta, fee_sol, kind: buy|sell|transfer|other}
Round trips per mint (FIFO in SOL) -> trades.json: entry/exit times, SOL in/out, PnL in SOL, hold hours, still held.
Hyperliquid (Axiom perps run on HL): userFillsByTime pages back to the start, userFunding -> hl_fills.jsonl.
"""
import json
import sys
import time
import urllib.request
from pathlib import Path

BOT = Path(__file__).resolve().parents[2]
OUT = BOT / "data" / "hivemind" / "owner_wallets"
CFG = OUT / "wallets.json"
RPC = "https://api.mainnet-beta.solana.com"
WSOL = "So11111111111111111111111111111111111111112"
USD = {"EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v": "USDC", "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB": "USDT"}
PACE = 0.25
LOCK = OUT / ".lock"


def _rpc(method, params, tries=6):
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode()
    for i in range(tries):
        try:
            req = urllib.request.Request(RPC, data=body, headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=40) as r:
                out = json.loads(r.read())
            if "error" in out:
                raise RuntimeError(str(out["error"])[:200])
            return out["result"]
        except Exception:
            if i == tries - 1:
                raise
            time.sleep(2 * (i + 1))


def _signatures(wallet, stop_at=None, cap=20000):
    sigs, before = [], None
    while len(sigs) < cap:
        p = {"limit": 1000}
        if before:
            p["before"] = before
        page = _rpc("getSignaturesForAddress", [wallet, p]) or []
        if not page:
            break
        for s in page:
            if s["signature"] == stop_at:
                return sigs
            sigs.append(s)
        before = page[-1]["signature"]
        time.sleep(PACE)
    return sigs


def _reduce(wallet, tx):
    m = tx.get("meta") or {}
    keys = [(k["pubkey"] if isinstance(k, dict) else k) for k in tx["transaction"]["message"]["accountKeys"]]
    sol = 0.0
    if wallet in keys:
        i = keys.index(wallet)
        sol = (m["postBalances"][i] - m["preBalances"][i]) / 1e9
    toks = {}
    for side, sg in (("preTokenBalances", -1), ("postTokenBalances", 1)):
        for b in m.get(side) or []:
            if b.get("owner") != wallet:
                continue
            amt = float((b.get("uiTokenAmount") or {}).get("uiAmount") or 0)
            toks[b["mint"]] = toks.get(b["mint"], 0.0) + sg * amt
    fee = (m.get("fee") or 0) / 1e9 if keys and keys[0] == wallet else 0.0
    sol_d = sol + toks.pop(WSOL, 0.0) + fee          # trade value excluding the network fee
    usd_d = sum(toks.pop(k, 0.0) for k in list(USD) if k in toks)
    others = {k: v for k, v in toks.items() if abs(v) > 1e-12}
    rows = []
    for mint, d in others.items():
        quote = sol_d if abs(sol_d) > 1e-6 else 0.0
        kind = ("buy" if d > 0 and (quote < 0 or usd_d < 0) else
                "sell" if d < 0 and (quote > 0 or usd_d > 0) else "transfer")
        rows.append({"mint": mint, "token_delta": d, "sol_delta": round(sol_d, 9) if len(others) == 1 else None,
                     "usd_delta": round(usd_d, 6) if len(others) == 1 else None, "fee_sol": fee, "kind": kind})
    if not rows and abs(sol_d) > 1e-6:
        rows.append({"mint": None, "token_delta": 0, "sol_delta": round(sol_d, 9), "usd_delta": round(usd_d, 6),
                     "fee_sol": fee, "kind": "sol_move"})
    return rows


def solana(wallet):
    path = OUT / "swaps.jsonl"
    have = set()
    newest = None
    if path.exists():
        for l in path.read_text(encoding="utf-8").splitlines():
            try:
                o = json.loads(l)
            except ValueError:
                continue
            if o.get("wallet") == wallet:
                have.add(o["sig"])
    st_p = OUT / "state.json"
    st = json.loads(st_p.read_text(encoding="utf-8")) if st_p.exists() else {}
    newest = st.get(wallet)
    sigs = [s for s in _signatures(wallet, stop_at=newest) if not s.get("err") and s["signature"] not in have]
    n = 0
    with open(path, "a", encoding="utf-8") as f:
        for s in reversed(sigs):                          # oldest first, so a crash resumes cleanly
            try:
                tx = _rpc("getTransaction", [s["signature"], {"encoding": "jsonParsed",
                                                              "maxSupportedTransactionVersion": 0}])
            except Exception:
                time.sleep(PACE * 4)
                continue
            if tx:
                for r in _reduce(wallet, tx):
                    f.write(json.dumps(dict(r, sig=s["signature"], ts=s.get("blockTime") or tx.get("blockTime"),
                                            wallet=wallet)) + "\n")
                n += 1
            time.sleep(PACE)
    if sigs:
        st[wallet] = sigs[0]["signature"]
        st_p.write_text(json.dumps(st), encoding="utf-8")
    return {"wallet": wallet[:6], "new_tx": n, "sigs_seen": len(sigs)}


def round_trips():
    """FIFO per (wallet, mint) in SOL: one trade = from flat to flat again (or still held)."""
    rows = []
    p = OUT / "swaps.jsonl"
    if p.exists():
        for l in p.read_text(encoding="utf-8").splitlines():
            try:
                o = json.loads(l)
            except ValueError:
                continue
            if o.get("kind") in ("buy", "sell") and o.get("sol_delta") is not None:
                rows.append(o)
    rows.sort(key=lambda r: r.get("ts") or 0)
    open_, trades = {}, []
    for r in rows:
        k = (r["wallet"], r["mint"])
        t = open_.setdefault(k, {"wallet": r["wallet"], "mint": r["mint"], "first": r["ts"], "qty": 0.0,
                                 "sol_in": 0.0, "sol_out": 0.0, "buys": 0, "sells": 0})
        if r["kind"] == "buy":
            t["qty"] += r["token_delta"]; t["sol_in"] += -r["sol_delta"]; t["buys"] += 1
        else:
            t["qty"] += r["token_delta"]; t["sol_out"] += r["sol_delta"]; t["sells"] += 1
        t["last"] = r["ts"]
        if t["sells"] and t["qty"] <= max(1e-9, 0.001 * abs(r["token_delta"])):
            trades.append(dict(t, closed=True, pnl_sol=round(t["sol_out"] - t["sol_in"], 6),
                               hold_h=round(((t["last"] or 0) - (t["first"] or 0)) / 3600, 2)))
            del open_[k]
    for t in open_.values():
        trades.append(dict(t, closed=False, pnl_sol=None, realized_sol=round(t["sol_out"] - t["sol_in"], 6),
                           hold_h=round((time.time() - (t["first"] or time.time())) / 3600, 2)))
    closed = [t for t in trades if t["closed"]]
    summ = {"updated": time.time(), "trades": len(trades), "closed": len(closed),
            "win_rate": round(sum(t["pnl_sol"] > 0 for t in closed) / len(closed), 3) if closed else None,
            "pnl_sol": round(sum(t["pnl_sol"] for t in closed), 4) if closed else None}
    (OUT / "trades.json").write_text(json.dumps({"summary": summ, "trades": trades}), encoding="utf-8")
    return summ


def hyperliquid(addr):
    import hl
    path = OUT / "hl_fills.jsonl"
    have = set()
    if path.exists():
        for l in path.read_text(encoding="utf-8").splitlines():
            try:
                o = json.loads(l)
                have.add((o.get("user"), o.get("tid")))
            except ValueError:
                pass
    start, n = 0, 0
    with open(path, "a", encoding="utf-8") as f:
        while True:
            fills = hl.post({"type": "userFillsByTime", "user": addr, "startTime": start, "aggregateByTime": False},
                            ttl=1) or []
            if not fills:
                break
            for x in fills:
                if (addr, x.get("tid")) not in have:
                    f.write(json.dumps(dict(x, user=addr)) + "\n"); n += 1
                    have.add((addr, x.get("tid")))
            last = max(int(x["time"]) for x in fills)
            if len(fills) < 2000 or last + 1 <= start:
                break
            start = last + 1
    fund = hl.post({"type": "userFunding", "user": addr, "startTime": 0}, ttl=1) or []
    (OUT / f"hl_funding_{addr[:8]}.json").write_text(json.dumps(fund), encoding="utf-8")
    return {"hl": addr[:8], "new_fills": n, "funding_rows": len(fund)}


def run():
    if not CFG.exists():
        return {"skipped": "no wallets.json"}
    cfg = json.loads(CFG.read_text(encoding="utf-8"))
    out = []
    for w in cfg.get("solana", []):
        try:
            out.append(solana(w))
        except Exception as e:
            out.append({"wallet": w[:6], "error": str(e)[:160]})
    for a in cfg.get("hyperliquid", []):
        try:
            out.append(hyperliquid(a))
        except Exception as e:
            out.append({"hl": a[:8], "error": str(e)[:160]})
    out.append(round_trips())
    with open(OUT / "runs.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps({"ts": time.time(), "out": out}) + "\n")
    return out


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    OUT.mkdir(parents=True, exist_ok=True)
    try:
        print(json.dumps(run(), indent=1))
    finally:
        try:
            LOCK.unlink()
        except OSError:
            pass
