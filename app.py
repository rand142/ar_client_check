import streamlit as st
import pandas as pd
from urllib.parse import urlparse, parse_qs
from xero_python.accounting import AccountingApi
from xero_python.api_client.oauth2 import OAuth2Token, OAuth2Api
from xero_python.api_client.configuration import Configuration
from xero_python.api_client.api_client import ApiClient

# -------------------------------
# CONFIGURATION
# -------------------------------
CLIENT_ID = "YOUR_CLIENT_ID"
CLIENT_SECRET = "YOUR_CLIENT_SECRET"
REDIRECT_URI = "https://your-app.streamlit.app"  # your deployed Streamlit app URL
TENANT_ID = "YOUR_TENANT_ID"

# -------------------------------
# STREAMLIT APP
# -------------------------------
st.title("📑 Client Statement List - Outstanding Amounts")

if "token" not in st.session_state:
    st.session_state.token = None

# Build OAuth2 API client
config = Configuration(oauth2_token=OAuth2Token(
    client_id=CLIENT_ID,
    client_secret=CLIENT_SECRET,
    redirect_uri=REDIRECT_URI
))
api_client = ApiClient(config)
oauth2_api = OAuth2Api(api_client)

# Step 1: If not logged in, show login button
if st.session_state.token is None:
    # Check if redirect URL contains code
    query_params = st.experimental_get_query_params()
    if "code" in query_params:
        # Step 2: Exchange code for token
        code = query_params["code"][0]
        token = oauth2_api.exchange_code_for_token(code)
        st.session_state.token = token
        st.success("✅ Logged in to Xero!")
    else:
        # Step 1a: Show login button
        auth_url = oauth2_api.build_authorization_url(scope=["accounting.transactions"])
        st.markdown(f"[Login to Xero]({auth_url})")

# Step 3: If logged in, fetch invoices
if st.session_state.token:
    api_client = ApiClient(Configuration(oauth2_token=st.session_state.token))
    accounting_api = AccountingApi(api_client)

    invoices = accounting_api.get_invoices(TENANT_ID).invoices
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

    st.dataframe(df)
