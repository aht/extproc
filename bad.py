from pc import *

# stuff that is still problematic

# heredoc
>>> cmd('cat', {0: here("foo bar")})
'foo bar'

# broken pipe
>>> pipe(Sh('exit 1'), Cmd('/bin/grep x'))
