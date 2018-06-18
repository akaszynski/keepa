#!/bin/bash

# clean dist folder
rm -rf ./dist/*

# build dist
python3 setup.py sdist

# upload to PyPI
twine upload dist/*
