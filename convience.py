import tempfile
from extproc import Sh, Cmd, Pipe

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
