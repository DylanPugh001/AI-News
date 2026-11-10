# AI-News

A free, no-AI-model daily digest of AI news, delivered to your inbox every morning at 06:00 SAST.

It collects AI news from free public sources, filters by keyword, and emails a sectioned list of linked headlines through Gmail SMTP. Runs on GitHub Actions, so there is nothing to host and no API cost.

## Sections
- **Big News:** Hacker News stories about AI, ranked by points (Algolia API).
- **New Models:** newly created trending models on Hugging Face, plus r/LocalLLaMA's top posts of the day (best-effort: Reddit often rate-limits or blocks cloud IPs, in which case that part is skipped).
- **New Tools & Startups:** Show HN launches, AI products from Product Hunt, and new AI GitHub repos from the past week (topics: llm, ai-agents, generative-ai, mcp).
- **News & Blogs:** latest posts from OpenAI, Google DeepMind, Hugging Face, TechCrunch AI, The Verge AI, Simon Willison and Latent Space (RSS).

## How it works
1. `digest.py` queries each source for items from the last 30 hours (GitHub: last 7 days).
2. It renders an HTML email and sends it with `smtplib` to `DIGEST_TO`. A failing source is logged and skipped, never fatal.
3. `.github/workflows/daily.yml` triggers it daily (cron `17 4 * * *` UTC) and on manual dispatch.

## Preview locally
    python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
    .venv/bin/python digest.py --dry-run && open preview.html

## Setup
1. Enable 2-Step Verification on the sending Google account and create an App Password: https://myaccount.google.com/apppasswords
2. Add repository secrets (Settings > Secrets and variables > Actions):
   - `GMAIL_USER`: the sending Gmail address
   - `GMAIL_APP_PASSWORD`: the app password
3. Run the "Daily AI digest" workflow once from the Actions tab to test.

Notes: GitHub cron can run 5-30 minutes late, and scheduled workflows pause after 60 days without repo activity.

## Customise
Edit `KEYWORDS`, `FEEDS`, `HN_MIN_POINTS` and `HN_MAX_ITEMS` at the top of `digest.py`. Change the recipient via `DIGEST_TO` in the workflow.
