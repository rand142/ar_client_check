import streamlit as st
import pandas as pd
from xero_python.accounting import AccountingApi
from xero_python.api_client.oauth2 import OAuth2Token
from xero_python.identity import IdentityApi
from xero_python.api_client.configuration import Configuration
from xero_python.api_client import ApiClient   # ✅ Correct import

# -------------------------------
# CONFIGURATION
# -------------------------------
CLIENT_ID = "YOUR_CLIENT_ID"
CLIENT_SECRET = "YOUR_CLIENT_SECRET"
REDIRECT_URI = "https://your-app.streamlit.app"  # your deployed Streamlit app URL

# -------------------------------
# STREAMLIT APP
# -------------------------------
st.title("📑 Client Statement List - Outstanding Amounts")

if "token" not in st.session_state:
    st.session_state.token = None
if "tenant_id" not in st.session_state:
    st.session_state.tenant_id = None

# Build OAuth2 API client (no redirect_uri here)
config = Configuration(oauth2_token=OAuth2Token(
    client_id=CLIENT_ID,
    client_secret=CLIENT_SECRET
))
api_client = ApiClient(config)
identity_api = IdentityApi(api_client)

# Step 1: If not logged in, show login button
if st.session_state.token is None:
    query_params = st.query_params   # ✅ updated for Streamlit 1.56
    if "code" in query_params:
        # Step 2: Exchange code for token
        code = query_params["code"][0]
        token = identity_api.exchange_code_for_token(code, redirect_uri=REDIRECT_URI)
        st.session_state.token = token
        st.success("✅ Logged in to Xero!")
    else:
        # Step 1a: Show login button
        auth_url = identity_api.build_authorization_url(
            scope=["accounting.transactions offline_access"],
            redirect_uri=REDIRECT_URI
        )
        st.markdown(f"[Login to Xero]({auth_url})")

# Step 2: If logged in, refresh token if needed
if st.session_state.token:
    if st.session_state.token.is_expired():
        st.session_state.token = identity_api.refresh_token(st.session_state.token)
        st.info("🔄 Token refreshed automatically")

    # Fetch available tenants
    tenants = identity_api.get_connections()
    tenant_options = {t.tenant_name: t.tenant_id for t in tenants}

    # Tenant selection dropdown
    if not st.session_state.tenant_id:
        selected_name = st.selectbox("Select Xero Organisation", list(tenant_options.keys()))
        if selected_name:
            st.session_state.tenant_id = tenant_options[selected_name]
            st.success(f"✅ Selected tenant: {selected_name}")

# Step 3: If tenant selected, fetch invoices
if st.session_state.token and st.session_state.tenant_id:
    api_client = ApiClient(Configuration(oauth2_token=st.session_state.token))
    accounting_api = AccountingApi(api_client)

    invoices = accounting_api.get_invoices(st.session_state.tenant_id).invoices
    data = []
    for inv in invoices:
        data.append({
            "Client": inv.contact.name,
            "Invoice #": inv.invoice_number,
            "Invoice Date": inv.date,
            "Due Date": inv.due_date,
            "Amount": inv.total,
            "Amount Paid": inv.amount_paid,
            "Outstanding": inv.amount_due,
            "Status": inv.status
        })
    df = pd.DataFrame(data)

    # Status filter
    status_options = df["Status"].unique().tolist()
    selected_status = st.selectbox("Filter by invoice status", ["All"] + status_options)

    if selected_status != "All":
        df = df[df["Status"] == selected_status]

    # Outstanding filter
    show_outstanding_only = st.checkbox("Show only invoices with outstanding balance")
    if show_outstanding_only:
        df = df[df["Outstanding"] > 0]

    st.dataframe(df)
