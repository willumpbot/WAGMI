"""Full human-simulation test suite.

Tests every TG button + command path by calling the underlying
Python functions directly. Reports PASS/FAIL per test + full
summary at end. Run: python tests/e2e_sim.py
"""
import sys
import urllib.request
from pathlib import Path

from memegine.config import settings
from memegine import (
    projects, reference_lib, x_fetch, reply_for, flow_post,
    grok_prompts, spongify, kilroy_compositor, brand as brand_mod,
    format_suggest, raid_parser, ops_db,
)

results = []


def T(name, ok, detail=""):
    results.append((name, ok, detail))
    status = "PASS" if ok else "FAIL"
    mark = "[OK]" if ok else "[!! ]"
    print(f"  {mark} {name}  {detail if not ok else ''}")


def section(title):
    print(f"\n=== {title} ===")


# Fixture
section("FIXTURE")
TWEET_URL = "https://x.com/tryfomo/status/2014745660193493069"
td = x_fetch.fetch(TWEET_URL, use_cache=False)
T("fetch tweet via syndication", td is not None)
if not td:
    print("FATAL: cant fetch, abort")
    sys.exit(1)
projects.set_active("kilroy")
settings.refresh_project("kilroy")
ops_db.tweet_upsert(
    id=td.id, handle=td.author_handle, text=td.text,
    created_at=td.created_at, favorite_count=td.favorite_count,
    reply_count=td.reply_count, payload=td.as_dict(),
)
t_dict = ops_db.tweets_recent(limit=1, handle=td.author_handle)[0]

# Test 1: raid syntax parser
section("TEST 1: raid syntax parser")
cases = [
    (f"{TWEET_URL}", False, "bare url"),
    (f"{TWEET_URL} raid kilroy", True, "raid kilroy"),
    (f"{TWEET_URL} spongify", True, "spongify"),
    (f"{TWEET_URL} motion video + caption", True, "motion video + caption"),
    (f"{TWEET_URL} kilroy", True, "brand only"),
]
for text, should, desc in cases:
    cmd = raid_parser.parse_and_normalize(text, default_brand="kilroy")
    T(f"parse [{desc}]", cmd.is_raid_command == should,
      f"is_raid={cmd.is_raid_command} want={should}")

# Test 2: reply plans per brand
section("TEST 2: reply plans per brand")
for brand in ("kilroy", "motion", "spong"):
    projects.set_active(brand)
    settings.refresh_project(brand)
    plan = reply_for.plan(TWEET_URL, generate_brief=False, open_browser=False)
    T(f"{brand}: plan returns", plan is not None)
    if plan:
        T(f"{brand}: has format matches", len(plan.format_matches) > 0,
          f"got {len(plan.format_matches)}")
        top = plan.format_matches[0].slug_or_id if plan.format_matches else ""
        T(f"{brand}: top format is brand-scoped",
          top.startswith(brand), f"top={top}")

# Test 3: Library refs
section("TEST 3: library refs")
for brand in ("motion", "spong", "kilroy"):
    projects.set_active(brand)
    settings.refresh_project(brand)
    entries = reference_lib.search()
    expect_empty = brand == "kilroy"
    T(f"{brand}: library has entries",
      len(entries) > 0 if not expect_empty else True,
      f"count={len(entries)}")
    if entries:
        plan = reply_for.plan(TWEET_URL, generate_brief=False,
                              open_browser=False)
        if plan:
            refs = plan.ref_matches
            T(f"{brand}: reply_for returns refs", len(refs) > 0,
              f"refs={len(refs)}")
            bad = 0
            for r in refs[:3]:
                if r.media_path and not Path(str(r.media_path)).exists():
                    bad += 1
            T(f"{brand}: ref paths exist", bad == 0, f"missing={bad}")

# Test 4: Make image
section("TEST 4: Make image prompts")
for brand in ("kilroy", "motion", "spong"):
    projects.set_active(brand)
    settings.refresh_project(brand)
    intent = f'reply to @{td.author_handle}: "{td.text[:120]}"'
    slug = flow_post._pick_format(intent, kind="image")
    T(f"{brand}: format slug", bool(slug), f"slug={slug}")
    try:
        prompt = grok_prompts.build(slug, target_tweet=t_dict)
        T(f"{brand}: grok prompt",
          bool(prompt) and 100 < len(prompt) < 3000,
          f"len={len(prompt)}")
    except Exception as e:
        T(f"{brand}: grok prompt", False, f"{type(e).__name__}: {e}")

# Test 5: Make video
section("TEST 5: Make video prompts")
for brand in ("kilroy", "motion", "spong"):
    projects.set_active(brand)
    settings.refresh_project(brand)
    slug = flow_post._pick_video_format(intent)
    try:
        prompt = grok_prompts.build(slug, target_tweet=t_dict)
        T(f"{brand}: video prompt", bool(prompt) and len(prompt) > 100,
          f"slug={slug} len={len(prompt)}")
    except Exception as e:
        T(f"{brand}: video prompt", False, f"{type(e).__name__}: {e}")

# Test 6: Raid pack
section("TEST 6: 5-asset raid pack")
for brand in ("kilroy", "motion", "spong"):
    projects.set_active(brand)
    settings.refresh_project(brand)
    try:
        result = flow_post.raid(td.text[:200], copy_clipboard=False)
        T(f"{brand}: raid pack", len(result.briefs) >= 3,
          f"briefs={len(result.briefs)}")
    except Exception as e:
        T(f"{brand}: raid pack", False, f"{type(e).__name__}: {e}")

