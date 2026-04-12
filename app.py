# app.py
import streamlit as st
import pandas as pd
from xero_python.accounting import AccountingApi
from xero_python.api_client.oauth2 import OAuth2Token
from xero_python.api_client.configuration import Configuration
from xero_python.api_client.api_client import ApiClient

# -------------------------------
# CONFIGURATION
# -------------------------------
CLIENT_ID = "YOUR_CLIENT_ID"
CLIENT_SECRET = "YOUR_CLIENT_SECRET"
REDIRECT_URI = "YOUR_REDIRECT_URI"
TENANT_ID = "YOUR_TENANT_ID"

# -------------------------------
# AUTHENTICATION
# -------------------------------
# Note: In production, implement proper OAuth2 flow with token refresh.
config = Configuration(oauth2_token=OAuth2Token(
    client_id=CLIENT_ID,
    client_secret=CLIENT_SECRET,
    redirect_uri=REDIRECT_URI
))
api_client = ApiClient(config)
accounting_api = AccountingApi(api_client)

# -------------------------------
# STREAMLIT APP
# -------------------------------
st.title("📑 Client Statement List - Outstanding Amounts")

# Fetch invoices from Xero
try:
    invoices = accounting_api.get_invoices(TENANT_ID).invoices
except Exception as e:
    st.error(f"Error fetching invoices: {e}")
    st.stop()

# Convert invoices to DataFrame
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

# Highlight outstanding balances
def highlight_outstanding(val):
    return 'background-color: #ffcccc' if val > 0 else ''

st.subheader("Invoice Details")
st.dataframe(df.style.applymap(highlight_outstanding, subset=['Outstanding']))

# Summary totals
st.subheader("Summary Totals")
col1, col2, col3 = st.columns(3)
col1.metric("Total Invoiced", f"{df['Amount'].sum():,.2f}")
col2.metric("Total Paid", f"{df['Amount Paid'].sum():,.2f}")
col3.metric("Total Outstanding", f"{df['Outstanding'].sum():,.2f}")

# Filters
st.subheader("Filters")
status_filter = st.selectbox("Filter by Status", options=["All"] + df["Status"].unique().tolist())
if status_filter != "All":
    filtered_df = df[df["Status"] == status_filter]
    st.dataframe(filtered_df.style.applymap(highlight_outstanding, subset=['Outstanding']))

# Export option
st.download_button(
    label="Download Outstanding Report (CSV)",
    data=df.to_csv(index=False),
    file_name="client_statements.csv",
    mime="text/csv"
)