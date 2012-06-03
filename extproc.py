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

class FakeP(object):
    pass

class Process(object):

    def _check_redirect_target(self, fd_target, fd_dict):
        ret_fd_dict = {}
        if _is_fileno(fd_target, fd_dict[fd_target]):
            ret_fd_dict[fd_target] = tempfile.TemporaryFile()
            return ret_fd_dict
        else:
            raise ValueError(
                "cannot capture the child's %d stream: it was redirected to %r"
                % (fd_target,  _name_or_self(fd_target)))

    def _verify_capture_args(self, fd_a, fd_dict):
        ret_fd_dict = {}
        if fd_a not in [1,2]:
            raise NotImplementedError(
                "can only capture a subset of fd [1, 2] for now")

        ret_fd_dict = self._check_redirect_target(fd_a, fd_dict)
        return ret_fd_dict

    def _cleanup_capture_dict(self, fd, fd_dict):
        if fd == STDOUT:
            target = STDERR
        else:
            target = STDOUT
        target_obj = fd_dict[target]
        if not _is_fileno(target, target_obj) and isinstance(target_obj, file):
            fd_dict[target].close()

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
        assert len(fd) > 0
        for stream_num in fd:
            fd_update_dict = self._verify_capture_args(stream_num, self.fd_objs)
            self.fd_objs.update(fd_update_dict)
        p = self._popen()
        if p.stdin:
            p.stdin.close()
        p.wait()
        if not set(fd) == set([1,2]):
             self._cleanup_capture_dict(fd[0], p.fd_objs)
        for stream_number in fd:
            self.fd_objs[stream_number].seek(0)
        return Capture(self.fd_objs[1], self.fd_objs[2], p.returncode)

    def _process_fd_pair(self, stream_num, fd_descriptor):
        """for now this just does error checking

        fd_descriptor is what is passed into the function
        """
        if not isinstance(stream_num, int):
            raise TypeError("fd keys must have type int")
        elif stream_num < 0 or stream_num >= 3:
             raise NotImplementedError(
                "redirection {%s: %s} not supported" % (
                     stream_num, fd_descriptor))
        if isinstance(fd_descriptor, basestring):
            new_fd = open(fd_descriptor, 'r' if stream_num == 0 else 'w')
            return new_fd
        elif isinstance(fd_descriptor, int):
            if stream_num == 2 and fd_descriptor == 1:
                return _ORIG_STDOUT
                #self.fd[STDERR] = _ORIG_STDOUT
            elif (fd_descriptor in (0, 1, 2)):
                raise NotImplementedError(
                    "redirection {%s: %s} not supported" % (stream_num, fd_descriptor))
            return fd_descriptor
        elif isinstance(fd_descriptor, file):
            return fd_descriptor
        else:
            assert 1==2, "fd_descriptors must be a string\
                          stream number or file"


class Cmd(Process):

    def _make_cmd(self, cmd_arg):
        if isinstance(cmd_arg, basestring):
            self.cmd = shlex.split(cmd_arg)
        elif isinstance(cmd_arg, (list, tuple)):
            self.cmd = cmd_arg
        else:
            raise TypeError(
                "'cmd' must be either of type string, list or tuple")

    """
    fd_objs is used for processed file descriptor arguments, open file
    objects, or number flags

    """
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

        self._make_cmd(cmd)
        self.cd = cd
        self.e = e
        self.env = os.environ.copy()
        self.env.update(e)
        self.fd_objs = DEFAULT_FD.copy()
        self.fd_objs.update(fd)

        for stream_num, fd_num in fd.iteritems():
            self.fd_objs[stream_num] = self._process_fd_pair(stream_num, fd_num)

    def __repr__(self):
        return "Cmd(%r, fd=%r, e=%r, cd=%r)" % (
          self.cmd, dict((k, _name_or_self(v)) for k, v in self.fd.iteritems()),
          self.e, self.cd)

    def __eq__(self, other):
        return (self.cmd == other.cmd) and (self.fd_objs == other.fd_objs) and\
               (self.env == other.env) and (self.cd == other.cd)

    def kill(self):
        if not getattr(self, 'p', False):
            raise Exception('No process to kill')
        try:
            return self.p.kill()
        except OSError:
            pass
        finally:
            for job in JOBS:
                if job is self:
                    JOBS.remove(self)

    def wait(self):
        if not getattr(self, 'p', False):
            raise Exception('No process to kill')
        try:
            return self.p.wait()
        finally:
            for job in JOBS:
                if job is self:
                    JOBS.remove(self)


    def run(self):
        """
        Fork-exec the Cmd and waits for its termination.

        Return the child's exit status.

        >>> Cmd(['/bin/sh', '-c', 'exit 1']).run()
        1
        """
        return subprocess.call(**self.popen_args)

    def spawn(self, append_to_jobs=True):
        """
        Fork-exec the Cmd but do not wait for its termination.

        Return a subprocess.Popen object (which is also stored in 'self.p')
        """
        if getattr(self, 'p', False):
            raise Exception('can only spawn once per cmd object')
        self.p = self._popen()
        if append_to_jobs:
            JOBS.append(self)
        return self.p


    @property
    def popen_args(self):
        return dict(args=self.cmd, cwd=self.cd, env=self.env,
          stdin=self.fd_objs[0], stdout=self.fd_objs[1], stderr=self.fd_objs[2])

    def _popen(self, **kwargs):
        basic_popen_args = self.popen_args
        basic_popen_args.update(kwargs)
        return decorate_popen(subprocess.Popen(**basic_popen_args))

