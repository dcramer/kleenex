#!/usr/bin/env python

from setuptools import setup, find_packages

tests_require = [
]

setup(
    name='nose-kleenex',
    version='0.10.1',
    author='David Cramer',
    author_email='dcramer@gmail.com',
    description='A discovery plugin for Nose which relies on code coverage.',
    url='http://github.com/dcramer/nose-kleenex',
    packages=find_packages(exclude=["tests"]),
    zip_safe=False,
    install_requires=[
        'nose>=0.9',
        'simplejson',
        'SQLAlchemy>=0.7',
    ],
    entry_points={
       'nose.plugins.0.10': [
            'kleenex = kleenex.plugin:TestCoveragePlugin'
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
