#!/usr/bin/env bash
set -euo pipefail

#1 commit code changes
./automation/agents/commit-push-Git.sh "push code changes"

# get updated services name form GitHub webhook
DOMAIN  = $(curl -s https://api.github.com/repos/hwsc-org/hwsc-react/contents/services/BASE | jq -r '.[].name')

#2 re-build updated images & push to CR
./automation/agents/build-domain-services.sh $DOMAIN

#3 DEPLOY UPDATED IMAGES to K8S
./automation/agents/load-images-k8s.sh $DOMAIN


service = "auth-service"
docker build -t ${service}:version3 ./services/BASE/$service
#./automation/agents/deploy-images-Kubernetes.sh $DOMAIN $service
kind load docker-image ${service}:version3 --name staging
#kubectl apply -f k8s/cloud/base/shared/${service}.yaml
kubectl rollout restart deployment ${service} -n explore


#4 RUN UNIT TEST (Docker node)
kubectl port-forward -n ingress-nginx "svc/ingress-nginx-controller" "8888:80"
  curl http://127.0.0.1:8888/api/auth/health
kubectl port-forward -n explore "svc/bff-marketing" "7010:7010"
  curl http://127.0.0.1:7010/health

#5 RUN INTEGRATION TEST
./automation/agents/smoke-test-staging.sh

#6 RUN UAT TESTFLOWS
./automation/agents/run-FRONTEND-API-gateway.sh
  # curl http://127.0.0.1:8080
  # click_button "Register"
  # click_button "Create Campaign"
  # check_Email_Box http://127.0.0.1:8025
