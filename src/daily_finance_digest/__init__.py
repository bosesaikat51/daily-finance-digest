"""Daily finance digest: fetch top financial headlines and email them."""

from __future__ import annotations

import html
import os
import smtplib
import sys
from datetime import datetime, timezone
from email.message import EmailMessage

import anthropic
import requests
from dotenv import load_dotenv

NEWS_API_URL = "https://newsapi.org/v2/top-headlines"
SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 465  # SSL port
SUMMARY_MODEL = "claude-haiku-4-5"


def fetch_headlines(api_key: str, limit: int = 10) -> list[dict]:
    """Fetch top business headlines from NewsAPI.

    Uses category=business which aggregates financial/market news from
    major outlets. `pageSize` caps results; NewsAPI free tier allows up to 100.
    """
    resp = requests.get(
        NEWS_API_URL,
        params={
            "category": "business",
            "language": "en",
            "pageSize": limit,
            "apiKey": api_key,
        },
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()
    if data.get("status") != "ok":
        raise RuntimeError(f"NewsAPI error: {data}")
    return data["articles"]


def summarize_headlines(articles: list[dict], api_key: str) -> list[str]:
    """Ask Claude for 3 bullets describing today's key themes.

    Returns an empty list on any failure — the caller falls back to the
    plain digest so a Claude outage never blocks the email.
    """
    headlines = "\n".join(
        f"- {a.get('title') or ''} ({(a.get('source') or {}).get('name') or ''}): "
        f"{a.get('description') or ''}"
        for a in articles
    )
    system = (
        "You are a financial news editor writing a concise daily brief. "
        "Given a list of business headlines, identify the 3 most important "
        "themes or stories. Output exactly 3 bullet points, one per line, "
        "each starting with '- '. Each bullet is a single plain-text "
        "sentence — no markdown, no headline quoting, no preamble."
    )
    try:
        client = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model=SUMMARY_MODEL,
            max_tokens=500,
            system=system,
            messages=[{"role": "user", "content": f"Today's headlines:\n{headlines}"}],
        )
        text = next((b.text for b in response.content if b.type == "text"), "")
        return [
            line.lstrip("-• ").strip()
            for line in text.splitlines()
            if line.strip().startswith(("-", "•"))
        ]
    except Exception as e:
        print(f"Summary generation failed: {e}", file=sys.stderr)
        return []


def format_summary_html(bullets: list[str]) -> str:
    if not bullets:
        return ""
    items = "".join(f"<li>{html.escape(b)}</li>" for b in bullets)
    return (
        '<div style="background:#f6f8fa;padding:12px 16px;border-radius:6px;'
        'margin-bottom:16px;">'
        "<h3 style=\"margin:0 0 8px 0;\">Today's key themes</h3>"
        f'<ul style="margin:0;padding-left:20px;">{items}</ul></div>'
    )


def format_html(articles: list[dict], summary_html: str = "") -> str:
    """Render headlines as a simple HTML email body."""
    today = datetime.now(timezone.utc).strftime("%A, %d %B %Y")
    items = []
    for art in articles:
        title = art.get("title") or "(no title)"
        url = art.get("url") or "#"
        source = (art.get("source") or {}).get("name") or "unknown"
        desc = art.get("description") or ""
        items.append(
            f'<li style="margin-bottom:12px;">'
            f'<a href="{url}"><b>{title}</b></a><br>'
            f'<small>{source}</small><br>'
            f'<span>{desc}</span></li>'
        )
    return (
        f"<html><body>"
        f"<h2>Daily Finance Digest — {today}</h2>"
        f"{summary_html}"
        f"<ol>{''.join(items)}</ol>"
        f"<hr><small>Automated by GitHub Actions.</small>"
        f"</body></html>"
    )


def send_email(
    *, sender: str, password: str, recipient: str, subject: str, html: str
) -> None:
    """Send an HTML email via Gmail SMTP over SSL."""
    msg = EmailMessage()
    msg["From"] = sender
    msg["To"] = recipient
    msg["Subject"] = subject
    msg.set_content("Your email client does not support HTML. See HTML version.")
    msg.add_alternative(html, subtype="html")

    with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT) as server:
        server.login(sender, password)
        server.send_message(msg)


def main() -> int:
    load_dotenv()  # reads .env locally; no-op on GitHub Actions

    try:
        api_key = os.environ["NEWS_API_KEY"]
        sender = os.environ["GMAIL_USER"]
        password = os.environ["GMAIL_APP_PASSWORD"]
        recipient = os.environ["RECIPIENT_EMAIL"]
    except KeyError as e:
        print(f"Missing required env var: {e}", file=sys.stderr)
        return 1

    articles = fetch_headlines(api_key)
    if not articles:
        print("No articles returned.", file=sys.stderr)
        return 1

    summary_html = ""
    anthropic_key = os.environ.get("ANTHROPIC_API_KEY")
    if anthropic_key:
        bullets = summarize_headlines(articles, anthropic_key)
        summary_html = format_summary_html(bullets)
        if bullets:
            print(f"Generated summary with {len(bullets)} bullets.")

    body_html = format_html(articles, summary_html)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    send_email(
        sender=sender,
        password=password,
        recipient=recipient,
        subject=f"Daily Finance Digest — {today}",
        html=body_html,
    )
    print(f"Sent {len(articles)} headlines to {recipient}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
