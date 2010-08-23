process control -- fork-exec and pipe with I/O redirection

Introduction
============

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
all of which is trivial to do on system shells. [1][2]

This module depends on Python 2.6, or where `subprocess` is available.
Doctests require `/bin/sh` to pass. Tested on Linux.

This is an alpha release. Some features are unimplemented. Expect bugs.


Let's start forking!


Cmd(), Sh() and Pipe()
============================

Those objects hold information to prepare for a fork-exec (or for
Pipe, a series thereof).

The first argument to `Cmd()` should be a list of command argurments.
If a string, it is passed to `shlex.split()`.  Thus, Cmd(['grep', 'my stuff'])
and Cmd('grep "my stuff"') are equivalent.

`Sh(cmd)` is equivalent to Cmd(['/bin/sh','-c', cmd]). It is also a subclass.

To construct a `Pipe()`, pass in a list of Cmd's.

run()
=====

`run()` performs a fork-exec-wait and return the child's exit status, e.g.

    >>> assert 0 == Cmd('true').run()
    >>> found_deadbeaf = Pipe(Cmd('dmesg'), Cmd('grep deadbeaf')).run()


spawn()
=======

`spawn()` performs a fork-exec and returns a `subprocess.Popen` object.
The following is equivalent to a `gvim -f &` on Unix shells:

    >>> gvim = Cmd(['gvim', '-f']).spawn()

You may do what you wish to the Popen object, for instance,

    >>> gvim.kill(15)


capture()
=========

`capture()` also performs a fork-exec-wait but capture the
child's stdin/stderr as file objects when possible, e.g.

    >>> Sh('echo -n foo').capture(1).stdout.read()
    'foo'
    >>> Sh('echo -n bar >&2').capture(2).stderr.read()
    'bar

The full return is a namedtuple `(stdin, stdout, exit_status)`, e.g.

    >>> out, err, status = Sh('echo -n foo; echo -n bar >&2').capture(1, 2)

Capturing is equivalent to shell backquotes aka command substitution
(which cannot capture stderr separate from stdout):

    $ out=`echo -n foo`
    $ outerr=$(echo -n foo; echo -n bar 2>&1 >&2)

`cmd()`, `sh()` and`pipe()` are safe shortcuts that setup the capture
of the child(ren)'s stdout, then read and close it. For example, the
following finds files modified in the last 30 minutes and pipes to
dmenu(1) to select a single item:

    >>> item = pipe(Cmd('find -mmin +30'), Cmd('dmenu'))


I/O redirection
===============

I/O redirections are performed by specifying a `fd` argument which
should be a dict mapping a subset of file descriptors `[0, 1, 2]` to
either open files, strings, or existing file descriptors, e.g.

    >>> sh('echo -n foo; echo -n bar >&2', fd={2: 1})
    'foobar'

The following append the child's stdout to the file 'abc' (equiv. to `echo foo >> abc`)

    >>> sh('echo foo', {1: open('abc', 'a')})

os.devnull (which is just the string `'/dev/null'` on Unix) also works:

    >>> Sh('echo ERROR >&2; echo bogus stuff', {1: os.devnull}).capture(2).stderr.read()
    'ERROR\n'

In fact you can pass in `fd=SILIENCE`, which will send everything
straight to hell, hmm... I mean `/dev/null`.


API REFERENCE
=============

See docstrings for now.


IMPLEMENTATION NOTES
====================

The main interpreter process had better be a single thread, since
forking multithreaded programs is not well understood by mortals. [3]

capture() use temporary files and is synchronous.  It might be worth
adding an `async=True` option to use `PIPE` for client code that knows
what it is doing.

It is really too bad that `subprocess` does not support full I/O redirection.

See also: ./TODO


REFERENCE
=========

[1] sh(1) -- http://heirloom.sourceforge.net/sh/sh.1.html
[2] The Scheme Shell -- http://www.scsh.net/docu/html/man.html
[3] http://golang.org/src/pkg/syscall/exec_unix.go
