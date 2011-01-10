#!/usr/bin/env python2

import os
import sys

from distutils.core import setup

__dir__ = os.path.realpath(os.path.dirname(__file__))

sys.path.insert(0, __dir__)
try:
    import extproc
finally:
    del sys.path[0]

classifiers = """
Development Status :: 3 - Alpha
Intended Audience :: Developers
License :: OSI Approved :: MIT License
Operating System :: OS Independent
Programming Language :: Python
Topic :: Software Development :: Libraries :: Python Modules
Topic :: Utilities
"""

__doc__ = """extproc -- easy fork-exec and pipe with I/O redirection

extproc is a layer on top of subprocess. The subprocess module supports
a rich API but is clumsy for many common use cases, namely sync/async
fork-exec, command substitution and pipelining, all of which is trivial
to do on system shells.

The goal is to make Python a sane alternative to non-trivial shell scripts.

Features:

  * Easy to fork-exec commands, wait or no wait
  * Easy to capture stdout/stderr of children (command substitution)
  * Easy to express I/O redirections
  * Easy to construct pipelines
  * Use short names for easy interactive typing

Documentation is at <http://github.com/aht/extproc/>.

This module depends on Python 2.6, or where subprocess is available.
Doctests require /bin/sh to pass. Tested on Linux.

This is an alpha release. Expect bugs.""".split('\n')

setup(
	name = 'extproc',
	version = '0.0.3',
	description = __doc__[0],
	long_description = "\n".join(__doc__[2:]),
	author = 'Anh Hai Trinh',
	author_email = 'moc.liamg@hnirt.iah.hna:otliam'[::-1],
	keywords='fork exec pipe IO redirection',
	url = 'http://github.com/aht/extproc/',
	platforms=['any'],
	classifiers=filter(None, classifiers.split("\n")),
	py_modules = ['extproc']
)
