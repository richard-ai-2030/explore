#!/usr/bin/env bash
set -euo pipefail

#1 DEPLOY APPLICATION SERVICES TO AWS
  #image: <your-account>.dkr.ecr.ap-southeast-1.amazonaws.com/auth-service:latest
  #aws eks update-kubeconfig   --region ap-southeast-1   --name microservices-cluster

  > kubectl apply -k k8s/cloud/overlays/aws/shared
  > kubectl wait -n explore --for=condition=available deployment --all --timeout=600s
  > kubectl port-forward -n ingress-nginx "svc/ingress-nginx-controller" "8888:80"

#2 place OBSERVATION & alerting
./agents/run-Prometheus-Grafana.sh

#3 redeploy FRONTENDS & API Gateway
./agents/run-FRONTEND-API-gateway.sh

#4 auto run UAT TOP10 AWASP
  > nextjs build
  > aws upload-to-S3 (private bucket)
  > aws cloudfront invalidating
  > ./agents/run-UAT-TOP10-AWASP-list.sh

#5 ROLLBACK procedure
  kubectl rollout status deployment auth-service -n explore
                  history / undo / undo --to-revision=2
  helm history my-release
       rollback upgrade my-release 2                
