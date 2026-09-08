FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       build-essential \
       libpango-1.0-0 \
       libpangoft2-1.0-0 \
       libharfbuzz0b \
       libfontconfig1 \
       libfreetype6 \
       libffi-dev \
       libcairo2 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY divya_enterprises ./divya_enterprises

WORKDIR /app/divya_enterprises
CMD ["sh", "-c", "python manage.py migrate && python manage.py runserver 0.0.0.0:8000"]
