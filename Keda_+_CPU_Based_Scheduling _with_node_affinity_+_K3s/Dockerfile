FROM python:3.10-slim

# System deps for OpenCV / MediaPipe
RUN apt-get update && apt-get install -y \
    libgl1 libglib2.0-0 && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt



# 3) Copy the rest of your project
COPY . /app

# 4) Select which script to run at container start
ARG APP=Images_From_Pi1.py
CMD ["python", "-u", "${APP}"]




