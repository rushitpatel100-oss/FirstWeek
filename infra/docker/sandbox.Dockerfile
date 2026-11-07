# The one fixed image every code-sandbox job runs in (ADR 0017). No secrets, no network at run time.
FROM python:3.12-slim
RUN pip install --no-cache-dir pytest==8.3.4 numpy==2.2.2 pandas==2.2.3 requests==2.32.3
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 HOME=/tmp
WORKDIR /work
