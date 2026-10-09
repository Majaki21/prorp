FROM python:3.12-slim
WORKDIR /app
COPY services/analytics_history/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY services/analytics_history/app ./app
COPY services/analytics_history/import_excel.py ./import_excel.py
COPY services/analytics_history/data ./seed-data
ENV ANALYTICS_HISTORY_DB=/data/analytics_history.db
EXPOSE 8010
CMD ["sh", "-c", "mkdir -p /data && if [ ! -f \"$ANALYTICS_HISTORY_DB\" ]; then cp /app/seed-data/analytics_history.db \"$ANALYTICS_HISTORY_DB\"; fi && uvicorn app.main:app --host 0.0.0.0 --port 8010"]