-include .env
export

PYTHON        := .venv/bin/python
REGION        ?= us-east-1
ECR_URL       ?= $(shell cd infra && terraform output -raw ecr_url 2>/dev/null)
IMAGE_TAG     ?= latest
IMAGE         := $(ECR_URL):$(IMAGE_TAG)

.PHONY: up down ingest dev eval test lint build push tf-apply tf-destroy deploy

## Local dev
up:
	docker compose up -d
	@echo "Waiting for pgvector..." && sleep 5

down:
	docker compose down -v

ingest:
	$(PYTHON) ingestion/ingest.py

dev:
	$(PYTHON) -m uvicorn app.main:app --reload --port 8000

## Quality
eval:
	$(PYTHON) eval/run_eval.py

test:
	$(PYTHON) -m pytest eval/test_eval.py -v

lint:
	$(PYTHON) -m ruff check app/ ingestion/ eval/

## Container
build:
	docker build -t policy-rag:$(IMAGE_TAG) .

push: build
	aws ecr get-login-password --region $(REGION) | \
	  docker login --username AWS --password-stdin $(ECR_URL)
	docker tag policy-rag:$(IMAGE_TAG) $(IMAGE)
	docker push $(IMAGE)

## Terraform
tf-apply:
	cd infra && terraform init && terraform apply -auto-approve

tf-destroy:
	cd infra && terraform destroy -auto-approve

## Kubernetes deploy
deploy:
	kubectl apply -f k8s/pgvector.yaml
	kubectl apply -f k8s/serviceaccount.yaml
	kubectl apply -f k8s/app.yaml
	kubectl apply -f k8s/ingest-job.yaml
	@echo "Waiting for LoadBalancer..."
	kubectl rollout status deployment/policy-rag-app
