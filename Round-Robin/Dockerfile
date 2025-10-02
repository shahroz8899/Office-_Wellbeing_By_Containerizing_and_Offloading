
FROM python:3.10-slim

# System deps for OpenCV / MediaPipe
RUN apt-get update && apt-get install -y \
    libgl1 libglib2.0-0 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Python deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# App code (all three scripts)
COPY Images_From_Pi1.py Images_From_Pi1_1.py Images_From_Pi1_2.py Images_From_Pi1_3.py Images_From_Pi1_4.py Images_From_Pi1_5.py Images_From_Pi1_6.py Images_From_Pi1_7.py Images_From_Pi1_8.py Images_From_Pi1_9.py ./

# Remove entrypoint logic
CMD ["python3"]


