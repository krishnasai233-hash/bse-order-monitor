import hashlib
import html
import json
import os
import smtplib
from datetime import datetime
from email.mime.text import MIMEText
from pathlib import Path
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

BSE_PAGE_URL = "https://www.bseindia.com/corporates/ann.html"
BSE_API_URL = "https://api.bseindia.com/BseIndiaAPI/api/AnnGetData/w"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/129.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Referer": BSE_PAGE_URL,
    "Origin": "https://www.bseindia.com",
}


# ---------------------------------------------------------
# Utility functions
# ---------------------------------------------------------

def clean_text(value):
    if value is None:
        return ""

    return " ".join(
        html.unescape(str(value))
        .replace("\r", " ")
        .replace("\n", " ")
        .split()
    )


def first_available(record, *field_names):
    for field_name in field_names:
        value = record.get(field_name)

        if value not in (None, ""):
            return clean_text(value)

    return ""


def load_seen_ids():
    if not STATE_FILE.exists():
        return set()

    try:
        data = json.loads(STATE_FILE.read_text(encoding="utf-8"))

        if isinstance(data, list):
            return set(str(item) for item in data)

    except Exception as error:
        print(f"Could not read state file: {error}")

    return set()


def save_seen_ids(seen_ids):
    # Retain a reasonable history while keeping the repository file small.
    recent_ids = sorted(seen_ids)[-2000:]

    STATE_FILE.write_text(
        json.dumps(recent_ids, indent=2),
        encoding="utf-8"
    )


def create_announcement_id(record):
    existing_id = first_available(
        record,
        "NEWSID",
        "NewsID",
        "ANNOUNCEMENTID",
        "AnnouncementId",
        "AttachmentName"
    )

    if existing_id:
        return existing_id

    identifying_text = "|".join([
        first_available(record, "SCRIP_CD", "Scrip_Code", "SLONGNAME"),
        first_available(record, "NEWS_SUB", "HEADLINE", "SUBJECT"),
        first_available(record, "DT_TM", "DissemDT", "NEWS_DT"),
        first_available(record, "ATTACHMENTNAME", "AttachmentName"),
    ])

    return hashlib.sha256(
        identifying_text.encode("utf-8")
    ).hexdigest()


def build_pdf_url(record):
    direct_url = first_available(
        record,
        "NSURL",
        "PDF_URL",
        "ATTACHMENT_URL"
    )

    if direct_url.startswith("http"):
        return direct_url

    attachment = first_available(
        record,
        "ATTACHMENTNAME",
        "AttachmentName"
    )

    if attachment:
        return (
            "https://www.bseindia.com/xml-data/"
            "corpfiling/AttachLive/"
            + attachment.lstrip("/")
        )

    return BSE_PAGE_URL


def send_email(subject, body):
    message = MIMEText(body, "plain", "utf-8")

    message["Subject"] = subject
    message["From"] = EMAIL_USER
    message["To"] = EMAIL_TO

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(EMAIL_USER, EMAIL_PASSWORD)
        server.sendmail(
            EMAIL_USER,
            EMAIL_TO,
            message.as_string()
        )


# ---------------------------------------------------------
# BSE data retrieval
# ---------------------------------------------------------

def fetch_announcements():
    today = datetime.now(IST).strftime("%Y%m%d")

    params = {
        "pageno": 1,
        "strCat": -1,
        "strPrevDate": today,
        "strScrip": "",
        "strSearch": "P",
        "strToDate": today,
        "strType": "C",
    }

    session = requests.Session()
    session.headers.update(HEADERS)

    # Establish the BSE session before requesting API data.
    landing_response = session.get(
        BSE_PAGE_URL,
        timeout=30
    )
    landing_response.raise_for_status()

    response = session.get(
        BSE_API_URL,
        params=params,
        timeout=30
    )
    response.raise_for_status()

    payload = response.json()

    records = payload.get("Table", [])

    if not isinstance(records, list):
        raise RuntimeError(
            "BSE API did not return the expected announcement list."
        )

    print(f"Total BSE announcements received: {len(records)}")

    return records


# ---------------------------------------------------------
# Filtering
# ---------------------------------------------------------

def is_order_announcement(record):
    combined_text = " ".join(
        clean_text(value).lower()
        for value in record.values()
        if isinstance(value, (str, int, float))
    )

    category_match = (
        "company update" in combined_text
        or "company_update" in combined_text
    )

    order_phrases = [
        "award of order",
        "receipt of order",
        "award_of_order",
        "receipt_of_order",
        "work order",
        "letter of award",
        "order received",
        "order win",
    ]

    order_match = any(
        phrase in combined_text
        for phrase in order_phrases
    )

    return category_match and order_match


def format_announcement(record):
    company = first_available(
        record,
        "SLONGNAME",
        "LONG_NAME",
        "COMPANY_NAME",
        "SCRIP_NAME"
    ) or "Company name unavailable"

    security_code = first_available(
        record,
        "SCRIP_CD",
        "Scrip_Code",
        "SCRIPCODE"
    ) or "Not available"

    headline = first_available(
        record,
        "NEWS_SUB",
        "HEADLINE",
        "SUBJECT",
        "NEWSSUB"
    ) or "Award/Receipt of Order"

    description = first_available(
        record,
        "MORE",
        "DESCRIPTION",
        "DETAILS",
        "NEWS_BODY"
    ) or "No additional description supplied."

    received_time = first_available(
        record,
        "DT_TM",
        "DissemDT",
        "NEWS_DT",
        "ReceivedTime"
    ) or "Not available"

    pdf_url = build_pdf_url(record)

    return {
        "company": company,
        "security_code": security_code,
        "headline": headline,
        "description": description,
        "received_time": received_time,
        "pdf_url": pdf_url,
    }


# ---------------------------------------------------------
# Main execution
# ---------------------------------------------------------

def main():
    all_records = fetch_announcements()

    matching_records = [
        record
        for record in all_records
        if is_order_announcement(record)
    ]

    print(
        "Matching Company Update / Order announcements: "
        f"{len(matching_records)}"
    )

    current_ids = {
        create_announcement_id(record)
        for record in matching_records
    }

    seen_ids = load_seen_ids()

    # First production run:
    # record existing announcements but do not email all old items.
    if not BASELINE_MARKER.exists():
        seen_ids.update(current_ids)
        save_seen_ids(seen_ids)

        BASELINE_MARKER.write_text(
            datetime.now(IST).isoformat(),
            encoding="utf-8"
        )

        print(
            "Baseline created. Existing matching announcements "
            "will not be emailed."
        )

        return

    new_records = [
        record
        for record in matching_records
        if create_announcement_id(record) not in seen_ids
    ]

    if not new_records:
        print("No new matching announcements were found.")
        return

    # Send one email for each newly detected announcement.
    for record in reversed(new_records):
        details = format_announcement(record)

        email_subject = (
            "New BSE Order Alert: "
            + details["company"]
        )

        email_body = f"""
NEW BSE ORDER ALERT

Company:
{details["company"]}

BSE Security Code:
{details["security_code"]}

Announcement:
{details["headline"]}

Details:
{details["description"]}

Exchange Received/Disseminated Time:
{details["received_time"]}

Announcement/PDF:
{details["pdf_url"]}

Source:
{BSE_PAGE_URL}

Detected by the BSE Order Monitor.
"""

        send_email(
            email_subject,
            email_body.strip()
        )

        announcement_id = create_announcement_id(record)
        seen_ids.add(announcement_id)

        print(
            "Alert sent for: "
            + details["company"]
        )

    save_seen_ids(seen_ids)


if __name__ == "__main__":
    main()
