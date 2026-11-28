# Postcard from Mai

A little online journal: books, coffee shops, movies & series, photos and small days.

**Live at:** https://postcardfrommai.github.io

## How to post
1. Go to **app.pagescms.org** and sign in with GitHub.
2. Open this repository and pick a section (Coffee postcards, Books, Movies & series, Photos, Days).
3. Tap **Add an entry**, fill in the form, add photos, and **Save**.
4. The site updates by itself within about a minute.

## What happens to photos
Every photo is processed automatically before it appears on the site: its hidden data (GPS location, phone model, time) is removed, it is resized for the web, and a "© Postcard from Mai" watermark is added. Keep **Location tags** off in your phone's camera settings, because the original upload is also kept in this repository.

## Files
- `content/` — your entries, one file each
- `media/` — your original photo uploads
- `site/index.html` — the design
- `tools/build.py` — builds the site and processes photos
- `.pages.yml` — the posting forms
- `.github/workflows/publish.yml` — publishes the site after every change

The watermark font is Liberation Serif Italic, under the SIL Open Font License (see `tools/LiberationSerif-LICENSE.txt`).

All words and photos © Mai.
