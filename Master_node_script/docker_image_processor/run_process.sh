#!/bin/sh

# Loop through all .jpg files in the /images directory
for img in /images/*.jpg; do
  if [ -f "$img" ]; then
    echo "Processing $img"
    python /script/process_image.py "$img"
  fi
done
