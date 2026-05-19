FROM python:3.13-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ ./src/
COPY main.py cli.py ./
COPY deploy/ ./deploy/

# Ports are configured via docker-compose.yml / .env
# No hardcoded EXPOSE — dynamic from config

CMD ["python", "main.py"]
