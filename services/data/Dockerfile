FROM python:3.12-slim
WORKDIR /app

COPY shared /app/shared
COPY services/data/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && pip install --no-cache-dir ./shared

COPY services/data/app ./app
COPY services/data/seed_data.json ./app/seed_data.json
RUN mkdir -p /data
VOLUME ["/data"]

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
