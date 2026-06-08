# The Eval Index

A living leaderboard of **LLM & AI-agent evaluation and benchmark tooling** — eval frameworks,
benchmark suites, observability, and red-teaming harnesses — ranked by **momentum** (stars,
push-recency, and how fast a repo is rising) computed from live GitHub signals.

Live: https://eval-index.vercel.app

## How it works (self-updating)

A daily GitHub Action runs the pipeline and redeploys:

1. `build_data.py` — searches GitHub across several eval-ecosystem queries, dedupes, filters to
   real eval tooling (precision over recall), categorizes by what it measures, scores momentum
   → `data.json` + SEO (`sitemap.xml`, `rss.xml`, `robots.txt`, `llms.txt`).
2. `gen_details.py` — one SEO'd landing page per tool (`p/<slug>/`) with `SoftwareSourceCode`
   JSON-LD + breadcrumb.
3. `gen_og.py` — renders the Open Graph card.
4. `deploy.py` — ships the static site to Vercel via the REST API (no CLI).

Static HTML/CSS/JS, no framework. Dark "benchmark scoreboard" aesthetic
(Archivo + IBM Plex Mono, electric-lime accent, leaderboard rows).

## Run locally

```bash
GITHUB_TOKEN=... python3 build_data.py
python3 gen_details.py && python3 gen_og.py
python3 -m http.server 8080
```
