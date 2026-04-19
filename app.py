import streamlit as st
import pandas as pd
import requests
import urllib.parse
import time
import smtplib
import hashlib
from email.mime.text import MIMEText
from datetime import datetime, timezone
from pymongo import MongoClient
from pymongo.server_api import ServerApi
from sqlalchemy import create_engine, text

from xero_python.accounting import AccountingApi
from xero_python.identity import IdentityApi
from xero_python.api_client import ApiClient
from xero_python.api_client.configuration import Configuration

# =============================
# VALIDATION HELPER
# =============================
def validate_secrets(required_keys, placeholder_values=None):
    missing = [key for key in required_keys if key not in st.secrets]
    placeholders = []
    if missing:
        st.error(f"❌ Missing secrets: {', '.join(missing)}")
    if placeholder_values:
        placeholders = [key for key, val in placeholder_values.items()
                        if st.secrets.get(key) == val]
        if placeholders:
            st.warning(f"⚠️ Placeholders detected: {', '.join(placeholders)}")
        else:
            st.success("No placeholders detected!")
    if not missing and not placeholders:
        st.success("🎉 All required secrets are present and valid!")
    return missing, placeholders

# =============================
# SECRETS VALIDATION
# =============================
required_keys = [
    "CLIENT_ID","CLIENT_SECRET","REDIRECT_URI","SLACK_WEBHOOK",
    "EMAIL_HOST","EMAIL_PORT","EMAIL_USER","EMAIL_PASS",
    "MONGO_URI","MONGO_DB","AUTH_URL","TOKEN_URL","SCOPES","DB_CONN_STR"
]

placeholder_values = {
    "CLIENT_ID": "your_xero_client_id",
    "CLIENT_SECRET": "your_xero_client_secret",
    "REDIRECT_URI": "https://your-app.streamlit.app",
    "EMAIL_USER": "your@email.com",
    "EMAIL_PASS": "your_app_password",
    "DB_CONN_STR": "postgresql://user:password@host:5432/dbname",
    "SLACK_WEBHOOK": "https://hooks.slack.com/services/XXX/YYY/ZZZ",
    "MONGO_URI": "mongodb+srv://<db_username>:<db_password>@cluster0.qjjfboi.mongodb.net/?appName=Cluster0",
    "MONGO_DB": "app_db"
}

missing, placeholders = validate_secrets(required_keys, placeholder_values)

# =============================
# SECRET VARIABLES
# =============================
CLIENT_ID = st.secrets.get("CLIENT_ID")
CLIENT_SECRET = st.secrets.get("CLIENT_SECRET")
REDIRECT_URI = st.secrets.get("REDIRECT_URI")
SCOPES = st.secrets.get("SCOPES")
AUTH_URL = st.secrets.get("AUTH_URL")
TOKEN_URL = st.secrets.get("TOKEN_URL")
DB_CONN_STR = st.secrets.get("DB_CONN_STR")
SLACK_WEBHOOK = st.secrets.get("SLACK_WEBHOOK")
EMAIL_USER = st.secrets.get("EMAIL_USER")
EMAIL_PASS = st.secrets.get("EMAIL_PASS")
EMAIL_HOST = st.secrets.get("EMAIL_HOST")
EMAIL_PORT = int(st.secrets.get("EMAIL_PORT", 587))

# =============================
# SAFE LOGIN URL BUILD
# =============================
login_url = None
if AUTH_URL and CLIENT_ID and REDIRECT_URI and SCOPES:
    login_url = AUTH_URL + "?" + urllib.parse.urlencode({
        "client_id": CLIENT_ID,
        "redirect_uri": REDIRECT_URI,
        "response_type": "code",
        "scope": SCOPES
    })
    st.success("✅ Login URL built successfully")
else:
    st.warning("⚠️ Cannot build login URL because one or more secrets are missing.")

if login_url:
    if st.button("🔑 Login to Xero"):
        st.markdown(
            f"<meta http-equiv='refresh' content='0; url={login_url}'>",
            unsafe_allow_html=True
        )
else:
    st.button("🔑 Login to Xero", disabled=True)

# =============================
# DB CONNECTION
# =============================
DB_AVAILABLE = False
engine = None
if DB_CONN_STR:
    try:
        engine = create_engine(DB_CONN_STR)
        DB_AVAILABLE = True
        st.success("✅ Connected to relational DB")
    except Exception as e:
        st.error(f"❌ DB connection failed: {e}")

