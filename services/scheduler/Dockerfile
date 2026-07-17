FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py .

RUN mkdir -p /app/data

EXPOSE 5003

# Single worker so APScheduler only runs one background thread
CMD ["gunicorn", "--bind", "0.0.0.0:5003", "--workers", "1", "--timeout", "60", "app:app"]
