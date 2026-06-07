terraform {
  required_version = ">= 1.6"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
  # Production upgrade: use S3 backend + DynamoDB lock
  # backend "s3" {
  #   bucket         = "your-tfstate-bucket"
  #   key            = "policy-rag/terraform.tfstate"
  #   region         = "us-east-1"
  #   dynamodb_table = "tf-locks"
  # }
}

provider "aws" {
  region = var.aws_region
}

data "aws_vpc" "default" {
  default = true
}

data "aws_subnets" "default" {
  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.default.id]
  }
}

data "aws_caller_identity" "current" {}
