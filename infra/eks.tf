# eks.tf — EKS cluster and worker node group.
#
# Creates two things:
#   1. EKS Cluster (policy-rag) — the Kubernetes control plane
#      Think of this as the "brain" of Kubernetes — it decides what runs where.
#      AWS manages this for you; you pay $0.10/hour just for the control plane.
#
#   2. Node Group (main) — the actual EC2 servers that run your pods
#      These are t3.small instances (1 node by default, max 2).
#      This is where your app, pgvector, and ingest job actually run.
#
# IAM roles are required because:
#   - The cluster needs permission to manage AWS resources (load balancers, etc.)
#   - The nodes need permission to pull images from ECR and join the cluster

# ─── IAM Role for the EKS Control Plane ───────────────────────────────────────

# This role lets the EKS service manage AWS resources on your behalf
resource "aws_iam_role" "eks_cluster" {
  name = "${var.cluster_name}-cluster-role"

  # Trust policy: only the EKS service can assume this role
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "eks.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

# Attach the AWS-managed EKS cluster policy to the role above
resource "aws_iam_role_policy_attachment" "eks_cluster_policy" {
  role       = aws_iam_role.eks_cluster.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonEKSClusterPolicy"
}

# ─── EKS Cluster ──────────────────────────────────────────────────────────────

resource "aws_eks_cluster" "main" {
  name     = var.cluster_name  # "policy-rag"
  role_arn = aws_iam_role.eks_cluster.arn
  version  = "1.30"

  vpc_config {
    # Place the cluster in the default VPC subnets (excluding us-east-1e)
    subnet_ids = data.aws_subnets.default.ids
  }

  # Wait for the IAM role to be fully ready before creating the cluster
  depends_on = [aws_iam_role_policy_attachment.eks_cluster_policy]
}

# ─── IAM Role for Worker Nodes (EC2 instances) ────────────────────────────────

# This role lets EC2 instances join the EKS cluster and pull images from ECR
resource "aws_iam_role" "node_group" {
  name = "${var.cluster_name}-node-role"

  # Trust policy: only EC2 service can assume this role
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "ec2.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

# Allow nodes to act as EKS worker nodes (register with cluster, describe resources)
resource "aws_iam_role_policy_attachment" "node_worker" {
  role       = aws_iam_role.node_group.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonEKSWorkerNodePolicy"
}

# Allow nodes to manage pod networking (VPC CNI plugin)
resource "aws_iam_role_policy_attachment" "node_cni" {
  role       = aws_iam_role.node_group.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonEKS_CNI_Policy"
}

# Allow nodes to pull Docker images from ECR (read-only)
resource "aws_iam_role_policy_attachment" "node_ecr" {
  role       = aws_iam_role.node_group.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonEC2ContainerRegistryReadOnly"
}

# ─── Node Group (Worker EC2 Instances) ────────────────────────────────────────

resource "aws_eks_node_group" "main" {
  cluster_name    = aws_eks_cluster.main.name
  node_group_name = "main"
  node_role_arn   = aws_iam_role.node_group.arn
  subnet_ids      = data.aws_subnets.default.ids
  instance_types  = [var.node_instance_type]  # default: t3.small

  # Auto-scaling config: start with 1 node, allow up to 2 during load
  scaling_config {
    desired_size = 1
    min_size     = 1
    max_size     = 2
  }

  # Wait for all node IAM policies to be attached before creating nodes
  depends_on = [
    aws_iam_role_policy_attachment.node_worker,
    aws_iam_role_policy_attachment.node_cni,
    aws_iam_role_policy_attachment.node_ecr,
  ]
}
