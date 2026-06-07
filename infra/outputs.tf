output "cluster_name" {
  value = aws_eks_cluster.main.name
}

output "ecr_url" {
  value = aws_ecr_repository.app.repository_url
}

output "irsa_role_arn" {
  value = aws_iam_role.app_irsa.arn
}

output "cluster_endpoint" {
  value = aws_eks_cluster.main.endpoint
}
