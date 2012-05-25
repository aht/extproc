import os
import subprocess

import tempfile
tf = tempfile.TemporaryFile()
proc_obj = subprocess.Popen('ls', stdout=-1)
proc_obj2 = subprocess.Popen(['wc', '-l'], stdin=proc_obj.stdout.fileno(), stdout=-1)
print proc_obj2.stdout.read()

