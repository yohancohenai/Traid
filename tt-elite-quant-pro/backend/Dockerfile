FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 postgresql-client && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY pyproject.toml ./
COPY ttq ./ttq
RUN pip install --no-cache-dir -e ".[dev]"
COPY alembic.ini ./
COPY alembic ./alembic
COPY scripts ./scripts
COPY tests ./tests
RUN useradd -m ttq && mkdir -p /app/artifacts && chown -R ttq /app
USER ttq
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request;urllib.request.urlopen('http://localhost:8000/api/health')"
CMD ["sh", "-c", "alembic upgrade head && uvicorn ttq.main:app --host 0.0.0.0 --port 8000 --workers 2 --proxy-headers --forwarded-allow-ips='*'"]
