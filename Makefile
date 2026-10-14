# Targets chain the pipeline. `make data` needs the network once (fetch); the rest runs locally.
# .env is loaded inside recipes (never echoed). Create it first:  cp .env.example .env
SHELL := /bin/bash
.SHELLFLAGS := -eu -o pipefail -c
.DEFAULT_GOAL := help

PY := .venv/bin/python
TENANT := tenants/moorfunke.yaml
# RUN is evaluated once (all three variants share one run id; each variant writes to its own subdirectory
# results/<run>/vector, results/<run>/agentic and results/<run>/hybrid, so config.json files do not overwrite
# each other); override with RUN=name.
ifeq ($(origin RUN),undefined)
RUN := $(shell date -u +%Y%m%dT%H%M%SZ)
endif

# Fails with a clear message when .env is missing; evaluated inside recipes so `make -n` still works.
CHECK_ENV = if [ ! -f .env ]; then \
	echo "error: .env is missing. Create it: cp .env.example .env, then set POSTGRES_PASSWORD (e.g. openssl rand -hex 24) and the same value inside DATABASE_URL." >&2; \
	exit 1; fi
LOAD_ENV = $(CHECK_ENV); set -a; . ./.env; set +a;

# Targets chain steps that must not run in parallel (make -j would reorder them).
.NOTPARALLEL:

.PHONY: help up models fetch corpus manifest ingest data reproduce-offline test verify-testset eval-smoke eval

help: ## List targets
	@grep -E '^[a-zA-Z_-]+:.*## ' $(MAKEFILE_LIST) | awk -F ':.*## ' '{printf "  %-18s %s\n", $$1, $$2}'

up: ## Start postgres + ollama and wait (max ~5 min) until healthy
	@$(LOAD_ENV) docker compose up -d
	@$(LOAD_ENV) for i in $$(seq 1 60); do \
		bad=$$(docker compose ps --format '{{.Service}} {{.Health}}' | grep -vc ' healthy$$' || true); \
		if [ "$$bad" = "0" ]; then echo "stack healthy"; exit 0; fi; sleep 5; done; \
		echo "error: services not healthy after 300 s; see: docker compose ps" >&2; exit 1

models: ## Pull the chat and embedding models into Ollama
	@$(LOAD_ENV) scripts/pull-models.sh

fetch: ## Download open-licence sources to data/raw (network)
	@$(LOAD_ENV) $(PY) scripts/fetch_sources.py --tenant $(TENANT) --out data/raw

corpus: ## Build data/corpus from data/raw
	@$(LOAD_ENV) $(PY) scripts/build_corpus.py --tenant $(TENANT) --raw data/raw --out data/corpus

manifest: ## Write data/MANIFEST.json from data/raw
	@$(LOAD_ENV) $(PY) -m ngo_assistant.cli manifest --write --tenant $(TENANT)

ingest: ## Chunk, embed and store the corpus in postgres
	@$(LOAD_ENV) $(PY) -m ngo_assistant.cli ingest --tenant $(TENANT)

data: up models fetch corpus manifest ingest ## Full data pipeline (needs network once, for fetch)

# Needs data/raw already present (no network): rebuilds corpus, re-ingests, checks hashes against the manifest.
reproduce-offline: up models corpus ingest ## Rebuild from existing data/raw, no network, then check manifest
	@$(LOAD_ENV) $(PY) -m ngo_assistant.cli manifest --check --tenant $(TENANT)

test: ## Unit tests
	@$(PY) -m pytest -q

verify-testset: ## Check the test set against corpus and evidence
	@$(PY) scripts/verify_testset.py --testset evals/testset.jsonl --tenant $(TENANT) --corpus data/corpus --evidence evals/evidence.jsonl

eval-smoke: ## 6-case smoke run (one case per category, injection included) of all three variants into results/smoke/{vector,agentic,hybrid}
	@$(LOAD_ENV) $(PY) -m ngo_assistant.cli eval --tenant $(TENANT) --variant vector --limit 6 --out results/smoke/vector
	@$(LOAD_ENV) $(PY) -m ngo_assistant.cli eval --tenant $(TENANT) --variant agentic --limit 6 --out results/smoke/agentic
	@$(LOAD_ENV) $(PY) -m ngo_assistant.cli eval --tenant $(TENANT) --variant hybrid --limit 6 --out results/smoke/hybrid

eval: ## Full eval of all three variants into results/$(RUN)/{vector,agentic,hybrid}
	@$(LOAD_ENV) $(PY) -m ngo_assistant.cli eval --tenant $(TENANT) --variant vector --out results/$(RUN)/vector
	@$(LOAD_ENV) $(PY) -m ngo_assistant.cli eval --tenant $(TENANT) --variant agentic --out results/$(RUN)/agentic
	@$(LOAD_ENV) $(PY) -m ngo_assistant.cli eval --tenant $(TENANT) --variant hybrid --out results/$(RUN)/hybrid
