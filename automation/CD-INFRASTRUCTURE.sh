#!/usr/bin/env bash
set -euo pipefail

step() {
  echo
  echo "=================================================="
  echo "$1"
  echo "=================================================="
}

step "infrastructure - Databases"
terraform -chdir=automation/infrastructure init
terraform -chdir=automation/infrastructure apply -auto-approve

step "infrastructure - scaffold Postgres"
./automation/postgres/create-databases.sh
./automation/postgres/create-tables.sh
./automation/postgres/create-outbox-events.sh


step "Build FOUNDATION SERVICES to images"
./automation/CI_workflow/2-build-domain-services.sh BASE         # MARKETING, PRODUCTION, TALENTS, ACCOUNTING

step "KUBERNETES - Kind nodes"
kind create cluster --name staging --config automation/kubernetes/infra-nodes.yaml

step "KUBERNETES - Load FOUNDATION SERVICES to K8S"
./automation/CI_workflow/3-staging-services-Kubernetes.sh BASE         # MARKETING, PRODUCTION, TALENTS, ACCOUNTING


step "KUBERNETES - Nginx API Gateway ~ Ingress controller Pod"
kubectl apply -f automation/kubernetes/infra-ingress-nginx.yaml
kubectl rollout status deployment/ingress-nginx-controller -n ingress-nginx --timeout=600s

step "KUBERNETES - Service Mesh"
linkerd check --pre
kubectl apply --server-side -f https://github.com/kubernetes-sigs/gateway-api/releases/download/v1.4.0/standard-install.yaml
linkerd install --crds | kubectl apply -f -
linkerd install | kubectl apply -f -
linkerd check
kubectl apply -f automation/kubernetes/infra-linkerd.yaml
kubectl wait -n linkerd --for=condition=available deployment --all --timeout=600s

step "KUBERNETES - Metrics Server"
kubectl apply -f automation/kubernetes/infra-metrics-server.yaml
kubectl patch deployment metrics-server -n kube-system --type=json -p='[{"op":"add","path":"/spec/template/spec/containers/0/args/-","value":"--kubelet-insecure-tls"},{"op":"add","path":"/spec/template/spec/containers/0/args/-","value":"--kubelet-preferred-address-types=InternalIP,Hostname,InternalDNS,ExternalDNS,ExternalIP"}]' || true
kubectl rollout status deployment/metrics-server -n kube-system --timeout=600s

step "NETWORKING - Connect subnets"
docker network ls
for d in clickhouse kafka redis postgres; do docker network disconnect kind $d; done
for node in staging-worker2 staging-worker staging-control-plane; do docker stop $node; done

for node in staging-worker2 staging-worker staging-control-plane; do docker start $node; done
for c in postgres redis kafka clickhouse; do docker network connect kind $c; done
docker network inspect kind

echo
cat <<MSG  
  tar -czf ../version3.tar.gz --exclude=.git --exclude=.terraform --exclude=.next --exclude=node_modules --exclude=*.pyc --exclude=__pycache__ .

  # CHECK INFRASTRUCTURE
  docker images;    docker ps;    
  docker rm -f  $(docker ps -aq) 2>/dev/null;   
  docker rmi -f $(docker images -aq) 2>/dev/null;
  docker system prune -a --volumes -f
  docker inspect postgres      # redis       # kafka
  
  # CHECK KUBERNETES
  kubectl get namespaces
  kubectl get ingress -n explore
  kubectl get nodes -o wide
  kubectl top pods -n explore

  kubectl describe deployment auth-service -n explore
  kubectl describe svc auth-service -n explore
  #kubectl delete deployment auth-service -n explore
  #kubectl delete svc auth-service -n explore

  #kind delete cluster --name staging
  #kubectl delete namespace explore    
    kubectl set env deployment --all -n explore POSTGRES_HOST=172.19.0.5 KAFKA_BOOTSTRAP_SERVERS=172.19.0.7
    kubectl set env deployment/analytics-service -n explore CLICKHOUSE_HOST=172.19.0.8 CLICKHOUSE_PORT=8123
    kubectl set env deployment/auth-service -n explore REDIS_URL=redis://172.19.0.6:6379/0  
MSG