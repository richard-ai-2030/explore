#!/usr/bin/env bash
set -euo pipefail

#1 [PRODUCTION] DEPLOY APPLICATION SERVICES TO AWS
  > kubectl apply -k k8s/cloud/overlays/aws/shared
  > kubectl wait -n explore --for=condition=available deployment --all --timeout=600s
  > kubectl port-forward -n ingress-nginx "svc/ingress-nginx-controller" "8888:80"

  #image: <your-account>.dkr.ecr.ap-southeast-1.amazonaws.com/auth-service:latest
  #aws eks update-kubeconfig   --region ap-southeast-1   --name microservices-cluster

#2 [PRODUCTION] run OBSERVATION & alerting
./agents/run-Prometheus-Grafana.sh

#3 [PRODUCTION] redeploy FRONTENDS & API Gateway
./agents/run-FRONTEND-API-gateway.sh

#4 [PRODUCTION] auto run TOP10 AWASP for UAT
  > nextjs build
  > aws upload-to-S3 (private bucket)
  > aws cloudfront invalidating
  > ./agents/run-UAT-TOP10-AWASP-list.sh
