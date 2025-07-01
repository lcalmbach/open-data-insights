import psycopg2
from datetime import date
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import markdown
import pandas as pd
from dotenv import load_dotenv
from decouple import config
from daily_tasks.utils import setup_logger
import time

load_dotenv()
logger = setup_logger(name=__name__, log_file="logs/mail.log")


# DB configuration
conn = psycopg2.connect(
    dbname=config("DB_NAME"),
    user=config("DB_USER"),
    password=config("DB_PASSWORD"),
    host=config("DB_HOST"),
    port=config("DB_PORT"),
)

# Email configuration
smtp_server = config("SMTP_SERVER", default="smtp.gmail.com")
smtp_port = config("SMTP_PORT", default=587, cast=int)
smtp_user = config("EMAIL_HOST_USER")
smtp_password = config("EMAIL_HOST_PASSWORD")


def send_mail(subject, html_body, from_email, to_email):
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = from_email
    msg["To"] = to_email

    # HTML content
    html_part = MIMEText(html_body, "html")
    msg.attach(html_part)

    with smtplib.SMTP(smtp_server, smtp_port) as server:
        server.starttls()
        server.login(smtp_user, smtp_password)
        server.send_message(msg)

    logger.info(f"Email sent to {to_email}")


def run():
    logger.info(f"Starting sending mails...")
    today = date.today()

    # 2. View in DataFrame laden
    cmd = "SELECT * FROM report_generator.v_insights2send"
    df = pd.read_sql_query(
        cmd,
        conn,
        params=(today,),
    )
    if df.empty:
        logger.info(f"no insights found for today. {today}")
    else:
        logger.info(f"Found {len(df)} stories to send.")
        for _, row in df.iterrows():
            subject = f"Open Data Story: {row['title']}"
            html_body = markdown.markdown(
                row["story"], extensions=["markdown.extensions.tables"]
            )
            to_email = row["email"]
            try:
                send_mail(
                    subject=subject,
                    html_body=html_body,
                    from_email="lcalmbach@gmail.com",
                    to_email=to_email,
                )
            except Exception as e:
                logger.error(f"Error sending email to {to_email}: {e}")
            time.sleep(2)
        cmd = "update report_generator.reports_story set is_sent = true"
        with conn.cursor() as cur:
            cur.execute(cmd)
            conn.commit()
        logger.info("Updated all records to is_sent = true.")
    conn.close()


if __name__ == "__main__":
    run()
