FROM python:3.11-slim

RUN useradd -m -u 1000 user
WORKDIR /app

COPY --chown=user:user requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY --chown=user:user . .
RUN mkdir -p /app/data && chown -R user:user /app/data

USER user

ENV HOME=/home/user \
    PATH="/home/user/.local/bin:$PATH" \
    PORT=7860 \
    PYTHONUNBUFFERED=1

EXPOSE 7860

CMD ["sh", "-c", "uvicorn backend.app:app --host 0.0.0.0 --port ${PORT:-7860}"]
