import pdb
import time
import os
import tempfile

from test_extproc.test_lib import ExtProcTest, STDIN, STDOUT, STDERR
from extproc import Sh, Pipe, Cmd, JOBS, fork_dec

class ExtProcPipeTest(ExtProcTest):

    def _test_Pipe(self):
        Pipe(Cmd('yes'), Cmd('cat', {1: os.devnull}))
        Pipe(Cmd(['yes'], fd={0: 0, 1: -1, 2: 2}, e={}, cd=None),
             Cmd(['cat'], fd={0: 0, 1: '/dev/null', 2: 2}, e={}, cd=None))

    def test_pipe_proc_interface(self):
        ### test Pipe ENV
        pipe_obj = Pipe(Pipe(Cmd("/bin/sh -c 'echo foo'")))

        self.assertSh(pipe_obj.capture(1).stdout.read(), 'foo')


    def test_pipe_proc_decorator(self):
        ### test Pipe ENV
        @fork_dec
        def echoer(stdin_f, stdout_f, stderr_f):
            for line in stdin_f:
                stdout_f.write(line + "\n")
        pipe_obj = Pipe(Cmd("/bin/sh -c 'echo foo'"),
                        echoer)
        self.assertSh(pipe_obj.capture(1).stdout.read(), 'foo')

        @fork_dec
        def echoer(stdin_f, stdout_f, stderr_f):
            for line in stdin_f:
                stdout_f.write(line+line + "\n")
        pipe_obj = Pipe(Cmd("/bin/sh -c 'echo foo'"),
                        echoer)
        self.assertSh(pipe_obj.capture(1).stdout.read(), 'foofoo')

    def _test_pipe_composable(self):
        """we should be able to compose pipes of pipes """
        Pipe(Pipe(Sh("echo foo")),
             Pipe(Sh("cat; echo bar")),
             Pipe(Cmd("cat", {1: os.devnull}))).run(),

        self.assertEquals(
            [0,0,0])


        self.assertEquals(len(JOBS), 0)
        " yes | grep no"
        yesno = Pipe(
            Pipe(Cmd('yes')),
            Pipe(Cmd(['grep', 'no']))).spawn()
        yesno.cmds[0].kill()
        self.assertEquals(yesno.cmds[-1].wait(), 1)
        self.assertEquals(yesno.wait(), 1)
        self.assertEquals(len(JOBS), 0)

        pipe_a = Pipe(Cmd('echo foo'))
        pdb.set_trace()
        ab = pipe_a._popen()

        self.assertSh(pipe_a.running_fd_objs[STDOUT].read(), 'foo')

    def _asfd(self):
        pipe_a=Pipe(Cmd('ls /usr/local/Cellar'))

        #


        pipe_b=Pipe(Cmd('wc -l'))
        outer_pipe = Pipe(pipe_a, pipe_b)
        self.assertSh(outer_pipe.capture(1).stdout.read(), '10')



    def test_run(self):
        pipe_obj = Pipe(Sh("echo foo"),
                        Sh("cat; echo bar"),
                        Cmd("cat", {1: os.devnull}))

        self.assertEquals(pipe_obj.run(), 0)
        self.assertEquals(pipe_obj.returncodes, [0,0,0])

    def test_spawn(self):
        self.assertEquals(len(JOBS), 0)
        " yes | grep no"
        yesno = Pipe(Cmd('yes'), Cmd(['grep', 'no'])).spawn()
        yesno.cmds[0].kill()
        self.assertEquals(yesno.cmds[-1].wait(), 1)
        self.assertEquals(yesno.wait(), 1)
        self.assertEquals(len(JOBS), 0)



    def chriss_recommended_syntax(self):
        '''
        ls().pipe_to(grep("pyc")).pipe_to(...)
        grep_example = Pipe(
            ls(),
            grep("pyc")
            )

        output =
        '''


    def test_capture(self):
        self.assertSh(
            Pipe(Sh('echo foo; echo bar >&2', {2: os.devnull}),
                 Cmd('cat')).capture(1).stdout.read(),
            'foo')

        self.assertSh(
            Pipe(Sh('echo foo; echo bar >&2'),
                 Cmd('cat', {1: os.devnull})).capture(2).stderr.read(),
            'bar')

        sh_call = Pipe(Sh('echo bar >&2; echo foo; exit 1'))
        out, err, status = sh_call.capture(1, 2)
        self.assertEquals(status, 1)
        # these tests pass on OS X, not sure how they will run on
        # linux
        self.assertSh(out.read(), 'foo')
        self.assertSh(err.read(), 'bar')

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
    def test_stdin_data(self):
        def raiseBadArgs():
            cmd_ = Cmd("sed s/i/I/g", stdin_data="Hi", fd={STDIN:"/foo"})
        #self.assertRaises(
        #self.assertEqual(r.std_out.rstrip(), "HI")
        #self.assertEqual(r.status_code, 0)

    def test_spawn_once(self):
        ab = Cmd('yes', {STDOUT: '/dev/null', STDERR: '/dev/null'})
        ab.spawn()
        self.assertRaises(Exception, lambda: ab.spawn())


    def _test_popen_fd_semantics(self):
        tf = tempfile.TemporaryFile()
        ab = Cmd('yes', {STDOUT: tf})
        ab._popen()
        self.assertTrue(tf is ab.fd_objs[STDOUT])

class ExtPipeSyntaxtTest(ExtProcTest):
    def test_pipeto(self):
        self.assertSh(
            Pipe(
                Cmd("echo foo"),
                Cmd("wc -c")).capture(1).stdout.read(), '4')
        self.assertSh(
            Cmd("echo foo").pipe_to(Cmd("wc -c")).capture(1).stdout.read(), '4')


        #or syntax, closer to bash pipes
        self.assertSh(
            (Cmd("echo foo") | Cmd("wc -c")).capture(1).stdout.read(), '4')

    def test_capture_sane(self):
        self.assertSh(
            Pipe(
                Cmd("echo foo"),
                Cmd("wc -c")).capture().stdout.read(), '4')

    def test_wait_callback(self):
        orig_val = [0]
        def val_mod():
            orig_val[0] = 8
        c = Cmd("sleep 1")
        c.spawn()
        self.assertEquals(orig_val, [0])
        c.wait(val_mod)
        self.assertEquals(orig_val, [8])

        orig_val = [0]
        p = Cmd("echo foo").pipe_to(Cmd("wc -c"))
        p.spawn()
        self.assertEquals(orig_val, [0])
        p.wait(val_mod)
        self.assertEquals(orig_val, [8])


        if __name__ == '__main__':
            unittest.main()
