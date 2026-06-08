#!/usr/bin/env python3
"""The Eval Index — recompute the living leaderboard of LLM/agent evaluation & benchmark
tooling from live GitHub signals and write data.json + SEO (sitemap, rss, robots, llms.txt).

Scope = anything you'd reach for to MEASURE an AI system: eval frameworks (deepeval,
promptfoo, openai/evals), benchmark suites (opencompass, OSWorld, beir), LLM observability
(langfuse, opik, mlflow), and red-teaming / safety harnesses. Gathered across several GitHub
searches, deduped, FILTERED (precision over recall), categorized by what they measure, and
scored by momentum (stars, push-recency, rising-newness). Run daily by the GitHub Action.

Only the GitHub *search* payload is used, so one run is a handful of API calls.
Env: GITHUB_TOKEN (required for a usable rate limit).
"""
from __future__ import annotations

import json
import math
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
API = "https://api.github.com"
SITE_URL = "https://eval.kymatalabs.com"   # fixed to the real alias after first deploy
SITE_NAME = "The Eval Index"

QUERIES = [
    "topic:llm-evaluation stars:>5",
    "topic:llm-eval stars:>3",
    "topic:evaluation stars:>20 llm",
    "llm evaluation framework in:name,description stars:>15",
    "llm benchmark in:name,description stars:>40",
    "agent evaluation in:name,description stars:>15",
    "prompt evaluation testing in:name,description stars:>10",
    "rag evaluation in:name,description stars:>15",
    "llm observability in:name,description stars:>40",
    "red teaming llm in:name,description stars:>20",
]


def token() -> str:
    return (os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN") or "").strip()


HEADERS = {"Accept": "application/vnd.github+json", "User-Agent": "eval-index"}
if token():
    HEADERS["Authorization"] = f"Bearer {token()}"

_EVAL_TOPICS = {"llm-evaluation", "llm-eval", "evaluation", "evals", "benchmark", "benchmarks",
                "llm-observability", "red-teaming", "llm-benchmark", "model-evaluation"}
_EVAL_PHRASES = re.compile(
    r"\b(eval(uation|s)?|benchmark(ing|s)?|leaderboard|red[- ]team(ing)?|llm test(ing)?"
    r"|prompt test(ing)?|rag eval|agent eval|observability|scoring|grader|judge model)\b", re.I)
# Repos that match a phrase/topic but are NOT eval tooling.
_DENY = {"toon-format/toon", "hlaingphyoaung/sqlmap", "swisskyrepo/payloadsallthethings",
         "xnhyacinth/awesome-llm-long-context-modeling", "huggingface/aisheets",
         "genieincodebottle/generative-ai", "mac-automl/mindpipe", "modeltc/lightcompress",
         "ai-ql/tuui"}
_ANTI = re.compile(
    r"\b(object notation|serialization format|sql injection|payload(s)? all|web scraper"
    r"|chat client|desktop app|mcp client|browser extension|game engine|kubernetes"
    r"|model compression|quantization|pruning|must-read|reading list|paper list"
    r"|comprehensive resources|curriculum)\b", re.I)


def gh(url: str, *, retries: int = 4):
    last = None
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=HEADERS), timeout=30) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            last = e
            if e.code in (403, 429):
                reset = e.headers.get("X-RateLimit-Reset")
                wait = 5 * (attempt + 1)
                if reset:
                    try:
                        wait = max(wait, min(60, int(reset) - int(time.time()) + 2))
                    except ValueError:
                        pass
                print(f"  rate-limited — sleeping {wait}s", file=sys.stderr)
                time.sleep(wait)
                continue
            if 500 <= e.code < 600:
                time.sleep(3 * (attempt + 1))
                continue
            raise
        except (urllib.error.URLError, TimeoutError) as e:
            last = e
            time.sleep(3 * (attempt + 1))
    if last:
        raise last
    raise RuntimeError(f"gh failed: {url}")


def search(q: str, per_page: int = 40) -> list[dict]:
    url = (f"{API}/search/repositories?q={urllib.parse.quote(q)}"
           f"&sort=stars&order=desc&per_page={per_page}")
    try:
        return gh(url).get("items", [])
    except Exception as e:
        print(f"  query failed [{q}]: {e}", file=sys.stderr)
        return []


def is_eval(r: dict) -> bool:
    full = (r.get("full_name") or "").lower()
    if full in _DENY:
        return False
    desc = r.get("description") or ""
    if _ANTI.search(desc):
        return False
    topics = {t.lower() for t in (r.get("topics") or [])}
    if topics & _EVAL_TOPICS:
        return True
    return bool(_EVAL_PHRASES.search(f"{r.get('name','')} {desc}"))


def categorize(r: dict) -> str:
    topics = {t.lower() for t in (r.get("topics") or [])}
    blob = f"{(r.get('name') or '').lower()} {(r.get('description') or '').lower()} {' '.join(topics)}"
    if re.search(r"observability|tracing|monitor|telemetry|langfuse|logging", blob):
        return "Observability"
    if re.search(r"red[- ]?team|jailbreak|safety|adversarial|guardrail", blob):
        return "Red Teaming & Safety"
    if re.search(r"\brag\b|retrieval", blob):
        return "RAG Eval"
    if re.search(r"agent|multi-agent|tool[- ]use", blob):
        return "Agent Eval"
    if re.search(r"\bcode\b|coding|swe-?bench|programming", blob):
        return "Coding Eval"
    if re.search(r"reasoning|math|logic|mmlu|gpqa", blob):
        return "Reasoning"
    if re.search(r"benchmark|dataset|suite|leaderboard|arena", blob):
        return "Benchmarks"
    return "Eval Frameworks"


