import streamlit as st
import pandas as pd
import requests
import urllib.parse
import time
import smtplib
import hashlib
from email.mime.text import MIMEText
from datetime import datetime, timezone
from pymongo import MongoClient, ASCENDING, DESCENDING
from pymongo.server_api import ServerApi
from sqlalchemy import create_engine, text

from xero_python.accounting import AccountingApi
from xero_python.identity import IdentityApi
from xero_python.api_client import ApiClient
from xero_python.api_client.configuration import Configuration

# =============================
# PAGE CONFIG
# =============================
st.set_page_config(page_title="Xero AR Monitor", page_icon="📊")

# =============================
# VALIDATION HELPER
# =============================
def validate_secrets(required_keys, placeholder_values=None):
    missing = [key for key in required_keys if key not in st.secrets]
    placeholders = []
    if missing:
        st.error(f"❌ Missing secrets: {', '.join(missing)}")
    if placeholder_values:
        placeholders = [
            key for key, val in placeholder_values.items()
            if st.secrets.get(key) == val
        ]
        if placeholders:
            st.warning(f"⚠️ Placeholder values still set: {', '.join(placeholders)}")
    if not missing and not placeholders:
        st.success("🎉 All required secrets are present and valid!")
    return missing, placeholders

# =============================
# SECRETS VALIDATION
# =============================
REQUIRED_KEYS = [
    "CLIENT_ID", "CLIENT_SECRET", "REDIRECT_URI", "SLACK_WEBHOOK",
    "EMAIL_HOST", "EMAIL_PORT", "EMAIL_USER", "EMAIL_PASS",
    "MONGO_URI", "MONGO_DB", "AUTH_URL", "TOKEN_URL", "SCOPES", "DB_CONN_STR"
]

PLACEHOLDER_VALUES = {
    "CLIENT_ID": "your_xero_client_id",
    "CLIENT_SECRET": "your_xero_client_secret",
    "REDIRECT_URI": "https://your-app.streamlit.app",
    "EMAIL_USER": "your@email.com",
    "EMAIL_PASS": "your_app_password",
    "DB_CONN_STR": "postgresql://user:password@host:5432/dbname",
    "SLACK_WEBHOOK": "https://hooks.slack.com/services/XXX/YYY/ZZZ",
    "MONGO_URI": "mongodb+srv://<db_username>:<db_password>@cluster0.qjjfboi.mongodb.net/?appName=Cluster0",
    "MONGO_DB": "",
}
with st.sidebar.expander("🔧 Config Status", expanded=False):
    missing, placeholders = validate_secrets(REQUIRED_KEYS, PLACEHOLDER_VALUES)

# =============================
# SECRET VARIABLES
# =============================
CLIENT_ID     = st.secrets.get("CLIENT_ID")
CLIENT_SECRET = st.secrets.get("CLIENT_SECRET")
REDIRECT_URI  = st.secrets.get("REDIRECT_URI")
SCOPES        = st.secrets.get("SCOPES")
AUTH_URL      = st.secrets.get("AUTH_URL")
TOKEN_URL     = st.secrets.get("TOKEN_URL")
DB_CONN_STR   = st.secrets.get("DB_CONN_STR")
SLACK_WEBHOOK = st.secrets.get("SLACK_WEBHOOK")
EMAIL_USER    = st.secrets.get("EMAIL_USER")
EMAIL_PASS    = st.secrets.get("EMAIL_PASS")
EMAIL_HOST    = st.secrets.get("EMAIL_HOST")
EMAIL_PORT    = int(st.secrets.get("EMAIL_PORT", 587))
MONGO_URI     = st.secrets.get("MONGO_URI")
MONGO_DB      = st.secrets.get("MONGO_DB")

# =============================
# DB CONNECTION
# =============================
DB_AVAILABLE = False
engine = None
if DB_CONN_STR and DB_CONN_STR != PLACEHOLDER_VALUES.get("DB_CONN_STR"):
    try:
        engine = create_engine(DB_CONN_STR)
        DB_AVAILABLE = True
    except Exception as e:
        st.sidebar.warning(f"⚠️ Relational DB connection failed: {e}")

