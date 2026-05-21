output "ecr_urls" {
  value = {
    for repo in aws_ecr_repository.services :
    repo.name => repo.repository_url
  }
}
