import hashlib
import html
import json
import os
import re
import smtplib
import xml.etree.ElementTree as ET

from datetime import datetime
from email.mime.text import MIMEText
from pathlib import Path
from urllib.parse import urljoin
from zoneinfo import ZoneInfo

import requests


# ---------------------------------------------------------
# Configuration
# ---------------------------------------------------------

EMAIL_USER = os.environ["EMAIL_USER"]
EMAIL_PASSWORD = os.environ["EMAIL_PASSWORD"]
EMAIL_TO = os.environ["EMAIL_TO"]

IST = ZoneInfo("Asia/Kolkata")

STATE_FILE = Path("seen_announcements.json")
BASELINE_MARKER = Path("baseline_created.txt")

BSE_RSS_URL = "https://www.bseindia.com/data/xml/announcements.xml"
BSE_ANNOUNCEMENTS_PAGE = (
    "https://www.bseindia.com/corporates/ann.html"
)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/129.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "application/rss+xml, application/xml, text/xml, "
        "text/html;q=0.9, */*;q=0.8"
    ),
    "Referer": "https://www.bseindia.com/",
}


# ---------------------------------------------------------
# Text and state-file functions
# ---------------------------------------------------------

def clean_text(value):
    if value is None:
        return ""

    text = html.unescape(str(value))

    # Remove HTML tags that may appear in RSS descriptions.
    text = re.sub(r"<[^>]+>", " ", text)

    return " ".join(
        text.replace("\r", " ")
        .replace("\n", " ")
        .split()
    )


def load_seen_ids():
    if not STATE_FILE.exists():
        return set()

    try:
        stored_data = json.loads(
            STATE_FILE.read_text(encoding="utf-8")
        )

        if isinstance(stored_data, list):
            return {
                str(item)
                for item in stored_data
            }

    except Exception as error:
        print(f"Could not read the state file: {error}")

    return set()


def save_seen_ids(seen_ids):
    # Retain the most recent 2,000 identifiers.
    stored_ids = sorted(seen_ids)[-2000:]

    STATE_FILE.write_text(
        json.dumps(stored_ids, indent=2),
        encoding="utf-8"
    )


def create_item_id(item):
    guid = clean_text(item.get("guid"))

    if guid:
        return guid

    identifying_text = "|".join([
        clean_text(item.get("title")),
        clean_text(item.get("link")),
        clean_text(item.get("published")),
        clean_text(item.get("description")),
    ])

    return hashlib.sha256(
        identifying_text.encode("utf-8")
    ).hexdigest()


# ---------------------------------------------------------
# Email function
# ---------------------------------------------------------

def send_email(subject, body):
    message = MIMEText(
        body,
        "plain",
        "utf-8"
    )

    message["Subject"] = subject
    message["From"] = EMAIL_USER
    message["To"] = EMAIL_TO

    with smtplib.SMTP_SSL(
        "smtp.gmail.com",
        465
    ) as server:
        server.login(
            EMAIL_USER,
            EMAIL_PASSWORD
        )

        server.sendmail(
            EMAIL_USER,
            EMAIL_TO,
            message.as_string()
        )


# ---------------------------------------------------------
# RSS retrieval and parsing
# ---------------------------------------------------------

def element_text(element, tag_name):
    child = element.find(tag_name)

    if child is None or child.text is None:
        return ""

    return clean_text(child.text)


def fetch_rss_announcements():
    response = requests.get(
        BSE_RSS_URL,
        headers=HEADERS,
        timeout=30
    )

    print(
        "RSS response status: "
        f"{response.status_code}"
    )

    response.raise_for_status()

    root = ET.fromstring(response.content)

    announcements = []

    for item_element in root.findall(".//item"):
        title = element_text(
            item_element,
            "title"
        )

        description = element_text(
            item_element,
            "description"
        )

        link = element_text(
            item_element,
            "link"
        )

        guid = element_text(
            item_element,
            "guid"
        )

        published = (
            element_text(item_element, "pubDate")
            or element_text(item_element, "date")
        )

        announcements.append({
            "title": title,
            "description": description,
            "link": link,
            "guid": guid,
            "published": published,
        })

    print(
        "Total RSS announcements received: "
        f"{len(announcements)}"
    )

    if not announcements:
        raise RuntimeError(
            "The BSE RSS feed was reachable, but it "
            "contained no announcement items."
        )

    return announcements


