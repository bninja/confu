import re
import setuptools


extras_require = {
    'tests': [
        'mock >=1.0,<2.0',
        'pytest >=2.5.2,<3',
        'pytest-cov >=1.7,<2',
    ]
}

setuptools.setup(
    name='con-fu',
    version=(
        re
        .compile(r".*__version__ = '(.*?)'", re.S)
        .match(open('confu/__init__.py').read())
        .group(1)
    ),
    url='https://github.com/bninja/confu',
    license='BSD',
    author='Egon Spengler',
    author_email='egon@gb.com',
    description='Fu for con.',
    long_description=open('README.rst').read(),
    packages=setuptools.find_packages('.', exclude=('tests', 'tests.*')),
    platforms='any',
    install_requires=[
        'ansible >= 2,<3',
        'boto >= 2.4.6,<3',
        'troposphere >= 2,<3',
        'click',
        'pilo >=0.4,<0.5',
        'virtualenv',
        'virtualenv-relocate',
    ],
    extras_require=extras_require,
    tests_require=extras_require['tests'],
    scripts=['bin/confu'],
    classifiers=[
        'Intended Audience :: Developers',
        'License :: OSI Approved :: BSD License',
        'Operating System :: OS Independent',
        'Programming Language :: Python',
        'Topic :: Internet :: WWW/HTTP :: Dynamic Content',
        'Topic :: Software Development :: Libraries :: Python Modules'
    ]
)
