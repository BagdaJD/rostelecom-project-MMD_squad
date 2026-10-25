FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1

WORKDIR /srv/backend

RUN apt-get update \
    && apt-get install -y --no-install-recommends libpq5 curl \
    && rm -rf /var/lib/apt/lists/*

COPY backend /srv/backend
ARG INSTALL_DEV=false
RUN if [ "$INSTALL_DEV" = "true" ]; then pip install --no-cache-dir -c constraints.txt -e '.[dev]'; \
    else pip install --no-cache-dir -c constraints.txt -e .; fi

RUN useradd -m app && mkdir -p /srv/backend/exports && chown -R app /srv/backend
USER app

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
