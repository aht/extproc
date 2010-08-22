#!/usr/bin/env python
"""
fork-exec and pipe with I/O redirection

Design goals:
  * Easy to fork-exec commands, sync. or async.
  * Easy to capture stdout/stderr of children (command substitution)
  * Easy to construct pipelines
  * Easy to express I/O redirections
  * Easy to type interactively

In effect, make Python more usable as a system shell.

Technically, pc.py is a layer on top of subprocess. The subprocess
module support a rich API but is clumsy for many common use cases,
namely sync/async fork-exec, command substitution and pipelining,
all of which is trivial to do on system shells. [1] [2]

The main interpreter process had better be a single thread, since
forking multithreaded programs is not well understood by mortals. [3]

Doctests require /bin/sh to pass. Tested on Linux.

[1] sh(1)
[2] The Scheme Shell http://www.scsh.net/docu/html/man.html
[3] http://golang.org/src/pkg/syscall/exec_unix.go

"""

import collections
import os
import shlex
import StringIO
import subprocess
import sys
import tempfile

DEFAULT_FD = {0: sys.stdin, 1: sys.stdout, 2: sys.stderr}
SILENCE = {0: os.devnull, 1: os.devnull, 2: os.devnull}
PIPE = subprocess.PIPE
assert PIPE == -1
STDOUT = subprocess.STDOUT
assert STDOUT == -2
CLOSE = -3


class NonZeroExit(Exception):
  def __init__(self, exit_status):
    self.exit_status = exit_status
  def __str__(self):
    return "child exited with status %s" % (self.exit_status)


Capture = collections.namedtuple("Capture", "stdout stderr")


class Cmd(object):
  def __init__(self, cmd, fd={}, e={}, cd=None):
    """
    Prepare for a fork-exec of 'cmd' with information about changing
    of working directory, extra environment variables and I/O
    redirections if necessary.
    
    Parameter 'cmd' should be a list, just like in subprocess.Popen().
    If it is a string, it is passed to shlex.split().
    
    Parameter 'e' should be a dict of *extra* enviroment variables.
    
    If fd[k] is a string, it will be open()'ed with mode 'r+'.
    It's best that the client pass in opened the files.
    
    The constructor only saves information in the object and does
    not actually execute anything.
    
    >>> Cmd("/bin/sh -c 'echo foo'")
    Cmd(['/bin/sh', '-c', 'echo foo'], cd=None, e={}, fd={0: '<stdin>', 1: '<stdout>', 2: '<stderr>'})
    
    >>> Cmd(['/bin/sh', '-c', 'echo -n foo; echo -n bar >&2'], fd={2: 1}).capture(1).read()
    'foobar'
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
      if isinstance(v, basestring):
        self.fd[k] = open(v, 'r' if k == 0 else ('w' if k in (1, 2) else 'r+'))
      elif isinstance(v, int):
        # self.fd[k] = os.fdopen(v, 'r' if k == 0 else ('w' if k in (1, 2) else 'r+'))
        if k == 2 and v == 1:
          self.fd[k] = STDOUT
   
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
    
    Return a subprocess.Popen object.
    """
    return subprocess.Popen(self.cmd, cwd=self.cd, env=self.env, stdin=self.fd[0], stdout=self.fd[1], stderr=self.fd[2])
  
  def capture(self, *fd):
    """
    Fork-exec the Cmd and wait for its termination, capturing child's
    stdout, stderr accordingly:
    
        * capture(0) returns the child's stdout file object
        * capture(1) returns the child's stderr file object
        * capture(0, 1) returns a named tuple of both
    
    When capture()'ing, the 'fd' parameter takes precedence over 'self.fd'.

    Don't forget to close the file objects!
    
    Raise NonZeroExit if the child's exit status != 0.
    The error object contains 'out' and/or 'err' attributes that were
    captured from the child before it terminates.
    
    >>> Cmd("sh -c 'echo -n foo'").capture().read()
    'foo'
   
    >>> Cmd("sh -c 'echo -n foo'").capture(1).read()
    'foo'
    
    >>> Cmd("sh -c 'echo -n bar >&2'").capture(2).read()
    'bar'
    
    >>> cout, cerr = Cmd("sh -c 'echo -n foo; echo -n bar >&2'").capture(1, 2)
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
      raise ValueError("can only capture a subset of fd [1, 2] for now")
    arg = dict(args=self.cmd, cwd=self.cd, env=self.env, stdout=PIPE, stderr=PIPE)
    if 1 not in fd:
    	arg['stdout'] = self.fd[1]
    if 2 not in fd:
    	arg['stderr'] = self.fd[2]
    p = subprocess.Popen(**arg)
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
    """
    shcmd = ['/bin/sh', '-c']
    if isinstance(cmd, basestring):
      shcmd += shlex.split(cmd)
    elif isinstance(cmd, (list, tuple)):
      shcmd += cmd
    super(Sh, self).__init__(shcmd, fd, e, cd)


