

# 🐳 Image Containerization & Processing Pipeline

This system is designed to receive images over MQTT from multiple Raspberry Pis, save them in organized folders, and automatically process them using a Docker container. The core orchestration is handled by `Image_get_and_containerizing.py`.

---

## 🧠 Overview

```text
[ Raspberry Pi Devices (pi1, pi2, pi3) ]
            |
      base64-encoded image
            |
      MQTT Broker (192.168.1.79)
            |
  Image_get_and_containerizing.py
     - Saves images to folders
     - Rebuilds Docker image
     - Starts polling script
            |
     poll_folders.py
     - Scans folders
     - Runs Docker container
            |
     process_image.py (in Docker)
     - Resizes image
     - Saves processed copy
```

---

## 📁 Files and Roles

### 🔹 `Image_get_and_containerizing.py`

- Connects to MQTT broker `192.168.1.79:1883`
- Subscribes to all `images/#` topics
- Skips messages from `images/jetson_orin`
- Saves received images to:
  - `received_images/images_from_pi1/pi1.jpg`
  - `received_images/images_from_pi2/pi2.jpg`
  - `received_images/images_from_pi3/pi3.jpg`
- Logs all activity to `mqtt_image_receiver.log`
- Removes any previous Docker image named `image-processor`
- Rebuilds the Docker image using:
  ```
  /home/shahroz/Project2.0/docker_image_processor
  ```
- Starts `poll_folders.py` in the background

---

### 🔹 `poll_folders.py`

- Watches folders inside:
  ```
  /home/shahroz/Project2.0/received_images/
  ```
- For every `.jpg` file found, checks if it's new or updated
- Calls a Docker container to process the image:
  ```bash
  docker run --rm -v <folder_path>:/images image-processor /images/<image_name>
  ```

---

### 🔹 `process_image.py` (Docker-Executed)

- Resizes incoming images to `1280x720` using Pillow
- Saves them as `processed_<original_name>.jpg` in the same directory (`/images`)
- Used exclusively inside the Docker container

---

## 🐳 Docker Setup

### Dockerfile (inside `docker_image_processor/`)

Ensure this file exists:

```Dockerfile
FROM python:3.9-slim
WORKDIR /images
COPY process_image.py /images/
RUN pip install pillow
ENTRYPOINT ["python", "process_image.py"]
```

### Build Trigger

Docker image is built automatically when `Image_get_and_containerizing.py` starts.

---

## 🔄 Workflow Summary

1. **Start the receiver script:**
   ```bash
   python3 Image_get_and_containerizing.py
   ```

2. This will:
   - Build a fresh Docker image
   - Begin listening for incoming images
   - Spawn the polling script in background

3. **Images are automatically processed and saved** as:
   ```
   /received_images/images_from_pi1/processed_pi1.jpg
   ```

---

## 📦 Requirements

Install on the master node:

```bash
sudo apt install docker.io
pip install paho-mqtt pillow
```

---

## 🧪 Testing Tips

- Use `mosquitto_pub` or MQTT Explorer to test image publishing
- Verify logs in `mqtt_image_receiver.log`
- Check folders like `received_images/images_from_pi1/` for output
- Manually run the Docker command if needed:
  ```bash
  docker run --rm -v $(pwd):/images image-processor /images/test.jpg
  ```

---

## 👤 Author

**Muhammad Shahroz Abbas**  
Doctoral Researcher, M3S, University of Oulu  
Expert in Edge-AI & Container-Based Orchestration

---

## 📜 License

This project is open for research and academic use.

