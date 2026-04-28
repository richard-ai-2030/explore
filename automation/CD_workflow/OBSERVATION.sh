kubectl get events -n explore --sort-by=.lastTimestamp | tail -n 25     # logs at Kubernetes level
kubectl logs -n ingress-nginx -l app.kubernetes.io/name=ingress-nginx   # API Gateway → [routing rules → rate limitting] → Pod

kubectl get pods -o wide -n ingress-nginx
kubectl get ingress -n explore

kubectl port-forward -n explore "svc/auth-service" "7000:7000"              # bypass Ingress controller
  curl http://127.0.0.1:7000/health


# execute a command inside a Pod
kubectl exec -it auth-service-75799cb866-25wlz -n explore -- /bin/bash
  apt update && apt install curl iputils-ping -y


# view Pod's log
kubectl logs -f deployment/auth-service -n explore
kubectl logs -n explore $(kubectl get pods -n explore | grep auth-service | awk '{print $1}' | head -n 1)

