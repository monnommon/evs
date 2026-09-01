FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN adduser --disabled-password --gecos "" evsuser && chown -R evsuser /app \
    && mkdir -p /app/staticfiles && chown evsuser /app/staticfiles
USER evsuser

EXPOSE 8000