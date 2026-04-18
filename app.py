# =============================
# FULL AR INTELLIGENCE PLATFORM
# =============================
# Features:
# - Multi-tenant AR aggregation
# - Aging + DSO + cashflow forecasting
# - Advanced risk scoring (behavioral + exposure)
# - Token auto-refresh + secure auth
# - Cached + scalable data layer
# =============================

import streamlit as st
import pandas as pd
import requests
import urllib.parse
import time
from datetime import datetime, timezone, timedelta

from xero_python.accounting import AccountingApi
from xero_python.identity import IdentityApi
from xero_python.api_client import ApiClient
from xero_python.api_client.configuration import Configuration

# =============================
# SECRETS
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

if token_expired(st.session_state.token):
    st.session_state.token = refresh_token(st.session_state.token)

# =============================
# API CLIENT
# =============================
config = Configuration(oauth2_token=st.session_state.token)
api_client = ApiClient(config)

# =============================
# TENANTS
# =============================
identity_api = IdentityApi(api_client)
tenants = identity_api.get_connections()

tenant_map = {t.tenant_name: t.tenant_id for t in tenants}

selected_tenants = st.multiselect(
    "Select Organisations",
    list(tenant_map.keys()),
    default=list(tenant_map.keys()),
)

# =============================
# DATA FETCH
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
        days_overdue = (now - due).days if due else 0

        data.append({
            "Tenant": tenant_id,
            "Client": inv.contact.name if inv.contact else "",
            "Invoice": inv.invoice_number,
            "Date": inv.date,
            "Due Date": due,
            "Outstanding": float(inv.amount_due or 0),
            "Days Overdue": days_overdue,
        })

    return pd.DataFrame(data)

# =============================
# BUILD DATA
# =============================
frames = []

for name in selected_tenants:
    df = fetch_invoices(st.session_state.token, tenant_map[name])
    df["Tenant Name"] = name
    frames.append(df)

if not frames:
    st.stop()

full_df = pd.concat(frames, ignore_index=True)

# =============================
# AGING
# =============================
def aging_bucket(days):
    if days <= 30:
        return "0-30"
    elif days <= 60:
        return "31-60"
    elif days <= 90:
        return "61-90"
    return "90+"

full_df["Aging Bucket"] = full_df["Days Overdue"].apply(aging_bucket)

# =============================
# DSO (Days Sales Outstanding)
# =============================
# Simplified: avg overdue days weighted
DSO = (full_df["Outstanding"] * full_df["Days Overdue"]).sum() / max(full_df["Outstanding"].sum(), 1)

# =============================
# CASHFLOW FORECAST
# =============================
def forecast(row):
    if row["Days Overdue"] <= 0:
        return datetime.now() + timedelta(days=7)
    elif row["Days Overdue"] <= 30:
        return datetime.now() + timedelta(days=14)
    elif row["Days Overdue"] <= 60:
        return datetime.now() + timedelta(days=30)
    else:
        return datetime.now() + timedelta(days=60)

full_df["Expected Payment Date"] = full_df.apply(forecast, axis=1)

# =============================
# ADVANCED RISK MODEL
# =============================
risk_df = full_df.groupby("Client").agg({
    "Outstanding": "sum",
    "Days Overdue": "max",
    "Invoice": "count"
}).reset_index()


def risk_score(row):
    score = 0

    # Exposure risk
    if row["Outstanding"] > 20000:
        score += 3
    elif row["Outstanding"] > 10000:
        score += 2

    # Delinquency
    if row["Days Overdue"] > 90:
        score += 4
    elif row["Days Overdue"] > 60:
        score += 2

    # Behavioral (many invoices unpaid)
    if row["Invoice"] > 5:
        score += 1

    return score

risk_df["Risk Score"] = risk_df.apply(risk_score, axis=1)

# =============================
# DASHBOARD
# =============================
st.title("🚀 AR Intelligence Platform")

col1, col2, col3, col4 = st.columns(4)

col1.metric("Total AR", f"{full_df['Outstanding'].sum():,.2f}")
col2.metric("Invoices", len(full_df))
col3.metric("DSO", f"{DSO:.1f} days")
col4.metric("High Risk Clients", (risk_df["Risk Score"] >= 5).sum())

# Aging chart
st.subheader("Aging Distribution")
st.bar_chart(full_df.groupby("Aging Bucket")["Outstanding"].sum())

# Forecast
st.subheader("Cashflow Forecast")
forecast_df = full_df.groupby("Expected Payment Date")["Outstanding"].sum()
st.line_chart(forecast_df)

# Risk
st.subheader("Client Risk Ranking")
st.dataframe(risk_df.sort_values("Risk Score", ascending=False))

# Detail
st.subheader("Invoice Level Detail")
st.dataframe(full_df)

# Download
st.download_button(
    "Download Full Dataset",
    full_df.to_csv(index=False).encode("utf-8"),
    "ar_intelligence.csv",
    "text/csv",
)
