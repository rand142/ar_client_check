```python
import streamlit as st
import pandas as pd
import requests
import urllib.parse
import time
import smtplib
from email.mime.text import MIMEText
from datetime import datetime, timezone
import pyodbc
from sqlalchemy import create_engine

from xero_python.accounting import AccountingApi
from xero_python.identity import IdentityApi
from xero_python.api_client import ApiClient
from xero_python.api_client.configuration import Configuration

# =============================
# SECRETS (SET IN STREAMLIT)
# =============================
CLIENT_ID = st.secrets["CLIENT_ID"]
CLIENT_SECRET = st.secrets["CLIENT_SECRET"]
REDIRECT_URI = st.secrets["REDIRECT_URI"]

SLACK_WEBHOOK = st.secrets["SLACK_WEBHOOK"]

EMAIL_HOST = st.secrets["EMAIL_HOST"]
EMAIL_PORT = st.secrets["EMAIL_PORT"]
EMAIL_USER = st.secrets["EMAIL_USER"]
EMAIL_PASS = st.secrets["EMAIL_PASS"]

DB_CONN_STR = st.secrets["DB_CONN_STR"]

AUTH_URL = "https://login.xero.com/identity/connect/authorize"
TOKEN_URL = "https://identity.xero.com/connect/token"
SCOPES = "offline_access accounting.transactions"

# =============================
# SESSION INIT
# =============================
if "token" not in st.session_state:
    st.session_state.token = None

# =============================
# TOKEN MGMT
# =============================
def token_expired(token):
    return time.time() > token.get("expires_at", 0)

def refresh_token(token):
    response = requests.post(
        TOKEN_URL,
        auth=requests.auth.HTTPBasicAuth(CLIENT_ID, CLIENT_SECRET),
        data={
            "grant_type": "refresh_token",
            "refresh_token": token["refresh_token"],
        },
    ).json()

    response["expires_at"] = time.time() + response.get("expires_in", 1800)
    return response

# =============================
# AUTH FLOW
# =============================
query_params = st.query_params

if st.session_state.token is None:
    if "code" in query_params:
        token = requests.post(
            TOKEN_URL,
            auth=requests.auth.HTTPBasicAuth(CLIENT_ID, CLIENT_SECRET),
            data={
                "grant_type": "authorization_code",
                "code": query_params["code"],
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

if token_expired(st.session_state.token):
    st.session_state.token = refresh_token(st.session_state.token)

# =============================
# DB CONNECTION
# =============================
engine = create_engine(DB_CONN_STR)

def log_alert(client, message):
    df = pd.DataFrame([{
        "client": client,
        "message": message,
        "timestamp": datetime.utcnow()
    }])
    df.to_sql("alerts_log", engine, if_exists="append", index=False)

# =============================
# SLACK ALERT
# =============================
def send_slack(message, client):
    payload = {"text": message}
    requests.post(SLACK_WEBHOOK, json=payload, timeout=5)
    log_alert(client, message)

# =============================
# EMAIL SENDER
# =============================
def send_email(to_email, subject, body):
    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = EMAIL_USER
    msg["To"] = to_email

    with smtplib.SMTP(EMAIL_HOST, EMAIL_PORT) as server:
        server.starttls()
        server.login(EMAIL_USER, EMAIL_PASS)
        server.send_message(msg)

# =============================
# API CLIENT
# =============================
config = Configuration(oauth2_token=st.session_state.token)
api_client = ApiClient(config)

identity_api = IdentityApi(api_client)
tenants = identity_api.get_connections()
tenant_map = {t.tenant_name: t.tenant_id for t in tenants}

selected_tenants = st.multiselect(
    "Select Organisations",
    list(tenant_map.keys()),
    default=list(tenant_map.keys()),
)

# =============================
# FETCH DATA
# =============================
@st.cache_data(ttl=300)
def fetch_invoices(token, tenant_id):
    config = Configuration(oauth2_token=token)
    api_client = ApiClient(config)
    accounting_api = AccountingApi(api_client)

    invoices = accounting_api.get_invoices(
        tenant_id,
        where='Type=="ACCREC"'
    ).invoices

    now = datetime.now(timezone.utc)
    data = []

    for inv in invoices:
        due = inv.due_date or inv.date
        days = (now - due).days if due else 0

        data.append({
            "Client": inv.contact.name if inv.contact else "",
            "Email": getattr(inv.contact, "email_address", ""),
            "Invoice": inv.invoice_number,
            "Outstanding": float(inv.amount_due or 0),
            "Days Overdue": days
        })

    return pd.DataFrame(data)

frames = []
for name in selected_tenants:
    df = fetch_invoices(st.session_state.token, tenant_map[name])
    df["Tenant"] = name
    frames.append(df)

full_df = pd.concat(frames, ignore_index=True)

# =============================
# RISK + ACTION ENGINE
# =============================
def risk_score(row):
    score = 0
    if row["Outstanding"] > 20000: score += 3
    if row["Days Overdue"] > 90: score += 4
    elif row["Days Overdue"] > 60: score += 2
    return score

def action(row):
    if row["Risk Score"] >= 7:
        return "ESCALATE"
    elif row["Risk Score"] >= 5:
        return "CALL"
    elif row["Risk Score"] >= 3:
        return "EMAIL"
    return "MONITOR"

full_df["Risk Score"] = full_df.apply(risk_score, axis=1)
full_df["Action"] = full_df.apply(action, axis=1)

# =============================
# AUTOMATION ENGINE
# =============================
def process_actions(df):
    for _, row in df.iterrows():
        client = row["Client"]
        email = row["Email"]
        msg = f"{client} owes {row['Outstanding']} ({row['Days Overdue']} days overdue)"

        if row["Action"] == "EMAIL" and email:
            send_email(
                email,
                "Outstanding Invoice Reminder",
                f"Dear {client},\n\nPlease settle {row['Outstanding']}.\n"
            )

        elif row["Action"] == "CALL":
            send_slack(f"📞 Call client: {msg}", client)

        elif row["Action"] == "ESCALATE":
            send_slack(f"🚨 ESCALATE: {msg}", client)

# Run automation
if st.button("▶ Run Collections Automation"):
    process_actions(full_df)
    st.success("Automation executed")

# =============================
# DASHBOARD
# =============================
st.title("🚀 Autonomous Collections Engine")

st.metric("Total Outstanding", f"{full_df['Outstanding'].sum():,.2f}")
st.metric("High Risk", (full_df["Risk Score"] >= 5).sum())

st.dataframe(full_df.sort_values("Risk Score", ascending=False))

# =============================
# SAVE TO DB
# =============================
if st.button("💾 Save Snapshot to DB"):
    full_df.to_sql("ar_snapshot", engine, if_exists="append", index=False)
    st.success("Saved to SQL Server")

# =============================
# DOWNLOAD
# =============================
st.download_button(
    "Download CSV",
    full_df.to_csv(index=False),
    "collections.csv"
)
```
