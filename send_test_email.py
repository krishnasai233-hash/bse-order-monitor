import os
import smtplib
import requests
from email.mime.text import MIMEText

sender = os.environ["EMAIL_USER"]
password = os.environ["EMAIL_PASSWORD"]
receiver = os.environ["EMAIL_TO"]

url = "https://www.bseindia.com/corporates/ann.html"

headers = {
    "User-Agent": (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
        "AppleWebKit/605.1.15 Version/17.0 Mobile/15E148 Safari/604.1"
    ),
    "Referer": "https://www.bseindia.com/"
}

response = requests.get(
    url,
    headers=headers,
    timeout=30
)

response.raise_for_status()

page_length = len(response.text)

message = f"""
BSE Monitor validation completed successfully.

BSE page response status: {response.status_code}
Downloaded page size: {page_length} characters

The GitHub workflow can access the BSE announcements page.

This is only a validation message. Actual announcement extraction
and duplicate prevention will be added in the next step.
"""

email = MIMEText(message)

email["Subject"] = "BSE Monitor Validation Successful"
email["From"] = sender
email["To"] = receiver

with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
    server.login(sender, password)
    server.sendmail(
        sender,
        receiver,
        email.as_string()
    )

print("BSE page accessed successfully")
print(f"HTTP status: {response.status_code}")
print(f"Page size: {page_length} characters")
print("Validation email sent successfully")
