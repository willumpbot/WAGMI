"""Telegram scanner: watches the owner's group chats for token contract addresses and answers with a risk card.

Runs as the OWNER's Telegram account (Telegram's official user API via Telethon), because bots cannot read
groups they were not added to. It only READS the chosen chats and only WRITES to the owner's own
"Saved Messages". It never posts in groups, never sends to anyone else, and never trades.
Invisible to other group members: it never sends read receipts (messages stay unread exactly as before) and it
re-asserts OFFLINE status every 2 minutes so the session never shows the owner as "online". The only trace is
the session in the owner's own Settings -> Devices, visible to them alone.

Setup (one time, by the owner):
  1. https://my.telegram.org -> API development tools -> create an app -> copy api_id and api_hash
  2. add to bot/.env:  TG_API_ID=12345678  and  TG_API_HASH=abcdef...
  3. in Claude Code:  ! python tools/hivemind/tg_listener.py --login      (phone number + the code Telegram sends)
  4. pick chats:      ! python tools/hivemind/tg_listener.py --chats       (lists your groups; default = all groups)
The session file lives in data/hivemind/tg/ (gitignored). It is as sensitive as a password: never share it.

While running (Task Scheduler keeps it alive):
  - any message containing a Solana or EVM contract address, or a pump.fun / dexscreener / birdeye link,
    triggers the laptop's memecard (liquidity, age, mcap, typical move, slippage, max position, fake-pool flags)
  - the card goes to Saved Messages with who posted it, in which chat, and when
  - every call is logged to data/hivemind/tg/calls.jsonl with the price at the time, so callers can later be
    graded on what their calls did (the "TG alpha engine" idea)
  - also forwards the current phone link to Saved Messages when the tunnel address changes
"""
import asyncio
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

BOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
TG = BOT / "data" / "hivemind" / "tg"
SESSION = TG / "owner"
CONF = TG / "config.json"
CALLS = TG / "calls.jsonl"
DEDUPE_S = 6 * 3600

SOL_RE = re.compile(r"(?<![1-9A-HJ-NP-Za-km-z])[1-9A-HJ-NP-Za-km-z]{32,44}(?![1-9A-HJ-NP-Za-km-z])")
EVM_RE = re.compile(r"(?<![0-9a-fA-Fx])0x[0-9a-fA-F]{40}(?![0-9a-fA-F])")
LINK_RE = re.compile(r"(?:pump\.fun/(?:coin/)?|dexscreener\.com/\w+/|birdeye\.so/token/|gmgn\.ai/\w+/token/)([1-9A-HJ-NP-Za-km-z]{32,44}|0x[0-9a-fA-F]{40})")


def _env(name):
    v = os.getenv(name)
    if v:
        return v
    try:
        for line in (BOT / ".env").read_text(encoding="utf-8").splitlines():
            if line.startswith(name + "="):
                return line.split("=", 1)[1].split("#")[0].strip().strip('"')
    except OSError:
        pass
    return None


def extract(text):
    """Contract addresses in a message. Base58 strings must mix digits and letters to avoid matching words."""
    found = []
    for m in LINK_RE.findall(text or ""):
        found.append(m)
    for m in EVM_RE.findall(text or ""):
        found.append(m)
    for m in SOL_RE.findall(text or ""):
        if any(ch.isdigit() for ch in m) and any(ch.isalpha() for ch in m) and not m.lower().startswith("http"):
            found.append(m)
    seen, out = set(), []
    for a in found:
        if a in seen or any(a != b and a in b for b in found):   # drop matches inside a longer address
            continue
        seen.add(a)
        out.append(a)
    return out


