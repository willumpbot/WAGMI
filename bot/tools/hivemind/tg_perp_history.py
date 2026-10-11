"""One-off: export $TICKER perp calls (Hyperliquid perps) from the Syndicate chat's full history, read-only.

The original history export only kept messages with contract addresses, so ticker calls like "$STRK long" were never
captured. Writes data/hivemind/tg/history_perp_calls.jsonl (local only: other people's messages). Run ONLY while
tg_listener is stopped (one Telegram connection per session). iter_messages never sends read receipts.
"""
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import tg_listener as tl

SYNDICATE = -1003904703116
OUT = tl.TG / "history_perp_calls.jsonl"


async def main():
    client = await tl._client()
    await client.connect()
    if not await client.is_user_authorized():
        raise SystemExit("not logged in")
    ent = await client.get_entity(SYNDICATE)
    n = k = 0
    senders = {}
    with open(OUT, "w", encoding="utf-8") as f:
        async for m in client.iter_messages(ent, reverse=True):
            n += 1
            sid = m.sender_id
            if "strk" in (m.message or "").lower():
                print("STRK mention:", m.date.isoformat()[:16], (m.message or "")[:120].replace(chr(10), " "), flush=True)
            if sid not in senders:
                try:
                    s = await m.get_sender()
                    senders[sid] = (getattr(s, "username", None) and "@" + s.username) or getattr(s, "first_name", None) or str(sid)
                except Exception:
                    senders[sid] = str(sid)
            pcs = tl.perp_calls(m.message or "", senders[sid])
            if not pcs:
                continue
            if sid not in senders:
                try:
                    s = await m.get_sender()
                    senders[sid] = (getattr(s, "username", None) and "@" + s.username) or getattr(s, "first_name", None) or str(sid)
                except Exception:
                    senders[sid] = str(sid)
            for tk, side in pcs:
                f.write(json.dumps({"ts": m.date.timestamp(), "chat_id": SYNDICATE, "chat": "Syndicate 2.0", "msg_id": m.id,
                                    "sender_id": sid, "sender": senders[sid], "kind": "perp", "ticker": tk, "side": side,
                                    "msg": (m.message or "")[:300]}, ensure_ascii=False) + "\n")
                k += 1
    await client.disconnect()
    print(f"{n} messages scanned, {k} perp mentions")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    asyncio.run(main())
