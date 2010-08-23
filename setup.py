#!/usr/bin/env python

import os
import sys

from distutils.core import setup

__dir__ = os.path.realpath(os.path.dirname(__file__))

sys.path.insert(0, __dir__)
try:
    import pc
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

__doc__ = """process control -- easy fork-exec and pipe with I/O redirection

Design goals:

  * Easy to fork-exec commands, wait or no wait
  * Easy to capture stdout/stderr of children (command substitution)
  * Easy to express I/O redirections
  * Easy to construct pipelines
  * Use short names for easy interactive typing

In effect, make Python more usable as a system shell.

Technically, pc.py is a layer on top of subprocess. The subprocess
module support a rich API but is clumsy for many common use cases,
namely sync/async fork-exec, command substitution and pipelining,
all of which is trivial to do on system shells.

Documentation is at <http://github.com/aht/pc.py/>.

This module depends on Python 2.6, or where subprocess is available.
Doctests require /bin/sh to pass. Tested on Linux.

This is an alpha release. Some features are unimplemented. Expect bugs.""".split('\n')

setup(
	name = 'pc',
	version = '0.0.1',
	description = __doc__[0],
	long_description = "\n".join(__doc__[2:]),
	author = 'Anh Hai Trinh',
	author_email = 'moc.liamg@hnirt.iah.hna:otliam'[::-1],
	keywords='fork exec pipe IO redirection',
	url = 'http://github.com/aht/pc.py',
	platforms=['any'],
	classifiers=filter(None, classifiers.split("\n")),
	py_modules = ['pc']
)
