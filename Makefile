# AirDriver — convenience targets.  Run `make help` for the list.
PY    ?= python3
VENV  := .venv
VPY   := $(VENV)/bin/python

.DEFAULT_GOAL := help

.PHONY: help install setup gui run scan doctor db offline clean uninstall

help: ## Show this help
	@echo "AirDriver — make targets:"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
	  | awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

install: ## Full system install (system deps + venv + launcher) — needs sudo
	sudo ./install.sh

setup: $(VPY) ## Set up a local venv with the GUI (no root)
$(VPY):
	$(PY) -m venv $(VENV)
	$(VPY) -m pip install --upgrade pip wheel
	$(VPY) -m pip install -e ".[gui]"

gui: setup ## Launch the GUI from the local venv
	$(VPY) -m airdriver

run: gui ## Alias for `gui`

scan: setup ## CLI: scan for adapters
	$(VPY) -m airdriver scan

doctor: setup ## CLI: system readiness check
	$(VPY) -m airdriver doctor

db: setup ## CLI: dump the chipset database
	$(VPY) -m airdriver db

offline: ## Pre-fetch driver sources for air-gapped installs (run while online)
	./scripts/fetch_offline_drivers.sh

clean: ## Remove the local venv and build artifacts
	rm -rf $(VENV) build dist *.egg-info airdriver/*.egg-info

uninstall: ## Remove the system launcher and local venv
	sudo rm -f /usr/local/bin/airdriver
	rm -rf $(VENV)
