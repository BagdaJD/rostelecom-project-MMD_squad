FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1

WORKDIR /srv/backend

RUN apt-get update \
    && apt-get install -y --no-install-recommends libpq5 curl \
    && rm -rf /var/lib/apt/lists/*

COPY backend/pyproject.toml /srv/backend/pyproject.toml
RUN pip install --no-cache-dir --upgrade pip && pip install --no-cache-dir -e .

COPY backend /srv/backend

# Не root: требование ИБ к контейнеризуемым сервисам.
RUN useradd -m app && chown -R app /srv/backend
USER app

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
