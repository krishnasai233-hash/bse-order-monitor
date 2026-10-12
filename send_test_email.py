import os
import smtplib
from email.mime.text import MIMEText

sender = os.environ["EMAIL_USER"]
password = os.environ["EMAIL_PASSWORD"]
receiver = os.environ["EMAIL_TO"]

msg = MIMEText(
    "✅ GitHub Actions test email is working successfully."
)

msg["Subject"] = "BSE Monitor Test"
msg["From"] = sender
msg["To"] = receiver

with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
    server.login(sender, password)
    server.sendmail(sender, receiver, msg.as_string())

print("Email Sent Successfully")
