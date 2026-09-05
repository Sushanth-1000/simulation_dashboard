# The dashboard, as a hosted web process.
#
# This is a real web application already -- an http.server with an SSE stream
# and POST endpoints -- so it needs a platform that runs a process and routes a
# port to it (Hugging Face Spaces, Render, Railway, Fly.io). It cannot be hosted
# by Streamlit Community Cloud, which routes one port to the Streamlit app and
# nothing else; an iframe pointing at 127.0.0.1 resolves to the *viewer's*
# machine, which is why that approach works on a laptop and nowhere else.

FROM python:3.12-slim

# Keeps the image small and the logs unbuffered, so a platform's log view shows
# the drive's output as it happens rather than when the buffer flushes.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Dependencies first, so an edit to the source does not re-download torch.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Only what the dashboard actually runs. The research tree -- experiments/,
# research/, benchmarks/, A-Z/ -- is deliberately not copied: it is not needed
# to serve the demonstration, and it is a large amount of unpublished material
# to put inside a public image.
COPY pyproject.toml README.md LICENSE NOTICE ./
COPY src/ ./src/
COPY demo/ ./demo/
COPY training/ ./training/
COPY config/ ./config/
COPY var/policy/synthetic.pt ./var/policy/synthetic.pt
COPY var/twin/ ./var/twin/
COPY var/calibration/ ./var/calibration/

# Installs `astra` from src/ so the package is importable without PYTHONPATH
# games. --no-deps because requirements.txt already pinned the runtime set and
# the project's own extras would pull stable-baselines3, which the dashboard
# never imports.
RUN pip install --no-cache-dir --no-deps -e .

# The platform supplies PORT; 0.0.0.0 is required or its proxy cannot reach us.
ENV HOST=0.0.0.0 \
    PORT=8000
EXPOSE 8000

CMD ["python", "-m", "demo.dashboard"]
