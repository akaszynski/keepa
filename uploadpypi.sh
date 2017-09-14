#!/bin/bash

# clean dist folder
rm -rf ./dist/*

# build dist
python setup.py sdist

# upload to PyPI
twine upload dist/*
