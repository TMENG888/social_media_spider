"""Run isolated regressions; refuse remote sockets and all subprocess launches."""
import os,runpy,socket,subprocess
import unittest.mock  # Import Windows asyncio subclasses before installing guards.
from pathlib import Path
def forbidden(*args,**kwargs):raise AssertionError('External I/O forbidden in offline tests')
socket.socket.connect=forbidden
socket.socket.connect_ex=forbidden
socket.create_connection=forbidden
subprocess.Popen=forbidden
for test in sorted(Path(__file__).parent.glob('test_*.py')):
    print(test.name,flush=True)
    runpy.run_path(str(test),run_name='__main__')
print('All offline bridge regressions passed.')