def _memecard():
    import importlib.util
    spec = importlib.util.spec_from_file_location("laptop_memecard", BOT / "data" / "laptop_mining" / "memecard.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _usd(v):
    v = float(v or 0)
    return f"${v / 1e6:.2f}M" if v >= 1e6 else f"${v / 1e3:.1f}k" if v >= 1e3 else f"${v:.0f}"


def format_card(c, chat, sender, ca):
    if not c.get("ok"):
        return f"🔎 {chat} · {sender}\n{ca}\nNot found on DexScreener (too new, dead, or not a token)."
    h = c.get("history") or {}
    flags = c.get("risk_flags") or []
    lines = [
        f"🔎 {c.get('name')} ({c.get('chain')}) · posted by {sender} in {chat}",
        f"mcap {_usd(c.get('market_cap'))} · liq {_usd(c.get('liquidity_usd'))} · vol24 {_usd(c.get('volume_24h_usd'))}",
        f"age {float(c.get('pair_age_days') or 0):.0f}d · 24h {((c.get('price_change') or {}).get('h24') or 0):+.1f}% · "
        f"typical day ±{float(c.get('expected_move_1d_pct') or h.get('daily_vol_pct') or 0):.0f}%",
        f"max position (≤2% slippage) {_usd(c.get('position_cap_usd_for_2pct_slip'))} · stop ~{float(c.get('suggested_stop_pct') or 0):.0f}%",
    ]
    if h.get("drawdown_from_ath_pct") is not None:
        lines.append(f"down {abs(h['drawdown_from_ath_pct']):.0f}% from ATH")
    if flags:
        lines.append("⚠ " + " · ".join(flags))
    lines.append(c.get("url") or "")
    lines.append(ca)
    return "\n".join(lines)


def _load_conf():
    try:
        return json.loads(CONF.read_text(encoding="utf-8"))
    except Exception:
        return {"chats": "all_groups"}


async def _client():
    from telethon import TelegramClient
    api_id, api_hash = _env("TG_API_ID"), _env("TG_API_HASH")
    if not api_id or not api_hash:
        raise SystemExit("Add TG_API_ID and TG_API_HASH to bot/.env first (from https://my.telegram.org).")
    TG.mkdir(parents=True, exist_ok=True)
    return TelegramClient(str(SESSION), int(api_id), api_hash)


async def login():
    client = await _client()
    await client.start()   # prompts for phone, code and 2FA password in the terminal
    me = await client.get_me()
    print(f"Logged in as {me.first_name} (@{me.username}). Session saved in {TG}.")
    await client.disconnect()


PENDING = TG / "pending_login.json"


async def login_start(phone):
    """Step 1 (non-interactive): ask Telegram to send a login code to the owner's Telegram app."""
    client = await _client()
    await client.connect()
    r = await client.send_code_request(phone)
    PENDING.write_text(json.dumps({"phone": phone, "hash": r.phone_code_hash}), encoding="utf-8")
    print("Code sent. Check your Telegram app (a message from 'Telegram'), then run:")
    print("  ! python tools/hivemind/tg_listener.py --code 12345")
    print("(add  --password YOURPASSWORD  if you use two-step verification)")
    await client.disconnect()


async def login_finish(code, password=None):
    """Step 2 (non-interactive): complete the login with the code (and 2FA password if set)."""
    from telethon.errors import SessionPasswordNeededError
    p = json.loads(PENDING.read_text(encoding="utf-8"))
    client = await _client()
    await client.connect()
    try:
        await client.sign_in(p["phone"], code, phone_code_hash=p["hash"])
    except SessionPasswordNeededError:
        if not password:
            print("Your account has two-step verification. Run again with:  --code " + code + " --password YOURPASSWORD")
            await client.disconnect()
            return
        await client.sign_in(password=password)
    me = await client.get_me()
    PENDING.unlink(missing_ok=True)
    print(f"Logged in as {me.first_name}. The scanner starts within 15 minutes (or now: task WAGMI-TGListener).")
    await client.disconnect()


async def list_chats():
    client = await _client()
    await client.connect()
    if not await client.is_user_authorized():
        raise SystemExit("Not logged in yet: run with --login first.")
    rows = []
    async for d in client.iter_dialogs():
        if d.is_group or d.is_channel:
            rows.append({"id": d.id, "title": d.name, "group": d.is_group})
    print(json.dumps(rows, indent=1, ensure_ascii=False))
    print("\nBy default every GROUP is watched. To limit it, write data/hivemind/tg/config.json as:")
    print('  {"chats": [<id>, <id>, ...]}')
    await client.disconnect()


async def run():
    from telethon import events
    client = await _client()
    await client.connect()
    if not await client.is_user_authorized():
        print("Not logged in: run with --login first.")
        return
    mc = _memecard()
    recent = {}
    conf = _load_conf()
    wanted = None if conf.get("chats") == "all_groups" else set(int(x) for x in conf.get("chats", []))

    @client.on(events.NewMessage(incoming=True))
    async def handler(ev):
        if not (ev.is_group or ev.is_channel):
            return
        if wanted is not None and ev.chat_id not in wanted:
            return
        cas = extract(ev.raw_text)
        if not cas:
            return
        chat = await ev.get_chat()
        sender = await ev.get_sender()
        chat_t = getattr(chat, "title", None) or str(ev.chat_id)
        snd = (getattr(sender, "username", None) and "@" + sender.username) or getattr(sender, "first_name", None) or str(ev.sender_id)
        for ca in cas[:3]:
            key = f"{ev.chat_id}|{ca}"
            if time.time() - recent.get(key, 0) < DEDUPE_S:
                continue
            recent[key] = time.time()
            try:
                card = await asyncio.get_event_loop().run_in_executor(None, mc.card, ca)
            except Exception as e:
                card = {"ok": False, "error": str(e)[:160]}
            with open(CALLS, "a", encoding="utf-8") as f:
                f.write(json.dumps({"ts": time.time(), "chat_id": ev.chat_id, "chat": chat_t, "sender_id": ev.sender_id,
                                    "sender": snd, "ca": ca, "msg": (ev.raw_text or "")[:300],
                                    "price_usd": card.get("price_usd"), "mcap": card.get("market_cap"),
                                    "liq": card.get("liquidity_usd"), "chain": card.get("chain"),
                                    "name": card.get("name"), "ok": card.get("ok")}, ensure_ascii=False) + "\n")
            await client.send_message("me", format_card(card, chat_t, snd, ca), link_preview=False)

    async def link_watch():
        import phone_link
        while True:
            try:
                r = phone_link.current_url()
                st = TG / "last_link.txt"
                old = st.read_text(encoding="utf-8") if st.exists() else ""
                if r and r != old:
                    token = (BOT / "data" / "hivemind" / "owner_token.txt").read_text(encoding="utf-8").strip()
                    await client.send_message("me", f"📈 WAGMI Terminal phone link (new tunnel address):\n{r}/t?k={token}",
                                              link_preview=False)
                    st.write_text(r, encoding="utf-8")
            except Exception:
                pass
            await asyncio.sleep(300)

    async def stay_invisible():
        """Keep the owner's account showing OFFLINE: a connected session can otherwise flip the account to
        'online' for anyone allowed to see last-seen. Messages are never marked as read (no read receipts are
        ever sent), and nothing is ever posted outside the owner's own Saved Messages."""
        from telethon.tl.functions.account import UpdateStatusRequest
        while True:
            try:
                await client(UpdateStatusRequest(offline=True))
            except Exception:
                pass
            await asyncio.sleep(120)

    client.loop.create_task(stay_invisible())
    client.loop.create_task(link_watch())
    n_groups = 0
    async for d in client.iter_dialogs():
        if (d.is_group or d.is_channel) and (wanted is None or d.id in wanted):
            n_groups += 1
    stamp = TG / "last_start.txt"
    if not stamp.exists() or time.time() - stamp.stat().st_mtime > 6 * 3600:
        await client.send_message("me", f"✅ WAGMI scanner online: watching {n_groups} groups/channels for contract "
                                        "addresses. Read-only, invisible to others. Cards will appear here.", link_preview=False)
    stamp.write_text(str(time.time()), encoding="utf-8")
    with open(TG / "listener.log", "a", encoding="utf-8") as f:
        f.write(f"{datetime.now(timezone.utc).isoformat(timespec='seconds')} listening on {n_groups} chats\n")
    print(f"{datetime.now(timezone.utc):%H:%M}Z listening ({n_groups} chats)")
    await client.run_until_disconnected()


if __name__ == "__main__":
    def _arg(flag):
        return sys.argv[sys.argv.index(flag) + 1] if flag in sys.argv and sys.argv.index(flag) + 1 < len(sys.argv) else None
    if "--phone" in sys.argv:
        asyncio.run(login_start(_arg("--phone")))
    elif "--code" in sys.argv:
        asyncio.run(login_finish(_arg("--code"), _arg("--password")))
    elif "--login" in sys.argv:
        asyncio.run(login())
    elif "--chats" in sys.argv:
        asyncio.run(list_chats())
    elif "--test" in sys.argv:
        sys.stdout.reconfigure(encoding="utf-8")
        msg = " ".join(a for a in sys.argv[1:] if a != "--test")
        cas = extract(msg)
        print("found:", cas)
        if cas:
            print(format_card(_memecard().card(cas[0]), "test-chat", "@tester", cas[0]))
    else:
        asyncio.run(run())
