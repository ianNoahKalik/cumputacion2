FROM python:3.11-slim

WORKDIR /app

# Copiar archivos necesarios
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY config.json .
COPY monitor.py .
COPY README.md .

# El contenedor debe ser interactivo para la TUI
ENV PYTHONUNBUFFERED=1

CMD ["python", "-u", "monitor.py"]
