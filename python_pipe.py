import os
import subprocess

import tempfile
tf = tempfile.TemporaryFile()
proc_obj = subprocess.Popen('ls', stdout=-1)
print "original pid", os.getpid()
out_file_r_num, out_file_w_num = os.pipe()
pid = os.fork()

in_file = proc_obj.stdout

if pid:
    print "got the pid ", pid, "we are the parent "
    out_file_w = os.fdopen(out_file_w_num, "w")
    out_file_r = os.fdopen(out_file_r_num)
    out_file_w.close()
    proc_obj2 = subprocess.Popen(['wc', '-l'], stdin=out_file_r, stdout=-1)
    print proc_obj2.stdout.read()

    #print out_file_r.read()
else:
    print "in the child didn't get a pid"
    out_file_w = os.fdopen(out_file_w_num, "w")
    out_file_r = os.fdopen(out_file_r_num)

    out_file_r.close()
    for line in in_file:
        out_file_w.write("1\n 2\n  3\n")


