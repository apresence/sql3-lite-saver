.PHONY: install lint test build release clean install-dev install-prod

install:
	pip install -e .[dev,retry]

install-prod:
	pip install -e .

install-dev:
	pip install -e .[dev,retry]

lint:
	ruff check src tests

test:
	python -m unittest discover -s tests -v

build: clean
	python -m build

release: build
	python -m twine check dist/*
	python -m twine upload dist/*

clean:
	rm -rf dist build *.egg-info __pycache__
