
FROM python:3.10-slim

RUN useradd -m appuser

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

RUN pip install watchdog

COPY . .

USER appuser

CMD  ["python", "client.py"]

