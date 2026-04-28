Auth-service returns identity headers X-Auth-User-Id, X-Auth-User-Email, X-Auth-User-Scopes:
    Authorization: Bearer <JWT token>    a JWT has 3 parts: header.payload.signature

Downstream services enforce service-local RBAC using `X-Auth-*` headers
    lead-to-order, procure-to-stock, hire-to-engage


### Add per-environment overlays such as `dev`, `staging`, and `prod`

Before (local)
  Docker runs containers
  Kubernetes might be local (minikube/kind)

After (AWS)
  Build images → push to ECR
  Terraform creates EKS cluster
  Apply your existing k8s/ manifests
  System runs in AWS

docker tag service:latest <ECR_URL>
docker push <ECR_URL>

image: <your-account>.dkr.ecr.ap-southeast-1.amazonaws.com/auth-service:latest

After terraform apply:
  aws eks update-kubeconfig \
  --region ap-southeast-1 \
  --name microservices-cluster

  kubectl apply -f k8s/  

This will cost money (EKS + EC2 + NAT Gateway)
  AWS account
  IAM permissions
Terraform state should move to remote backend (e.g., S3)  