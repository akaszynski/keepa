"""
Setup for keepaAPI
"""
from setuptools import setup
import os
from io import open as io_open

package_name = 'keepaAPI'

# Get version from ./_version.py
__version__ = None
version_file = os.path.join(os.path.dirname(__file__),
                            package_name,
                            '_version.py')

with io_open(version_file, mode='r') as fd:
    exec(fd.read())

setup(
    name=package_name,
    packages=[package_name],
    version=__version__,
    description='Interfaces with keepa.com',
    long_description=open('README.rst').read(),
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
        'Programming Language :: Python :: 3.6',
        'Programming Language :: Python :: 3.7',
    ],
    url='https://github.com/akaszynski/keepaAPI',

    keywords='keepa',

    # Might work with earlier versions (untested)
    install_requires=['numpy>=1.9.3', 'requests>=2.2']

)