class Pipe(object):
  def __init__(self, *cmd):
    """
    Prepare a pipeline from a list of Cmd's.
    """
    for c in cmd[:-1]:
      c.fd[1] = PIPE
    self.fd = {0: cmd[0].fd[0], 1: cmd[-1].fd[1], 2: sys.stderr}
    self.cmd = cmd
  
  def __repr__(self):
    return "Pipe(%s, cd=%s, e=%s)" % (
    	", ".join("Cmd(%s)" % c.cmd for c in self.cmd), self.cd, self.e
    )
  
  def run(self):
    """
    Fork-exec the pipeline and waits for its termination.
    
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
    
    Return a subprocess.Popen object.
    """
    raise NotImplementedError()
  
  def capture(self, *fd):
    """
    Fork-exec the pipeline and wait for its termination, capturing the last child's
    stdout.
    
    Return the child's stdout file object. Don't forget to close it!
    
    Raise NonZeroExit if the child's exit status != 0.
    The error object contains a 'stdout'  attribute that were
    captured from the child before it terminates.
    """
    if isinstance(fd, int):
      fd = set([fd])
    else:
      fd = set(fd) or set([1])
    if not fd <= set([1]):
      raise ValueError("can only capture fd 1 for now")
    prev = self.cmd[0].fd[0]
    for c in self.cmd[:-1]:
      c.p = subprocess.Popen(c.cmd, stdin=prev, stdout=c.fd[1], stderr=c.fd[2], cwd=c.cd, env=c.env)
      prev = c.p.stdout
    c = self.cmd[-1]
    if 1 in fd:
      c.p = subprocess.Popen(c.cmd, stdin=prev, stdout=PIPE, stderr=c.fd[2], cwd=c.cd, env=c.env)
    else:
      c.p = subprocess.Popen(c.cmd, stdin=prev, stdout=c.fd[1], stderr=c.fd[2], cwd=c.cd, env=c.env)
    if c.p.wait() != 0:
      ex = NonZeroExit(c.p.returncode)
      if 1 in fd: ex.stdout = c.p.stdout
      try:
        raise ex
      finally:
        if c.p.stdout: c.p.stdout.close()
        if c.p.stderr: c.p.stderr.close()
    if len(fd) == 1:
      if 1 in fd:
        if c.p.stderr: c.p.stderr.close()
        return c.p.stdout
    return Capture(c.p.stdout, StringIO.StringIO())


def here(string):
  """
  ### >>> capture('cat', {0: here("foo bar")})
  'foo bar'
  """
  f = tempfile.TemporaryFile()
  f.write(string)
  f.seek(0)
  return f

def cmd(cmd, fd={}, e={}, cd=None):
  """
  Run the Cmd with its arguments, then returns its stdout as a byte string.
  
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
  Run the shell command with its arguments, then returns its stdout as a byte string.
  
  >>> sh('echo -n foo; echo -n bar >&2', {2: 1})
  'foobar'
  """
  f = Cmd(cmd, fd=fd, e=e, cd=cd).capture(1)
  try:
    s = f.read()
  finally:
    f.close()
  return s

def pipe(*cmds):
  """
  Run the pipeline with given Cmd's, then returns its stdout as a byte string.
  """
  f = Pipe(*cmds).capture(1)
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
  """
  pass


if __name__ == '__main__':
  import doctest
  n = doctest.testmod().failed
  if n > 0:
    sys.exit(n)
