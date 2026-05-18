#!/usr/bin/env bash
set -euo pipefail

# CD PIPELINE AUTOMATION

# deploy APPLICATION SERVICES
./automation/CD_workflow/2-deploy-APP-SERVICES.sh

# run OBSERVATIONS
./automation/CD_workflow/3-run-OBSERVATION-alerting.sh

# run FRONTENDS & API Gateway
./automation/CD_workflow/4-run-FRONTEND-API-gateway.sh


# auto UAT with TOP10 AWASP list
  > nextjs build
  > aws upload-to-S3 (private bucket)
  > aws cloudfront invalidating
  > ./automation/CD_workflow/run-FRONTEND.sh


# auto deploy services to AWS
  > kubectl apply -k k8s/cloud/overlays/aws/shared
  > kubectl wait -n explore --for=condition=available deployment --all --timeout=600s
  > kubectl port-forward -n ingress-nginx "svc/ingress-nginx-controller" "8888:80"

image: <your-account>.dkr.ecr.ap-southeast-1.amazonaws.com/auth-service:latest

aws eks update-kubeconfig \
  --region ap-southeast-1 \
  --name microservices-cluster
