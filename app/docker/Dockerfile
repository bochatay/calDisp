FROM python:3.12-slim

WORKDIR /app

# Noto Sans (fonts-noto-core) fournit la police de l'image et ses glyphes
# accentues (é, à, ç...). DejaVu et Liberation restent installes en repli.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        fonts-noto-core \
        fonts-dejavu-core \
        fonts-liberation \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
