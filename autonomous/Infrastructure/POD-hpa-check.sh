#!/usr/bin/env bash
set -euo pipefail

for n in ingress-nginx explore; do  
  kubectl get deployments -o wide -n $n;     # how your Pods are created (from images GHCR, port, replicas..)
  kubectl get svc         -o wide -n $n;     # IP access point & load balancer for a group of Pods
  kubectl get hpa  -o wide -n $n;

  kubectl get pods -o wide -n $n;            # independent deployable unit where the actual application lives
  kubectl get endpoints -n $n;               # Endpoints are only populated when Pod is Running and Readiness probe passes
done