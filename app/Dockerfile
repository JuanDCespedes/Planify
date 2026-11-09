FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8000

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && groupadd --system planify \
    && useradd --system --gid planify --home-dir /app planify \
    && mkdir -p /data /identity /planning /notifications /legacy \
    && chown planify:planify /data /identity /planning /notifications /legacy

COPY --chown=planify:planify . .

ENV PLANIFY_ENV=production \
    PLANIFY_DATABASE_URL=sqlite:////data/planify.db

USER planify
EXPOSE 8000 8100 8101 8102

CMD ["python", "serve.py"]
