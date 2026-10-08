"""Export every contract-address call from the owner's chosen chats' full history (read-only).

Reads data/hivemind/tg/config.json "chats", walks each chat's whole message history oldest -> newest with the
owner's session (iter_messages never sends read receipts), and writes data/hivemind/tg/history_calls.jsonl:
one row per (message, contract address) with chat, sender, timestamp, message excerpt, and whether it was the
first time that CA appeared in that chat. Stays local (data/hivemind is gitignored): it contains other people's
messages. Run only while tg_listener is stopped, since two live connections on one session can get it revoked.
"""
import asyncio
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import tg_listener as tl

OUT = tl.TG / "history_calls.jsonl"


async def main():
    conf = tl._load_conf()
    chats = [int(x) for x in conf.get("chats", [])]
    client = await tl._client()
    await client.connect()
    if not await client.is_user_authorized():
        raise SystemExit("not logged in")
    total = 0
    with open(OUT, "w", encoding="utf-8") as f:
        for cid in chats:
            ent = await client.get_entity(cid)
            title = getattr(ent, "title", str(cid))
            seen, n_msgs, n_calls = set(), 0, 0
            senders = {}
            async for m in client.iter_messages(ent, reverse=True):
                n_msgs += 1
                cas = tl.extract(m.message or "")
                if not cas:
                    continue
                sid = m.sender_id
                if sid not in senders:
                    try:
                        s = await m.get_sender()
                        senders[sid] = (getattr(s, "username", None) and "@" + s.username) or getattr(s, "first_name", None) or str(sid)
                    except Exception:
                        senders[sid] = str(sid)
                for ca in cas[:3]:
                    f.write(json.dumps({"ts": m.date.timestamp(), "chat_id": cid, "chat": title, "msg_id": m.id,
                                        "sender_id": sid, "sender": senders[sid], "ca": ca,
                                        "first_in_chat": ca not in seen, "msg": (m.message or "")[:300]},
                                       ensure_ascii=False) + "\n")
                    seen.add(ca)
                    n_calls += 1
            total += n_calls
            print(f"{title}: {n_msgs} messages, {n_calls} CA mentions, {len(seen)} distinct CAs, {len(senders)} posters",
                  flush=True)
    await client.disconnect()
    print("total CA mentions:", total)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    t = time.time()
    asyncio.run(main())
    print(f"done in {time.time() - t:.0f}s")