def days_since(iso: str | None) -> float | None:
    if not iso:
        return None
    try:
        return (datetime.now(timezone.utc) - datetime.fromisoformat(iso.replace("Z", "+00:00"))).total_seconds() / 86400.0
    except ValueError:
        return None


def momentum(r: dict, max_stars: int) -> int:
    stars = r.get("stargazers_count", 0) or 0
    star_norm = math.log10(stars + 1) / math.log10(max(max_stars, 10) + 1)
    pushed = days_since(r.get("pushed_at"))
    recency = 0.2 if pushed is None else max(0.0, 1.0 - max(0.0, pushed) / 180.0)
    created = days_since(r.get("created_at"))
    young = (1.0 - created / 120.0) if (created is not None and created < 120 and stars >= 20) else 0.0
    return max(1, min(100, round((0.55 * star_norm + 0.32 * recency + 0.13 * young) * 100)))


def slugify(full_name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", full_name.lower()).strip("-")


def build_items() -> list[dict]:
    seen: dict[str, dict] = {}
    for q in QUERIES:
        for r in search(q):
            full = r.get("full_name")
            if full and full not in seen and is_eval(r):
                seen[full] = r
        time.sleep(0.7)
    raw = list(seen.values())
    max_stars = max((r.get("stargazers_count", 0) or 0) for r in raw) if raw else 10
    items = []
    for r in raw:
        owner = r.get("owner") or {}
        items.append({
            "name": r.get("name", ""), "full_name": r.get("full_name", ""),
            "slug": slugify(r.get("full_name", "")), "url": r.get("html_url", ""),
            "owner": owner.get("login", ""), "owner_avatar": owner.get("avatar_url", ""),
            "stars": r.get("stargazers_count", 0) or 0, "forks": r.get("forks_count", 0) or 0,
            "open_issues": r.get("open_issues_count", 0) or 0, "language": r.get("language") or "",
            "license": ((r.get("license") or {}) or {}).get("spdx_id") or "",
            "pushed_at": r.get("pushed_at"), "created_at": r.get("created_at"),
            "description": (r.get("description") or "").strip(), "topics": r.get("topics") or [],
            "category": categorize(r), "momentum": momentum(r, max_stars),
        })
    items.sort(key=lambda x: (x["momentum"], x["stars"]), reverse=True)
    for i, it in enumerate(items, 1):
        it["rank"] = i
    return items


def write_json(items: list[dict]) -> dict:
    cats: dict[str, int] = {}
    for it in items:
        cats[it["category"]] = cats.get(it["category"], 0) + 1
    data = {"generated_at": datetime.now(timezone.utc).isoformat(), "count": len(items),
            "categories": [{"name": k, "count": v} for k, v in sorted(cats.items(), key=lambda x: -x[1])],
            "items": items}
    with open(os.path.join(HERE, "data.json"), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    return data


def write_seo(data: dict) -> None:
    items = data["items"]
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    urls = [f"  <url><loc>{SITE_URL}/</loc><lastmod>{now}</lastmod><changefreq>daily</changefreq><priority>1.0</priority></url>"]
    for it in items:
        urls.append(f"  <url><loc>{SITE_URL}/p/{it['slug']}/</loc><lastmod>{now}</lastmod>"
                    f"<changefreq>weekly</changefreq><priority>0.6</priority></url>")
    open(os.path.join(HERE, "sitemap.xml"), "w", encoding="utf-8").write(
        '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        + "\n".join(urls) + "\n</urlset>\n")
    open(os.path.join(HERE, "robots.txt"), "w", encoding="utf-8").write(
        f"User-agent: *\nAllow: /\nSitemap: {SITE_URL}/sitemap.xml\n")

    def esc(s):
        return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    rss_items = [
        f"    <item><title>{esc(it['full_name'])} — momentum {it['momentum']}</title>"
        f"<link>{SITE_URL}/p/{it['slug']}/</link><guid isPermaLink=\"false\">{esc(it['full_name'])}</guid>"
        f"<description>{esc(it['description'][:300])}</description></item>" for it in items[:30]]
    open(os.path.join(HERE, "rss.xml"), "w", encoding="utf-8").write(
        '<?xml version="1.0" encoding="UTF-8"?>\n<rss version="2.0">\n  <channel>\n'
        f"    <title>{SITE_NAME}</title>\n    <link>{SITE_URL}</link>\n"
        "    <description>The living leaderboard of LLM &amp; agent evaluation and benchmark tooling.</description>\n"
        + "\n".join(rss_items) + "\n  </channel>\n</rss>\n")

    lines = [f"# {SITE_NAME}", "",
             "> The living leaderboard of LLM and agent evaluation & benchmark tooling, ranked",
             "> daily by momentum (stars, push-recency, rising-newness) from live GitHub signals.", "",
             f"Updated: {data['generated_at']}", f"Tools indexed: {data['count']}", "",
             "## Top eval tools by momentum", ""]
    for it in items[:40]:
        lines.append(f"- [{it['full_name']}]({it['url']}) — momentum {it['momentum']}, "
                     f"⭐{it['stars']} — {it['category']} — {it['description'][:100]}")
    open(os.path.join(HERE, "llms.txt"), "w", encoding="utf-8").write("\n".join(lines) + "\n")


def main() -> int:
    if not token():
        print("WARNING: no GITHUB_TOKEN — low rate limit, partial results", file=sys.stderr)
    items = build_items()
    if not items:
        print("ERROR: no eval tools found — refusing to write empty data.json", file=sys.stderr)
        return 1
    data = write_json(items)
    write_seo(data)
    print(f"wrote data.json: {len(items)} eval tools across {len(data['categories'])} categories")
    print("  top 5:", ", ".join(f"{it['full_name']}({it['momentum']})" for it in items[:5]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
