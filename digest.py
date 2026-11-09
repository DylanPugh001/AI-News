#!/usr/bin/env python3
"""Daily AI news digest. No AI model involved: public APIs + RSS feeds,
keyword filtering, ranking by popularity, and an HTML email via Gmail SMTP.

Sections:
  Big News            Hacker News stories about AI, ranked by points
  New Models          Hugging Face trending (recently created) + r/LocalLLaMA top
  New Tools & Startups  Show HN, Product Hunt launches, new GitHub repos
  News & Blogs        OpenAI, DeepMind, HF, TechCrunch, The Verge, Simon Willison, Latent Space

Usage:
  python digest.py --dry-run     # writes preview.html, sends nothing
  python digest.py               # sends the email (needs env vars below)

Env vars for sending:
  GMAIL_USER          the Gmail address that sends
  GMAIL_APP_PASSWORD  a Gmail *app password* (not your normal password)
  DIGEST_TO           recipient, defaults to GMAIL_USER
"""
import argparse
import html
import os
import re
import smtplib
import sys
import time
from datetime import datetime, timedelta, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from urllib.parse import urlparse

import feedparser
import requests

# ---- Config you can tweak -------------------------------------------------

LOOKBACK_HOURS = 30         # a bit over 24h so a late run never misses items
HN_MIN_POINTS = 40          # Big News threshold
HN_MAX_ITEMS = 12
SHOW_HN_MIN_POINTS = 8      # Show HN threshold (launches get fewer points)
SHOW_HN_MAX_ITEMS = 8
HF_MODEL_MAX_AGE_DAYS = 21  # only list trending models created this recently
HF_MAX_ITEMS = 8
REDDIT_MAX_ITEMS = 6
PH_MAX_ITEMS = 8
GH_MAX_ITEMS = 8
GH_TOPICS = ["llm", "ai-agents", "generative-ai", "mcp"]
FEED_MAX_PER_SOURCE = 4

# Whole-word, case-insensitive match against titles (and taglines for Product Hunt).
KEYWORDS = [
    "AI", "LLM", "LLMs", "GPT", "ChatGPT", "OpenAI", "Anthropic", "Claude",
    "Gemini", "DeepMind", "Mistral", "Llama", "Qwen", "DeepSeek", "Grok",
    "agent", "agents", "agentic", "MCP", "RAG", "transformer", "diffusion",
    "fine-tuning", "inference", "neural", "machine learning", "Copilot",
    "Cursor", "Hugging Face", "Nvidia", "GPU", "model", "models",
]

# Lab/news sources: shown as latest posts, no keyword filter (already AI-focused).
FEEDS = {
    "OpenAI": "https://openai.com/news/rss.xml",
    "Google DeepMind": "https://deepmind.google/blog/rss.xml",
    "Hugging Face": "https://huggingface.co/blog/feed.xml",
    "TechCrunch AI": "https://techcrunch.com/category/artificial-intelligence/feed/",
    "The Verge AI": "https://www.theverge.com/rss/ai-artificial-intelligence/index.xml",
    "Simon Willison": "https://simonwillison.net/atom/everything/",
    "Latent Space": "https://www.latent.space/feed",
}

# ---------------------------------------------------------------------------

UA = {"User-Agent": "ai-digest/1.0 (personal daily digest)"}
KW_RE = re.compile(
    r"(?<![\w-])(" + "|".join(re.escape(k) for k in KEYWORDS) + r")(?![\w-])",
    re.IGNORECASE,
)
TAG_RE = re.compile(r"<[^>]+>")


def warn(msg):
    print(f"[warn] {msg}", file=sys.stderr)


def get(url, **kw):
    r = requests.get(url, headers=UA, timeout=20, **kw)
    r.raise_for_status()
    return r


def fresh(entry, cutoff_ts):
    """True if a feed entry was published within the lookback window."""
    ts = entry.get("published_parsed") or entry.get("updated_parsed")
    return bool(ts) and time.mktime(ts) >= cutoff_ts - 6 * 3600


def clean(text, limit=140):
    text = html.unescape(TAG_RE.sub("", text or "")).strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def domain(url):
    return urlparse(url).netloc.removeprefix("www.")


# ---- Collectors: each returns a list of {title,url,meta,sub} --------------

