FROM node:22-bookworm

# Install Python, Tesseract OCR and required system packages
RUN apt-get update && apt-get install -y \
    python3 \
    python3-venv \
    python3-pip \
    tesseract-ocr \
    tesseract-ocr-eng \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Create isolated Python environment
RUN python3 -m venv /opt/venv

ENV PATH="/opt/venv/bin:$PATH"
ENV PYTHON_BIN="/opt/venv/bin/python"
ENV NODE_ENV="production"

# Install Python dependencies
COPY redactor/requirements.txt /app/redactor/requirements.txt

RUN pip install --no-cache-dir -r /app/redactor/requirements.txt \
    && python -m spacy download en_core_web_sm

# Install Node dependencies
COPY backend/package*.json /app/backend/

RUN cd /app/backend && npm install --omit=dev

# Copy the complete application
COPY . /app

EXPOSE 3000

# Start Express server
CMD ["node", "backend/server.js"]