def decorate_popen(popen_obj):
    popen_obj.fd_objs = {
        STDIN:popen_obj.stdin,
        STDOUT:popen_obj.stdout,
        STDERR:popen_obj.stderr}
    return popen_obj

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


class Pipe(Process):
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
            if _is_fileno(1, c.fd_objs[STDOUT]):
              c.fd_objs[STDOUT] = PIPE

        self.fd_objs = {STDIN: cmds[0].fd_objs[STDIN],
                   STDOUT: cmds[-1].fd_objs[STDOUT],
                   STDERR: STDERR}
        self.cmds = cmds

    def __repr__(self):
        return "Pipe(%s)" % (",\n     ".join(map(repr, self.cmds)),)

    def run(self):
        """
        Fork-exec the pipeline and wait for its termination.

        Return an array of all children's exit status.
        """
        prev = self.cmds[0].fd_objs[STDIN]
        for c in self.cmds:
            c.p = c._popen(stdin=prev)
            prev = c.p.stdout
        for c in self.cmds:
            c.p.wait()
        for c in self.cmds[:-1]:
            if c.fd_objs[STDOUT] == PIPE:
                c.p.stdout.close()
        return [c.p.returncode for c in self.cmds]

    def _popen(self, stdin=0, stdout=1, stderr=2):
        """
        Fork-exec the pipeline and wait for its termination.

        Return an array of all children's exit status.
        """
        #prev = self.cmds[0].fd[STDIN]
        prev = stdin
        for c in self.cmds:
            c.p = c._popen(stdin=prev)
            prev = c.p.stdout
        for c in self.cmds:
            c.p.wait()
        for c in self.cmds[:-1]:
            if c.fd[STDOUT] == PIPE:
                c.p.stdout.close()
        fp = FakeP()
        fp.stdin = self.fd[0]
        fp.stdout = self.fd[1]
        fp.stderr = self.fd[2]
        #fp.stdout = self.cmds[-1].p.stdout
        return fp
        #return [c.p.returncode for c in self.cmds]

    def spawn(self):
        """
        Fork-exec the pipeline but do not wait for its termination.

        After spawned, each self.cmd[i] will have a 'p' attribute that is
        the spawned subprocess.Popen object.

        Remember that all of [c.p.stdout for c in self.cmd] are open files.
       """
        if getattr(self, 'p', False):
            raise Exception('you can only spawn a Cmd object once')

        prev = self.cmds[0].fd_objs[STDIN]
        for c in self.cmds:
            c.p = c._popen(stdin=prev)
            prev = c.p.stdout
        JOBS.append(self)
        return self

    def kill(self):
        try:
            for c in self.cmds:
                c.kill()
        finally:
            for job in JOBS:
                if job is self:
                    JOBS.remove(self)

    def wait(self):
        try:
            return self.cmds[-1].wait()
        finally:
            for job in JOBS:
                if job is self:
                    JOBS.remove(self)


    def capture(self, *fd):
        """
        Fork-exec the Cmd and wait for its termination, capturing the
        output and/or error.

        :param fd: a list of file descriptors to capture, should be a
        subset of [1, 2] where

          * 1 represents what the children would have written to the
            parent's stdout
          * 2 represents what the children would have written to the
            parent's stderr

        Return a namedtuple (stdout, stderr, exit_status) where stdout and
        stderr are captured file objects or None and exit_status is a list
        of all children's exit statuses.

        Don't forget to close the file objects!

        """
        assert len(fd) > 0
        for descriptor in fd:
            fd_update_dict = self._verify_capture_args(descriptor, self.fd_objs)
            self.fd_objs.update(fd_update_dict)

        if STDERR in fd:
            self.fd_objs[STDERR] = tempfile.TemporaryFile()

        ## start piping
        prev = self.cmds[0].fd_objs[0]
        for c in self.cmds[:-1]:
            if not _is_fileno(STDIN, c.fd_objs[STDIN]):
                prev = c.fd_objs[STDIN]
            if STDERR in fd and _is_fileno(STDERR, c.fd_objs[STDERR]):
                c.fd_objs[STDERR] = self.fd_objs[STDERR]
            c.p = c._popen(stdin=prev)
            prev = c.p.stdout
        ## prepare and fork the last child
        c = self.cmds[-1]
        if not _is_fileno(STDIN, c.fd_objs[STDIN]):
            prev = c.fd_objs[STDIN]
        if STDOUT in fd:
            ## we made sure that c.fd[1] had not been redirected before
            c.fd_objs[STDOUT] = tempfile.TemporaryFile()
            self.fd_objs[STDOUT] = c.fd_objs[STDOUT]
        if STDERR in fd and _is_fileno(STDERR, c.fd_objs[STDERR]):
            c.fd_objs[STDERR] = self.fd_objs[STDERR]
        c.p = c._popen(stdin=prev)
        ## wait for all children
        for c in self.cmds:
            c.p.wait()
        ## close all unneeded files
        for c in self.cmds[:-1]:
            if c.fd_objs[STDOUT] == PIPE:
              c.p.stdout.close()
        if not set(fd) == set([1,2]):
            #self._cleanup_capture(fd[0], p)
            self._cleanup_capture_dict(fd[0], self.fd_objs)
        for descriptor in fd:
            self.fd_objs[descriptor].seek(0)

        return Capture(
            self.fd_objs[1], self.fd_objs[2],
            [c.p.returncode for c in self.cmds])

if __name__ == '__main__':
    import doctest
    n = doctest.testmod().failed
    if n > 0:
        sys.exit(n)
