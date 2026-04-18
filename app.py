# =============================
# ADVANCED XERO STREAMLIT APP
# =============================
# Features:
# - Multi-tenant dashboard
# - Aging buckets (30/60/90)
# - Client risk scoring
# - Token auto-refresh
# - Session persistence
# - Caching + scheduled refresh
# - Secure secrets handling

import streamlit as st
import pandas as pd
import requests
import urllib.parse
import time
from datetime import datetime, timezone

from xero_python.accounting import AccountingApi
from xero_python.identity import IdentityApi
from xero_python.api_client import ApiClient
from xero_python.api_client.configuration import Configuration

# =============================
# SECRETS (use Streamlit secrets)
# =============================
CLIENT_ID = st.secrets["CLIENT_ID"]
CLIENT_SECRET = st.secrets["CLIENT_SECRET"]
REDIRECT_URI = st.secrets["REDIRECT_URI"]

AUTH_URL = "https://login.xero.com/identity/connect/authorize"
TOKEN_URL = "https://identity.xero.com/connect/token"
SCOPES = "offline_access accounting.transactions"

# =============================
# SESSION INIT
# =============================
if "token" not in st.session_state:
    st.session_state.token = None

if "tenant_ids" not in st.session_state:
    st.session_state.tenant_ids = {}

# =============================
# TOKEN HELPERS
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
# LOGIN FLOW
# =============================
query_params = st.query_params

if st.session_state.token is None:
    if "code" in query_params:
        code = query_params["code"]

        token = requests.post(
            TOKEN_URL,
            auth=requests.auth.HTTPBasicAuth(CLIENT_ID, CLIENT_SECRET),
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": REDIRECT_URI,
            },
        ).json()

        token["expires_at"] = time.time() + token.get("expires_in", 1800)
        st.session_state.token = token
        st.rerun()

    else:
        params = {
            "response_type": "code",
            "client_id": CLIENT_ID,
            "redirect_uri": REDIRECT_URI,
            "scope": SCOPES,
        }

        login_url = AUTH_URL + "?" + urllib.parse.urlencode(params)
        st.markdown(f"[Login to Xero]({login_url})")
        st.stop()

# =============================
# AUTO REFRESH TOKEN
# =============================
if token_expired(st.session_state.token):
    st.session_state.token = refresh_token(st.session_state.token)

# =============================
# API CLIENT
# =============================
config = Configuration(oauth2_token=st.session_state.token)
api_client = ApiClient(config)

# =============================
# LOAD TENANTS
# =============================
identity_api = IdentityApi(api_client)
tenants = identity_api.get_connections()

st.session_state.tenant_ids = {
    t.tenant_name: t.tenant_id for t in tenants
}

selected_tenants = st.multiselect(
    "Select Organisations",
    list(st.session_state.tenant_ids.keys()),
    default=list(st.session_state.tenant_ids.keys()),
)

# =============================
# DATA FETCH WITH CACHE
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

    data = []
    now = datetime.now(timezone.utc)

    for inv in invoices:
        due = inv.due_date or inv.date
        days_overdue = (now - due).days if due else 0

        data.append({
            "Tenant": tenant_id,
            "Client": inv.contact.name if inv.contact else "",
            "Invoice": inv.invoice_number,
            "Due Date": due,
            "Outstanding": float(inv.amount_due or 0),
            "Days Overdue": days_overdue,
        })

    return pd.DataFrame(data)

# =============================
# BUILD DATASET
# =============================
all_data = []

for name in selected_tenants:
    tenant_id = st.session_state.tenant_ids[name]
    df = fetch_invoices(st.session_state.token, tenant_id)
    df["Tenant Name"] = name
    all_data.append(df)

if not all_data:
    st.stop()

full_df = pd.concat(all_data, ignore_index=True)

# =============================
# AGING BUCKETS
# =============================
def assign_bucket(days):
    if days <= 30:
        return "0-30"
    elif days <= 60:
        return "31-60"
    elif days <= 90:
        return "61-90"
    else:
        return "90+"

full_df["Aging Bucket"] = full_df["Days Overdue"].apply(assign_bucket)

# =============================
# CLIENT RISK SCORING
# =============================
risk_df = full_df.groupby("Client").agg({
    "Outstanding": "sum",
    "Days Overdue": "max"
}).reset_index()


def risk_score(row):
    score = 0

    if row["Outstanding"] > 10000:
        score += 2
    if row["Days Overdue"] > 60:
        score += 2
    if row["Days Overdue"] > 90:
        score += 3

    return score

risk_df["Risk Score"] = risk_df.apply(risk_score, axis=1)

# =============================
# DASHBOARD
# =============================
st.title("📊 Multi-Tenant AR Dashboard")

col1, col2, col3 = st.columns(3)

col1.metric("Total Outstanding", f"{full_df['Outstanding'].sum():,.2f}")
col2.metric("Invoices", len(full_df))
col3.metric("High Risk Clients", (risk_df["Risk Score"] >= 4).sum())

# Aging summary
aging_summary = full_df.groupby("Aging Bucket")["Outstanding"].sum()
st.bar_chart(aging_summary)

# Risk table
st.subheader("Client Risk Overview")
st.dataframe(risk_df.sort_values("Risk Score", ascending=False))

# Detailed data
st.subheader("Invoice Details")
st.dataframe(full_df)

# Download
st.download_button(
    "Download Full Dataset",
    full_df.to_csv(index=False).encode("utf-8"),
    "ar_dashboard.csv",
    "text/csv",
)