# =============================
# MONGO CONNECTION
# =============================
MONGO_AVAILABLE = False
alerts = snapshot = tokens = None  # FIX: declare upfront so they're always bound

mongo_uri = st.secrets.get("MONGO_URI")
mongo_db  = st.secrets.get("MONGO_DB")

if mongo_uri and mongo_uri != PLACEHOLDER_VALUES.get("MONGO_URI"):
    try:
        mongo_client = MongoClient(mongo_uri, server_api=ServerApi("1"))
        mongo_client.admin.command("ping")
        db = mongo_client[mongo_db]
        alerts   = db.alerts_log
        snapshot = db.ar_snapshot
        tokens   = db.oauth_tokens
        MONGO_AVAILABLE = True
    except Exception as e:
        st.sidebar.warning(f"⚠️ MongoDB connection failed: {e}")

# =============================
# INDEX INITIALIZATION
# =============================
def init_indexes():
    if not MONGO_AVAILABLE:
        return
    try:
        alerts.create_index([("alert_key", ASCENDING)], unique=True)
        alerts.create_index([("client", ASCENDING)])
        alerts.create_index([("timestamp", DESCENDING)])
        snapshot.create_index([("tenant", ASCENDING)])
        snapshot.create_index([("invoice", ASCENDING)])
        snapshot.create_index([("captured_at", DESCENDING)])
        tokens.create_index([("tenant", ASCENDING)], unique=True)
        tokens.create_index([("expires_at", ASCENDING)])
    except Exception as e:
        st.sidebar.warning(f"⚠️ Index initialization failed: {e}")

init_indexes()

# =============================
# HELPERS
# =============================
def get_alert_key(client, action, amount):
    raw = f"{client}_{action}_{amount}"
    return hashlib.md5(raw.encode()).hexdigest()


def already_sent(key):
    """
    FIX: previously returned False silently when DB unavailable,
    allowing duplicate alerts. Now warns explicitly.
    """
    if not DB_AVAILABLE:
        st.warning("⚠️ Deduplication skipped — relational DB unavailable.")
        return False
    try:
        query = text("SELECT 1 FROM alerts_log WHERE alert_key = :key LIMIT 1")
        result = pd.read_sql(query, engine, params={"key": key})
        return not result.empty
    except Exception as e:
        st.warning(f"⚠️ already_sent check failed: {e}")
        return False


def sent_recently(client):
    if not DB_AVAILABLE:
        return False
    try:
        query = text("""
            SELECT 1 FROM alerts_log
            WHERE client = :client
              AND created_at > NOW() - INTERVAL '3 days'
            LIMIT 1
        """)
        df = pd.read_sql(query, engine, params={"client": client})
        return not df.empty
    except Exception as e:
        st.warning(f"⚠️ sent_recently check failed: {e}")
        return False


def log_alert(client, message, key):
    if not DB_AVAILABLE:
        return
    try:
        df = pd.DataFrame([{
            "client": client,
            "message": message,
            "alert_key": key,
            "created_at": datetime.now(timezone.utc),
        }])
        df.to_sql("alerts_log", engine, if_exists="append", index=False)
    except Exception as e:
        st.warning(f"⚠️ log_alert failed: {e}")


def send_slack(message, client, key):
    if not SLACK_WEBHOOK:
        st.warning("⚠️ Slack webhook not configured.")
        return
    if already_sent(key):
        return
    try:
        requests.post(SLACK_WEBHOOK, json={"text": message}, timeout=5)
        log_alert(client, message, key)
    except Exception as e:
        st.warning(f"⚠️ Slack send failed: {e}")


def generate_email(client, amount, days):
    if days <= 30:
        return f"Dear {client},\n\nJust a friendly reminder of {amount:,.2f} outstanding."
    elif days <= 60:
        return f"Dear {client},\n\nYour balance of {amount:,.2f} is overdue. Please arrange payment."
    else:
        return f"FINAL NOTICE: {client}, immediate payment of {amount:,.2f} is required."


