# -*- coding: utf-8 -*-
"""
Setup.py for keepaAPI

Upload to PyPi using
python setup.py sdist upload -r pypi

"""
from setuptools import setup
import numpy

setup(
    name='keepaAPI',
    packages = ['keepaAPI'],

    # Version
    version='0.13.1',

    description='Interfaces with keepa.com',
    long_description=open('README.rst').read(),

    # Author details
    author='Alex Kaszynski',
    author_email='akascap@gmail.com',

    license='Apache Software License',
    classifiers=[
        'Development Status :: 4 - Beta',

        # Target audience
        'Intended Audience :: End Users/Desktop',
        'Topic :: Database :: Front-Ends',

        # MIT License
        'License :: OSI Approved :: Apache Software License',

        # Tested only on Python 2.7 (untested with 3)
        'Programming Language :: Python :: 2.7',
        'Programming Language :: Python :: 3.4',
    ],

    # Website
    url = 'https://github.com/akaszynski/keepaAPI',

    keywords='keepa',                    

    include_dirs=[numpy.get_include()],       
                           
    # Might work with earlier versions (untested)
    install_requires=['numpy>=1.9.3', 'requests>=2.2']

)

