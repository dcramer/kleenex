#!/usr/bin/env python

from setuptools import setup, find_packages

tests_require = [
]

setup(
    name='nose-bleed',
    version='0.2.0',
    author='David Cramer',
    author_email='dcramer@gmail.com',
    description='A progressive coverage plugin for Nose.',
    url='http://github.com/dcramer/nose-bleed',
    packages=find_packages(exclude=["tests"]),
    zip_safe=False,
    install_requires=[
        'nose>=0.9',
        'simplejson',
        'SQLAlchemy>=0.7',
    ],
    entry_points={
       'nose.plugins.0.10': [
            'nose_bleed = nose_bleed.plugin:TestCoveragePlugin'
        ]
    },
    license='Apache License 2.0',
    tests_require=tests_require,
    extras_require={'test': tests_require},
    test_suite='runtests.runtests',
    include_package_data=True,
    classifiers=[
        'Intended Audience :: Developers',
        'Intended Audience :: System Administrators',
        'Operating System :: OS Independent',
        'Topic :: Software Development'
    ],
)
