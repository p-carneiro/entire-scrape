"""
Scraper for entire.io/news → generates an RSS 2.0 feed (rss.xml)

Uses Playwright (async) to handle JavaScript-rendered content.
Only updates rss.xml when new articles are found.

Works in: local Python, Google Colab, GitHub Actions

Install dependencies:
    pip install playwright nest_asyncio
    playwright install chromium
"""

import asyncio
import re
import xml.dom.minidom
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

import nest_asyncio
from playwright.async_api import async_playwright

# Allows asyncio.run() to work inside Colab's existing event loop
nest_asyncio.apply()

# ── Config ────────────────────────────────────────────────────────────────────
BASE_URL = "https://entire.io"
NEWS_URL = "https://entire.io/news/"
OUTPUT_FILE = "rss.xml"
FEED_TITLE = "Entire Newsroom"
FEED_DESCRIPTION = "Latest news and press releases from Entire."
# ─────────────────────────────────────────────────────────────────────────────


def parse_date(date_str):
    """Try several date formats and return an RFC 2822 string for RSS."""
    date_str = date_str.strip()
    formats = [
        "%d %B %Y",   # 10 February 2026
        "%d %b %Y",   # 10 Feb 2026
        "%B %d, %Y",  # February 10, 2026
        "%Y-%m-%d",   # 2026-02-10
    ]
    for fmt in formats:
        try:
            dt = datetime.strptime(date_str, fmt)
            return dt.strftime("%a, %d %b %Y 00:00:00 +0000")
        except ValueError:
            continue
    return datetime.now(timezone.utc).strftime("%a, %d %b %Y 00:00:00 +0000")


def load_existing_guids(filepath):
    """Return a set of GUIDs already present in an existing RSS file."""
    try:
        tree = ET.parse(filepath)
        return {guid.text for guid in tree.findall(".//guid") if guid.text}
    except (FileNotFoundError, ET.ParseError):
        return set()


async def scrape_articles():
    """Launch a headless browser, render the page, and extract articles."""
    articles = []
    seen_urls = set()

    date_pattern = re.compile(
        r"^\d{1,2}\s+\w+\s+\d{4}$|^\w+\s+\d{1,2},?\s+\d{4}$|^\d{4}-\d{2}-\d{2}$"
    )

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        print(f"Fetching {NEWS_URL} ...")
        await page.goto(NEWS_URL, wait_until="networkidle")

        links = await page.eval_on_selector_all(
            "a[href]",
            """elements => elements.map(el => ({
                href: el.href,
                text: el.innerText.trim()
            }))"""
        )

        for link in links:
            href = link["href"]
            text = link["text"]

            if not href.startswith(BASE_URL + "/news/"):
                continue
            if href == NEWS_URL:
                continue
            if href in seen_urls:
                continue
            seen_urls.add(href)

            lines = [l.strip() for l in text.splitlines() if l.strip()]
            if not lines:
                continue

            pub_date = None
            title_lines = lines

            if date_pattern.match(lines[0]):
                pub_date = parse_date(lines[0])
                title_lines = lines[1:]

            title = " ".join(title_lines).strip()
            if not title:
                continue

            articles.append({
                "title": title,
                "link": href,
                "pub_date": pub_date or datetime.now(timezone.utc).strftime("%a, %d %b %Y 00:00:00 +0000"),
                "description": title,
            })

        await browser.close()

    return articles


def build_rss(articles):
    """Build and return a pretty-printed RSS 2.0 XML string."""
    rss = ET.Element("rss", version="2.0")
    rss.set("xmlns:atom", "http://www.w3.org/2005/Atom")

    channel = ET.SubElement(rss, "channel")
    ET.SubElement(channel, "title").text = FEED_TITLE
    ET.SubElement(channel, "link").text = NEWS_URL
    ET.SubElement(channel, "description").text = FEED_DESCRIPTION
    ET.SubElement(channel, "language").text = "en-us"
    ET.SubElement(channel, "lastBuildDate").text = datetime.now(timezone.utc).strftime(
        "%a, %d %b %Y %H:%M:%S +0000"
    )
    atom_link = ET.SubElement(channel, "atom:link")
    atom_link.set("href", NEWS_URL + "rss.xml")
    atom_link.set("rel", "self")
    atom_link.set("type", "application/rss+xml")

    for article in articles:
        item = ET.SubElement(channel, "item")
        ET.SubElement(item, "title").text = article["title"]
        ET.SubElement(item, "link").text = article["link"]
        ET.SubElement(item, "guid").text = article["link"]
        ET.SubElement(item, "pubDate").text = article["pub_date"]
        ET.SubElement(item, "description").text = article["description"]

    raw_xml = ET.tostring(rss, encoding="unicode")
    pretty_xml = xml.dom.minidom.parseString(raw_xml).toprettyxml(indent="  ")
    lines = pretty_xml.splitlines()
    lines[0] = '<?xml version="1.0" encoding="UTF-8"?>'
    return "\n".join(lines)


async def main():
    articles = await scrape_articles()

    if not articles:
        print("No articles found. The page structure may have changed.")
        return

    existing_guids = load_existing_guids(OUTPUT_FILE)
    new_articles = [a for a in articles if a["link"] not in existing_guids]

    if not new_articles:
        print(f"No new articles found ({len(articles)} article(s) already in feed). Nothing to update.")
        return

    print(f"Found {len(new_articles)} new article(s):")
    for a in new_articles:
        print(f"  • {a['title'][:80]}")

    rss_content = build_rss(articles)

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write(rss_content)

    print(f"\nRSS feed updated: {OUTPUT_FILE}")


if __name__ == "__main__":
    asyncio.run(main())
