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
  
# CREATE CLUSTER AUTOCALING


kubectl wait -n explore --for=condition=available deployment --all --timeout=600s
