#!/usr/bin/env python
"""
http://www.scsh.net/docu/html/man.html
http://golang.org/pkg/os/#ForkExec

Design goals:
  * Easy to construct pipelines with I/O redirections
  * Use short names for easy typing

Tests require /bin/sh to pass.
"""

# TODO: I/O redirection
# TODO: remove subprocess dependency, as it doesn't support full I/O redirection.
# 	* can only send stderr to stdout
# 	* dup(3)'ping anything must use a different "framework"


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
    Prepare for a fork exec of 'cmd' with information about changing
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
      if isinstance(v, basestring):
        self.fd[k] = open(v, 'r' if k == 0 else ('w' if k in (1, 2) else 'r+'))
   
  def __repr__(self):
    return "Cmd(%s, cd=%s, e=%s, fd=%s)" % tuple(map(repr,
    	[self.cmd, self.cd, self.e, dict((k, v.name) for k, v in self.fd.iteritems())]
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
    
    When capture()'ing, the 'fd' parameter take precedence over 'self.fd'.
    
    Raise NonZeroExit if the child's exit status != 0.
    
    >>> Cmd("sh -c 'echo -n foo'").capture()
    'foo'
   
    >>> Cmd("sh -c 'echo -n foo'").capture(1)
    'foo'
    
    >>> Cmd("sh -c 'echo -n bar >&2'").capture(2)
    'bar'
    
    >>> Cmd("sh -c 'echo -n bar >&2'", fd={2: 1}).capture(1)
    'bar'
    
    >>> Cmd("sh -c 'echo -n foo; echo -n  bar >&2'").capture(1, 2)
    Capture(out='foo', err='bar')
    """
    if isinstance(fd, int):
      fd = set([fd])
    else:
      fd = set(fd) or set([1])
    if not fd <= set([1, 2]):
      raise ValueError("can only capture fd 1, 2, or both")
    arg = dict(args=self.cmd, cwd=self.cd, env=self.env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if 1 not in fd:
    	del arg['stdout']
    if 2 not in fd:
    	del arg['stderr']
    p = subprocess.Popen(**arg)
    ## TODO: rewrite to just return the file objects, there maybe lots of data ...
    ## plus, there will be a blocked thread read()'ing on either
    ## the child's stdout or stderr if nothing comes out of it :(
    out, err = p.communicate()
    if p.returncode != 0:
      ex = NonZeroExit(n)
      if arg.has_key('stdout'): ex.out = out
      if arg.has_key('stderr'): ex.err = err
      raise ex
    if len(fd) == 1:
      if arg.has_key('stdout'): return out
      if arg.has_key('stderr'): return err
    return Capture(out, err)


class Chain(Cmd):
  def __init__(self, fd=[], cd='', env={}, *cmd):
    pass


def here(doc):
  """
  #>>> capture('cat', fd={0: here("foo bar")})
  'foo bar'
  """
  f = tempfile.TemporaryFile()
  f.write(doc)
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
  capture("sh -c 'echo foo bar'")
  'foo bar'
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
