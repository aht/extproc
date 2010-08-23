#!/usr/bin/env python
#-*- coding: utf-8 -*-
"""
process control: fork-exec and pipe with I/O redirection

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

The main interpreter process had better be a single thread, since
forking multithreaded programs is not well understood by mortals. [3]

This module depends on Python 2.6, or where subprocess is available.
Doctests require /bin/sh to pass. Tested on Linux.

This is an alpha release. Some features are unimplemented. Expect bugs.


Reference:

[1] sh(1) -- http://heirloom.sourceforge.net/sh/sh.1.html
[2] The Scheme Shell -- http://www.scsh.net/docu/html/man.html
[3] http://golang.org/src/pkg/syscall/exec_unix.go

"""


import collections
import os
import shlex
import subprocess
import sys
import tempfile


DEFAULT_FD = {0: 0, 1: 1, 2: 2}
SILENCE = {0: os.devnull, 1: os.devnull, 2: os.devnull}
PIPE = subprocess.PIPE # should be -1
STDOUT = subprocess.STDOUT # should be -2
CLOSE = None
assert CLOSE not in (PIPE, STDOUT) # should never happen

JOBS = []


def is_fileno(n, f):
  return (f is n) or (hasattr(f, 'fileno') and f.fileno() == n)


class NonZeroExit(Exception):
  def __init__(self, exit_status):
    self.exit_status = exit_status
  def __str__(self):
    if self.exit_status > 0:
      return "child exited with status %s" % (self.exit_status)
    else:
      return "child terminated by signal %s" % (-self.exit_status)

Capture = collections.namedtuple("Capture", "stdout stderr")


