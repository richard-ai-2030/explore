#!/usr/bin/env bash
set -euo pipefail

step() {
  echo
  echo "=================================================="
  echo "$1"
  echo "=================================================="
}

step "infrastructure - Cloud & Databases"
terraform -chdir=automation/cloud_formation init
terraform -chdir=automation/cloud_formation apply -auto-approve

step "infrastructure - scaffold Postgres"
./automation/postgres/create-databases.sh
./automation/postgres/create-tables.sh
./automation/postgres/create-outbox-events.sh


step "Build foundational SERVICES to images"
./automation/agents/build-domain-services.sh BASE
./automation/agents/build-domain-services.sh MARKETING

step "KUBERNETES - create Cluster"
kind create cluster --name staging --config k8s/cluster/infra-nodes.yaml

step "KUBERNETES - load foundational IMAGES to Cluster"
./automation/agents/load-images-k8s.sh BASE
./automation/agents/load-images-k8s.sh MARKETING


step "KUBERNETES - Nginx API Gateway ~ Ingress controller Pod"
kubectl apply -f k8s/cluster/infra-ingress-nginx.yaml
kubectl rollout status deployment/ingress-nginx-controller -n ingress-nginx --timeout=600s

step "KUBERNETES - Service Mesh"
linkerd check --pre
kubectl apply --server-side -f https://github.com/kubernetes-sigs/gateway-api/releases/download/v1.4.0/standard-install.yaml
linkerd install --crds | kubectl apply -f -
linkerd install | kubectl apply -f -
linkerd check
kubectl apply -f k8s/cluster/infra-linkerd.yaml
kubectl wait -n linkerd --for=condition=available deployment --all --timeout=600s
kubectl annotate namespace explore linkerd.io/inject=enabled

step "KUBERNETES - Metrics Server"
kubectl apply -f k8s/cluster/infra-metrics-server.yaml
kubectl patch deployment metrics-server -n kube-system --type=json -p='[{"op":"add","path":"/spec/template/spec/containers/0/args/-","value":"--kubelet-insecure-tls"},{"op":"add","path":"/spec/template/spec/containers/0/args/-","value":"--kubelet-preferred-address-types=InternalIP,Hostname,InternalDNS,ExternalDNS,ExternalIP"}]' || true
kubectl rollout status deployment/metrics-server -n kube-system --timeout=600s


echo
cat <<MSG  
  tar -czf ../version3.tar.gz --exclude=.git --exclude=.terraform --exclude=.next --exclude=node_modules --exclude=*.pyc --exclude=__pycache__ .

  # CHECK INFRASTRUCTURE
  docker images;    docker ps;
  docker inspect postgres      # redis       # kafka
  #docker rm -f  $(docker ps -aq) 2>/dev/null;   docker rmi -f $(docker images -aq) 2>/dev/null;  docker system prune -a --volumes -f;
  #kind delete cluster --name staging;           kubectl delete namespace explore;
    
  # CHECK KUBERNETES CLUSTER
  kubectl get namespaces
  kubectl get ingress -n explore
  kubectl get nodes -o wide
  kubectl top pods -n explore
  kubectl get events -n explore --sort-by=.lastTimestamp | tail -n 25
  kubectl logs -n ingress-nginx -l app.kubernetes.io/name=ingress-nginx

  # CHECK SERVICE MESH
  kubectl get namespace explore -o yaml
  kubectl rollout restart deployment -n explore
  kubectl get pods -n explore -w
  kubectl get pod auth-service-5968bd99dd-4qxsf -n explore -o jsonpath='{.spec.containers[*].name}'
  linkerd identity -n explore auth-service-5968bd99dd-4qxsf
MSG