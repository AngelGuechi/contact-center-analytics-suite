FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt ./
COPY 02-modern-ai/requirements.txt ./02-modern-ai/requirements.txt
RUN python -m pip install --no-cache-dir -r requirements.txt \
    && useradd --create-home --uid 10001 qa \
    && mkdir /data && chown qa:qa /data
COPY --chown=qa:qa . .
ENV QA_DATA_DIR=/data PYTHONUNBUFFERED=1
USER qa
EXPOSE 8503
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8503/_stcore/health',timeout=3)"
ENTRYPOINT ["python", "launch.py"]
CMD ["ai", "--host", "0.0.0.0", "--port", "8503"]
