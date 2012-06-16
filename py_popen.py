import os
import sys
import traceback
import pickle
from subprocess import Popen, _cleanup, mswindows, gc, _eintr_retry_call

class PyPopen(Popen):
    def __init__(self, py_func, bufsize=0, executable=None,
                 stdin=None, stdout=None, stderr=None,
                 preexec_fn=None, close_fds=False, shell=False,
                 cwd=None, env=None, universal_newlines=False,
                 startupinfo=None, creationflags=0):
        """Create new Popen instance."""
        _cleanup()

        self._child_created = False
        if not isinstance(bufsize, (int, long)):
            raise TypeError("bufsize must be an integer")

        if mswindows:
            if preexec_fn is not None:
                raise ValueError("preexec_fn is not supported on Windows "
                                 "platforms")
            if close_fds and (stdin is not None or stdout is not None or
                              stderr is not None):
                raise ValueError("close_fds is not supported on Windows "
                                 "platforms if you redirect stdin/stdout/stderr")
        else:
            # POSIX
            if startupinfo is not None:
                raise ValueError("startupinfo is only supported on Windows "
                                 "platforms")
            if creationflags != 0:
                raise ValueError("creationflags is only supported on Windows "
                                 "platforms")

        self.stdin = None
        self.stdout = None
        self.stderr = None
        self.pid = None
        self.returncode = None
        self.universal_newlines = universal_newlines

        # Input and output objects. The general principle is like
        # this:
        #
        # Parent                   Child
        # ------                   -----
        # p2cwrite   ---stdin--->  p2cread
        # c2pread    <--stdout---  c2pwrite
        # errread    <--stderr---  errwrite
        #
        # On POSIX, the child objects are file descriptors.  On
        # Windows, these are Windows file handles.  The parent objects
        # are file descriptors on both platforms.  The parent objects
        # are None when not using PIPEs. The child objects are None
        # when not redirecting.

        (p2cread, p2cwrite,
         c2pread, c2pwrite,
         errread, errwrite) = self._get_handles(stdin, stdout, stderr)

        self._execute_child(py_func, executable, preexec_fn, close_fds,
                            cwd, env, universal_newlines,
                            startupinfo, creationflags, shell,
                            p2cread, p2cwrite,
                            c2pread, c2pwrite,
                            errread, errwrite)

        if mswindows:
            if p2cwrite is not None:
                p2cwrite = msvcrt.open_osfhandle(p2cwrite.Detach(), 0)
            if c2pread is not None:
                c2pread = msvcrt.open_osfhandle(c2pread.Detach(), 0)
            if errread is not None:
                errread = msvcrt.open_osfhandle(errread.Detach(), 0)

        if p2cwrite is not None:
            self.stdin = os.fdopen(p2cwrite, 'wb', bufsize)
        if c2pread is not None:
            if universal_newlines:
                self.stdout = os.fdopen(c2pread, 'rU', bufsize)
            else:
                self.stdout = os.fdopen(c2pread, 'rb', bufsize)
        if errread is not None:
            if universal_newlines:
                self.stderr = os.fdopen(errread, 'rU', bufsize)
            else:
                self.stderr = os.fdopen(errread, 'rb', bufsize)


    def _execute_child(self, py_func, executable, preexec_fn, close_fds,
                       cwd, env, universal_newlines,
                       startupinfo, creationflags, shell,
                       p2cread, p2cwrite,
                       c2pread, c2pwrite,
                       errread, errwrite):
        """Execute program (POSIX version)"""

        # For transferring possible exec failure from child to parent
        # The first char specifies the exception type: 0 means
        # OSError, 1 means some other error.
        errpipe_read, errpipe_write = os.pipe()
        try:
            try:
                self._set_cloexec_flag(errpipe_write)

                gc_was_enabled = gc.isenabled()
                # Disable gc to avoid bug where gc -> file_dealloc ->
                # write to stderr -> hang.  http://bugs.python.org/issue1336
                gc.disable()
                try:
                    self.pid = os.fork()
                except:
                    if gc_was_enabled:
                        gc.enable()
                    raise
                self._child_created = True
                if self.pid == 0:
                    # Child
                    try:
                        # Close parent's pipe ends
                        if p2cwrite is not None:
                            os.close(p2cwrite)
                        if c2pread is not None:
                            os.close(c2pread)
                        if errread is not None:
                            os.close(errread)
                        os.close(errpipe_read)

                        # Dup fds for child
                        if p2cread is not None:
                            os.dup2(p2cread, 0)
                        if c2pwrite is not None:
                            os.dup2(c2pwrite, 1)
                        if errwrite is not None:
                            os.dup2(errwrite, 2)

                        # Close pipe fds.  Make sure we don't close the same
                        # fd more than once, or standard fds.
                        if p2cread is not None and p2cread not in (0,):
                            os.close(p2cread)
                        if c2pwrite is not None and c2pwrite not in (p2cread, 1):
                            os.close(c2pwrite)
                        if errwrite is not None and errwrite not in (p2cread, c2pwrite, 2):
                            os.close(errwrite)

                        # Close all other fds, if asked for
                        if close_fds:
                            self._close_fds(but=errpipe_write)

                        if cwd is not None:
                            os.chdir(cwd)

                        if preexec_fn:
                            preexec_fn()

                        child_stdin = os.fdopen(0, "r")
                        child_stdout = os.fdopen(1, "w")
                        child_stderr = os.fdopen(2, "w")
                        #call the child function
                        py_func(child_stdin, child_stdout, child_stderr)
                        child_stdin.close()
                        child_stdout.close()
                        child_stderr.close()

                    except:
                        exc_type, exc_value, tb = sys.exc_info()
                        # Save the traceback and attach it to the exception object
                        exc_lines = traceback.format_exception(exc_type,
                                                               exc_value,
                                                               tb)
                        exc_value.child_traceback = ''.join(exc_lines)
                        os.write(errpipe_write, pickle.dumps(exc_value))

                    # This exitcode won't be reported to applications, so it
                    # really doesn't matter what we return.
                    #os._exit(0)
                    # in the case of extproc, the exit status does
                    # matter, we want the exit status to be 0
                    os._exit(0)

                # Parent
                if gc_was_enabled:
                    gc.enable()
            finally:
                # be sure the FD is closed no matter what
                os.close(errpipe_write)

            if p2cread is not None and p2cwrite is not None:
                os.close(p2cread)
            if c2pwrite is not None and c2pread is not None:
                os.close(c2pwrite)
            if errwrite is not None and errread is not None:
                os.close(errwrite)

            # Wait for exec to fail or succeed; possibly raising exception
            # Exception limited to 1M
            data = _eintr_retry_call(os.read, errpipe_read, 1048576)
        finally:
            # be sure the FD is closed no matter what
            #pass
            os.close(errpipe_read)

        if data != "":
            print data
            _eintr_retry_call(os.waitpid, self.pid, 0)
            child_exception = pickle.loads(data)
            for fd in (p2cwrite, c2pread, errread):
                if fd is not None:
                    os.close(fd)
            raise child_exception
