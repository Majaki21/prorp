FROM python:3.12-slim

WORKDIR /app

COPY shared /app/shared
COPY services/presentation/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && pip install --no-cache-dir ./shared

COPY services/presentation/app ./app

CMD ["python", "app/run.py"]
