# DEPLOY FOUNDATION SERVICES
kubectl apply -k k8s/cloud/overlays/local/shared
kubectl wait -n explore --for=condition=available deployment --all --timeout=600s
#kubectl delete -k k8s/cloud/overlays/local/shared

  for n in ingress-nginx explore; do  
    kubectl get deployments -o wide -n $n;     # how your Pods are created (from images GHCR, port, replicas..)
    kubectl get svc         -o wide -n $n;     # IP access point & load balancer for a group of Pods
    kubectl get hpa  -o wide -n $n;

    kubectl get pods -o wide -n $n;            # independent deployable unit where the actual application lives
    kubectl get endpoints -n $n;               # Endpoints are only populated when Pod is Running and Readiness probe passes
  done
  
# DEPLOY DOMAIN SERVICES
kubectl apply -k k8s/cloud/overlays/local/marketing
kubectl wait -n explore --for=condition=available deployment --all --timeout=600s
#kubectl delete -k k8s/cloud/overlays/local/marketing

# DEPLOY AUTOSCALING
kubectl apply -k k8s/autoscaling/overlays/local/shared
kubectl apply -k k8s/autoscaling/overlays/local/marketing
kubectl wait -n explore --for=condition=available deployment --all --timeout=600s
  #kubectl delete -k k8s/autoscaling/overlays/local/shared  
  #kubectl delete hpa --all -n explore
  #kubectl scale deployment --all --replicas=1 -n explore

echo
cat <<MSG  

?? still no records at notifications and events table
reorganize Kafka topics and consumer groups
reorganize Redis key

# play with Service Mesh : mTLS, rounting/retries/timeout, failover handling
  REST + JSON | HTTP 1.1           VS   GRAPHQL + JSON
  gRPC + Protobuf | HTTP 2.0

?? adding scaling per RPS instead of CPU, rate limiting ? at Nginx, at each domain service


?? enforce RBAC using `X-Auth-*` headers for Downstream services (a JWT has 3 parts: header.payload.signature)

Rollback procedure
  kubectl rollout status deployment auth-service -n explore
                  history / undo / undo --to-revision=2
  helm history my-release
       rollback upgrade my-release 2                
MSG