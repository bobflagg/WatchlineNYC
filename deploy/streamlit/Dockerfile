# The Streamlit app image. Build context is the repo root (see docker-compose.yml),
# so paths below are repo-relative.
FROM python:3.13-slim

# uv resolves + installs from the committed lock for a reproducible env.
RUN pip install --no-cache-dir uv

WORKDIR /app

# Dependency layer: copy only the lock inputs first so image builds cache well.
COPY pyproject.toml uv.lock README.md ./
COPY watchline ./watchline
RUN uv sync --frozen --no-dev

# Belt-and-suspenders so `import watchline...` resolves regardless of how the
# project is packaged.
ENV PYTHONPATH=/app

EXPOSE 8501

# Bind all interfaces (Caddy proxies to it). CORS/XSRF are disabled because the
# app sits behind Caddy basic-auth on a single origin — this avoids WebSocket
# handshake friction through the proxy for a gated POC.
CMD ["uv", "run", "streamlit", "run", "watchline/discovery/ui/app.py", \
     "--server.port=8501", "--server.address=0.0.0.0", \
     "--server.headless=true", "--browser.gatherUsageStats=false", \
     "--server.enableCORS=false", "--server.enableXsrfProtection=false"]