# Test 7: Spongify pfp
section("TEST 7: Spongify")
projects.set_active("kilroy")
settings.refresh_project("kilroy")
try:
    batch = spongify.spongify_handles([td.author_handle])
    T("spongify: pfp resolved", len(batch.targets) > 0,
      f"targets={len(batch.targets)} fails={len(batch.failures)}")
    if batch.targets:
        tgt = batch.targets[0]
        T("spongify: pfp file", Path(tgt.local_pfp_path).exists(),
          str(tgt.local_pfp_path))
        T("spongify: prompt",
          "spongmonkey" in tgt.prompt.lower() and "fur" in tgt.prompt.lower())
except Exception as e:
    T("spongify", False, f"{type(e).__name__}: {e}")

# Test 8: Kilroy pfp transform
section("TEST 8: Kilroy their pfp (compositor)")
try:
    pfp_url = (t_dict.get("author_profile_image_url")
               or spongify._profile_pic_url(td.author_handle))
    T("kpfp: pfp url found", bool(pfp_url))
    if pfp_url:
        req = urllib.request.Request(pfp_url,
                                     headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=15) as r:
            pfp_bytes = r.read()
        T("kpfp: pfp downloaded", len(pfp_bytes) > 1000,
          f"{len(pfp_bytes)} bytes")
        result = kilroy_compositor.kilroy_onto(
            pfp_bytes, position="bottom-right", size_pct=0.32,
            text=f"@{td.author_handle.upper()} WAS HERE",
        )
        T("kpfp: composite",
          result.image_bytes is not None and len(result.image_bytes) > 1000,
          f"{len(result.image_bytes)} bytes mode={result.mode}")
except Exception as e:
    T("kpfp", False, f"{type(e).__name__}: {e}")

# Test 9: Caption
section("TEST 9: Caption")
for brand in ("kilroy", "motion", "spong"):
    projects.set_active(brand)
    settings.refresh_project(brand)
    plate = brand_mod.current_plate()
    T(f"{brand}: brand plate",
      plate is not None and bool(plate.tagline),
      f"tagline={plate.tagline[:40]}")

# Test 10: /gallery
section("TEST 10: /gallery logic")
for brand in ("motion", "spong"):
    projects.set_active(brand)
    settings.refresh_project(brand)
    entries = reference_lib.recent(5)
    T(f"/gallery {brand}: entries", len(entries) > 0, f"count={len(entries)}")
    if entries:
        e = entries[0]
        path = e.get("path") or (settings.references_dir /
                                  e.get("filename", ""))
        T(f"/gallery {brand}: path exists",
          Path(str(path)).exists(), str(path)[-50:])
projects.set_active("motion")
settings.refresh_project("motion")
all_motion = reference_lib.search()
wildlife = [e for e in all_motion
            if "wildlife" in [t.lower() for t in e.get("tags", [])]]
T("/gallery motion wildlife", len(wildlife) > 0, f"count={len(wildlife)}")
wealth = [e for e in all_motion
          if "wealth" in [t.lower() for t in e.get("tags", [])]]
T("/gallery motion wealth", len(wealth) > 0, f"count={len(wealth)}")

# Test 11: expansion
section("TEST 11: topic expansion")
tests = [
    ("cope", ["trader"]),
    ("pump", ["wealth", "flex"]),
    ("apex", ["predator", "wildlife"]),
    ("rug", ["cope"]),
    ("bag", ["cash"]),
]
for term, must in tests:
    kw = reply_for._keywords(f"{term} is real")
    has_all = all(t in kw for t in must)
    T(f"'{term}' expands", has_all, f"got={kw[:6]}")

# Test 12: video paths
section("TEST 12: video paths")
mv = Path(r"C:\Users\vince\WAGMI\memegine-inbox\drive-folder\MOTION")
T("motion videos exist",
  mv.exists() and sum(1 for _ in mv.glob("*.MOV")) > 0)
if mv.exists():
    vc = sum(1 for f in mv.iterdir()
             if f.suffix.lower() in (".mov", ".mp4"))
    T("motion: 40+ videos", vc >= 40, f"count={vc}")
sv = Path(r"C:\Users\vince\WAGMI\memegine\data\projects\spong\videos\GF0SQC.mp4")
T("spong video exists",
  sv.exists() and sv.stat().st_size > 100_000,
  f"size={sv.stat().st_size if sv.exists() else 0}")

# Test 13: ops_db (reset to kilroy where watchlist was seeded)
section("TEST 13: ops_db (kilroy)")
projects.set_active("kilroy")
settings.refresh_project("kilroy")
T("watchlist populated", len(ops_db.watchlist_list()) > 10,
  f"count={len(ops_db.watchlist_list())}")
T("tweets in cache", len(ops_db.tweets_recent(limit=5)) > 0)

# summary
print(f"\n{'=' * 50}")
passed = sum(1 for _, ok, _ in results if ok)
failed = sum(1 for _, ok, _ in results if not ok)
print(f"{passed}/{len(results)} PASSED · {failed} FAILED")
print("=" * 50)
if failed:
    print("\nFAILURES:")
    for name, ok, detail in results:
        if not ok:
            print(f"  [!!] {name}  {detail}")
sys.exit(0 if failed == 0 else 1)
