# daily-finance-digest

Emails the top 10 financial news headlines every weekday morning.
Runs on GitHub Actions — no server needed.

## How it works

1. GitHub Actions cron triggers the workflow at 07:00 UTC, Mon–Fri.
2. The workflow runs `python -m daily_finance_digest`.
3. The script fetches headlines from [NewsAPI.org](https://newsapi.org/)
   and emails them via Gmail SMTP.

## Local development

```bash
uv sync              # install dependencies from uv.lock
cp .env.example .env # then fill in real values
uv run python -m daily_finance_digest
```

## Required secrets

Set these as GitHub repo secrets (Settings -> Secrets and variables -> Actions):

| Secret | What it is |
|---|---|
| `NEWS_API_KEY` | Free API key from newsapi.org |
| `GMAIL_USER` | Your Gmail address |
| `GMAIL_APP_PASSWORD` | 16-char Gmail App Password (not your login password!) |
| `RECIPIENT_EMAIL` | Where to send the digest |
| `ANTHROPIC_API_KEY` | *(optional)* Claude API key. If set, the email is prefixed with a 3-bullet AI summary of today's themes. |
