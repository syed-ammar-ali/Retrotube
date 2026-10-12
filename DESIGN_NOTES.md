# RetroTube design notes: the 2006-2007 skin

Built from 13 reference screenshots (2006 home/watch/videos/channels/categories/join,
2007 home/videos/channels/sign-in, 2008 and 2009 home). The screenshots showed four
distinct eras, not one gradual look, so RetroTube ships the **2006-07 peak** first.
Colours and sizes live in the `:root` block of `static/css/retro.css`, so a 2008 or 2009
skin can later override that block and a few layout rules.

## Deliberate differences from the original

| Original | RetroTube | Why |
|---|---|---|
| YouTube logo, "Broadcast Yourself" | Own text logo and tagline | Trademarks |
| Flash player and its controls | Official YouTube iframe, 425x350, unframed | YouTube policy forbids altering the player |
| Own hosting | YouTube Data API | The premise |
| (none) | Time Machine tab, year list in the Videos rail | The nostalgia feature (2006-2016) |
| Original category icons | Own coloured letter tiles | Original artwork |

## Measured from the screenshots

- Page 875px, white. Links #0033CC underlined. Arial 12px.
- Tabs pastel blue #BBCCEE, rounded top, active gray; search bar #CCCCCC under the tabs.
- Panels #EEEEEE with #CCCCCC header bars; sub-bar #DCDCDC; "What's New" cream box with orange heading.
- Stars red, empties gray, filled to the half star. Rating counts have no commas ("31035 ratings").
- Durations bold and zero-padded ("04:37"). Thumbnails 120x90, 1px gray frame.
- Pagination reads `Pages: 1 2 3 4 5 Next`.

## Pages

- **Home**: Videos being watched right now, Promoted Videos, Featured Videos with a tab strip; right column Login, What's New, Time Machine, tags.
- **Videos**: left rail (Browse, Time, Time Machine, Category), heading like `Most Viewed : (Today) : All`, 5-wide grid.
- **Search**: list rows with duration, tags, Added/From/Views and a ratings count.
- **Watch**: title, player, rate/links/stats box, Recent Comments band; right About This Video (URL and Embed) and Explore More Videos; narrow history column.
- **Categories**: gray 3-column panel, tile, name, blurb, tag links. **Channels**: 3-column cards. **Join/Login**: two columns.

## Not yet built

2008 (960px, orange-and-gray) and 2009 (five-column footer, Location/Language) skins; a 2005 reference is still missing.
Sort options with no data here (Most Discussed, Top Favorites, Most Linked, Most Responded) are omitted.

## How it is checked

`YT_API_KEY=x SECRET_KEY=x python tools/preview.py $PWD/preview_out` renders every page with stub
data in Chromium (`pip install playwright`). It needs no Redis, Postgres or YouTube key.
