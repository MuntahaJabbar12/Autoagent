# Runs on Hugging Face Spaces (Docker), Render, Railway or any container host.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    OUTPUT_DIR=/tmp/autoagent-output \
    PORT=7860

# Hugging Face Spaces runs containers as user 1000.
RUN useradd -m -u 1000 app
WORKDIR /home/app/autoagent

COPY --chown=app requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY --chown=app app ./app
COPY --chown=app static ./static

USER app
EXPOSE 7860
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT} --proxy-headers --forwarded-allow-ips='*'"]