def hn_search(queries, tag, min_points, cutoff_ts, require_kw=True):
    seen, out = set(), []
    for q in queries:
        try:
            hits = get(
                "https://hn.algolia.com/api/v1/search",
                params={
                    "query": q, "tags": tag, "hitsPerPage": 40,
                    "numericFilters": f"created_at_i>{cutoff_ts},points>{min_points}",
                },
            ).json().get("hits", [])
        except Exception as e:
            warn(f"HN query {q!r} failed: {e}")
            continue
        for h in hits:
            title = h.get("title") or ""
            oid = h["objectID"]
            if oid in seen or (require_kw and not KW_RE.search(title)):
                continue
            seen.add(oid)
            disc = f"https://news.ycombinator.com/item?id={oid}"
            url = h.get("url") or disc
            out.append({
                "title": title, "url": url, "points": h.get("points") or 0,
                "meta": f'{h.get("points") or 0} pts · {domain(url)} · '
                        f'<a href="{disc}" style="color:#777">{h.get("num_comments") or 0} comments</a>',
                "sub": "",
            })
    out.sort(key=lambda s: s["points"], reverse=True)
    return out


def big_news(cutoff_ts):
    queries = ["AI", "LLM", "OpenAI", "Anthropic", "Claude", "Gemini", "GPT",
               "machine learning", "agents", "model"]
    return hn_search(queries, "story", HN_MIN_POINTS, cutoff_ts)[:HN_MAX_ITEMS]


def show_hn(cutoff_ts):
    queries = ["AI", "LLM", "agent", "GPT", "Claude", "MCP", "model"]
    return hn_search(queries, "show_hn", SHOW_HN_MIN_POINTS, cutoff_ts)[:SHOW_HN_MAX_ITEMS]


def hf_trending_models():
    try:
        models = get(
            "https://huggingface.co/api/models",
            params={"sort": "trendingScore", "limit": 60},
        ).json()
    except Exception as e:
        warn(f"Hugging Face models failed: {e}")
        return []
    min_created = (datetime.now(timezone.utc) - timedelta(days=HF_MODEL_MAX_AGE_DAYS)).isoformat()
    out = []
    for m in models:
        if (m.get("createdAt") or "") < min_created:
            continue
        mid = m["id"]
        out.append({
            "title": mid, "url": f"https://huggingface.co/{mid}",
            "meta": f'trending {m.get("trendingScore", 0)} · {m.get("likes", 0)} likes'
                    + (f' · {m["pipeline_tag"]}' if m.get("pipeline_tag") else ""),
            "sub": "",
        })
    return out[:HF_MAX_ITEMS]


def reddit_localllama():
    # Reddit rate-limits generic user agents and often blocks cloud IPs, so this
    # source is best-effort: one retry, then the section is simply skipped.
    url = "https://www.reddit.com/r/LocalLLaMA/top/.rss?t=day"
    headers = {"User-Agent": "python:ai-digest:v1.0 (personal daily digest)"}
    parsed = None
    for attempt in range(2):
        try:
            r = requests.get(url, headers=headers, timeout=20)
            r.raise_for_status()
            parsed = feedparser.parse(r.content)
            break
        except Exception as e:
            warn(f"Reddit attempt {attempt + 1} failed: {e}")
            time.sleep(5)
    if parsed is None:
        return []
    return [{"title": e.title, "url": e.link, "meta": "r/LocalLLaMA", "sub": ""}
            for e in parsed.entries[:REDDIT_MAX_ITEMS]]


def product_hunt(cutoff_ts):
    try:
        parsed = feedparser.parse(get("https://www.producthunt.com/feed").content)
    except Exception as e:
        warn(f"Product Hunt failed: {e}")
        return []
    out = []
    for e in parsed.entries:
        # PH summaries end with "Discussion | Link" boilerplate; drop it.
        tagline = clean(re.sub(r"\s*Discussion\s*\|\s*Link\s*$", "", clean(e.get("summary", ""), 400)))
        if not fresh(e, cutoff_ts) or not KW_RE.search(f"{e.title} {tagline}"):
            continue
        out.append({"title": e.title, "url": e.link, "meta": "", "sub": tagline})
    return out[:PH_MAX_ITEMS]


def github_new_repos():
    since = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%d")
    headers = dict(UA)
    if os.environ.get("GITHUB_TOKEN"):  # optional, raises the rate limit
        headers["Authorization"] = f"Bearer {os.environ['GITHUB_TOKEN']}"
    seen, out = set(), []
    for topic in GH_TOPICS:
        try:
            r = requests.get(
                "https://api.github.com/search/repositories",
                params={"q": f"topic:{topic} created:>{since}", "sort": "stars", "per_page": 10},
                headers=headers, timeout=20,
            )
            r.raise_for_status()
        except Exception as e:
            warn(f"GitHub topic {topic!r} failed: {e}")
            continue
        for it in r.json().get("items", []):
            if it["full_name"] in seen:
                continue
            seen.add(it["full_name"])
            out.append({
                "title": it["full_name"], "url": it["html_url"], "stars": it["stargazers_count"],
                "meta": f'★ {it["stargazers_count"]} · {it.get("language") or "n/a"} · new this week',
                "sub": clean(it.get("description") or ""),
            })
    out.sort(key=lambda x: x["stars"], reverse=True)
    return out[:GH_MAX_ITEMS]


