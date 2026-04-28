#!/usr/bin/env bash
set -euo pipefail

kubectl create namespace monitoring || true

helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm repo update
helm upgrade --install monitoring prometheus-community/kube-prometheus-stack   -n monitoring   -f monitoring/kube-prometheus-stack-values.yaml
helm upgrade --install blackbox prometheus-community/prometheus-blackbox-exporter   -n monitoring   -f monitoring/blackbox-values.yaml

kubectl apply -f monitoring/servicemonitors.yaml
kubectl apply -f monitoring/probes.yaml
kubectl apply -f monitoring/alerts.yaml
kubectl apply -f monitoring/grafana-dashboard-configmap.yaml

nohup kubectl -n monitoring port-forward svc/monitoring-kube-prometheus-prometheus 9090:9090 >/tmp/prometheus-port-forward.log 2>&1 &
    #http://127.0.0.1:9090

nohup kubectl -n monitoring port-forward svc/monitoring-grafana 9091:80 >/tmp/grafana-port-forward.log 2>&1 &
    #http://127.0.0.1:9091       admin / admin123
    #Dashboards → menu "Core Services-Latency and RPS"

nohup kubectl port-forward svc/bff-marketing -n explore 9092:7010 >/tmp/bff-marketing-port-forward.log 2>&1 &
    #http://127.0.0.1:9092/metrics
    #    app_http_requests_total
    #    app_http_request_duration_seconds
    #    app_payment_events_processed_total
    #    app_notification_events_total