class Cmd(object):
  def __init__(self, cmd, fd={}, e={}, cd=None):
    """
    Prepare for a fork-exec of 'cmd' with information about changing
    of working directory, extra environment variables and I/O
    redirections if necessary.
    
    :param cmd: a list of command argurments.  If a string, it
        is passed to shlex.split().
    
    :param e: a dict of *extra* enviroment variables.
    
    :param fd: a dict mapping k in [0, 1, 2] → v of type [file, int, string, None]
    
      Whatever is pointed to by fd[0], fd[1] and fd[2] will become the
      child's stdin, stdout and stderr, respectively.

      If any of key [0, 1, 2] is not specified, then it takes the
      values [0, 1, 2] respectively -- in effect, reusing the parent's
      [stdin, stdout, stderr].
      
      Currently, the following redirects work:
      * when v is an int: redirection of {2: 1} or {k: v} for v ≥ 3 and v is an open file descriptor
      * when v is a string: if it can be open()'ed with mode 'r+'
      * when v is a file: always, and offer the most control over mode of operation
      * when v is None: close the file descriptor k after fork, not implemented

    Note that the constructor only saves information in the object and
    does not actually execute anything.
    
    >>> Cmd("/bin/sh -c 'echo foo'")
    Cmd(['/bin/sh', '-c', 'echo foo'], cd=None, e={}, fd={0: 0, 1: 1, 2: 2})
    """
    if isinstance(cmd, basestring):
      self.cmd = shlex.split(cmd)
    elif isinstance(cmd, (list, tuple)):
      self.cmd = cmd
    else:
      raise TypeError("'cmd' must be either a string, a list or a tuple")
    self.cd = cd
    self.e = e
    self.env = os.environ.copy()
    self.env.update(e)
    self.fd = DEFAULT_FD.copy()
    self.fd.update(fd)
    for k, v in fd.iteritems():
      if not isinstance(k, int):
        raise TypeError("fd keys must have type int")
      elif k < 0 or k >= 3:
        raise NotImplementedError("redirection {%s: %s} not supported" % (k, v))
      if isinstance(v, basestring):
        self.fd[k] = open(v, 'r' if k == 0 else ('w' if k in (1, 2) else 'r+'))
      elif isinstance(v, int):
        if k == 2 and v == 1:
          self.fd[k] = STDOUT
        elif (v in (0, 1, 2)):
          raise NotImplementedError("redirection {%s: %s} not supported" % (k, v))
      elif v is CLOSE:
        raise NotImplementedError("closing is not supported")
      elif not hasattr(v, 'fileno'):
        raise ValueError("fd value %s is not a file, int, string or None" % (v,))
   
  def __repr__(self):
    return "Cmd(%s, cd=%s, e=%s, fd=%s)" % (self.cmd, self.cd, self.e, dict(
    			(k, v.name if isinstance(v, file) else v) for k, v in self.fd.iteritems()
    		))
  
  def run(self):
    """
    Fork-exec the Cmd and waits for its termination.
    
    Return the child's exit status.
    
    >>> Cmd(['/bin/sh', '-c', 'exit 1']).run()
    1
    """
    return subprocess.call(self.cmd, cwd=self.cd, env=self.env, stdin=self.fd[0], stdout=self.fd[1], stderr=self.fd[2])
  
  def spawn(self):
    """
    Fork-exec the Cmd but do not wait for its termination.
    
    Return a subprocess.Popen object (which is also stored in 'self.p')
    """
    self.p = subprocess.Popen(self.cmd, cwd=self.cd, env=self.env, stdin=self.fd[0], stdout=self.fd[1], stderr=self.fd[2])
    JOBS.append(self)
    return self.p
  
  def capture(self, *fd):
    """
    Fork-exec the Cmd and wait for its termination, capturing the
    output and/or error:
    
      * capture(1) returns the child's stdout file object
      * capture(2) returns the child's stderr file object
      * capture(1, 2) returns a named tuple of both
    
    Don't forget to close the file objects!
    
    Note that only the fds that reuse the parent's stdout/stderr (when
    it had not been redirected them elsewhere) can be captured.

    Raise NonZeroExit if the child's exit status != 0.  The error
    object contains 'stdout' and/or 'stderr' attributes that were
    captured from it before termination.
    
    >>> Cmd("/bin/sh -c 'echo -n foo'").capture().read()
    'foo'
   
    >>> Cmd("/bin/sh -c 'echo -n foo'").capture(1).read()
    'foo'
    
    >>> Cmd("/bin/sh -c 'echo -n bar >&2'").capture(2).read()
    'bar'
    
    >>> cout, cerr = Cmd("/bin/sh -c 'echo -n foo; echo -n bar >&2'").capture(1, 2)
    >>> cout.read()
    'foo'
    >>> cerr.read()
    'bar'
    """
    if isinstance(fd, int):
      fd = set([fd])
    else:
      fd = set(fd) or set([1])
    if not fd <= set([1, 2]):
      raise NotImplementedError("can only capture a subset of fd [1, 2] for now")
    if 1 in fd:
      if is_fileno(1, self.fd[1]):
        self.fd[1] = PIPE
      else:
        raise ValueError("cannot capture the child's stdout: it had been redirected to %s" % self.fd[1])
    if 2 in fd:
      if is_fileno(2, self.fd[2]):
        self.fd[2] = PIPE
      else:
        raise ValueError("cannot capture the child's stderr: it had been redirected to %s" % self.fd[2])
    p = subprocess.Popen(self.cmd, cwd=self.cd, env=self.env, stdin=self.fd[0], stdout=self.fd[1], stderr=self.fd[2])
    if p.stdin:
      p.stdin.close()
    if p.wait() != 0:
      ex = NonZeroExit(p.returncode)
      if 1 in fd: ex.stdout = p.stdout
      if 2 in fd: ex.stderr = p.stderr
      try:
        raise ex
      finally:
        if p.stdout: p.stdout.close()
        if p.stderr: p.stderr.close()
    if len(fd) == 1:
      if 1 in fd:
        if p.stderr: p.stderr.close()
        return p.stdout
      else:
        if p.stdout: p.stdout.close()
        return p.stderr
    return Capture(p.stdout, p.stderr)


class Sh(Cmd):
  def __init__(self, cmd, fd={}, e={}, cd=None):
    """
    Prepare for a fork-exec of a shell command.
    
    Equivalent to Cmd(['/bin/sh', '-c', cmd], **kwargs).
    """
    super(Sh, self).__init__(['/bin/sh', '-c', cmd], fd=fd, e=e, cd=cd)
  
  def __repr__(self):
    return "Sh(%s, cd=%s, e=%s, fd=%s)" % (repr(self.cmd[2]), self.cd, self.e, dict(
    			(k, v.name if isinstance(v, file) else v) for k, v in self.fd.iteritems()
    		))