# =============================
# MONGO CONNECTION
# =============================
MONGO_AVAILABLE = False
db = None
try:
    client = MongoClient(st.secrets["MONGO_URI"], server_api=ServerApi('1'))
    client.admin.command('ping')
    db = client[st.secrets["MONGO_DB"]]
    alerts = db.alerts_log
    snapshot = db.ar_snapshot
    tokens = db.oauth_tokens
    MONGO_AVAILABLE = True
    st.success("✅ Connected to MongoDB")
except Exception as e:
    st.error(f"❌ MongoDB connection failed: {e}")

# =============================
# INDEX INITIALIZATION
# =============================
def init_indexes():
    if not MONGO_AVAILABLE:
        return
    from pymongo import ASCENDING, DESCENDING
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
        st.warning(f"⚠️ Index initialization failed: {e}")

init_indexes()

# =============================
# HELPERS
# =============================
def get_alert_key(client, action, amount):
    raw = f"{client}_{action}_{amount}"
    return hashlib.md5(raw.encode()).hexdigest()

def already_sent(key):
    if not DB_AVAILABLE:
        return False
    try:
        query = text("SELECT 1 FROM alerts_log WHERE alert_key = :key LIMIT 1")
        result = pd.read_sql(query, engine, params={"key": key})
        return not result.empty
    except Exception as e:
        st.warning(f"⚠️ already_sent failed: {e}")
        return False

def sent_recently(client):
    if not DB_AVAILABLE:
        return False
    try:
        query = text("""
            SELECT * FROM alerts_log
            WHERE client = :client
            AND created_at > NOW() - INTERVAL '3 days'
            LIMIT 1
        """)
        df = pd.read_sql(query, engine, params={"client": client})
        return not df.empty
    except Exception as e:
        st.warning(f"⚠️ sent_recently failed: {e}")
        return False

def log_alert(client, message, key):
    if not DB_AVAILABLE:
        return
    try:
        df = pd.DataFrame([{
            "client": client,
            "message": message,
            "alert_key": key,
            "created_at": datetime.utcnow()
        }])
        df.to_sql("alerts_log", engine, if_exists="append", index=False)
    except Exception as e:
        st.warning(f"⚠️ log_alert failed: {e}")

def send_slack(message, client, key):
    if not SLACK_WEBHOOK:
        st.warning("⚠️ Slack webhook not configured")
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
        st.error(f"Email failed: {e}")

# =============================
# SESSION
# =============================
if "token" not in st.session_state:
    st.session_state.token = None

# =============================
# AUTH + LOGGING
# =============================
qp = st.query_params

def log_oauth_event(status, details=None):
    if MONGO_AVAILABLE:
        alerts.insert_one({
            "event": "oauth_callback",
            "status": status,
            "details": details,
            "timestamp": datetime.utcnow()
        })

if st.session_state.token is None:
    if "code" in qp:
        token = requests.post(
            TOKEN_URL,
            auth=requests.auth.HTTPBasicAuth(CLIENT_ID, CLIENT_SECRET),
            data={
                "grant_type": "authorization_code",
                "code": qp["code"],
                "redirect_uri": REDIRECT_URI,
            },
        ).json()

        if "access_token" in token:
            token["expires_at"] = time.time() + token.get("expires_in", 1800)
            st.session_state.token = token
            log_oauth_event("success", {"expires_in": token.get("expires_in")})
            st.rerun()
        else:
            log_oauth_event("failure", {"response": token})
            st.error("❌ OAuth exchange failed.")
    elif "error" in qp:
        log_oauth_event("failure", {"error": qp["error"], "desc": qp.get("error_description")})
        st.error(f"❌ OAuth failed: {qp['error']}")
    else:
        login_url = AUTH_URL + "?" + urllib.parse.urlencode({
            "response_type": "code",
            "client_id": CLIENT_ID,
            "redirect_uri": REDIRECT_URI,
            "scope": SCOPES,
        })
        st.markdown(f"[Login to Xero]({login_url})")
        st.stop()

# Refresh token
if time.time() > st.session_state.token.get("expires_at", 0):
    new_token = requests.post(
        TOKEN_URL,
        auth=requests.auth.HTTPBasicAuth(CLIENT_ID, CLIENT_SECRET),
        data={
            "grant_type": "refresh_token",
            "refresh_token": st.session_state.token["refresh_token"],
        },
    ).json()

    new_token["expires_at"] = time.time() + new_token.get("expires_in", 1800)
    st.session_state.token = new_token
