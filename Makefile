# Simple makefile to simplify repetitive build env management tasks under posix

CODESPELL_DIRS ?= ./
CODESPELL_SKIP ?= "*.pyc,*.txt,*.gif,*.png,*.jpg,*.ply,*.vtk,*.vti,*.js,*.html,*.doctree,*.ttf,*.woff,*.woff2,*.eot,*.mp4,*.inv,*.pickle,*.ipynb,flycheck*,./.git/*,./.hypothesis/*,*.yml,./docs/_build/*,./docs/images/*,./dist/*,*~,.hypothesis*,./docs/examples/*,*.mypy_cache/*,*cover,./tests/htmlcov/*,*.css,*.svg"
CODESPELL_IGNORE ?= "ignore_words.txt"

all: doctest

doctest: codespell

codespell:
	@echo "Running codespell"
	@codespell $(CODESPELL_DIRS) -S $(CODESPELL_SKIP) -I $(CODESPELL_IGNORE)
