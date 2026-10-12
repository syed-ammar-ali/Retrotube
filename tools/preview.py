"""Render RetroTube templates with stub data and screenshot them in Chromium.

    YT_API_KEY=x SECRET_KEY=x python tools/preview.py [outdir] [page ...]

Run from the project root. Needs `pip install playwright` and a Chromium for it.
"""
import sys
import urllib.parse
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace as NS

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
import main  # noqa: E402

OUT = Path(sys.argv[1] if len(sys.argv) > 1 else HERE / "preview_out")
ONLY = set(sys.argv[2:])
OUT.mkdir(parents=True, exist_ok=True)
CSS_URL = (HERE / "static" / "css" / "retro.css").as_uri()
env = main.templates.env
NOW = datetime.now(timezone.utc)


def thumb(n):
    hue = (n * 47) % 360
    svg = (f"<svg xmlns='http://www.w3.org/2000/svg' width='120' height='90'>"
           f"<defs><linearGradient id='g' x1='0' y1='0' x2='1' y2='1'>"
           f"<stop offset='0' stop-color='hsl({hue},55%,45%)'/><stop offset='1' stop-color='hsl({(hue+60)%360},60%,25%)'/></linearGradient></defs>"
           f"<rect width='120' height='90' fill='url(#g)'/><polygon points='50,33 50,57 72,45' fill='white' opacity='.85'/></svg>")
    return "data:image/svg+xml," + urllib.parse.quote(svg)


TITLES = ["Evolution of Dance", "Charlie bit my finger - again !", "Lonely Island - Lazy Sunday", "Numa Numa Dance",
          "Dramatic Chipmunk", "OK Go - Here It Goes Again", "Sneezing Baby Panda", "Guitar cover: Canon in D",
          "Skate or die: 2006 reel", "Leave Britney Alone!", "David After Dentist", "Star Wars Kid Remix"]


def vid(n, year=2007, stars=4.3):
    return {
        "id": f"vid{n:08d}", "title": TITLES[n % len(TITLES)], "channel": ["judsonlaipply", "HDCYT", "nbc", "gary"][n % 4],
        "channel_id": "UC1", "description": "This is a short description of the video that goes on for a little while so we can see how wrapping works in the list view.",
        "published": f"June 1{n % 9}, {year}", "published_iso": f"{year}-06-1{n % 9}T10:00:00Z", "year": year,
        "duration": f"{n % 5:02d}:{(n * 7) % 60:02d}", "ratings": 31035 - n * 1000, "views": 1234567 * (n + 1), "thumb": thumb(n),
        "tags": ["funny", "dance", "viral"], "category_id": "23", "category": "Comedy", "stars": stars - (n % 3) * 0.6,
    }


class MockURL:
    path = "/"


class Req:
    base_url = "http://localhost:8000/"
    session = {}
    url = MockURL


USER = NS(username="bob", about="I like old videos.", joined_at=NOW - timedelta(days=400), profile_theme={"bg_color": "#CC181E"},
          bulletins=[{"body": "Welcome to my channel!", "created_at": "Oct 09, 2026"}])
comment = lambda n: NS(username=["alice", "carol", "dave"][n % 3], body="This video takes me right back. Remember when everything buffered for 10 minutes?",
                       created_at=NOW - timedelta(days=n * 3 + 1))
vids = [vid(i) for i in range(12)]
watch_video = {**vid(0), "embed_url": "about:blank", "embed_code": '<iframe width="425" height="350" src="https://www.youtube.com/embed/vid00000000" frameborder="0"></iframe>',
               "likes": 900, "dislikes": 100, "ratings_total": 1000, "community_stars": 4.6, "local_avg": 4.0, "local_count": 3,
               "user_stars": 5, "display_stars": 4.6, "is_favorite": False}


def links(labels, active, prefix="/browse?x="):
    return [{"label": l, "href": prefix + l, "active": l == active} for l in labels]


