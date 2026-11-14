# Thin wrapper around tasks.py so that `make setup`, `make data` and `make dev` work
# wherever make is installed. On Windows without make, run `python tasks.py <target>`.

PYTHON ?= python

.PHONY: setup data dev test build serve check

setup:
	$(PYTHON) tasks.py setup

data:
	$(PYTHON) tasks.py data

dev:
	$(PYTHON) tasks.py dev

test:
	$(PYTHON) tasks.py test

build:
	$(PYTHON) tasks.py build

serve:
	$(PYTHON) tasks.py serve

check:
	$(PYTHON) tasks.py check