def send_email(to_email, subject, body, client, key):
    if not all([EMAIL_HOST, EMAIL_USER, EMAIL_PASS]):
        st.warning("⚠️ Email credentials not fully configured.")
        return
    if already_sent(key) or sent_recently(client):
        return
    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = EMAIL_USER
    msg["To"] = to_email
    try:
        with smtplib.SMTP(EMAIL_HOST, EMAIL_PORT) as server:
            server.starttls()
            server.login(EMAIL_USER, EMAIL_PASS)
            server.send_message(msg)
        log_alert(client, body, key)
    except Exception as e:
        st.error(f"❌ Email failed: {e}")

# =============================
# OAUTH LOGGING HELPER
# =============================
def log_oauth_event(status, details=None):
    if MONGO_AVAILABLE and alerts is not None:
        alerts.insert_one({
            "event": "oauth_callback",
            "status": status,
            "details": details,
            "timestamp": datetime.now(timezone.utc),
        })

# =============================
# SESSION STATE
# =============================
if "token" not in st.session_state:
    st.session_state.token = None

# =============================
# AUTH FLOW
# =============================
qp = st.query_params

if st.session_state.token is None:
    # FIX: guard against missing TOKEN_URL/CLIENT_ID before making HTTP calls
    can_auth = all([AUTH_URL, TOKEN_URL, CLIENT_ID, CLIENT_SECRET, REDIRECT_URI, SCOPES])

    # FIX: use .get() instead of direct key access to avoid KeyError
    if "code" in qp:
        if not can_auth:
            st.error("❌ Cannot complete OAuth — one or more auth secrets are missing.")
            st.stop()

        resp = requests.post(
            TOKEN_URL,
            auth=requests.auth.HTTPBasicAuth(CLIENT_ID, CLIENT_SECRET),
            data={
                "grant_type": "authorization_code",
                "code": qp.get("code"),
                "redirect_uri": REDIRECT_URI,
            },
        )
        token = resp.json()

        if "access_token" in token:
            token["expires_at"] = time.time() + token.get("expires_in", 1800)
            st.session_state.token = token
            log_oauth_event("success", {"expires_in": token.get("expires_in")})
            st.rerun()
        else:
            log_oauth_event("failure", {"response": token})
            st.error("❌ OAuth token exchange failed.")
            st.stop()

    elif "error" in qp:
        log_oauth_event("failure", {
            "error": qp.get("error"),
            "desc": qp.get("error_description"),
        })
        st.error(f"❌ OAuth failed: {qp.get('error')}")
        st.stop()

    else:
        # Show login prompt
        if can_auth:
            login_url = AUTH_URL + "?" + urllib.parse.urlencode({
                "response_type": "code",
                "client_id": CLIENT_ID,
                "redirect_uri": REDIRECT_URI,
                "scope": SCOPES,
            })
            st.title("Xero AR Monitor")
            if st.button("🔑 Login to Xero"):
                st.markdown(
                    f"<meta http-equiv='refresh' content='0; url={login_url}'>",
                    unsafe_allow_html=True,
                )
        else:
            st.error("⚠️ Cannot build login URL — one or more auth secrets are missing or unset.")
        st.stop()

# =============================
# TOKEN REFRESH
# =============================
if time.time() > st.session_state.token.get("expires_at", 0):
    if not all([TOKEN_URL, CLIENT_ID, CLIENT_SECRET]):
        st.error("❌ Cannot refresh token — auth secrets missing.")
        st.session_state.token = None
        st.rerun()

    new_token = requests.post(
        TOKEN_URL,
        auth=requests.auth.HTTPBasicAuth(CLIENT_ID, CLIENT_SECRET),
        data={
            "grant_type": "refresh_token",
            "refresh_token": st.session_state.token.get("refresh_token"),
        },
    ).json()

    if "access_token" not in new_token:
        st.error("❌ Token refresh failed. Please log in again.")
        st.session_state.token = None
        st.rerun()

    new_token["expires_at"] = time.time() + new_token.get("expires_in", 1800)
    st.session_state.token = new_token

# =============================
# APP CONTINUES HERE (authenticated)
# =============================
st.success("✅ Authenticated with Xero")
