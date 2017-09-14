# -*- coding: utf-8 -*-
"""
Setup.py for keepaAPI

Upload to PyPi using
python setup.py sdist upload -r pypi

"""
from setuptools import setup
import os
from io import open as io_open

package_name = 'keepaAPI'

# Get version from tqdm/_version.py
__version__ = None
version_file = os.path.join(os.path.dirname(__file__), package_name, '_version.py')
with io_open(version_file, mode='r') as fd:
    # execute file from raw string
    exec(fd.read())
    

setup(
    name=package_name,
    packages = [package_name],

    # Version
    version=__version__,

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

