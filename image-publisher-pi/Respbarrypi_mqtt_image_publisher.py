import os
import logging
import paho.mqtt.client as mqtt
import time
import base64

# Configuration
broker = '192.168.1.79'  # Replace with the IP address of the local server Raspberry Pi
port = 1883
topic = 'images/pi1'
image_counter_file = 'image_counter.txt'
image_directory = './'
processed_folder = 'received_images'

# Set up logging
logging.basicConfig(filename='image_capture_mqtt.log', level=logging.INFO,
                    format='%(asctime)s %(levelname)s:%(message)s')

# MQTT callbacks
def on_connect(client, userdata, flags, rc):
    if rc == 0:
        logging.info(f"Connected to broker {broker}:{port} with result code {rc}")
        print(f"Connected to broker {broker}:{port} with result code {rc}")
    else:
        logging.error(f"Failed to connect to broker {broker}:{port} with result code {rc}")
        print(f"Failed to connect to broker {broker}:{port} with result code {rc}")

def on_publish(client, userdata, mid):
    logging.info(f"Message published with mid {mid}")

# Capture image
def capture_image(image_path):
    try:
        os.system(f'fswebcam -r 1280x720 --no-banner {image_path}')
        logging.info(f"Image captured and saved to {image_path}")
    except Exception as e:
        logging.error(f"Failed to capture image: {e}")

# Publish image
def publish_image(client, image_path):
    try:
        # Read and encode image
        with open(image_path, 'rb') as file:
            image_data = base64.b64encode(file.read()).decode()

        # Publish encoded image
        result = client.publish(topic, image_data, qos=1)
        if result.rc == mqtt.MQTT_ERR_SUCCESS:
            logging.info(f"Image {image_path} published successfully.")
        else:
            logging.error(f"Failed to publish image {image_path}. Error code: {result.rc}")

        # Move file to processed folder
        os.makedirs(processed_folder, exist_ok=True)
        os.rename(image_path, os.path.join(processed_folder, os.path.basename(image_path)))

    except Exception as e:
        logging.error(f"Failed to publish image: {e}")

# Get next image number
def get_next_image_number(counter_file):
    try:
        with open(counter_file, 'r') as file:
            number = int(file.read().strip())
    except FileNotFoundError:
        number = 1
    return number

# Update image number
def update_image_number(counter_file, number):
    with open(counter_file, 'w') as file:
        file.write(str(number))

# Main function
def main():
    client = mqtt.Client()
    client.on_connect = on_connect
    client.on_publish = on_publish

    logging.info(f"Connecting to broker {broker}:{port}")
    try:
        client.connect(broker, port, 60)
    except Exception as e:
        logging.error(f"Connection failed: {e}")
        print(f"Connection failed: {e}")
        return

    client.loop_start()

    while True:
        try:
            image_number = get_next_image_number(image_counter_file)
            image_path = os.path.join(image_directory, f"image_{image_number:04d}.jpg")

            capture_image(image_path)
            publish_image(client, image_path)

            image_number += 1
            update_image_number(image_counter_file, image_number)

            time.sleep(3)
        except KeyboardInterrupt:
            logging.info("Keyboard interrupt detected. Stopping the script.")
            break
        except Exception as e:
            logging.error(f"Unexpected error occurred: {e}")
            print(f"Unexpected error occurred: {e}")
            time.sleep(60)

    client.loop_stop()
    client.disconnect()

if __name__ == "__main__":
    main()
