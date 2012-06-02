import unittest
import os
from extproc import run, Sh, sh, Pipe


def sh_strip(in_):
    in2 = in_.replace('\n','')
    return in2.strip()
class ExtProcTest(unittest.TestCase):

    def test_sanity(self):
        self.assertEquals(run('true'), 0)
        self.assertEquals(run('false'), 1)

    def test_Sh(self):
        sh_call = Sh('echo bar >&2; echo foo; exit 1')
        out, err, status = sh_call.capture(1, 2)
        self.assertEquals(status, 1)
        # these tests pass on OS X, not sure how they will run on linux
        self.assertEquals(out.read().strip(), 'foo')
        self.assertEquals(err.read().strip(), 'bar')

    def test_sh(self):
        """ test Cmd ENV """
        self.assertEquals(
            sh('echo $var', e={'var': 'foobar'}).strip(), 'foobar')

        self.assertRaises(
            NotImplementedError,
            lambda: sh('echo foo; echo bar >&2', {1: 2}))

        ### test Cmd impossible capture
        self.assertRaises(
            ValueError,
            lambda: sh("echo bogus stuff", {1: os.devnull}))

        ### test Pipe stderr capture
        pipe = Pipe(Sh('echo foo; sleep 0.01; echo  bar >&2'), Sh('cat >&2'))
        self.assertEquals(sh_strip(pipe.capture(2).stderr.read()), 'foobar')





if __name__ == '__main__':
    unittest.main()
