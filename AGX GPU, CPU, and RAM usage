AGX GPU, CPU, and RAM usage


agx@agx-desktop:~$ sudo cat /var/lib/node_exporter/gpu_metrics.prom
jetson_gpu_usage_percent 0
jetson_memory_used_mb 5765
jetson_cpu_combined_percent 23
agx@agx-desktop:~$ sudo cat /usr/local/bin/gpu_metrics_exporter.sh
#!/bin/bash

OUT="/var/lib/node_exporter/gpu_metrics.prom"
LOG="/tmp/gpu_exporter_debug.log"

while true; do
  echo "[$(date)] Running scrape..." >> "$LOG"

  # Capture tegrastats output (1 line only)
  TSTAT=$(timeout 3s tegrastats | head -n 1)
  echo "[$(date)] TSTAT=$TSTAT" >> "$LOG"

  # Extract metrics using updated and correct regex
  RAM_USED_MB=$(echo "$TSTAT" | grep -oP 'RAM \K[0-9]+(?=/)')
  GPU_USAGE=$(echo "$TSTAT" | grep -oP 'GR3D_FREQ \K[0-9]+(?=%)')
  CPU_RAW=$(echo "$TSTAT" | grep -oP 'CPU \[\K[^\]]+')
  CPU_USAGE=$(echo "$CPU_RAW" | grep -oP '[0-9]+(?=%)' | awk '{sum+=$1} END {print sum}')

  # Fallback values if parsing failed
  RAM_USED_MB=${RAM_USED_MB:-0}
  GPU_USAGE=${GPU_USAGE:-0}
  CPU_USAGE=${CPU_USAGE:-0}

  # Write to Prometheus-compatible format
  cat <<EOF > "$OUT"
jetson_gpu_usage_percent $GPU_USAGE
jetson_memory_used_mb $RAM_USED_MB
jetson_cpu_combined_percent $CPU_USAGE
EOF

  echo "[$(date)] Wrote GPU=$GPU_USAGE, RAM=$RAM_USED_MB, CPU=$CPU_USAGE" >> "$LOG"

  sleep 1
done
agx@agx-desktop:~$ sudo cat /etc/systemd/system/node_exporter.service
[Unit]
Description=Node Exporter
After=network.target

[Service]
User=agx
ExecStart=/usr/local/bin/node_exporter \
  --collector.textfile.directory=/var/lib/node_exporter/

[Install]
WantedBy=default.target
