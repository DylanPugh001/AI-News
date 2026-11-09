#!/usr/bin/env python3
"""Daily AI news digest. No AI model involved: just HN's API + RSS feeds,
keyword filtering, ranking by points, and an HTML email via Gmail SMTP.

Usage:
  python digest.py --dry-run     # writes preview.html, sends nothing
  python digest.py               # sends the email (needs env vars below)

Env vars for sending:
  GMAIL_USER          the Gmail address that sends (can be your own)
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
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from urllib.parse import urlparse

import feedparser
import requests

# ---- Config you can tweak -------------------------------------------------

HN_MIN_POINTS = 40          # ignore low-traction HN posts
HN_MAX_ITEMS = 15
LOOKBACK_HOURS = 30         # a bit over 24h so a late run never misses items

# Whole-word, case-insensitive match against titles.
KEYWORDS = [
    "AI", "LLM", "LLMs", "GPT", "ChatGPT", "OpenAI", "Anthropic", "Claude",
    "Gemini", "DeepMind", "Mistral", "Llama", "Qwen", "DeepSeek", "Grok",
    "agent", "agents", "agentic", "MCP", "RAG", "transformer", "diffusion",
    "fine-tuning", "inference", "neural", "machine learning", "Copilot",
    "Cursor", "Hugging Face", "Nvidia", "GPU", "model", "models",
]

# Official/primary sources: shown in full (latest few), no keyword filter.
FEEDS = {
    "OpenAI": "https://openai.com/news/rss.xml",
    "Google DeepMind": "https://deepmind.google/blog/rss.xml",
    "Hugging Face": "https://huggingface.co/blog/feed.xml",
    "Simon Willison": "https://simonwillison.net/atom/everything/",
    "Latent Space": "https://www.latent.space/feed",
}
FEED_MAX_PER_SOURCE = 4

# ---------------------------------------------------------------------------

UA = {"User-Agent": "ai-digest/1.0 (personal daily digest)"}
KW_RE = re.compile(
    r"(?<![\w-])(" + "|".join(re.escape(k) for k in KEYWORDS) + r")(?![\w-])",
    re.IGNORECASE,
)


def hn_stories(cutoff_ts):
    """Top HN stories mentioning AI keywords, via the Algolia search API."""
    seen, out = {}, []
    queries = ["AI", "LLM", "OpenAI", "Anthropic", "Claude", "Gemini", "GPT",
               "machine learning", "agents", "model"]
    for q in queries:
        try:
            r = requests.get(
                "https://hn.algolia.com/api/v1/search",
                params={
                    "query": q,
                    "tags": "story",
                    "numericFilters": f"created_at_i>{cutoff_ts},points>{HN_MIN_POINTS}",
                    "hitsPerPage": 40,
                },
                headers=UA, timeout=20,
            )
            r.raise_for_status()
        except Exception as e:
            print(f"[warn] HN query {q!r} failed: {e}", file=sys.stderr)
            continue
        for h in r.json().get("hits", []):
            title = h.get("title") or ""
            oid = h["objectID"]
            if oid in seen or not KW_RE.search(title):
                continue
            seen[oid] = True
            out.append({
                "title": title,
                "url": h.get("url") or f"https://news.ycombinator.com/item?id={oid}",
                "discussion": f"https://news.ycombinator.com/item?id={oid}",
                "points": h.get("points") or 0,
                "comments": h.get("num_comments") or 0,
            })
    out.sort(key=lambda s: s["points"], reverse=True)
    return out[:HN_MAX_ITEMS]


def feed_items(cutoff_ts):
    """Recent posts from each RSS/Atom source."""
    result = {}
    for name, url in FEEDS.items():
        try:
            resp = requests.get(url, headers=UA, timeout=20)
            resp.raise_for_status()
            parsed = feedparser.parse(resp.content)
        except Exception as e:
            print(f"[warn] feed {name} failed: {e}", file=sys.stderr)
            continue
        items = []
        for e in parsed.entries:
            ts = e.get("published_parsed") or e.get("updated_parsed")
            if not ts or time.mktime(ts) < cutoff_ts - 6 * 3600:
                continue  # skip old / undated
            items.append({"title": e.get("title", "(untitled)"), "url": e.get("link", "")})
        if items:
            result[name] = items[:FEED_MAX_PER_SOURCE]
    return result


def domain(url):
    return urlparse(url).netloc.removeprefix("www.")


def render(hn, feeds):
    today = datetime.now().strftime("%A, %d %B %Y")
    esc = html.escape
    parts = [
        '<div style="font-family:-apple-system,Segoe UI,Roboto,sans-serif;'
        'max-width:640px;margin:0 auto;color:#1a1a1a;line-height:1.45">',
        f'<h1 style="font-size:22px;margin:0 0 4px">AI digest</h1>'
        f'<div style="color:#777;margin-bottom:20px">{esc(today)}</div>',
    ]
    if hn:
        parts.append('<h2 style="font-size:16px;border-bottom:1px solid #ddd;'
                     'padding-bottom:4px">Hacker News</h2>')
        for s in hn:
            parts.append(
                f'<p style="margin:10px 0"><a href="{esc(s["url"])}" '
                f'style="color:#0b57d0;text-decoration:none;font-weight:600">{esc(s["title"])}</a>'
                f' <span style="color:#888;font-size:13px">({esc(domain(s["url"]))})</span><br>'
                f'<span style="color:#777;font-size:13px">{s["points"]} pts · '
                f'<a href="{esc(s["discussion"])}" style="color:#777">{s["comments"]} comments</a></span></p>'
            )
    for name, items in feeds.items():
        parts.append(f'<h2 style="font-size:16px;border-bottom:1px solid #ddd;'
                     f'padding-bottom:4px;margin-top:26px">{esc(name)}</h2>')
        for it in items:
            parts.append(
                f'<p style="margin:8px 0"><a href="{esc(it["url"])}" '
                f'style="color:#0b57d0;text-decoration:none">{esc(it["title"])}</a></p>'
            )
    if not hn and not feeds:
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
    hn, feeds = hn_stories(cutoff), feed_items(cutoff)
    body = render(hn, feeds)
    subject = f"AI digest · {datetime.now().strftime('%a %d %b')} · {len(hn)} HN + {sum(len(v) for v in feeds.values())} posts"

    if args.dry_run:
        with open("preview.html", "w") as f:
            f.write(body)
        print(f"{subject}\nWrote preview.html")
        return
    send(subject, body)
    print("Sent:", subject)


if __name__ == "__main__":
    main()
