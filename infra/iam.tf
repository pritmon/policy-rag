# iam.tf — IRSA (IAM Roles for Service Accounts) setup.
#
# Problem: our app pods need to call AWS Bedrock (Nova LLM + Titan Embed).
# Bedrock requires AWS credentials. But we can't hardcode credentials in the pod.
#
# Solution: IRSA — pods automatically get AWS credentials through a Kubernetes
# Service Account linked to an IAM role. No secrets needed anywhere.
#
# How IRSA works (simplified):
#   1. EKS has an OIDC identity provider (like a passport office)
#   2. Each pod shows its "passport" (service account token) to AWS
#   3. AWS checks the OIDC provider and grants the pod its IAM role
#   4. The pod can now call Bedrock — no hardcoded keys ever
#
# Files that use this:
#   k8s/serviceaccount.yaml — annotated with the IRSA role ARN
#   k8s/app.yaml            — uses the service account
#   k8s/ingest-job.yaml     — uses the service account

# ─── OIDC Provider ────────────────────────────────────────────────────────────

# Get the TLS certificate of the EKS OIDC issuer (needed for the trust)
data "tls_certificate" "eks" {
  url = aws_eks_cluster.main.identity[0].oidc[0].issuer
}

# Register the EKS OIDC provider with AWS IAM so pods can authenticate
resource "aws_iam_openid_connect_provider" "eks" {
  client_id_list  = ["sts.amazonaws.com"]
  thumbprint_list = [data.tls_certificate.eks.certificates[0].sha1_fingerprint]
  url             = aws_eks_cluster.main.identity[0].oidc[0].issuer
}

# ─── IAM Role for the App Pod ─────────────────────────────────────────────────

# This is the role our app pod will assume to call Bedrock.
# The trust policy says: only the policy-rag-sa service account in the default
# namespace of THIS cluster can assume this role. Very narrow, very secure.
resource "aws_iam_role" "app_irsa" {
  name = "${var.cluster_name}-app-irsa"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Principal = {
        # Only the OIDC provider for THIS EKS cluster can grant this role
        Federated = aws_iam_openid_connect_provider.eks.arn
      }
      Action = "sts:AssumeRoleWithWebIdentity"
      Condition = {
        StringEquals = {
          # Only allow the specific service account: default/policy-rag-sa
          "${replace(aws_iam_openid_connect_provider.eks.url, "https://", "")}:sub" = "system:serviceaccount:default:policy-rag-sa"
        }
      }
    }]
  })
}

# ─── Bedrock Permission ───────────────────────────────────────────────────────

# Grant the app role permission to call Bedrock InvokeModel (Nova + Titan)
resource "aws_iam_role_policy" "bedrock" {
  name = "bedrock-invoke"
  role = aws_iam_role.app_irsa.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["bedrock:InvokeModel"]  # only what we need — no other permissions
      Resource = "*"                      # all Bedrock models in the region
    }]
  })
}