class Pipe(object):
  def __init__(self, *cmd, **kwargs):
    """
    Prepare a pipeline from a list of Cmd's.

    The stdins of cmd[1:] will be changed to use pipe input,
    e.g. a pathetic pipeline such as 'echo foo | cat < file'
    will become 'echo foo | cat'.
    
    Extra enviroments 'e' will be exported to all sub-commands.
    
    >>> Pipe(Cmd('yes'), Cmd('cat', {1: os.devnull}))
    Pipe(Cmd(['yes'], cd=None, e={}, fd={0: 0, 1: -1, 2: 2}),
         Cmd(['cat'], cd=None, e={}, fd={0: 0, 1: '/dev/null', 2: 2}))
    """
    self.e = kwargs.get('e', {})
    self.env = os.environ.copy()
    self.env.update(self.e)
    for c in cmd:
      c.e.update(self.e)
      c.env.update(self.e)
    for c in cmd[:-1]:
      c.fd[1] = PIPE
    self.fd = {0: cmd[0].fd[0], 1: cmd[-1].fd[1], 2: sys.stderr}
    self.cmd = cmd
  
  def __repr__(self):
    return "Pipe(%s)" % (",\n     ".join(map(repr, self.cmd)),)
  
  def run(self):
    """
    Fork-exec the pipeline and wait for its termination.
    
    Return the last child's exit status.
    """
    prev = self.cmd[0].fd[0]
    for c in self.cmd:
      c.p = subprocess.Popen(c.cmd, stdin=prev, stdout=c.fd[1], stderr=c.fd[2], cwd=c.cd, env=c.env)
      prev = c.p.stdout
    return self.cmd[-1].p.wait()
  
  def spawn(self):
    """
    Fork-exec the pipeline but do not wait for its termination.
    
    After spawned, each self.cmd[i] will have a 'p' attribute that is
    the spawned subprocess.Popen object.
    
    >>> yesno = Pipe(Cmd('yes'), Cmd(['grep', 'no'])).spawn()
    >>> yesno.cmd[0].p.kill()
    >>> yesno.cmd[-1].p.wait()
    1
    """
    prev = self.cmd[0].fd[0]
    for c in self.cmd:
      c.p = subprocess.Popen(c.cmd, stdin=prev, stdout=c.fd[1], stderr=c.fd[2], cwd=c.cd, env=c.env)
      prev = c.p.stdout
    JOBS.append(self)
    return self
  
  def capture(self, *fd):
    """
    Fork-exec the Cmd and wait for its termination, capturing the
    output and/or error.
    
      * capture(1) returns the last child's stdout file object
      * capture(2) returns a temporary file object that every
      child has been writing to as its stderr (when its stderr is not
      redirected elsewhere).
      * capture(1, 2) returns a named tuple of both
    
    The effect of capture(2) is similar to redirecting a subshell which runs
    the pipeline, e.g. '( (echo -n foo >&2; echo -n bar) | cat >&2 ) 2>out'.
    This implementation does not double-fork, however.
    
    Don't forget to close the file objects!
    
    Raise NonZeroExit if the last child's exit status != 0.  The error
    object contains 'stdout' and/or 'stderr' attributes that were
    captured from it before termination.
    
    >>> Pipe(Sh('echo -n foo; echo -n bar >&2', {2: os.devnull}), Cmd('cat')).capture().read()
    'foo'
    
    >>> Pipe(Sh('echo -n foo; echo -n bar >&2'), Cmd('cat', {1: os.devnull})).capture(2).read()
    'bar'
    """
    if isinstance(fd, int):
      fd = set([fd])
    else:
      fd = set(fd) or set([1])
    if not fd <= set([1, 2]):
      raise NotImplementedError("can only capture a subset of fd [1, 2] for now")
    if 1 in fd and not is_fileno(1, self.fd[1]):
      raise ValueError("cannot capture the last child's stdout: it had been redirected to %s" % self.fd[1])
    temp = None
    if 2 in fd:
      temp = tempfile.TemporaryFile()
      self.fd[2] = temp
    prev = self.cmd[0].fd[0]
    for c in self.cmd[:-1]:
      if 2 in fd and is_fileno(2, c.fd[2]):
        c.fd[2] = temp
      c.p = subprocess.Popen(c.cmd, stdin=prev, stdout=c.fd[1], stderr=c.fd[2], cwd=c.cd, env=c.env)
      prev = c.p.stdout
    c = self.cmd[-1]
    if 1 in fd:
      c.fd[1] = PIPE
    if 2 in fd and is_fileno(2, c.fd[2]):
      c.fd[2] = temp
    c.p = subprocess.Popen(c.cmd, stdin=prev, stdout=c.fd[1], stderr=c.fd[2], cwd=c.cd, env=c.env)
    c.p.wait()
    if temp: temp.seek(0)
    if c.p.returncode != 0:
      ex = NonZeroExit(c.p.returncode)
      if 1 in fd: ex.stdout = c.p.stdout
      if 2 in fd: ex.stderr = temp
      try:
        raise ex
      finally:
        if c.p.stdout: c.p.stdout.close()
        if temp: temp.close()
    if len(fd) == 1:
      if 1 in fd:
        if temp: temp.close()
        return c.p.stdout
      if 2 in fd:
        if c.p.stdout: c.p.stdout.close()
        return temp
    return Capture(c.p.stdout, temp)


