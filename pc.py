#!/usr/bin/env python
"""
fork-exec and pipe with I/O redirection

http://www.scsh.net/docu/html/man.html
http://golang.org/pkg/os/#ForkExec

Design goals:
  * Easy to fork-exec, capturing child's stdout/stderr or reuse parent's
  * Easy to construct pipelines
  * Easy to express I/O redirections
  * Easy to type

In effect, make Python more usable as a system shell.

Doctests require /bin/sh to pass. Tested on Linux.
"""

import collections, os, shlex, StringIO, subprocess, sys, tempfile

DEFAULT_FD = {0: sys.stdin, 1: sys.stdout, 2: sys.stderr}
SILENCE = {0: os.devnull, 1: os.devnull, 2: os.devnull}
PIPE = subprocess.PIPE
CLOSE = -1


class NonZeroExit(Exception):
  def __init__(self, exit_status):
    self.exit_status = exit_status
  def __str__(self):
    return "child exited with status %s" % (self.exit_status)


Capture = collections.namedtuple("Capture", "out err")


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
    
    >>> Cmd(['sh', '-c', 'echo -n foo; echo -n bar >&2'], fd={2: 1}).capture(1)
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
      elif k == 2 and v == 1:
        self.fd[k] = subprocess.STDOUT
   
  def __repr__(self):
    return "Cmd(%s, cd=%s, e=%s, fd=%s)" % (self.cmd, self.cd, self.e, dict(
    			(k, v.name if isinstance(v, file) else v) for k, v in self.fd.iteritems()
    		))
  
  def run(self):
    """
    Run the Cmd and waits for its termination.
    
    Return the child's exit status.
    
    >>> Cmd(['/bin/sh', '-c', 'exit 1']).run()
    1
    """
    return subprocess.call(self.cmd, cwd=self.cd, env=self.env, stdin=self.fd[0], stdout=self.fd[1], stderr=self.fd[2])
  
  def spawn(self):
    """
    Run the Cmd but do not wait for its termination.
    
    Return a subprocess.Popen object.
    """
    return subprocess.Popen(self.cmd, cwd=self.cd, env=self.env, stdin=self.fd[0], stdout=self.fd[1], stderr=self.fd[2])
  
  def capture(self, *fd):
    """
    Run the Cmd and wait for its termination, capturing child's
    stdout, stderr accordingly:
    
        * capture(0) returns the child's stdout byte string
        * capture(1) returns the child's stderr byte string
        * capture(0, 1) returns a named tuple of both
    
    When capture()'ing, the 'fd' parameter takes precedence over 'self.fd'.
    
    Raise NonZeroExit if the child's exit status != 0.
    The error object contains 'out' and/or 'err' attributes that were
    captured from the child before it terminates.
    
    >>> Cmd("sh -c 'echo -n foo'").capture()
    'foo'
   
    >>> Cmd("sh -c 'echo -n foo'").capture(1)
    'foo'
    
    >>> Cmd("sh -c 'echo -n bar >&2'").capture(2)
    'bar'
    
    >>> Cmd("sh -c 'echo -n foo; echo -n bar >&2'").capture(1, 2)
    Capture(out='foo', err='bar')
    """
    if isinstance(fd, int):
      fd = set([fd])
    else:
      fd = set(fd) or set([1])
    if not fd <= set([1, 2]):
      raise ValueError("can only capture fd 1, 2, or both, but no other")
    arg = dict(args=self.cmd, cwd=self.cd, env=self.env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if 1 not in fd:
    	arg['stdout'] = self.fd[1]
    if 2 not in fd:
    	arg['stderr'] = self.fd[2]
    p = subprocess.Popen(**arg)
    ### TODO: rewrite to just return the file objects, there maybe lots of data ...
    out, err = p.communicate()
    if p.returncode != 0:
      ex = NonZeroExit(n)
      if 1 in fd: ex.out = out
      if 2 in fd: ex.err = err
      raise ex
    if len(fd) == 1:
      if 1 in fd:
        return out
      else:
        return err
    return Capture(out, err)


class Pipe(Cmd):
  def __init__(self, *cmd, **kwargs):
    self.cd = kwargs.get('cd')
    self.e = kwargs.get('e', {})
    self.env = os.environ.copy()
    self.env.update(self.e)
    self.fd = DEFAULT_FD.copy()
    self.fd.update(kwargs.get('fd', {}))
    for k, v in self.fd.iteritems():
      if not isinstance(k, int):
        raise TypeError("fd keys must have type int")
      if isinstance(v, basestring):
        self.fd[k] = open(v, 'r' if k == 0 else ('w' if k in (1, 2) else 'r+'))
      elif k == 2 and v == 1:
        self.fd[k] = subprocess.STDOUT
    for c in cmd[:-1]:
      c.fd[1] = subprocess.PIPE
    self.cmd = cmd
  
  def __repr__(self):
    return "Pipe(%s, cd=%s, e=%s, fd=%s)" % (
    	", ".join("Cmd(%s)" % c.cmd for c in self.cmd), self.cd, self.e, dict(
    			(k, v.name if isinstance(v, file) else v) for k, v in self.fd.iteritems()
    		))


def here(string):
  """
  ### >>> capture('cat', {0: here("foo bar")})
  'foo bar'
  """
  f = tempfile.TemporaryFile()
  f.write(string)
  f.seek(0)
  return f

def run(*args, **kwargs):
  """
  >>> run(['sh', '-c', 'exit 2'])
  2
  """
  return Cmd(*args, **kwargs).run()

def capture(*args, **kwargs):
  """
  >>> capture(['sh', '-c', 'echo -n foo; echo -n bar >&2'], {2: 1})
  'foobar'
  """
  return Cmd(*args, **kwargs).capture()

def spawn(*args, **kwargs):
  return Cmd(*args, **kwargs).spawn()


def __test():
  """
  """
  pass


if __name__ == '__main__':
  import doctest
  n = doctest.testmod().failed
  if n > 0:
    import sys
    sys.exit(n)
