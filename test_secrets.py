import streamlit as st

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

st.title("🔑 Secrets Test")

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