def here(string):
  """
  Make a temporary file from a string for use in redirection.
  
  >>> cmd('cat', {0: here("foo bar")})
  'foo bar'
  """
  t = tempfile.TemporaryFile()
  t.write(string)
  t.seek(0)
  return t

def run(cmd, fd={}, e={}, cd=None):
  """
  Perform a fork-exec-wait of a Cmd and return its exit status.
  
  >>> run('cat /dev/null')
  0
  """
  return Cmd(cmd, fd=fd, e=e, cd=cd).run()

def cmd(cmd, fd={}, e={}, cd=None):
  """
  Perform a fork-exec-wait of a Cmd and return the its stdout
  as a byte string.
  
  >>> cmd(['/bin/sh', '-c', 'echo -n foo; echo -n bar >&2'], {2: 1})
  'foobar'
  """
  f = Cmd(cmd, fd=fd, e=e, cd=cd).capture(1)
  try:
    s = f.read()
  finally:
    f.close()
  return s

def sh(cmd, fd={}, e={}, cd=None):
  """
  Perform a fork-exec-wait of a Sh command and return its stdout
  as a byte string.
  
  >>> sh('echo -n foo >&2', {2: 1})
  'foo'
  """
  f = Sh(cmd, fd=fd, e=e, cd=cd).capture(1)
  try:
    s = f.read()
  finally:
    f.close()
  return s

def pipe(*cmds, **kwargs):
  """
  Run the pipeline with given Cmd's, then returns its stdout as a byte string.
  """
  f = Pipe(*cmds, **kwargs).capture(1)
  try:
    s = f.read()
  finally:
    f.close()
  return s

def spawn(cmd, fd={}, e={}, cd=None, sh=False):
  if sh:
    return Sh(cmd, fd=fd, e=e, cd=cd).spawn()
  else:
    return Cmd(cmd, fd=fd, e=e, cd=cd).spawn()


def __test():
  """
  >>> sh('echo -n foo; echo -n bar >&2', {2: 1})
  'foobar'
  
  >>> sh('echo -n $var', e={'var': 'foobar'})
  'foobar'
  
  >>> sh('echo -n foo; echo -n bar >&2', {1: 2})
  Traceback (most recent call last):
  ...
  NotImplementedError: redirection {1: 2} not supported
  
  >>> f = tempfile.TemporaryFile()
  >>> Sh('echo -n foo', {1: f.fileno()}).run()
  0
  >>> f.seek(0); f.read()
  'foo'
  
  >>> sh('echo -n foo; echo -n bar >&2', {5: 12})
  Traceback (most recent call last):
  ...
  NotImplementedError: redirection {5: 12} not supported
  
  >>> sh("echo bogus stuff", {1: os.devnull}) #doctest: +ELLIPSIS
  Traceback (most recent call last):
  ...
  ValueError: cannot capture ...
  
  >>> pipe(Sh('echo -n $x'), Sh('cat; echo -n $x'), e=dict(x='foobar'))
  'foobarfoobar'
  
  >>> pipe(Sh("echo bogus"), Cmd("cat", {1: os.devnull})) #doctest: +ELLIPSIS
  Traceback (most recent call last):
  ...
  ValueError: cannot capture ...
  
  >>> Pipe(Sh('echo -n foo; sleep 0.005; echo -n bar >&2'), Sh('cat >&2')).capture(2).read()
  'foobar'
  
  >>> Pipe(Cmd('yes'), Cmd('cat', {1: os.devnull})).spawn() #doctest: +ELLIPSIS
  Pipe(...
  >>> JOBS[-1].cmd[0].p.kill()
  >>> JOBS[-1].cmd[-1].p.wait()
  0
  """
  pass


if __name__ == '__main__':
  import doctest
  n = doctest.testmod().failed
  if n > 0:
    sys.exit(n)