PAGES = {
    "index_anon": ("index.html", dict(user=None, videos=vids, tags=[{"name": n, "size": s} for n, s in
                   [("music", 5), ("funny", 4), ("cats", 3), ("anime", 2), ("guitar", 1), ("news", 2), ("dance", 4), ("soccer", 1), ("remix", 2)]],
                   watching=vids[:4], active_tab="home")),
    "index_user": ("index.html", dict(user=USER, videos=vids, tags=[], watching=vids[:4], active_tab="home")),
    "browse_year": ("browse.html", dict(user=None, title="t", data=dict(videos=vids[:10], page=2, total_pages=5), sort_links=links(["Most Viewed", "Top Rated", "Most Recent"], "Most Viewed"),
                    time_links=[], year_links=[], year_i=2007, cat_links=links(["All"] + [n for _, n in main.CATEGORIES], "All"), rail_years=links([str(y) for y in main.ERAS], "2007"),
                    heading="Most Viewed : (2007) : All", base="/browse?s=mp&page=", active_tab="timemachine")),
    "browse_alltime": ("browse.html", dict(user=None, title="t", data=dict(videos=vids[:10], page=1, total_pages=5), sort_links=links(["Most Viewed", "Top Rated", "Most Recent"], "Most Viewed"),
                       time_links=links(["Today", "This Week", "This Month", "All Time"], "Today"), year_links=[], year_i=None, cat_links=links(["All"] + [n for _, n in main.CATEGORIES], "All"),
                       rail_years=links([str(y) for y in main.ERAS], ""), heading="Most Viewed : (Today) : All", base="/browse?s=mp&page=", active_tab="videos")),
    "results": ("results.html", dict(user=None, q="dance", year=None, order="relevance", data=dict(videos=vids[:10], page=1, total_pages=5),
                sorts=[{"key": k, "label": v, "href": "/x"} for k, v in main.ORDERS.items()], base="/results?search_query=dance&page=", active_tab="videos")),
    "watch": ("watch.html", dict(user=USER, video=watch_video, comments=[comment(i) for i in range(4)], total_comments=4, cp=1, comment_pages=1,
              comment_base="/watch?v=x&cp=", history=vids[1:4], related=[], era_videos=vids[2:8], era_year=2007, active_tab="videos")),
    "profile": ("profile.html", dict(user=USER, target=USER, is_owner=True, wallpaper=main.wallpaper_css(USER.profile_theme), favorites=vids[:8], fav_total=8,
                fav_pages=1, fp=1, fav_base="/profile/bob?fp=", comment_count=3, rating_count=5, active_tab="channel")),
    "categories": ("categories.html", dict(user=None, categories=main.CATEGORIES, info=main.CATEGORY_INFO, active_tab="categories")),
    "channels": ("channels.html", dict(user=None, members=[NS(username=n, joined_at=NOW - timedelta(days=i * 9), about="Hi, I make videos.") for i, n in enumerate(["alice", "bob", "carol", "dave"])], active_tab="channels")),
    "register": ("auth.html", dict(user=None, mode="register", error=None, active_tab="")),
    "community": ("community.html", dict(user=None, comments=[dict(user="alice", body="Great one!", when=(NOW - timedelta(days=2)).isoformat(), video_id="vid00000001", title="Numa Numa Dance")],
                  members=["alice", "bob"], active_tab="community")),
    "timemachine": ("timemachine.html", dict(user=None, eras=main.ERAS, active_tab="timemachine")),
    "login": ("auth.html", dict(user=None, mode="login", error=None, active_tab="")),
}


def render(name):
    tpl, ctx = PAGES[name]
    html = env.get_template(tpl).render(**{"request": Req, "csrf": "tok", "q": "", **ctx})
    return html.replace("/static/css/retro.css", CSS_URL)


if __name__ == "__main__":
    from playwright.sync_api import sync_playwright
    names = [n for n in PAGES if not ONLY or n in ONLY]
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page(viewport={"width": 1000, "height": 800})
        for n in names:
            f = OUT / f"{n}.html"
            f.write_text(render(n), encoding="utf-8")
            pg.goto(f.resolve().as_uri())
            pg.screenshot(path=str(OUT / f"{n}.png"), full_page=True)
            print("shot", n)
        b.close()
