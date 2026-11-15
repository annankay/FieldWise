# FieldWise production image
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    FIELDWISE_HOST=0.0.0.0 FIELDWISE_PORT=8000 FIELDWISE_DATA_DIR=/data
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY backend ./backend
COPY frontend ./frontend
COPY scripts ./scripts
COPY run.py .

# downloaded NASA data lives on a persistent volume
RUN mkdir -p /data && useradd --create-home fieldwise && chown -R fieldwise /data /app
USER fieldwise
VOLUME ["/data"]
EXPOSE 8000
HEALTHCHECK --interval=60s --timeout=5s CMD python -c "import urllib.request,os;urllib.request.urlopen('http://127.0.0.1:'+os.environ.get('PORT',os.environ['FIELDWISE_PORT'])+'/api/health')"
# one worker: background downloads and job status live in this process
CMD ["sh", "-c", "uvicorn backend.api:app --host 0.0.0.0 --port ${PORT:-$FIELDWISE_PORT} --workers 1 --proxy-headers --forwarded-allow-ips='*'"]
