kubectl apply -k k8s/cloud/overlays/local/shared
kubectl apply -k k8s/cloud/overlays/local/talents
kubectl wait -n explore --for=condition=available deployment --all --timeout=600s
  
  kubectl get deployments -o wide -n explore    # how your Pods are created (from images, port, replicas..)
  kubectl get svc         -o wide -n explore    # IP access point & load balancer for a group of Pods

  #kubectl describe deployment auth-service -n explore
  #kubectl describe svc auth-service -n explore
  #kubectl delete deployment auth-service -n explore
  #kubectl delete svc auth-service -n explore
  kubectl delete -k k8s/cloud/overlays/local/talents
  
kubectl get pods -o wide -n explore           # independent deployable unit where the actual application lives
kubectl get endpoints -n explore              # Endpoints are only populated when Pod is Running and Readiness probe passes

kubectl get hpa  -o wide -n explore  
kubectl scale deployment --all --replicas=1 -n explore
kubectl delete hpa --all -n explore


kubectl port-forward -n ingress-nginx "svc/ingress-nginx-controller" "8888:80"
curl http://127.0.0.1:8888/api/auth/health
./automation/CI_workflow/smoke-test.sh

./automation/CD_workflow/run-FRONTEND.sh
  #http://127.0.0.1:808x          http://127.0.0.1:8025


echo
cat <<MSG  
  docker build -t auth-service:version3 ./services/BASE/auth-service
  kind load docker-image auth-service:version3 --name staging  
  kubectl apply -f k8s/cloud/base/shared/auth-service.yaml
  kubectl rollout restart deployment auth-service -n explore
MSG