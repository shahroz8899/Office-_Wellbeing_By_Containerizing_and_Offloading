#!/bin/bash

NAMESPACE="posture"

echo -e "\n🔍 1. Node Eligibility Labels:"
kubectl get nodes --show-labels | grep posture || echo "❌ No posture labels found"

echo -e "\n📊 2. KEDA External Scaler - /allowed:"
curl -s http://localhost:8088/allowed | jq || echo "❌ Scaler not reachable"

echo -e "\n📦 3. Job Statuses:"
kubectl -n $NAMESPACE get jobs -o wide

echo -e "\n🌀 4. Pod Lifecycle & Restarts:"
kubectl -n $NAMESPACE get pods -o wide

echo -e "\n📄 5. Last 10 lines of logs from Completed Jobs:"
JOBS=$(kubectl -n $NAMESPACE get jobs --no-headers | awk '$2 ~ /1\/1/ {print $1}')
for job in $JOBS; do
  pod=$(kubectl -n $NAMESPACE get pods --selector=job-name=$job -o jsonpath="{.items[0].metadata.name}")
  echo -e "\n🔹 Logs for $job ($pod):"
  kubectl -n $NAMESPACE logs $pod --tail=10 || echo "⚠️ Log fetch failed for $pod"
done
