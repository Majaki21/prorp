FROM python:3.12-slim
WORKDIR /app
COPY shared /app/shared
COPY services/simulation/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && pip install --no-cache-dir ./shared
COPY services/simulation/app ./app
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
