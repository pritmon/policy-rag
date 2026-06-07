# main.tf — Root Terraform configuration.
#
# This file does 3 things:
#   1. Declares which version of Terraform and AWS provider is required
#   2. Configures the AWS provider (which region to deploy into)
#   3. Looks up the default VPC and its subnets so we don't have to create new ones
#
# We use the DEFAULT VPC (the one AWS creates automatically for every account)
# to keep costs low — no NAT gateways, no custom networking needed.
#
# Note: us-east-1e is excluded from the subnet list because EKS does not
# support creating control plane instances in that availability zone.

terraform {
  required_version = ">= 1.6"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }

  # Production upgrade: store Terraform state in S3 instead of local file.
  # Local state is fine for demos but should not be used in a team/prod environment.
  # backend "s3" {
  #   bucket         = "your-tfstate-bucket"
  #   key            = "policy-rag/terraform.tfstate"
  #   region         = "us-east-1"
  #   dynamodb_table = "tf-locks"   # prevents two people applying at the same time
  # }
}

# Tell the AWS provider which region to deploy everything into
provider "aws" {
  region = var.aws_region
}

# Look up the default VPC — every AWS account has one pre-created
data "aws_vpc" "default" {
  default = true
}

# Look up the subnets inside the default VPC.
# Filter to only supported EKS availability zones (us-east-1e is not supported).
data "aws_subnets" "default" {
  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.default.id]
  }
  # EKS does not support creating control plane nodes in us-east-1e.
  # Including it causes: UnsupportedAvailabilityZoneException on cluster creation.
  filter {
    name   = "availabilityZone"
    values = ["us-east-1a", "us-east-1b", "us-east-1c", "us-east-1d", "us-east-1f"]
  }
}

# Get the current AWS account ID (used in IAM role ARN construction)
data "aws_caller_identity" "current" {}
