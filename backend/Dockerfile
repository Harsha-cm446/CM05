FROM python:3.11-slim

WORKDIR /app

# System dependencies for OpenCV
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 libglib2.0-0 && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Pre-download Vosk STT model during build so it's available instantly at runtime
# Uses the smaller model for Docker deployments (40MB vs 1.8GB)
# Set VOSK_MODEL_NAME env var to override at runtime
ENV VOSK_MODEL_NAME=vosk-model-small-en-us-0.15
RUN printf 'try:\n from vosk import Model, SetLogLevel\n SetLogLevel(-1)\n print("Downloading Vosk model...")\n m = Model(model_name="vosk-model-small-en-us-0.15")\n print("Vosk model ready")\nexcept Exception as e:\n print("Vosk model pre-download skipped: " + str(e))\n' | python

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
