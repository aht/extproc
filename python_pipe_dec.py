import os
import subprocess

import tempfile
tf = tempfile.TemporaryFile()

class ProcLike(object):
    pass



def fork_decorator(f):

    def inner_func(in_file):
        out_file_r_num, out_file_w_num = os.pipe()
        out_file_w = os.fdopen(out_file_w_num, "w")
        out_file_r = os.fdopen(out_file_r_num)

        pid = os.fork()
        if pid:
            print "we are the child"
            out_file_r.close()
            f(in_file, out_file_w)
        else:
            pl = ProcLike()
            pl.stdout = out_file_r
            return pl
    return inner_func

@fork_decorator
def triple_lines(in_file, out_file):
    for line in in_file:
        out_file.write("1\n 2\n  3\n")

proc_obj = subprocess.Popen('ls', stdout=-1)
py_pipe_obj = triple_lines(proc_obj.stdout)
proc_obj2 = subprocess.Popen(['wc', '-l'], stdin=py_pipe_obj.stdout, stdout=-1)
print proc_obj2.stdout.read()


@fork_decorator
def triple_lines(in_file, out_file):
    for line in in_file:

        Pipe(Sh("echo foo"), Sh("cat; echo bar"), triple_lines, Cmd("cat", {1: os.devnull})).run()

class PyForkable(object):
    """ this is the object that wraps a python function that is to be
    used in a Pipe sequence, it implements the interface of command

    Ideally
    """
    def __init__(self, f):
        self.f = f
        self.fd = {}

    def _popen(self, stdin=0, stdout=1, stderr=2):


        def make_forkable(f):
            """ this is the actual decorator that is wrapped around a function  """
