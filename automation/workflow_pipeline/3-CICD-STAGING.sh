#!/usr/bin/env bash
set -euo pipefail

#1 commit code changes
./automation/agents/commit-push-Git.sh "push code changes"

#2 re-build updated images & push to CR
./automation/agents/build-domain-services.sh BASE
# TRIGGER BULDING ONLY CHANGED SERVICES FROM GITHUB PUSH
#docker build -t auth-service:version3 ./services/BASE/auth-service

#3 DEPLOY UPDATED IMAGES to K8S
./automation/agents/deploy-images-Kubernetes.sh BASE
# or customizing to use ./automation/agents/deploy-images-Kubernetes.sh BASE auth
#kind load docker-image auth-service:version3 --name staging
#kubectl apply -f k8s/cloud/base/shared/auth-service.yaml
#kubectl rollout restart deployment auth-service -n explore

#4 RUN UNIT TEST (Docker node)
kubectl port-forward -n ingress-nginx "svc/ingress-nginx-controller" "8888:80"
  curl http://127.0.0.1:8888/api/auth/health
kubectl port-forward -n explore "svc/auth-service" "7000:7000"
  curl http://127.0.0.1:7000/health
kubectl port-forward -n explore "svc/bff-marketing" "7010:7010"
  curl http://127.0.0.1:7010/health

#5 RUN INTEGRATION TEST
./automation/agents/test-smoke-staging.sh

#6 RUN UAT TESTFLOWS
./automation/agents/run-FRONTEND-API-gateway.sh
  # curl http://127.0.0.1:8080
  # click_button "Register"
  # click_button "Create Campaign"
  # check_Email_Box http://127.0.0.1:8025
