"""Pre-fill the Redis cache for the Time Machine so visitors never pay quota.

Run it daily or weekly (cron). Each Time Machine list (a year + sort order) costs
one search call (100 units) plus one videos.list call (1 unit) and then serves
all 5 of its pages, so the whole Time Machine (11 years x 2 sort orders = 22
lists) is about 2,200 units and fits in a single run. Lists that are already
cached are skipped for free, and the cache entries live 7 days.

It stops at --budget units so live visitors always keep some allowance (the
daily total resets at midnight Pacific time). With --stars-pages it also looks up
the star scores for the first pages of each list, pausing between lookups to stay
under Return YouTube Dislike's 100-requests-per-minute limit.

    set -a; source .env; set +a
    python warm_cache.py --budget 6000 --stars-pages 1
"""
import argparse
import asyncio
import time
from types import SimpleNamespace

import httpx
import redis.asyncio as aioredis
from fastapi import HTTPException

import main


async def warm(budget: int, stars_pages: int) -> None:
    app = SimpleNamespace(
        state=SimpleNamespace(
            redis=aioredis.from_url(main.REDIS_URL, decode_responses=True),
            http=httpx.AsyncClient(timeout=10),
        )
    )
    lists = stars_done = 0
    try:
        for year in main.ERAS:
            for order in ("viewCount", "rating"):
                before = await main.quota_used(app)
                cached = await main.cache_get(app, main.search_cache_key("", year, order))
                if cached is None and before >= budget:
                    print(f"Stopped at {before} units used today (budget {budget}). "
                          f"Warmed {lists} new lists; run again tomorrow.")
                    return
                try:
                    videos = await main.fetch_search_results(app, "", year, order)
                except HTTPException as exc:
                    print(f"Stopped: {exc.detail}")
                    return
                if cached is None:
                    lists += 1
                for v in videos[: stars_pages * main.PAGE_SIZE]:
                    entry = await main.cache_get(app, f"ryd:{v['id']}")
                    if entry and time.time() - entry.get("at", 0) < main.RYD_FRESH:
                        continue
                    await main.fetch_ryd(app, v["id"])
                    stars_done += 1
                    await asyncio.sleep(0.75)  # about 80 lookups a minute
        print(f"Done. Warmed {lists} new lists and {stars_done} star scores; "
              f"the whole Time Machine is cached.")
    finally:
        await app.state.http.aclose()
        await app.state.redis.aclose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--budget", type=int, default=6000,
                        help="stop once today's quota use reaches this many units")
    parser.add_argument("--stars-pages", type=int, default=1,
                        help="also pre-fetch star scores for the first N pages of each "
                             "list (10 videos per page); 0 to skip")
    args = parser.parse_args()
    asyncio.run(warm(args.budget, args.stars_pages))
