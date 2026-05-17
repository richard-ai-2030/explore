# CI PIPELINE AUTOMATION
# developers push codes to Git repo 
  
# auto build images for each Git push 
  > build-domain-services.sh
# auto push to GHCR for each image built
  > load-services-to-kind.sh
# auto TEST with a Docker container node
  > ./automation/CI_workflow/smoke-test.sh


# CD PIPELINE AUTOMATION
# auto deploy services to Kubernetes for each QC passed
  > kubectl apply -k k8s/cloud/overlays/aws/shared
  > kubectl wait -n explore --for=condition=available deployment --all --timeout=600s
  > kubectl port-forward -n ingress-nginx "svc/ingress-nginx-controller" "8888:80"

# enable Service Mesh : mTLS, rounting/retries/timeout, failover handling
  REST + JSON | HTTP 1.1           VS   GRAPHQL + JSON
  gRPC + Protobuf | HTTP 2.0

# auto UAT with TOP10 AWASP list
  > nextjs build
  > aws upload-to-S3 (private bucket)
  > aws cloudfront invalidating
  > ./automation/CD_workflow/run-FRONTEND.sh


# AWS PIPELINE AUTOMATION
image: <your-account>.dkr.ecr.ap-southeast-1.amazonaws.com/auth-service:latest

aws eks update-kubeconfig \
  --region ap-southeast-1 \
  --name microservices-cluster
