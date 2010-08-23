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


run(), spawn() and capture()
============================

`Cmd` objects hold fork-exec info and can be run(), spawn()'ed or capture()'d.


`Cmd.run()` performs a fork-exec-wait -- a "normal" shell's command, e.g.

    >>> exit_status = Cmd('dmesg').run()

Sh(cmd, **kwargs) is equivalent to Cmd(['/bin/sh', '-c', cmd], **kwargs), and
run(*args, **kwargs) is equivalent to Cmd(*args, **kwargs).run().


`Cmd.spawn()` performs a fork-exec and returns a `subprocess.Popen` object.
The following is equivalent to a `gvim -f &` on Unix shell:

    >>> gvim = Cmd(['gvim', '-f']).spawn()
    >>> gvim.kill(15)

spawn(*args, **kwargs) is equivalent to Cmd(*args, **kwargs).spawn().


`Cmd.captured()` also performs a fork-exec-wait but capture the
child's stdin/stderr as file objects when possible, e.g.

    >>> 'foo' == Sh('echo -n foo').capture(1).stdout.read()
    >>> 'err' == Sh('echo -n foo >&2').capture(2).stderr.read()

The full return is a namedtuple `(stdin, stdout, exit_status)`, e.g.

    >>> out, err, status = Sh('echo -n foo; echo -n bar >&2').capture(1, 2)

Capturing is equivalent to shell backquotes aka command substitution
(which cannot capture stderr separate from stdout):

    $ out=`echo -n foo`
    $ outerr=$(echo -n foo; echo -n bar 2>&1 >&2)

cmd(*) returns Cmd(*).capture(1).stdout.read() wrapped in a try: ... finally: close() clause.

sh(*)` returns Sh(*).capture(1).stdout.read() wrapped in a try: ... finally: close() clause.


I/O redirection
===============

I/O redirections are performed by specifying a `fd` argument which
should be a dict mapping a subset of file descriptors `[0, 1, 2]` to
either open files, strings, or existing file descriptors, e.g.

    >>> out = sh('echo -n foo; echo -n bar >&2', fd={2: 1})

The following append the child's stdout to the file 'abc' (equiv. to `echo foo >> abc`)

    >>> out = sh('echo foo', {1: open('abc', 'a')})

os.devnull (which is just the string `'/dev/null'` on Unix) also works:

    >>> out = sh('echo bogus stuff', {1: os.devnull})

In fact you can pass in `fd=SILIENCE`, which will send everything
straight to hell, hmm... I mean `/dev/null`.


Pipe
====

`Pipe` are constructed by a list of Cmd's. Pipes can also be run(), spawn()'ed or capture()'d, e.g.

    >>> exit_status = Pipe(Cmd('dmesg'), Cmd('grep x')).run()
    
    >>> out = Pipe(Cmd('dmesg'), Cmd('grep x')).capture(1).stdout.read()

pipe(*args, **kwargs) returns Pipe(*args, **kwargs).capture(1).read()
wrapped in a try: ... finally: close() clause.

The following finds files modified in the last 30 minutes and pipes to
dmenu(1) to select a single item:

    >>> item = pipe(Cmd('find -mmin +30'), Cmd('dmenu'))



API REFERENCE
=============

See docstrings for now.


IMPLEMENTATION NOTES
====================

The main interpreter process had better be a single thread, since
forking multithreaded programs is not well understood by mortals. [3]

`Cmd.capture()` and `Pipe.capture()` use temporary files and is
synchronous.  It might be worth adding an `async=True` option to use
`PIPE` for client code that knows what it is doing.

It is really too bad that `subprocess` does not support full I/O redirection.

See also: ./TODO


REFERENCE
=========

[1] sh(1) -- http://heirloom.sourceforge.net/sh/sh.1.html
[2] The Scheme Shell -- http://www.scsh.net/docu/html/man.html
[3] http://golang.org/src/pkg/syscall/exec_unix.go
