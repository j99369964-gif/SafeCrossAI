# Build from the REPOSITORY ROOT so the image can include app/, models/ and data/:
#     docker build -f pwa/Dockerfile -t safecross-pwa .
#     docker run -p 8000:8000 --env-file pwa/.env safecross-pwa
FROM python:3.12-slim

WORKDIR /srv
ENV PYTHONUNBUFFERED=1 PORT=8000

COPY pwa/requirements.txt /srv/pwa/requirements.txt
RUN pip install --no-cache-dir -r /srv/pwa/requirements.txt

# The server shares the Streamlit app's Streamlit-free modules (app/safecross_core.py, app/route_utils.py)
# and loads the trained model bundle and the demo data at start-up.
COPY app/safecross_core.py app/route_utils.py /srv/app/
COPY pwa/server /srv/pwa/server
COPY pwa/web /srv/pwa/web
COPY models /srv/models
COPY data/sample /srv/data/sample
COPY reports /srv/reports

# One worker: the rate limiter keeps its counts in memory. For several workers, move it to a shared store (e.g. Redis).
CMD ["sh", "-c", "gunicorn 'server:create_app()' --chdir /srv/pwa/server --bind 0.0.0.0:${PORT} --workers 1 --threads 4 --timeout 60"]
