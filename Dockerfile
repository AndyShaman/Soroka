FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
        tesseract-ocr tesseract-ocr-rus tesseract-ocr-eng \
        ffmpeg \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml ./
RUN pip install --no-cache-dir -e .

COPY src ./src

RUN mkdir -p /app/data
VOLUME ["/app/data"]

CMD ["python", "-m", "src.bot.main"]
