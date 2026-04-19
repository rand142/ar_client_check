# 📁 test_secrets.py
import streamlit as st
from pymongo.mongo_client import MongoClient
from pymongo.server_api import ServerApi

st.title("🔑 Secrets & MongoDB Test")

# -------------------------------
# Required keys check
# -------------------------------
required_keys = [
    "CLIENT_ID",
    "CLIENT_SECRET",
    "REDIRECT_URI",
    "SLACK_WEBHOOK",
    "EMAIL_HOST",
    "EMAIL_PORT",
    "EMAIL_USER",
    "EMAIL_PASS",
    "MONGO_URI",
    "MONGO_DB",
    "AUTH_URL",
    "TOKEN_URL",
    "SCOPES",
    "DB_CONN_STR"
]

missing = []
for key in required_keys:
    if key not in st.secrets:
        missing.append(key)
    else:
        st.write(f"✅ {key} found")

if missing:
    st.error(f"❌ Missing secrets: {', '.join(missing)}")
else:
    st.success("🎉 All required secrets are present!")

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
    "MONGO_URI": "mongodb+srv://<db_username>:<db_password>@cluster0.qjjfboi.mongodb.net/?appName=Cluster0",
}

for key, placeholder in PLACEHOLDER_VALUES.items():
    if st.secrets.get(key) == placeholder:
        st.warning(f"⚠️ Secret {key} is still a placeholder. Please update it with a real value.")

# -------------------------------
# MongoDB connection test
# -------------------------------
try:
    client = MongoClient(st.secrets["MONGO_URI"], server_api=ServerApi('1'))
    client.admin.command('ping')
    st.success("✅ Pinged your deployment. Connected to MongoDB!")
    db = client[st.secrets["MONGO_DB"]]
    st.write("Collections:", db.list_collection_names())
except Exception as e:
    st.error(f"❌ MongoDB connection failed: {e}")
