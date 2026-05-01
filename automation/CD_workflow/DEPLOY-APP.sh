# CHECK FOUNDATION SHARED SERVICES
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
  
kubectl port-forward -n ingress-nginx "svc/ingress-nginx-controller" "8888:80"
  curl http://127.0.0.1:8888/api/auth/health
kubectl port-forward -n explore "svc/auth-service" "7000:7000"
  curl http://127.0.0.1:7000/health
  
# CHECK DOMAIN SERVICES
kubectl apply -k k8s/cloud/overlays/local/marketing
kubectl wait -n explore --for=condition=available deployment --all --timeout=600s
#kubectl delete -k k8s/cloud/overlays/local/marketing

# CHECK AUTOSCALING
kubectl apply -k k8s/autoscaling/overlays/local/shared
kubectl apply -k k8s/autoscaling/overlays/local/marketing
kubectl wait -n explore --for=condition=available deployment --all --timeout=600s
#kubectl delete -k k8s/autoscaling/overlays/local/shared  
  #kubectl delete hpa --all -n explore
  #kubectl scale deployment --all --replicas=1 -n explore

# CHECK SMOKE TEST
./automation/CI_workflow/smoke-test.sh
./automation/CD_workflow/run-FRONTEND.sh
  #http://127.0.0.1:808x          http://127.0.0.1:8025

echo
cat <<MSG  
  docker build -t auth-service:version3 ./services/BASE/auth-service
  kind load docker-image auth-service:version3 --name staging  
  kubectl apply -f k8s/cloud/base/shared/auth-service.yaml
  kubectl rollout restart deployment auth-service -n explore

AWS ALB runs outside the Kubernetes cluster. It does load balancing + intelligent routing, TLS termination but rate limiting is not native to ALB itself.

NGINX runs inside the Kubernetes cluster, as a Pod (Deployment, HPA). It is feature-rich including all above.
NGINX is acting like a lightweight API Gateway, but it’s not a full API Gateway in the traditional sense.

# ?? adding scaling per RPS instead of CPU, rate limiting ? at Nginx, at each domain service
# ?? create MongoDB and update Analytics with ElasticSearch
reorganize Kafka topics and consumer groups
reorganize Redis key
what is Helm?
explore GraphQL
still no records at notifications and events table

enforce RBAC using `X-Auth-*` headers for Downstream services (a JWT has 3 parts: header.payload.signature)

MSG