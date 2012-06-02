import unittest
import time
import os
import tempfile
from extproc import (
    run, Sh, sh, Pipe, pipe, Cmd, here, JOBS, cmd)
STDIN, STDOUT, STDERR = 0, 1, 2

def sh_strip(in_):
    in2 = in_.replace('\n','')
    return in2.strip()
class ExtProcTest(unittest.TestCase):

    def assertSh(self, str1, str2):
        self.assertEquals(sh_strip(str1), sh_strip(str2))

class LowerCaseTest(ExtProcTest):
    """ test the lowercase convience functions """

    def test_sanity(self):
        self.assertEquals(run('true'), 0)
        self.assertEquals(run('false'), 1)

    def test_Sh(self):
        sh_call = Sh('echo bar >&2; echo foo; exit 1')
        out, err, status = sh_call.capture(1, 2)
        self.assertEquals(status, 1)
        # these tests pass on OS X, not sure how they will run on
        # linux
        self.assertSh(out.read(), 'foo')
        self.assertSh(err.read(), 'bar')


    def test_sh(self):
        """ test Cmd ENV """
        self.assertSh(sh('echo $var', e={'var': 'foobar'}), 'foobar')

        self.assertRaises(
            NotImplementedError,
            lambda: sh('echo foo; echo bar >&2', {1: 2}))

        ### test Cmd impossible capture
        self.assertRaises(
            ValueError,
            lambda: sh("echo bogus stuff", {1: os.devnull}))

        ### test Pipe stderr capture
        pipe_ = Pipe(Sh('echo foo; sleep 0.01; echo  bar >&2'), Sh('cat >&2'))
        self.assertSh(pipe_.capture(2).stderr.read(), 'foobar')

        ### test Pipe ENV
        self.assertSh(
            pipe(Sh('echo $x'), Sh('cat; echo $x'), e=dict(x='foobar')),
            'foobarfoobar')
        ### test Pipe impossible capture
        self.assertRaises(
            ValueError,
            lambda:pipe(Sh("echo bogus"), Cmd("cat", {1: os.devnull})))

        ### test Pipe pathetic case
        self.assertSh(pipe(Sh("echo foo"), Cmd("cat", {0: here("bar")})), 'bar')

        ### test JOBS
        self.assertEquals(len(JOBS), 0)
        Pipe(Cmd('yes'), Cmd('cat', {1: os.devnull})).spawn()
        JOBS[-1].cmds[0].p.kill()
        self.assertEquals(JOBS[-1].cmds[-1].p.wait(), 0)

        ### test Cmd redirect {1: n}
        f = tempfile.TemporaryFile()
        self.assertEquals(
            Sh('echo foo', {1: f.fileno()}).run(), 0)
        f.seek(0)
        self.assertSh(f.read(), 'foo')



    def test_sh2(self):
        self.assertSh(sh('echo foo >&2', {STDERR: 1}), 'foo')

    def test_cmd(self):
        self.assertSh(
            cmd(['/bin/sh', '-c', 'echo foo; echo bar >&2'], {2: 1}), 'foobar')

    def test_run(self):
        self.assertEquals(run('cat /dev/null'), 0)

    def test_here(self):
        self.assertSh(cmd('cat', {0: here("foo bar")}), 'foo bar')

class ExtProcPipeTest(ExtProcTest):

    def _test_Pipe(self):
        Pipe(Cmd('yes'), Cmd('cat', {1: os.devnull}))
        Pipe(Cmd(['yes'], fd={0: 0, 1: -1, 2: 2}, e={}, cd=None),
             Cmd(['cat'], fd={0: 0, 1: '/dev/null', 2: 2}, e={}, cd=None))

    def test_run(self):
        self.assertEquals(
            Pipe(Sh("echo foo"),
                 Sh("cat; echo bar"),
                 Cmd("cat", {1: os.devnull})).run(),
            [0,0,0])

    def _test_spawn(self):
        """FIXME: I'm not sure why this test is failing, let me
        complete the test suite and see if ohters are failing, maybe
        there is a more obvious cause """
        yesno = Pipe(Cmd('yes'), Cmd(['grep', 'no'])).spawn()
        time.sleep(0.5)
        yesno.cmd[0].p.kill()
        time.sleep(0.5)
        self.assertEquals(yesno.cmd[-1].p.wait(), 1)

    def test_capture(self):
        self.assertSh(
            Pipe(Sh('echo foo; echo bar >&2', {2: os.devnull}),
                 Cmd('cat')).capture(1).stdout.read(),
            'foo')

        self.assertSh(
            Pipe(Sh('echo foo; echo bar >&2'),
                 Cmd('cat', {1: os.devnull})).capture(2).stderr.read(),
            'bar')

class ExtProcCmdTest(ExtProcTest):
    def test_CMD(self):
        self.assertEquals(Cmd(['grep', 'my stuff']), Cmd('grep "my stuff"'))

    def test_capture(self):

        self.assertSh(
            Cmd("/bin/sh -c 'echo foo'").capture(1).stdout.read(), 'foo')

        self.assertSh(
            Cmd("/bin/sh -c 'echo bar >&2'").capture(2).stderr.read(), 'bar')

        c_obj = Cmd("/bin/sh -c 'echo  foo; echo  bar >&2'")
        cout, cerr, status = c_obj.capture(1, 2)
        self.assertSh(cout.read(), 'foo')
        self.assertSh(cerr.read(), 'bar')

if __name__ == '__main__':
    unittest.main()
