# Makefile — Shortcuts for every common task in this project.
#
# Instead of remembering long commands, you type short ones:
#   make up      → start the local database
#   make ingest  → load the policy document into it
#   make dev     → run the app on your laptop
#   make eval    → run the quality exam
#   make deploy  → ship everything to Kubernetes on AWS
#
# Think of it as the project's remote control — one button per job.

# Load variables from .env (API keys, region, etc.) so every command sees them
-include .env
export

# Use the Python inside this project's virtual environment
PYTHON        := .venv/bin/python
# Default AWS region (can be overridden: make push REGION=us-west-2)
REGION        ?= us-east-1
# Ask Terraform for the ECR repository address (where Docker images go)
ECR_URL       ?= $(shell cd infra && terraform output -raw ecr_url 2>/dev/null)
IMAGE_TAG     ?= latest
IMAGE         := $(ECR_URL):$(IMAGE_TAG)

# These names are commands, not files — always run them when asked
.PHONY: up down ingest dev eval test lint build push tf-apply tf-destroy deploy

## ── Local development ────────────────────────────────────────────────

# Start the local pgvector database (Docker) and give it 5s to wake up
up:
	docker compose up -d
	@echo "Waiting for pgvector..." && sleep 5

# Stop the local database and erase its data (-v removes the volume)
down:
	docker compose down -v

# Load policy.md into the database (chunk → embed → store)
ingest:
	$(PYTHON) ingestion/ingest.py

# Run the app locally with auto-reload (code changes apply instantly)
dev:
	$(PYTHON) -m uvicorn app.main:app --reload --port 8000

## ── Quality checks ───────────────────────────────────────────────────

# Run the exam: ask golden questions, score the answers, write report.json
eval:
	$(PYTHON) eval/run_eval.py

# Check the exam scores meet the minimum floors (pass/fail gate)
test:
	$(PYTHON) -m pytest eval/test_eval.py -v

# Check code style — catches typos and messy code before they bite
lint:
	$(PYTHON) -m ruff check app/ ingestion/ eval/

## ── Container (Docker) ───────────────────────────────────────────────

# Pack the app into a Docker image
build:
	docker build -t policy-rag:$(IMAGE_TAG) .

# Build, log in to AWS ECR, and upload the image there
push: build
	aws ecr get-login-password --region $(REGION) | \
	  docker login --username AWS --password-stdin $(ECR_URL)
	docker tag policy-rag:$(IMAGE_TAG) $(IMAGE)
	docker push $(IMAGE)

## ── Infrastructure (Terraform) ───────────────────────────────────────

# Create ALL AWS resources (EKS cluster, ECR, IAM roles) — takes ~15 min
tf-apply:
	cd infra && terraform init && terraform apply -auto-approve

# DELETE all AWS resources — run this when done to stop the bills!
tf-destroy:
	cd infra && terraform destroy -auto-approve

## ── Deploy to Kubernetes ─────────────────────────────────────────────

# Apply all k8s manifests: database, permissions, app, ingest job
deploy:
	kubectl apply -f k8s/pgvector.yaml
	kubectl apply -f k8s/serviceaccount.yaml
	kubectl apply -f k8s/app.yaml
	kubectl apply -f k8s/ingest-job.yaml
	@echo "Waiting for LoadBalancer..."
	kubectl rollout status deployment/policy-rag-app
