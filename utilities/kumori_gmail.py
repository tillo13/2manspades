"""Minimal Gmail sender for kumori.

Sends as kumoridotai@gmail.com via Gmail API + OAuth (refresh token in
KUMORI_GMAIL_OAUTH_REFRESH_TOKEN secret on kumori-404602). Mirrors the
pattern used in galactica/utilities/gmail_utils.py.

⚠️  SHARED SENDING IDENTITY — read before adding a new caller.
Every one of Andy's apps sends as this single consumer Gmail account, so they all
share ONE sender reputation. Mail that looks like spam from any app gets mail from
EVERY app throttled or blocked, user-facing Sync reports included.

  • Never one email per event. Dedupe by signature, collapse repeats, then cool down.
  • Cap volume per hour and per day, in code. A crash loop must send one message, not one per tick.
  • Prefer a daily digest over a stream of alerts.
  • Never bulk-send to a list; a consumer Gmail account cannot meet Gmail's bulk-sender rules.
  • A 5.7.1 or 5.7.30 bounce is a symptom. Fix the sending loop, do not silence the alert.

Incident 2026-09-06 → 09-08: a 2manspades cron crash loop sent an alert per failure with an
identical subject; Gmail returned 550 5.7.1 "likely unsolicited mail" and 550 5.7.30 "DKIM
authentication didn't pass". Full detail in the kumori-infrastructure skill, "Shared sending
identity".

ENFORCED since 2026-09-21 (task #34): every send passes utilities.mail_guard.admit() first,
which records the attempt in kumori_ops.mail_ledger and refuses (never queues) a repeat of the
same recipient + subject within an hour, or anything past the app's hourly / daily cap. The
guard lives in its own module (2026-09-24) so every other app's sender, Gmail API or SMTP,
vendors and calls the same one.
"""
import base64
import json
import logging
import time
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from utilities.mail_guard import admit

logger = logging.getLogger(__name__)

PROJECT_ID = 'kumori-404602'
OAUTH_SECRET_ID = 'KUMORI_GMAIL_OAUTH_REFRESH_TOKEN'
SENDER_EMAIL = 'kumoridotai@gmail.com'

_service = None
_creds = None
_sm_client = None


def _get_service():
    global _service, _creds, _sm_client
    from google.auth.transport.requests import Request
    from google.cloud import secretmanager
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    if _creds is None:
        if _sm_client is None:
            _sm_client = secretmanager.SecretManagerServiceClient()
        name = f"projects/{PROJECT_ID}/secrets/{OAUTH_SECRET_ID}/versions/latest"
        payload = json.loads(
            _sm_client.access_secret_version(request={"name": name}).payload.data.decode("UTF-8")
        )
        _creds = Credentials(
            token=None,
            refresh_token=payload["refresh_token"],
            client_id=payload["client_id"],
            client_secret=payload["client_secret"],
            token_uri=payload["token_uri"],
            scopes=payload.get("scopes"),
        )

    if not _creds.valid:
        _creds.refresh(Request())
        _service = None

    if _service is None:
        _service = build("gmail", "v1", credentials=_creds, cache_discovery=False)
    return _service


def send_email(to: str, subject: str, html_body: str, from_name: str = 'Kumori', app: str = 'kumori',
               dedupe: bool = True, reply_to: str = None, bcc: str = None) -> bool:
    """Send an HTML email. Returns True on success, False if refused or failed.

    Refused (logged at ERROR, never queued) when mail_guard.admit() says it is a repeat or
    over the app's cap. Retries on transient errors (SSL EOF, connection reset, 5xx).
    2026-05-07: 8am digest dropped silently on a single _ssl.c:2427 EOF — added 3
    attempts with backoff so a one-off TLS hiccup at Google's end doesn't kill an email."""
    ok, _reason = admit(app, to, subject, dedupe=dedupe)
    if not ok:
        return False
    message = MIMEMultipart()
    message['From'] = f'{from_name} <{SENDER_EMAIL}>'
    message['To'] = to
    message['Subject'] = subject
    if reply_to:
        message['Reply-To'] = reply_to     # a contact form's reply goes to the person who wrote in
    if bcc:
        message['Bcc'] = bcc               # Gmail API delivers Bcc and strips it from the copy sent
    message.attach(MIMEText(html_body, 'html'))
    raw = base64.urlsafe_b64encode(message.as_bytes()).decode()

    last_err = None
    for attempt in range(3):
        try:
            _get_service().users().messages().send(userId='me', body={'raw': raw}).execute()
            if attempt > 0:
                logger.warning(f"gmail_utils: succeeded on retry {attempt} ({subject!r})")
            else:
                logger.info(f"gmail_utils: email sent to {to} ({subject!r})")
            return True
        except Exception as e:
            last_err = e
            global _service
            _service = None  # rebuild client — handles stale TLS / token races
            if attempt < 2:
                time.sleep(1.0 * (attempt + 1))  # 1s, 2s
                logger.warning(f"gmail_utils: send attempt {attempt + 1} failed ({e}), retrying")
    logger.error(f"gmail_utils: send failed after 3 attempts: {last_err}")
    return False
