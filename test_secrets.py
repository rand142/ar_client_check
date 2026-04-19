# 📁 test_secrets.py
import streamlit as st
from pymongo.mongo_client import MongoClient
from pymongo.server_api import ServerApi

st.title("🔑 Secrets & MongoDB Test")

# -------------------------------
# Required keys check
# -------------------------------
required_keys = [
    "CLIENT_ID","CLIENT_SECRET","REDIRECT_URI","SLACK_WEBHOOK",
    "EMAIL_HOST","EMAIL_PORT","EMAIL_USER","EMAIL_PASS",
    "MONGO_URI","MONGO_DB","AUTH_URL","TOKEN_URL","SCOPES","DB_CONN_STR"
]

present = []
missing = []

for key in required_keys:
    if key in st.secrets:
        present.append(key)
    else:
        missing.append(key)

# -------------------------------
# Placeholder detection
# -------------------------------
PLACEHOLDER_VALUES = {
    "CLIENT_ID": "your_xero_client_id",
    "CLIENT_SECRET": "your_xero_client_secret",
    "REDIRECT_URI": "https://your-app.streamlit.app",
    "EMAIL_USER": "your@email.com",
    "EMAIL_PASS": "your_app_password",
    "DB_CONN_STR": "postgresql://user:password@host:5432/dbname",
    "SLACK_WEBHOOK": "https://hooks.slack.com/services/XXX/YYY/ZZZ",
    "MONGO_URI": "mongodb+srv://randalltoerien_db_user:4cDJN0WFRkIKpFc7@cluster0.qjjfboi.mongodb.net/?retryWrites=true&w=majority",
    "MONGO_DB": "app_db"
}

placeholders = []
for key, placeholder in PLACEHOLDER_VALUES.items():
    if st.secrets.get(key) == placeholder:
        placeholders.append(key)

# -------------------------------
# Output formatting
# -------------------------------
st.subheader("✅ Secrets Present")
if present:
    st.write(", ".join(present))
else:
    st.error("No secrets found!")

if missing:
    st.subheader("❌ Missing Secrets")
    st.error(", ".join(missing))

if placeholders:
    st.subheader("⚠️ Placeholders Detected")
    st.warning(", ".join(placeholders))
else:
    st.success("No placeholders detected!")

# -------------------------------
# MongoDB connection test
# -------------------------------
st.subheader("🔗 MongoDB Connection")
try:
    client = MongoClient(st.secrets["MONGO_URI"], server_api=ServerApi('1'))
    client.admin.command('ping')
    db = client[st.secrets["MONGO_DB"]]
    st.success("✅ Pinged your deployment. Connected to MongoDB!")
    st.write("Collections:", db.list_collection_names())
except Exception as e:
    st.error(f"❌ MongoDB connection failed: {e}")
