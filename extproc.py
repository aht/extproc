#!/usr/bin/env python2
#-*- coding: utf-8 -*-
"""
extproc: fork-exec and pipe with I/O redirection

extproc is a layer on top of subprocess. The subprocess module supports
a rich API but is clumsy for many common use cases, namely sync/async
fork-exec, command substitution and pipelining, all of which is trivial
to do on system shells. [1][2]

The goal is to make Python a sane alternative to non-trivial shell scripts.

Features:

  * Easy to fork-exec commands, wait or no wait
  * Easy to capture stdout/stderr of children (command substitution)
  * Easy to express I/O redirections
  * Easy to construct pipelines
  * Use short names for easy interactive typing

The main interpreter process had better be a single thread, since
forking multithreaded programs is not well understood by mortals. [3]

This module depends on Python 2.6, or where subprocess is available.
Doctests require /bin/sh to pass. Tested on Linux.

This is an alpha release. Expect bugs.


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


STDIN, STDOUT, STDERR = 0, 1, 2
DEFAULT_FD = {STDIN: 0, STDOUT: 1, STDERR: 2}
SILENCE = {0: os.devnull, 1: os.devnull, 2: os.devnull}

PIPE = subprocess.PIPE # should be -1
_ORIG_STDOUT = subprocess.STDOUT # should be -2
CLOSE = None

JOBS = []

Capture = collections.namedtuple("Capture", "stdout stderr exit_status")

def _is_fileno(n, f):
    return (f is n) or (hasattr(f, 'fileno') and f.fileno() == n)

def _name_or_self(f):
    return (hasattr(f, 'name') and f.name) or f


class Cmd(object):
    def __init__(self, cmd, fd={}, e={}, cd=None):
        """
        Prepare for a fork-exec of 'cmd' with information about changing
        of working directory, extra environment variables and I/O
        redirections if necessary.

        :param cmd: a list of command argurments.  If a string, it
            is passed to shlex.split().

        :param e: a dict of *extra* enviroment variables.

        :param fd: a dict mapping k in [0, 1, 2] → v of type [file, string, int]

          Whatever is pointed to by fd[0], fd[1] and fd[2] will become the
          child's stdin, stdout and stderr, respectively.

          If any of key [0, 1, 2] is not specified, then it takes the
          values [0, 1, 2] respectively -- in effect, reusing the parent's
          [stdin, stdout, stderr].

          The value fd[k] can be of type
          * file: always works and offer the most control over mode of operation
          * string: works if can be open()'ed with mode 'r' when k == 0,
            or mode 'w' for k in [1, 2]
         * int: works for redirection {2: 1}
                or {k: v} when v ≥ 3 and v is an existing file descriptor

        Note that the constructor only saves information in the object and
        does not actually execute anything.

        >>> Cmd("/bin/sh -c 'echo foo'")
        Cmd(['/bin/sh', '-c', 'echo foo'], fd={0: 0, 1: 1, 2: 2}, e={}, cd=None)

        >>> Cmd(['grep', 'my stuff']) == Cmd('grep "my stuff"')
        True
        """
        if isinstance(cmd, basestring):
            self.cmd = shlex.split(cmd)
        elif isinstance(cmd, (list, tuple)):
            self.cmd = cmd
        else:
            raise TypeError("'cmd' must be either of type string, list or tuple")
        self.cd = cd
        self.e = e
        self.env = os.environ.copy()
        self.env.update(e)
        self.fd = DEFAULT_FD.copy()
        self.fd.update(fd)

        for stream_num in fd.keys():
            if not isinstance(stream_num, int):
                raise TypeError("fd keys must have type int")
            elif stream_num < 0 or stream_num >= 3:
                fd_num = fd[stream_num]
                raise NotImplementedError(
                  "redirection {%s: %s} not supported" % (stream_num, fd_num))

        for stream_num, fd_num in fd.iteritems():
            if isinstance(fd_num, basestring):
                self.fd[stream_num] = open(fd_num, 'r' if stream_num == 0 else 'w')
            elif isinstance(fd_num, int):
                if stream_num == 2 and fd_num == 1:
                    self.fd[STDERR] = _ORIG_STDOUT
                elif (fd_num in (0, 1, 2)):
                    raise NotImplementedError(
                      "redirection {%s: %s} not supported" % (stream_num, fd_num))
            elif stream_num is CLOSE:
                raise NotImplementedError("closing is not supported")
            elif not hasattr(fd_num, 'fileno'):
                raise ValueError(
                  "fd value %s is not a file, string, int, or CLOSE" % (fd_num,))

    def __repr__(self):
      return "Cmd(%r, fd=%r, e=%r, cd=%r)" % (
        self.cmd, dict((k, _name_or_self(v)) for k, v in self.fd.iteritems()),
        self.e, self.cd)

    def __eq__(self, other):
      return (self.cmd == other.cmd) and (self.fd == other.fd) and\
             (self.env == other.env) and (self.cd == other.cd)

    def run(self):
      """
      Fork-exec the Cmd and waits for its termination.

      Return the child's exit status.

      >>> Cmd(['/bin/sh', '-c', 'exit 1']).run()
      1
      """
      return subprocess.call(**self.popen_args)

    def spawn(self):
      """
      Fork-exec the Cmd but do not wait for its termination.

      Return a subprocess.Popen object (which is also stored in 'self.p')
      """
      self.p = self._popen()
      JOBS.append(self)
      return self.p

    def capture(self, *fd):
        """
        Fork-exec the Cmd and wait for its termination, capturing the
        output and/or error.

        :param fd: a list of file descriptors to capture,
                   should be a subset of [1, 2] where
          * 1 represents the child's stdout
          * 2 represents the child's stderr

        Return a namedtuple (stdout, stderr, exit_status) where
        stdout and stderr are captured file objects or None.

        Don't forget to close the file objects!

       >>> Cmd("/bin/sh -c 'echo -n foo'").capture(1).stdout.read()
       'foo'

       >>> Cmd("/bin/sh -c 'echo -n bar >&2'").capture(2).stderr.read()
       'bar'

       """
        if not fd:
            raise ValueError("what do you want to capture?")
        if isinstance(fd, int):
            fd = set([fd])
        else:
            fd = set(fd) or set([1])
        if not fd <= set([1, 2]):
            raise NotImplementedError(
              "can only capture a subset of fd [1, 2] for now")
        if STDOUT in fd:
            if _is_fileno(STDOUT, self.fd[STDOUT]):
                self.fd[STDOUT] = tempfile.TemporaryFile()
            else:
                raise ValueError(
                  "cannot capture the child's stdout: it had been redirected to %r"
                      % _name_or_self(self.fd[1]))
        if 2 in fd:
            if _is_fileno(2, self.fd[2]):
                self.fd[2] = tempfile.TemporaryFile()
            else:
                raise ValueError(
                  "cannot capture the child's stderr: it had been redirected to %r"
                      % _name_or_self(self.fd[2]))
        p = self._popen()
        if p.stdin:
            p.stdin.close()
        p.wait()
        if len(fd) == 1:
            if 1 in fd:
                if p.stderr:
                    p.stderr.close()
            else:
                if p.stdout:
                    p.stdout.close()
        if 1 in fd:
            self.fd[1].seek(0)
        if 2 in fd:
            self.fd[2].seek(0)
        return Capture(self.fd[1], self.fd[2], p.returncode)

    @property
    def popen_args(self):
        return dict(args=self.cmd, cwd=self.cd, env=self.env,
          stdin=self.fd[0], stdout=self.fd[1], stderr=self.fd[2])

    def _popen(self, **kwargs):
        basic_popen_args = self.popen_args
        basic_popen_args.update(kwargs)
        return subprocess.Popen(**basic_popen_args)

class Sh(Cmd):
  def __init__(self, cmd, fd={}, e={}, cd=None):
    """
    Prepare for a fork-exec of a shell command.

    Equivalent to Cmd(['/bin/sh', '-c', cmd], **kwargs).
    """
    super(Sh, self).__init__(['/bin/sh', '-c', cmd], fd=fd, e=e, cd=cd)

  def __repr__(self):
    return "Sh(%r, fd=%r, e=%r, cd=%r)" % (self.cmd[2], dict(
                        (k, _name_or_self(v)) for k, v in self.fd.iteritems()
                ), self.e, self.cd)


class Pipe(object):
  def __init__(self, *cmds, **kwargs):
    """
    Prepare a pipeline from a list of Cmd's.

    :parameter e: extra environment variables to be exported to all
                  sub-commands, must be a keyword argument
    """
    self.e = kwargs.get('e', {})
    self.env = os.environ.copy()
    self.env.update(self.e)
    for c in cmds:
        c.e.update(self.e)
        c.env.update(self.e)
    for c in cmds[:-1]:
        if _is_fileno(1, c.fd[STDOUT]):
          c.fd[STDOUT] = PIPE
    self.fd = {STDIN: cmds[0].fd[STDIN], STDOUT: cmds[-1].fd[STDOUT], 2: 2}
    self.cmds = cmds

  def __repr__(self):
    return "Pipe(%s)" % (",\n     ".join(map(repr, self.cmds)),)

  def run(self):
    """
    Fork-exec the pipeline and wait for its termination.

    Return an array of all children's exit status.
    """
    prev = self.cmds[0].fd[STDIN]
    for c in self.cmds:
        c.p = c._popen(stdin=prev)
        prev = c.p.stdout
    for c in self.cmds:
        c.p.wait()
    for c in self.cmds[:-1]:
        if c.fd[STDOUT] == PIPE:
          c.p.stdout.close()
    return [c.p.returncode for c in self.cmds]

  def spawn(self):
    """
    Fork-exec the pipeline but do not wait for its termination.

    After spawned, each self.cmd[i] will have a 'p' attribute that is
    the spawned subprocess.Popen object.

    Remember that all of [c.p.stdout for c in self.cmd] are open files.
   """
    prev = self.cmds[0].fd[STDIN]
    for c in self.cmds:
        c.p = c._popen(stdin=prev)
        prev = c.p.stdout
    JOBS.append(self)
    return self

  def capture(self, *fd):
    """
    Fork-exec the Cmd and wait for its termination, capturing the
    output and/or error.

    :param fd: a list of file descriptors to capture, should be a
    subset of [1, 2] where
      * 1 represents what the children would have written to the parent's stdout
      * 2 represents what the children would have written to the parent's stderr

    Return a namedtuple (stdout, stderr, exit_status) where stdout and
    stderr are captured file objects or None and exit_status is a list
    of all children's exit statuses.

    Don't forget to close the file objects!

    """
    if not fd:
      raise ValueError("what do you want to capture?")
    if isinstance(fd, int):
      fd = set([fd])
    else:
      fd = set(fd) or set([1])
    if not fd <= set([1, 2]):
      raise NotImplementedError(
        "can only capture a subset of fd [1, 2] for now")
    if 1 in fd and not _is_fileno(1, self.fd[1]):
      raise ValueError(
        "cannot capture the last child's stdout: it had been redirected to %r"
                % _name_or_self(self.fd[1]))
    temp = None
    if 2 in fd:
      self.fd[2] = tempfile.TemporaryFile()
    ## start piping
    prev = self.cmds[0].fd[0]
    for c in self.cmds[:-1]:
      if not _is_fileno(0, c.fd[0]):
        prev = c.fd[0]
      if 2 in fd and _is_fileno(2, c.fd[2]):
        c.fd[2] = self.fd[2]
      c.p = c._popen(stdin=prev)
      prev = c.p.stdout
    ## prepare and fork the last child
    c = self.cmds[-1]
    if not _is_fileno(0, c.fd[0]):
      prev = c.fd[0]
    if 1 in fd:
      ## we made sure that c.fd[1] had not been redirected before
      c.fd[1] = tempfile.TemporaryFile()
      self.fd[1] = c.fd[1]
    if 2 in fd and _is_fileno(2, c.fd[2]):
      c.fd[2] = self.fd[2]
    c.p = c._popen(stdin=prev)
    ## wait for all children
    for c in self.cmds:
      c.p.wait()
    ## close all unneeded files
    for c in self.cmds[:-1]:
      if c.fd[1] == PIPE:
        c.p.stdout.close()
    if len(fd) == 1:
      if 1 in fd and not _is_fileno(2, self.fd[2]): self.fd[2].close()
      if 2 in fd and not _is_fileno(1, self.fd[1]): self.fd[1].close()
    if 1 in fd: self.fd[1].seek(0)
    if 2 in fd: self.fd[2].seek(0)
    return Capture(self.fd[1], self.fd[2], [c.p.returncode for c in self.cmds])


def here(string):
  """
  Make a temporary file from a string for use in redirection.
  """
  t = tempfile.TemporaryFile()
  t.write(string)
  t.seek(0)
  return t

def run(cmd, fd={}, e={}, cd=None):
  """
  Perform a fork-exec-wait of a Cmd and return its exit status.
  """
  return Cmd(cmd, fd=fd, e=e, cd=cd).run()

def cmd(cmd, fd={}, e={}, cd=None):
  """
  Perform a fork-exec-wait of a Cmd and return the its stdout
  as a byte string.
  """
  f = Cmd(cmd, fd=fd, e=e, cd=cd).capture(1).stdout
  try:
    s = f.read()
  finally:
    f.close()
  return s

def sh(cmd, fd={}, e={}, cd=None):
  """
  Perform a fork-exec-wait of a Sh command and return its stdout
  as a byte string.
  """
  f = Sh(cmd, fd=fd, e=e, cd=cd).capture(1).stdout
  try:
    s = f.read()
  finally:
    f.close()
  return s

def pipe(*cmds, **kwargs):
  """
  Run the pipeline with given Cmd's, then returns its stdout as a byte string.
  """
  f = Pipe(*cmds, **kwargs).capture(1).stdout
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



def __failing():
  """
  ### test Cmd redirect {1: n}
  >>> f = tempfile.TemporaryFile()
  >>> Sh('echo -n foo', {1: f.fileno()}).run()
  0

  ###>>> f.seek(0); f.read()
  ###'foo'


  """

if __name__ == '__main__':
  import doctest
  n = doctest.testmod().failed
  if n > 0:
    sys.exit(n)
