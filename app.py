import streamlit as st
import pandas as pd
import requests
import urllib.parse
from xero_python.accounting import AccountingApi
from xero_python.identity import IdentityApi
from xero_python.api_client import ApiClient
from xero_python.api_client.configuration import Configuration

# -------------------------------
# CONFIGURATION
# -------------------------------
CLIENT_ID = "YOUR_CLIENT_ID"
CLIENT_SECRET = "YOUR_CLIENT_SECRET"
REDIRECT_URI = "https://your-app.streamlit.app"

AUTH_URL = "https://login.xero.com/identity/connect/authorize"
TOKEN_URL = "https://identity.xero.com/connect/token"

SCOPES = "offline_access accounting.transactions"

# -------------------------------
# STREAMLIT STATE
# -------------------------------
if "token" not in st.session_state:
    st.session_state.token = None

if "tenant_id" not in st.session_state:
    st.session_state.tenant_id = None

# -------------------------------
# UI
# -------------------------------
st.title("📑 Client Statement List - Outstanding Amounts")

# -------------------------------
# STEP 1: LOGIN
# -------------------------------
query_params = st.query_params

if st.session_state.token is None:

    # Handle redirect with code
    if "code" in query_params:
        code = query_params["code"]

        basic_auth = requests.auth.HTTPBasicAuth(CLIENT_ID, CLIENT_SECRET)

        response = requests.post(
            TOKEN_URL,
            auth=basic_auth,
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": REDIRECT_URI,
            },
        )

        token = response.json()

        if "access_token" in token:
            st.session_state.token = token
            st.success("✅ Logged in to Xero!")
            st.rerun()
        else:
            st.error(f"Token error: {token}")

    else:
        # Build login URL manually
        params = {
            "response_type": "code",
            "client_id": CLIENT_ID,
            "redirect_uri": REDIRECT_URI,
            "scope": SCOPES,
        }

        login_url = AUTH_URL + "?" + urllib.parse.urlencode(params)

        st.markdown(f"[🔐 Login to Xero]({login_url})")
        st.stop()

# -------------------------------
# STEP 2: API CLIENT
# -------------------------------
config = Configuration(oauth2_token=st.session_state.token)
api_client = ApiClient(config)

# -------------------------------
# STEP 3: GET TENANTS
# -------------------------------
identity_api = IdentityApi(api_client)
tenants = identity_api.get_connections()

tenant_map = {t.tenant_name: t.tenant_id for t in tenants}

if not st.session_state.tenant_id:
    selected = st.selectbox("Select Xero Organisation", list(tenant_map.keys()))

    if selected:
        st.session_state.tenant_id = tenant_map[selected]
        st.rerun()

# -------------------------------
# STEP 4: FETCH INVOICES
# -------------------------------
accounting_api = AccountingApi(api_client)

invoices = accounting_api.get_invoices(
    st.session_state.tenant_id,
    where='Type=="ACCREC"'
).invoices

data = []
for inv in invoices:
    data.append({
        "Client": inv.contact.name if inv.contact else "",
        "Invoice #": inv.invoice_number,
        "Invoice Date": inv.date,
        "Due Date": inv.due_date,
        "Amount": float(inv.total or 0),
        "Amount Paid": float(inv.amount_paid or 0),
        "Outstanding": float(inv.amount_due or 0),
        "Status": inv.status
    })

df = pd.DataFrame(data)

# -------------------------------
# FILTERS
# -------------------------------
status_options = sorted(df["Status"].dropna().unique().tolist())
selected_status = st.selectbox("Filter by status", ["All"] + status_options)

if selected_status != "All":
    df = df[df["Status"] == selected_status]

if st.checkbox("Show only outstanding"):
    df = df[df["Outstanding"] > 0]

# -------------------------------
# DISPLAY
# -------------------------------
st.dataframe(df, use_container_width=True)

# -------------------------------
# DOWNLOAD
# -------------------------------
csv = df.to_csv(index=False).encode("utf-8")

st.download_button(
    "📥 Download CSV",
    csv,
    "invoices.csv",
    "text/csv"
)
