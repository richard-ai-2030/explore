# Build foundational SERVICES to Docker images
./automation/agents/build-domain-services.sh BASE
./automation/agents/build-domain-services.sh MARKETING

# Load foundational IMAGES to K8s
./automation/agents/load-images-k8s.sh BASE
./automation/agents/load-images-k8s.sh MARKETING


for service in BASE MARKETING PRODUCTION TALENTS ACCOUNTING; do
  ./automation/agents/build-domain-services.sh $service       # Re-build SERVICES to images
  ./automation/agents/load-images-k8s.sh $service             # Re-load IMAGES to K8S
done

for service in shared marketing production talents accounting; do
  kubectl apply -k k8s/cloud/overlays/local/$service          # Create (re-apply) Deployment and Service
  #kubectl delete -k k8s/cloud/overlays/local/$service
done

for service in shared marketing production talents accounting; do
  kubectl apply -k k8s/autoscaling/overlays/local/$service    # create Pod Autoscaling
  #kubectl delete -k k8s/autoscaling/overlays/local/$service
done
  
# CREATE CLUSTER AUTOCALING  # CREATE CLUSTER AUTOCALING

kubectl wait -n explore --for=condition=available deployment --all --timeout=600s

for service in auth-service bff-marketing; do
  kubectl describe deployment $service -n explore
  kubectl describe svc $service -n explore
  kubectl logs deployment/$service -n explore
  kubectl logs svc/$service -n explore
  #kubectl delete deployment $service -n explore
  #kubectl delete svc $service -n explore
done

  #kubectl set env deployment --all -n explore POSTGRES_HOST=172.19.0.5 KAFKA_BOOTSTRAP_SERVERS=172.19.0.7
  #kubectl set env deployment/auth-service -n explore REDIS_URL=redis://172.19.0.6:6379/0  
  #kubectl scale deployment --all --replicas=1 -n explore
  #kubectl delete hpa --all -n explore
