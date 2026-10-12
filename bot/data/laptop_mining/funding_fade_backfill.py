"""STEP 3: backfill hourly fundingHistory for the 140 signal coins over the study window.

Own cache (funding_cache.sqlite) -- deliberately NOT crunch/panels.sqlite, because the hourly
j5 job owns that file and its funding_hist table holds only the FIRST ~999 rows from
now-365d (Oct-Nov 2025), which does not overlap the 2026-04..2026-10 study window at all.

Throttled 0.8s/call. 500 rows per call; page forward by startTime.
"""
import json, os, sqlite3, sys, time, datetime as dt, urllib.request

API="https://api.hyperliquid.xyz/info"
CACHE=r"C:/Users/vince/WAGMI/bot/data/laptop_mining/funding_cache.sqlite"
SCR=r"C:/Users/vince/AppData/Local/Temp/claude/C--windows-System32/acf03186-eb2f-4645-840c-0730784e417f/scratchpad"
T0=int(dt.datetime(2026,4,1,tzinfo=dt.UTC).timestamp()*1000)
T1=int(dt.datetime(2026,10,12,tzinfo=dt.UTC).timestamp()*1000)

def post(body,tries=5,pause=0.8):
    last=None
    for k in range(tries):
        try:
            rq=urllib.request.Request(API,data=json.dumps(body).encode(),
                                      headers={"Content-Type":"application/json"})
            out=json.load(urllib.request.urlopen(rq,timeout=45))
            time.sleep(pause); return out
        except Exception as e:
            last=e; time.sleep(4*(k+1))
    raise RuntimeError(str(last)[:80])

con=sqlite3.connect(CACHE,timeout=60)
con.execute("PRAGMA journal_mode=WAL")
con.execute("""CREATE TABLE IF NOT EXISTS funding (
    coin TEXT NOT NULL, t INTEGER NOT NULL, rate REAL, premium REAL,
    PRIMARY KEY (coin,t)) WITHOUT ROWID""")
con.execute("""CREATE TABLE IF NOT EXISTS fetchlog (
    coin TEXT PRIMARY KEY, ok INTEGER, rows INTEGER, tmin INTEGER, tmax INTEGER, note TEXT)""")
con.commit()

coins=sorted(set(x["coin"] for x in json.load(open(os.path.join(SCR,"signals.json")))))
print("%d coins to backfill, window %s .. %s"%(len(coins),
    dt.datetime.fromtimestamp(T0/1000,dt.UTC).date(), dt.datetime.fromtimestamp(T1/1000,dt.UTC).date()),flush=True)

for n,coin in enumerate(coins,1):
    done=con.execute("SELECT ok FROM fetchlog WHERE coin=?",(coin,)).fetchone()
    if done and done[0]==1:
        continue
    rows=[]; cur=T0; calls=0; err=""
    try:
        while cur<T1 and calls<20:
            r=post({"type":"fundingHistory","coin":coin,"startTime":cur,"endTime":T1})
            calls+=1
            if not r: break
            tt=[]
            for x in r:
                try: tt.append((coin,int(x["time"]),float(x["fundingRate"]),float(x.get("premium") or 0)))
                except Exception: continue
            if not tt: break
            rows+=tt
            mx=max(x[1] for x in tt)
            if mx<=cur: break
            cur=mx+3_600_000
    except RuntimeError as e:
        err=str(e)
    if rows:
        con.executemany("INSERT OR REPLACE INTO funding (coin,t,rate,premium) VALUES (?,?,?,?)",rows)
        ts=[x[1] for x in rows]
        con.execute("INSERT OR REPLACE INTO fetchlog VALUES (?,?,?,?,?,?)",
                    (coin,0 if err else 1,len(rows),min(ts),max(ts),err))
    else:
        con.execute("INSERT OR REPLACE INTO fetchlog VALUES (?,?,?,?,?,?)",
                    (coin,0,0,None,None,err or "empty"))
    con.commit()
    if n%10==0 or err:
        print("  %3d/%d %-10s rows=%-5d calls=%-3d %s"%(n,len(coins),coin,len(rows),calls,err),flush=True)
print("DONE",flush=True)
