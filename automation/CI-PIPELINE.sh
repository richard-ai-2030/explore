#!/usr/bin/env bash
set -euo pipefail

# CI PIPELINE AUTOMATION

# developers commit code changes
./automation/CI_workflow/1-commit-push-Git.sh "improve codes"

# auto build images for each Git push 
./automation/CI_workflow/2-build-domain-services.sh

# auto push to Containers Registry for each image built
./automation/CI_workflow/3-staging-services-Kubernetes.sh

# AUTO TEST with a Docker container node
# Unit Test
kubectl port-forward -n ingress-nginx "svc/ingress-nginx-controller" "8888:80"
  curl http://127.0.0.1:8888/api/auth/health
kubectl port-forward -n explore "svc/auth-service" "7000:7000"
  curl http://127.0.0.1:7000/health

# Integration Test
./automation/CI_workflow/4-staging-smoke-test.sh

# RUN UAT Testflow
./automation/CD_workflow/4-run-FRONTEND-API-gateway.sh
  # open Browser, go to http://127.0.0.1:808x
  # click button Register
  # click button Create Campaign
  # check Email Box http://127.0.0.1:8025
