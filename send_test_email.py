import os
import smtplib
import requests
from bs4 import BeautifulSoup
from email.mime.text import MIMEText

sender = os.environ["EMAIL_USER"]
password = os.environ["EMAIL_PASSWORD"]
receiver = os.environ["EMAIL_TO"]

url = "https://www.bseindia.com/corporates/ann.html"

html = requests.get(url, timeout=30).text

msg = MIMEText(
    f"""
BSE Monitor Executed Successfully

Length of page fetched:
{len(html)} characters

Next step:
Parse Order Announcements
"""
)

msg["Subject"] = "BSE Order Monitor Running"
msg["From"] = sender
msg["To"] = receiver

with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
    server.login(sender, password)
    server.sendmail(sender, receiver, msg.as_string())

print("Success")