def blog_feeds(cutoff_ts):
    """{source name: [items]} for the lab/news RSS feeds."""
    result = {}
    for name, url in FEEDS.items():
        try:
            parsed = feedparser.parse(get(url).content)
        except Exception as e:
            warn(f"feed {name} failed: {e}")
            continue
        items = [{"title": e.get("title", "(untitled)"), "url": e.get("link", ""), "meta": "", "sub": ""}
                 for e in parsed.entries if fresh(e, cutoff_ts)]
        if items:
            result[name] = items[:FEED_MAX_PER_SOURCE]
    return result


# ---- Rendering -------------------------------------------------------------

def item_html(it):
    esc = html.escape
    meta = f'<br><span style="color:#777;font-size:13px">{it["meta"]}</span>' if it["meta"] else ""
    sub = f'<br><span style="color:#555;font-size:13px">{esc(it["sub"])}</span>' if it["sub"] else ""
    return (
        f'<p style="margin:10px 0"><a href="{esc(it["url"])}" '
        f'style="color:#0b57d0;text-decoration:none;font-weight:600">{esc(it["title"])}</a>'
        f'{sub}{meta}</p>'
    )


def section(title, items_html):
    if not items_html:
        return ""
    return (f'<h2 style="font-size:17px;border-bottom:2px solid #1a1a1a;padding-bottom:4px;'
            f'margin:30px 0 8px">{html.escape(title)}</h2>{items_html}')


def render(sections, blogs):
    esc = html.escape
    today = datetime.now().strftime("%A, %d %B %Y")
    parts = [
        '<div style="font-family:-apple-system,Segoe UI,Roboto,sans-serif;'
        'max-width:640px;margin:0 auto;color:#1a1a1a;line-height:1.45">',
        f'<h1 style="font-size:22px;margin:0 0 4px">AI digest</h1>'
        f'<div style="color:#777">{esc(today)}</div>',
    ]
    for title, groups in sections:
        body = ""
        for label, items in groups:
            if not items:
                continue
            if label:
                body += f'<h3 style="font-size:13px;color:#777;text-transform:uppercase;margin:16px 0 0">{esc(label)}</h3>'
            body += "".join(item_html(i) for i in items)
        parts.append(section(title, body))
    blog_body = ""
    for name, items in blogs.items():
        blog_body += f'<h3 style="font-size:13px;color:#777;text-transform:uppercase;margin:16px 0 0">{esc(name)}</h3>'
        blog_body += "".join(
            f'<p style="margin:6px 0"><a href="{esc(i["url"])}" style="color:#0b57d0;text-decoration:none">{esc(i["title"])}</a></p>'
            for i in items)
    parts.append(section("News & Blogs", blog_body))
    if len(parts) == 2:
        parts.append("<p>Nothing found today (or every source failed).</p>")
    parts.append("</div>")
    return "".join(parts)


def send(subject, body_html):
    user = os.environ["GMAIL_USER"]
    pw = os.environ["GMAIL_APP_PASSWORD"]
    to = os.environ.get("DIGEST_TO", user)
    msg = MIMEMultipart("alternative")
    msg["Subject"], msg["From"], msg["To"] = subject, user, to
    msg.attach(MIMEText("Open this email in an HTML-capable client.", "plain"))
    msg.attach(MIMEText(body_html, "html"))
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s:
        s.login(user, pw)
        s.sendmail(user, [to], msg.as_string())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="write preview.html, don't send")
    args = ap.parse_args()

    cutoff = int(datetime.now(timezone.utc).timestamp()) - LOOKBACK_HOURS * 3600
    news = big_news(cutoff)
    models = hf_trending_models()
    local = reddit_localllama()
    launches = show_hn(cutoff)
    ph = product_hunt(cutoff)
    gh = github_new_repos()
    blogs = blog_feeds(cutoff)

    sections = [
        ("Big News", [("", news)]),
        ("New Models", [("Hugging Face trending (new)", models), ("r/LocalLLaMA today", local)]),
        ("New Tools & Startups", [("Show HN", launches), ("Product Hunt", ph), ("New GitHub repos", gh)]),
    ]
    body = render(sections, blogs)
    total = len(news) + len(models) + len(local) + len(launches) + len(ph) + len(gh) \
        + sum(len(v) for v in blogs.values())
    subject = f"AI digest · {datetime.now().strftime('%a %d %b')} · {total} items"

    if args.dry_run:
        with open("preview.html", "w") as f:
            f.write(body)
        print(f"{subject}\nnews={len(news)} models={len(models)} localllama={len(local)} "
              f"showhn={len(launches)} ph={len(ph)} gh={len(gh)} blogs={ {k: len(v) for k, v in blogs.items()} }")
        print("Wrote preview.html")
        return
    send(subject, body)
    print("Sent:", subject)


if __name__ == "__main__":
    main()
