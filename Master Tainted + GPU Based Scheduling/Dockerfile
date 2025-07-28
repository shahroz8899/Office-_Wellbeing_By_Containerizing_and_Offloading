FROM python:3.10-slim

# Install system dependencies for OpenCV, MediaPipe
RUN apt-get update && apt-get install -y \
    libgl1-mesa-glx \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# Set work directory
WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY mqtt_posture_analyzer_with_db.py .

CMD ["python", "mqtt_posture_analyzer_with_db.py"]

