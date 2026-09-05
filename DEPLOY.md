# Hosting the live dashboard

`demo/dashboard.py` is a complete web application: an `http.server` serving a
static page, a Server-Sent Events stream, and POST endpoints for the fault and
transport buttons. Hosting it needs a platform that runs a **process** and routes
a port to it.

## Why not Streamlit Community Cloud

It cannot work there, for three independent reasons:

1. **One port.** Streamlit Cloud routes its own app's port to the internet.
   A second HTTP server started inside the container is not reachable.
2. **`127.0.0.1` in an iframe is the *viewer's* machine.** An
   `<iframe src="http://127.0.0.1:8000">` is resolved by the visitor's browser,
   so it points at their laptop, not the server. This is why the iframe approach
   appears to work when you test it locally -- there, the viewer and the server
   really are the same host -- and shows nothing once hosted.
3. **Same-origin endpoints.** The page's JavaScript reads `/events` and posts to
   `/fault/...` and `/control/...` relative to its own origin. Those only exist
   on the dashboard server.

## Deploying

The image builds and runs anywhere that takes a Dockerfile. `HOST` and `PORT`
are read from the environment, which is the convention these platforms use.

```bash
docker build -t astra-dashboard .
docker run --rm -p 8000:8000 astra-dashboard
# then open http://127.0.0.1:8000/
```

### Hugging Face Spaces

Create a Space with SDK **Docker**, push this repository, and set the Space's
port to 8000. No other configuration is needed.

### Render / Railway / Fly.io

Point the service at the Dockerfile. Each of these sets `PORT` itself; the
dashboard reads it, so leave it alone. `HOST` is already `0.0.0.0` in the image.

## Local use

Unchanged, and still binds loopback by default:

```bash
uv run python -m demo.dashboard
uv run python -m demo.dashboard --port 8080 --host 0.0.0.0   # reachable on the LAN
```

## One operational note

There is no authentication. Anyone who can open the URL can press the fault
buttons and drive the vehicle into HALT. That is fine for a demonstration you are
presenting, and worth knowing before you share the link widely.
