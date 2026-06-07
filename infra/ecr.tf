# ecr.tf — Elastic Container Registry (ECR) repository.
#
# ECR is like a private Docker Hub hosted inside your AWS account.
# You push your Docker image here, and EKS pulls it from here when deploying.
#
# Why not use Docker Hub?
#   - ECR is inside AWS — faster pulls for EKS (same network, no internet)
#   - Private by default — only your AWS account can access it
#   - No rate limits on pulls (Docker Hub throttles free accounts)
#
# Lifecycle policy:
#   Automatically deletes old images when more than 5 are stored.
#   Prevents the repository from filling up with stale builds over time.

# Create the ECR repository for the policy-rag Docker image
resource "aws_ecr_repository" "app" {
  name                 = var.ecr_repo_name       # "policy-rag"
  image_tag_mutability = "MUTABLE"               # allows pushing :latest repeatedly

  image_scanning_configuration {
    scan_on_push = true  # automatically scan images for known security vulnerabilities
  }
}

# Lifecycle policy: keep only the 5 most recent images, delete older ones
resource "aws_ecr_lifecycle_policy" "app" {
  repository = aws_ecr_repository.app.name

  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "Keep last 5 images — delete older ones automatically"
      selection = {
        tagStatus   = "any"                 # applies to all tags (including :latest)
        countType   = "imageCountMoreThan"
        countNumber = 5                     # keep at most 5 images
      }
      action = { type = "expire" }          # delete images beyond the limit
    }]
  })
}
