FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PORT=8080

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

COPY main.py foundry_app.py ./
COPY soc_pipeline ./soc_pipeline
COPY sql ./sql
COPY README.md ./

EXPOSE 8080

CMD ["gunicorn", "--bind", "0.0.0.0:8080", "foundry_app:app"]
