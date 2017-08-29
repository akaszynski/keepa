# -*- coding: utf-8 -*-
"""
Setup.py for keepaAPI

Upload to PyPi using
python setup.py sdist upload -r pypi

"""
from setuptools import setup

setup(
    name='keepaAPI',
    packages = ['keepaAPI'],

    # Version
    version='0.14',

    description='Interfaces with keepa.com',
    long_description=open('README.rst').read(),

    # Author details
    author='Alex Kaszynski',
    author_email='akascap@gmail.com',

    license='Apache Software License',
    classifiers=[
        'Development Status :: 5 - Production/Stable',
        'Intended Audience :: End Users/Desktop',
        'Topic :: Database :: Front-Ends',
        'License :: OSI Approved :: Apache Software License',
        'Programming Language :: Python :: 2.7',
        'Programming Language :: Python :: 3.4',
        'Programming Language :: Python :: 3.5',
    ],

    # Website
    url = 'https://github.com/akaszynski/keepaAPI',

    keywords='keepa',

    # Might work with earlier versions (untested)
    install_requires=['numpy>=1.9.3', 'requests>=2.2']

)

