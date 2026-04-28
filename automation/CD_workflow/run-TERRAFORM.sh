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


step "Build DOMAIN SERVICES to images"
./automation/CI_workflow/build-domain-services.sh BASE         # MARKETING, PRODUCTION, TALENTS, ACCOUNTING

step "KUBERNETES - Kind nodes"
kind create cluster --name staging --config automation/kubernetes/infra-nodes.yaml

step "KUBERNETES - Load DOMAIN SERVICES to Kind"
./automation/CI_workflow/load-services-to-kind.sh BASE         # MARKETING, PRODUCTION, TALENTS, ACCOUNTING


step "KUBERNETES - Ingress controller ALB / Nginx"
kubectl apply -f automation/kubernetes/infra-ingress-nginx.yaml
kubectl rollout status deployment/ingress-nginx-controller -n ingress-nginx --timeout=600s

step "KUBERNETES - Metrics Server"
kubectl apply -f automation/kubernetes/infra-metrics-server.yaml
kubectl patch deployment metrics-server -n kube-system --type=json -p='[{"op":"add","path":"/spec/template/spec/containers/0/args/-","value":"--kubelet-insecure-tls"},{"op":"add","path":"/spec/template/spec/containers/0/args/-","value":"--kubelet-preferred-address-types=InternalIP,Hostname,InternalDNS,ExternalDNS,ExternalIP"}]' || true
kubectl rollout status deployment/metrics-server -n kube-system --timeout=600s

step "KUBERNETES - Service Mesh"
linkerd check --pre
kubectl apply --server-side -f https://github.com/kubernetes-sigs/gateway-api/releases/download/v1.4.0/standard-install.yaml
linkerd install --crds | kubectl apply -f -
linkerd install | kubectl apply -f -
linkerd check
kubectl apply -f automation'/kubernetes/infra-linkerd.yaml
kubectl wait -n linkerd --for=condition=available deployment --all --timeout=600s

echo
cat <<MSG  
  tar -czf ../version3.tar.gz --exclude=.git --exclude=.terraform --exclude=.next --exclude=node_modules --exclude=*.pyc --exclude=__pycache__ .

  docker rm -f  $(docker ps -aq) 2>/dev/null
  docker rmi -f $(docker images -aq) 2>/dev/null
  docker system prune -a --volumes -f
  kind delete cluster --name staging

  docker images
  docker ps
  docker network ls
  kubectl get namespaces
  #kubectl delete namespace explore

  # CHECK NETWORKING  
  docker network inspect kind
  for d in kafka redis postgres; do docker network disconnect kind $d; done
  for c in postgres redis kafka; do docker network connect kind $c; done  
  docker inspect postgres        # redis         # kafka

  # CHECK POSTGRES  
  kubectl run postgres   --rm -it   --restart=Never   --image=postgres:16-alpine   --env="PGPASSWORD=postgres"   --command --   \
  psql -h 172.19.0.5 -U postgres -d auth_service \
  -c "SELECT * FROM outbox_events ORDER BY created_at DESC LIMIT 1"
  -c "\dt"

    psql -h localhost -p 5432 -U postgres
    docker exec -it postgres psql -U postgres    

  # CHECK REDIS
  kubectl run redis --rm -it --image=redis:7-alpine -- sh
    redis-cli -h 172.19.0.6 MONITOR
    redis-cli -h 172.19.0.6 -p 6379
      SET test:key "hello"         GET test:key        DEL test:key
    docker exec -it redis redis-cli MONITOR
    docker logs -f redis        docker logs --tail 20 redis

  # CHECK KAFKA
  kubectl run kafka --rm -it --restart=Never --image=confluentinc/cp-kafka:latest bash
    kafka-console-consumer --bootstrap-server 172.19.0.7:9092 --topic explore.events

  kubectl run kafkaproducer --rm -it --restart=Never --image=confluentinc/cp-kafka:latest --command --   \
    kafka-console-producer --bootstrap-server 172.19.0.7:9092 --topic explore.events


  docker run -it --rm --network explore_infra_net confluentinc/cp-kafka:latest bash
    kafka-console-consumer --bootstrap-server kafka:29092 --topic explore.events

  docker run -it --rm --network explore_infra_net confluentinc/cp-kafka:latest \
    kafka-console-consumer --bootstrap-server kafka:29092 --topic explore.events

  docker exec -it kafka     kafka-console-producer --bootstrap-server kafka:29092 --topic explore.events

  docker logs -f kafka        docker logs --tail 20 kafka


  # CHECK KUBERNETES
  kubectl get nodes -o wide
  kubectl top pods -n explore    
    kubectl set env deployment --all -n explore POSTGRES_HOST=172.19.0.6 REDIS_URL=redis://172.19.0.5:6379/0 KAFKA_BOOTSTRAP_SERVERS=172.19.0.7
    kubectl set env deployment/auth-service -n explore POSTGRES_HOST=172.19.0.6
    kubectl exec -it auth-service-84b7cd99b4-x924k -n explore -- env | grep REDIS
MSG