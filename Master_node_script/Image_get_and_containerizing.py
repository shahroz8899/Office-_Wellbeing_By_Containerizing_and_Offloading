import os
import logging
import paho.mqtt.client as mqtt
import base64
import re
import subprocess

# Configuration
broker = '192.168.1.79'
port = 1883
base_folder = 'received_images'  # Base directory for all received images

# Set up logging
logging.basicConfig(filename='mqtt_image_receiver.log', level=logging.INFO,
                    format='%(asctime)s %(levelname)s:%(message)s')

# MQTT callbacks
def on_connect(client, userdata, flags, rc):
    logging.info(f"Connected with result code {rc}")
    print(f"Connected with result code {rc}")
    # Subscribe to all topics under "images/"
    client.subscribe("images/#")

def on_message(client, userdata, msg):
    try:
        # Skip messages from the "images/jetson_orin" topic
        if msg.topic == 'images/jetson_orin':
            return

        # Decode image data from the payload
        image_data = base64.b64decode(msg.payload)

        # Extract prefix from the topic (e.g., 'images/pi1' -> 'pi1')
        topic_parts = msg.topic.split('/')
        prefix = topic_parts[1] if len(topic_parts) > 1 else "unknown"

        # Set folder path based on extracted prefix
        folder_path = os.path.join(base_folder, f"images_from_{prefix}")
        os.makedirs(folder_path, exist_ok=True)

        # Save the image with a fixed name for each prefix
        image_path = os.path.join(folder_path, f"{prefix}.jpg")
        with open(image_path, 'wb') as file:
            file.write(image_data)

        logging.info(f"Image saved to {image_path}")
    except Exception as e:
        logging.error(f"Failed to save image: {e}")


# Function to start the MQTT receiver
def start_mqtt_receiver():
    # Start the poll_folders.py script as a subprocess
    subprocess.Popen(['python3', '/home/shahroz/Project2.0/poll_folders.py'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    client = mqtt.Client()
    client.on_connect = on_connect
    client.on_message = on_message

    client.connect(broker, port, 60)
    client.loop_start()

    try:
        while True:
            pass  # Keep the script running to receive messages
    except KeyboardInterrupt:
        logging.info("Keyboard interrupt detected. Stopping the script.")
    except Exception as e:
        logging.error(f"Unexpected error occurred: {e}")
    finally:
        client.loop_stop()
        client.disconnect()

if __name__ == "__main__":
    # Remove the previous Docker image
    try:
        subprocess.run(['docker', 'rmi', '-f', 'image-processor'], check=True)
        logging.info("Previous Docker image 'image-processor' removed successfully.")
    except subprocess.CalledProcessError as e:
        logging.error(f"Failed to remove Docker image: {e}")

    # Build the Docker image automatically before starting the receiver
    try:
        subprocess.run(['docker', 'build', '--no-cache', '-t', 'image-processor', '/home/shahroz/Project2.0/docker_image_processor'], check=True)
        logging.info("Docker image 'image-processor' built successfully.")
    except subprocess.CalledProcessError as e:
        logging.error(f"Failed to build Docker image: {e}")
        exit(1)

    start_mqtt_receiver()
