#!/usr/bin/env bash
set -euo pipefail

#1 [STAGING] developers commit code changes
./agents/commit-push-Git.sh "push code changes"

#2 [STAGING] auto build the updated image for each Git push (push to CR)
docker build -t auth-service:version3 ./services/BASE/auth-service
# or customizing to use ./agents/build-domain-services.sh BASE auth
# or rebuild all ./agents/build-domain-services.sh BASE

#3 [STAGING] AUTO DEPLOY THE UPDATED IMAGE
kind load docker-image auth-service:version3 --name staging
#kubectl apply -f k8s/cloud/base/shared/auth-service.yaml
kubectl rollout restart deployment auth-service -n explore

# or customizing to use ./agents/deploy-images-Kubernetes.sh BASE auth
# or redeploy all ./agents/deploy-images-Kubernetes.sh BASE


#4 [STAGING] auto run Unit Test (Docker container node)
kubectl port-forward -n ingress-nginx "svc/ingress-nginx-controller" "8888:80"
  curl http://127.0.0.1:8888/api/auth/health
kubectl port-forward -n explore "svc/auth-service" "7000:7000"
  curl http://127.0.0.1:7000/health

#5 [STAGING] auto run Integration Test
./agents/test-smoke-staging.sh

#6 [STAGING] auto redeploy Frontend & run UAT Testflow
./agents/run-FRONTEND-API-gateway.sh
  # open Browser, go to http://127.0.0.1:808x
  # click button Register
  # click button Create Campaign
  # check Email Box http://127.0.0.1:8025
