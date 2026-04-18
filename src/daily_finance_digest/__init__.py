"""Daily finance digest: fetch top financial headlines and email them."""

from __future__ import annotations

import html
import os
import smtplib
import sys
from datetime import datetime, timezone
from email.message import EmailMessage
from typing import Literal

import anthropic
import requests
from dotenv import load_dotenv
from pydantic import BaseModel

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


class TermOfTheDay(BaseModel):
    term: str
    plain_english: str
    why_today: str


class MarketInsight(BaseModel):
    area: str
    direction: Literal["positive", "negative", "mixed", "uncertain"]
    reasoning: str


class DigestContent(BaseModel):
    themes: list[str]
    insights: list[MarketInsight]
    term: TermOfTheDay


def generate_digest_content(
    articles: list[dict], api_key: str
) -> DigestContent | None:
    """Ask Claude for today's themes and a 'term of the day'.

    Returns None on any failure — the caller falls back to the plain
    digest so a Claude outage never blocks the email.
    """
    headlines = "\n".join(
        f"- {a.get('title') or ''} ({(a.get('source') or {}).get('name') or ''}): "
        f"{a.get('description') or ''}"
        for a in articles
    )
    system = (
        "You are a financial news editor writing a concise daily brief "
        "for a curious learner building financial literacy. Given today's "
        "business headlines, produce:\n"
        "1. Exactly 3 themes — the most important stories or patterns of "
        "the day, each as one plain-text sentence.\n"
        "2. Two or three market insights — concrete possible effects "
        "on sectors, asset classes, or regions. Each insight has:\n"
        "   - 'area': a specific market area (e.g. 'US tech stocks', "
        "'European banks', '10-year Treasuries', 'gold', 'energy ETFs'). "
        "Stay at sector/asset-class level; never name individual stocks "
        "unless a headline features one prominently.\n"
        "   - 'direction': one of 'positive', 'negative', 'mixed', or "
        "'uncertain'.\n"
        "   - 'reasoning': one sentence explaining the logic with hedged "
        "language ('could', 'may', 'historically', 'all else equal'). "
        "This is educational observation, not investment advice.\n"
        "   If today's news lacks clear market implications, produce "
        "fewer insights (even just one) rather than invent them.\n"
        "3. One 'term of the day' — a moderately-technical financial or "
        "economics term that appears in or is directly relevant to "
        "today's news. Avoid extremely basic terms (stock, bond, "
        "dividend, IPO) and extremely obscure ones. Good examples: "
        "'yield curve inversion', 'quantitative tightening', "
        "'basis points', 'duration risk', 'carry trade'. For the term, "
        "provide a plain-English definition (2 sentences, no jargon) "
        "and one sentence on how it's relevant today."
    )
    try:
        client = anthropic.Anthropic(api_key=api_key)
        response = client.messages.parse(
            model=SUMMARY_MODEL,
            max_tokens=1500,
            system=system,
            messages=[
                {"role": "user", "content": f"Today's headlines:\n{headlines}"}
            ],
            output_format=DigestContent,
        )
        return response.parsed_output
    except Exception as e:
        print(f"AI content generation failed: {e}", file=sys.stderr)
        return None


def format_themes_html(themes: list[str]) -> str:
    if not themes:
        return ""
    items = "".join(f"<li>{html.escape(t)}</li>" for t in themes)
    return (
        '<div style="background:#f6f8fa;padding:12px 16px;border-radius:6px;'
        'margin-bottom:16px;">'
        "<h3 style=\"margin:0 0 8px 0;\">Today's key themes</h3>"
        f'<ul style="margin:0;padding-left:20px;">{items}</ul></div>'
    )


def format_insights_html(insights: list[MarketInsight]) -> str:
    if not insights:
        return ""
    colors = {
        "positive": "#2e7d32",
        "negative": "#c62828",
        "mixed": "#6a1b9a",
        "uncertain": "#616161",
    }
    rows = []
    for i in insights:
        color = colors.get(i.direction, "#616161")
        rows.append(
            f'<li style="margin-bottom:10px;border-left:3px solid {color};'
            f'padding:2px 0 2px 10px;list-style:none;">'
            f"<b>{html.escape(i.area)}</b> "
            f'<span style="color:{color};text-transform:uppercase;'
            f'font-size:0.75em;font-weight:700;margin-left:4px;">'
            f"{i.direction}</span><br>"
            f'<span style="color:#333;">{html.escape(i.reasoning)}</span>'
            f"</li>"
        )
    return (
        '<div style="background:#eef3ff;padding:12px 16px;border-radius:6px;'
        'margin-top:16px;">'
        '<h3 style="margin:0 0 10px 0;">Potential market impact</h3>'
        f'<ul style="margin:0;padding:0;">{"".join(rows)}</ul>'
        '<p style="margin:8px 0 0 0;color:#666;"><small>'
        "Educational observations, not investment advice.</small></p>"
        "</div>"
    )


def format_term_html(term: TermOfTheDay) -> str:
    return (
        '<div style="background:#fff8e1;border-left:4px solid #f9a825;'
        'padding:12px 16px;margin-top:20px;border-radius:4px;">'
        '<h3 style="margin:0 0 6px 0;">'
        f"Term of the day: {html.escape(term.term)}</h3>"
        f'<p style="margin:0 0 8px 0;">{html.escape(term.plain_english)}</p>'
        '<p style="margin:0;color:#555;"><small><i>Why today:</i> '
        f"{html.escape(term.why_today)}</small></p>"
        "</div>"
    )


def format_html(
    articles: list[dict],
    themes_html: str = "",
    insights_html: str = "",
    term_html: str = "",
) -> str:
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
        f"{themes_html}"
        f"<ol>{''.join(items)}</ol>"
        f"{insights_html}"
        f"{term_html}"
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

    themes_html = ""
    insights_html = ""
    term_html = ""
    anthropic_key = os.environ.get("ANTHROPIC_API_KEY")
    if anthropic_key:
        digest = generate_digest_content(articles, anthropic_key)
        if digest:
            themes_html = format_themes_html(digest.themes)
            insights_html = format_insights_html(digest.insights)
            term_html = format_term_html(digest.term)
            print(
                f"AI content: {len(digest.themes)} themes + "
                f"{len(digest.insights)} insights + "
                f"term '{digest.term.term}'."
            )

    body_html = format_html(articles, themes_html, insights_html, term_html)
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
