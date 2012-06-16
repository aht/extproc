import unittest
from extproc import JOBS
STDIN, STDOUT, STDERR = 0, 1, 2


def sh_strip(in_):
    in2 = in_.replace('\n','')
    return in2.strip()

class ExtProcTest(unittest.TestCase):

    def tearDown(self):
        for c in JOBS:
            c.kill()

    def assertSh(self, str1, str2):
        self.assertEquals(sh_strip(str1), sh_strip(str2))
