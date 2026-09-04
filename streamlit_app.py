import os
import sys
import socket
import threading
import time
import urllib.request
import streamlit as st
import streamlit.components.v1 as components

# Ensure local project modules (astra, demo, training) are on Python path
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

st.set_page_config(
    page_title="ASTRA Safety & Calibration Dashboard",
    page_icon="🛡️",
    layout="wide",
    initial_sidebar_state="expanded",
)

def is_port_open(port: int = 8000) -> bool:
    """Check if the backend server port is listening."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) == 0

@st.cache_resource
def ensure_backend_server():
    """Ensure the ASTRA dashboard server is running in a background thread."""
    if is_port_open(8000):
        return True

    def run_server():
        try:
            from demo.dashboard import main
            main(["--port", "8000"])
        except Exception as e:
            print(f"Error starting dashboard server: {e}")

    thread = threading.Thread(target=run_server, daemon=True, name="astra-dashboard-bg")
    thread.start()

    # Wait up to 5 seconds for port to open
    for _ in range(25):
        if is_port_open(8000):
            break
        time.sleep(0.2)
    return True

# Initialize backend server
ensure_backend_server()

# Sidebar Navigation & Controls
st.sidebar.title("🛡️ ASTRA Control Center")
st.sidebar.caption("Autonomous Safety, Trust & Runtime Architecture")

st.sidebar.markdown("---")
st.sidebar.subheader("🎬 Scenario Selection")

def post_endpoint(endpoint: str):
    try:
        req = urllib.request.Request(f"http://127.0.0.1:8000{endpoint}", method="POST")
        urllib.request.urlopen(req, timeout=2.0)
    except Exception as e:
        st.sidebar.error(f"Action failed: {e}")

col1, col2 = st.sidebar.columns(2)
with col1:
    if st.button("🌌 Enter Tunnel", use_container_width=True):
        post_endpoint("/context/tunnel")
with col2:
    if st.button("🌫️ Heavy Fog", use_container_width=True):
        post_endpoint("/context/fog")

if st.sidebar.button("🛣️ Certified Road", use_container_width=True):
    post_endpoint("/context/road")

st.sidebar.markdown("---")
st.sidebar.subheader("⚠️ Inject Fault")

f_col1, f_col2 = st.sidebar.columns(2)
with f_col1:
    if st.button("🔴 IMU Dropout", use_container_width=True):
        post_endpoint("/fault/dropout")
    if st.button("📉 Position Drift", use_container_width=True):
        post_endpoint("/fault/position_drift")
with f_col2:
    if st.button("📍 Position Bias", use_container_width=True):
        post_endpoint("/fault/position_bias")
    if st.button("⚡ Speed Bias", use_container_width=True):
        post_endpoint("/fault/speed_bias")

st.sidebar.markdown("---")
if st.sidebar.button("↺ Restart / Reset Pipeline", type="primary", use_container_width=True):
    post_endpoint("/control/reset")

# Main Content Area: Embed Live HTML Dashboard
st.markdown(
    """
    <style>
    .block-container {
        padding-top: 1rem;
        padding-bottom: 0rem;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

st.title("🛡️ ASTRA Safety & Verification Dashboard")
st.caption("Live Closed-Loop Simulation with Real-Time OD-9 Telemetry & Core-B Safety Enforcement")

# Render Dashboard inside Streamlit Component IFrame
components.iframe("http://127.0.0.1:8000", height=900, scrolling=True)