# ---------------------------------------------------------
# Order-announcement filtering
# ---------------------------------------------------------

def is_order_announcement(item):
    searchable_text = " ".join([
        clean_text(item.get("title")),
        clean_text(item.get("description")),
    ]).lower()

    order_phrases = [
        "award of order",
        "receipt of order",
        "award_of_order",
        "receipt_of_order",
        "work order",
        "letter of award",
        "order received",
        "received an order",
        "order win",
        "order secured",
        "contract award",
        "awarded contract",
        "purchase order",
    ]

    return any(
        phrase in searchable_text
        for phrase in order_phrases
    )


def extract_company_and_code(title):
    cleaned_title = clean_text(title)

    # Typical title:
    # Company Ltd - 500000 - Announcement...
    match = re.match(
        r"^(.*?)\s*-\s*(\d{6})\s*-\s*(.*)$",
        cleaned_title
    )

    if match:
        return {
            "company": clean_text(match.group(1)),
            "security_code": match.group(2),
            "headline": clean_text(match.group(3)),
        }

    return {
        "company": cleaned_title or "Company unavailable",
        "security_code": "Not available",
        "headline": cleaned_title or "Order announcement",
    }


def normalize_link(link):
    cleaned_link = clean_text(link)

    if not cleaned_link:
        return BSE_ANNOUNCEMENTS_PAGE

    return urljoin(
        "https://www.bseindia.com/",
        cleaned_link
    )


# ---------------------------------------------------------
# Main process
# ---------------------------------------------------------

def main():
    all_announcements = fetch_rss_announcements()

    matching_announcements = [
        item
        for item in all_announcements
        if is_order_announcement(item)
    ]

    print(
        "Matching order announcements: "
        f"{len(matching_announcements)}"
    )

    current_ids = {
        create_item_id(item)
        for item in matching_announcements
    }

    seen_ids = load_seen_ids()

    # First successful production run:
    # create a baseline but do not email existing announcements.
    if not BASELINE_MARKER.exists():
        seen_ids.update(current_ids)
        save_seen_ids(seen_ids)

        BASELINE_MARKER.write_text(
            datetime.now(IST).isoformat(),
            encoding="utf-8"
        )

        print(
            "Baseline created successfully. "
            "Existing announcements were recorded "
            "without sending emails."
        )

        return

    new_announcements = [
        item
        for item in matching_announcements
        if create_item_id(item) not in seen_ids
    ]

    if not new_announcements:
        print(
            "No new matching order announcements found."
        )
        return

    # RSS feeds commonly list the newest entry first.
    # Reverse the list so emails are sent oldest to newest.
    for item in reversed(new_announcements):
        title_details = extract_company_and_code(
            item.get("title")
        )

        description = clean_text(
            item.get("description")
        )

        published = clean_text(
            item.get("published")
        ) or "Not available"

        announcement_link = normalize_link(
            item.get("link")
        )

        subject = (
            "New BSE Order Alert: "
            f"{title_details['company']}"
        )

        body = f"""
NEW BSE ORDER ALERT

Company:
{title_details["company"]}

BSE Security Code:
{title_details["security_code"]}

Announcement:
{title_details["headline"]}

Details:
{description or "No additional description supplied."}

Published:
{published}

Announcement Link:
{announcement_link}

BSE Corporate Announcements:
{BSE_ANNOUNCEMENTS_PAGE}

Detected by the BSE Order Monitor.
""".strip()

        send_email(
            subject,
            body
        )

        announcement_id = create_item_id(item)
        seen_ids.add(announcement_id)

        print(
            "Email alert sent for: "
            f"{title_details['company']}"
        )

    save_seen_ids(seen_ids)

    print(
        "Announcement history updated successfully."
    )


if __name__ == "__main__":
    main()
