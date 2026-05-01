### Add per-environment overlays such as `dev`, `staging`, and `prod`
This will cost money (EKS + EC2 + NAT Gateway)
  AWS account
  IAM permissions

Terraform state should move to remote backend (e.g., S3)  

image: <your-account>.dkr.ecr.ap-southeast-1.amazonaws.com/auth-service:latest

aws eks update-kubeconfig \
  --region ap-southeast-1 \
  --name microservices-cluster

AUTOMATION
CI workflows:
git status
git add .