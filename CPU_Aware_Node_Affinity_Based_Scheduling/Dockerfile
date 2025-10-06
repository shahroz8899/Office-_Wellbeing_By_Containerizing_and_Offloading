# Base image
FROM python:3.10-slim

# Workdir inside the image
WORKDIR /app

# (Optional) system deps you might need
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential ffmpeg libgl1 \
 && rm -rf /var/lib/apt/lists/*

# 1) Copy ONLY requirements first (better layer caching)
COPY requirements.txt /app/requirements.txt

# 2) Install deps
RUN pip install --no-cache-dir -r requirements.txt

# 3) Copy the rest of your project
COPY . /app

# 4) Select which script to run at container start
ARG APP=Images_From_Pi1.py
CMD ["python", "-u", "${APP}"]

