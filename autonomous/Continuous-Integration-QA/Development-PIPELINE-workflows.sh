#!/usr/bin/env bash
set -euo pipefail

#1 commit code changes
./automation/agents/commit-push-Git.sh "push code changes"

# get updated services name form GitHub webhook
DOMAIN=$(curl -s https://api.github.com/repos/hwsc-org/hwsc-react/contents/services/BASE | jq -r '.[].name')
service="bff-marketing"

#2 re-build updated images & push to CR
./automation/agents/services-domain-build.sh BASE bff-marketing

#3 DEPLOY UPDATED IMAGES to K8S
./automation/agents/load-images-k8s.sh BASE bff-marketing
kubectl rollout restart deployment ${service} -n explore
#kubectl apply -f k8s/cloud/base/shared/${service}.yaml


#4 check UNIT TEST (Docker node) a small piece of code
kubectl port-forward -n ingress-nginx "svc/ingress-nginx-controller" "8888:80"
  curl http://127.0.0.1:8888/api/auth/health
kubectl port-forward -n explore "svc/bff-marketing" "7010:7010"
  curl http://127.0.0.1:7010/health

#5 check INTEGRATION TEST (multiple components working together) Regression test
./automation/agents/smoke-test-staging.sh

#6 check SYSTEM TEST (rate limiting, autoscaling)
k6 run frontends/test-app/rate-limit-test.js

#7 check UAT, user end-to-end FLOWS
./automation/agents/Frontend-API-gateway.sh
  # curl http://127.0.0.1:8080
  # click_button "Register"
  # click_button "Create Campaign"
  # check_Email_Box http://127.0.0.1:8025
