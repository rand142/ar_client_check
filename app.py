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
from sqlalchemy import create_engine, text

from xero_python.accounting import AccountingApi
from xero_python.identity import IdentityApi
from xero_python.api_client import ApiClient
from xero_python.api_client.configuration import Configuration

# =============================
# VALIDATION HELPER
# =============================
def validate_secrets(required_keys, placeholder_values=None):
    """
    Validate secrets at startup.
    Returns (missing, placeholders) lists.
    """
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
# SAFE LOGIN URL BUILD
# =============================
AUTH_URL = st.secrets.get("AUTH_URL")
CLIENT_ID = st.secrets.get("CLIENT_ID")
REDIRECT_URI = st.secrets.get("REDIRECT_URI")
SCOPES = st.secrets.get("SCOPES")

if AUTH_URL and CLIENT_ID and REDIRECT_URI and SCOPES:
    login_url = AUTH_URL + "?" + urllib.parse.urlencode({
        "client_id": CLIENT_ID,
        "redirect_uri": REDIRECT_URI,
        "response_type": "code",
        "scope": SCOPES
    })
    st.success("✅ Login URL built successfully")
else:
    login_url = None
    st.warning("⚠️ Cannot build login URL because one or more secrets are missing.")

# =============================
# DB CONNECTION
# =============================
DB_AVAILABLE = False
engine = None

if st.secrets.get("DB_CONN_STR"):
    try:
        engine = create_engine(st.secrets["DB_CONN_STR"])
        DB_AVAILABLE = True
        st.success("✅ Connected to relational DB")
    except Exception as e:
        st.warning(f"⚠️ DB connection failed: {e}")


# =============================
# MONGO CONNECTION
# =============================
from pymongo.server_api import ServerApi

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
except KeyError as ke:
    st.warning(f"⚠️ Missing secret: {ke}")
except Exception as e:
    st.warning(f"⚠️ MongoDB connection failed: {e}")

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

# Run once at startup
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
        query = text("SELECT 1 FROM alerts_log WHERE alert_key = :key")
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
            SELECT TOP 1 * FROM alerts_log
            WHERE client = :client
            AND created_at > DATEADD(day, -3, GETDATE())
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
        st.warning(f"⚠️ Email send failed: {e}")

# =============================
# SLACK
# =============================
def send_slack(message, client, key):
    if already_sent(key):
        return
    requests.post(SLACK_WEBHOOK, json={"text": message}, timeout=5)
    log_alert(client, message, key)

# =============================
# EMAIL (WITH TONE)
# =============================
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
# AUTH
# =============================
qp = st.query_params

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

        token["expires_at"] = time.time() + token.get("expires_in", 1800)
        st.session_state.token = token
        st.rerun()
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

# =============================
# API
# =============================
api_client = ApiClient(Configuration(oauth2_token=st.session_state.token))
identity_api = IdentityApi(api_client)

tenant_map = {t.tenant_name: t.tenant_id for t in identity_api.get_connections()}

selected = st.multiselect(
    "Select Organisations",
    list(tenant_map.keys()),
    default=list(tenant_map.keys())
)

# =============================
# FETCH
# =============================
@st.cache_data(ttl=300)
def fetch(token, tenant):
    api = AccountingApi(ApiClient(Configuration(oauth2_token=token)))
    invs = api.get_invoices(tenant, where='Type=="ACCREC"').invoices

    now = datetime.now(timezone.utc)
    rows = []

    for i in invs:
        due = i.due_date or i.date
        days = (now - due).days if due else 0

        rows.append({
            "Client": i.contact.name if i.contact else "",
            "Email": getattr(i.contact, "email_address", ""),
            "Outstanding": float(i.amount_due or 0),
            "Days Overdue": days
        })

    return pd.DataFrame(rows)

frames = [fetch(st.session_state.token, tenant_map[t]) for t in selected]

if not frames:
    st.warning("No data found")
    st.stop()

df = pd.concat(frames, ignore_index=True)

# =============================
# RISK + ACTION
# =============================
def risk(r):
    s = 0
    if r["Outstanding"] > 20000: s += 3
    if r["Days Overdue"] > 90: s += 4
    elif r["Days Overdue"] > 60: s += 2
    return s

def action(r):
    if r["Risk"] >= 7: return "ESCALATE"
    if r["Risk"] >= 5: return "CALL"
    if r["Risk"] >= 3: return "EMAIL"
    return "MONITOR"

df["Risk"] = df.apply(risk, axis=1)
df["Action"] = df.apply(action, axis=1)

# =============================
# AUTOMATION
# =============================
def run(df):
    for _, r in df.iterrows():
        client = r["Client"]
        amount = r["Outstanding"]
        key = get_alert_key(client, r["Action"], amount)

        msg = f"{client} owes {amount} ({r['Days Overdue']} days)"

        if r["Action"] == "EMAIL" and r["Email"]:
            body = generate_email(client, amount, r["Days Overdue"])
            send_email(r["Email"], "Invoice Reminder", body, client, key)

        elif r["Action"] == "CALL":
            send_slack(f"📞 Call: {msg}", client, key)

        elif r["Action"] == "ESCALATE":
            send_slack(f"🚨 ESCALATE: {msg}", client, key)

# =============================
# UI
# =============================
st.title("🚀 Autonomous Collections Engine")

st.metric("Total AR", f"{df['Outstanding'].sum():,.2f}")
st.metric("High Risk", (df["Risk"] >= 5).sum())

if st.button("▶ Run Automation"):
    run(df)
    st.success("Automation complete")

st.dataframe(df.sort_values("Risk", ascending=False))

# =============================
# SAVE
# =============================
if st.button("💾 Save Snapshot"):
    if DB_AVAILABLE:
        df.to_sql("ar_snapshot", engine, if_exists="append", index=False)
        st.success("Saved to DB")
    else:
        st.warning("DB not available")
