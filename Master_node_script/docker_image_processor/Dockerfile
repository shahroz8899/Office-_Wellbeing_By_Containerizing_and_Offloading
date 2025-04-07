FROM python:3.9-slim

# Set working directory for scripts
WORKDIR /script

# Install necessary Python libraries
RUN pip install --no-cache-dir pillow

# Copy the Python script into the container
COPY process_image.py /script/

# Set entrypoint to use Python
ENTRYPOINT ["python", "/script/process_image.py"]

