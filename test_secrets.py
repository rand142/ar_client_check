# 📁 test_secrets_and_mongo.py
import streamlit as st
from pymongo.mongo_client import MongoClient
from pymongo.server_api import ServerApi

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
    client = MongoClient(st.secrets["MONGO_URI"], server_api=ServerApi('1'))
    client.admin.command('ping')
    st.success("✅ Pinged your deployment. Connected to MongoDB!")
    db = client[st.secrets["MONGO_DB"]]
    st.write("Collections:", db.list_collection_names())
except Exception as e:
    st.error(f"❌ MongoDB connection failed: {e}")
