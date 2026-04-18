# 📁 test_secrets_and_mongo.py
import streamlit as st
from pymongo import MongoClient

st.title("🔑 Secrets & MongoDB Test")

# List of required keys
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
    "SCOPES"
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
# MongoDB connection test
# -------------------------------
try:
    client = MongoClient(st.secrets["MONGO_URI"])
    db = client[st.secrets["MONGO_DB"]]

    collections = db.list_collection_names()
    if collections:
        st.success(f"📂 Connected to MongoDB! Collections: {collections}")
    else:
        st.warning("⚠️ Connected to MongoDB, but no collections found.")
except Exception as e:
    st.error(f"❌ MongoDB connection failed: {e}")
