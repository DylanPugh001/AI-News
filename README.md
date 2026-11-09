# AI-News

A free, no-AI-model daily digest of AI news, delivered to your inbox every morning at 06:00 SAST.

It pulls top AI-related stories from **Hacker News** (via the Algolia API, ranked by points) and the latest posts from **OpenAI, Google DeepMind, Hugging Face, Simon Willison and Latent Space** (via RSS), filters by keyword, and emails a clean list of linked headlines through Gmail SMTP. Runs on GitHub Actions, so there is nothing to host and no API cost.

## How it works
1. `digest.py` queries HN for stories from the last 30 hours that match AI keywords and have 40+ points (top 15 kept).
2. It adds recent posts from the RSS/Atom feeds listed in `FEEDS`.
3. It renders an HTML email and sends it with `smtplib` to `DIGEST_TO`.
4. `.github/workflows/daily.yml` triggers it daily (cron `0 4 * * *` UTC) and on manual dispatch.

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
