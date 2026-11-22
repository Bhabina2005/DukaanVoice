import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import main

cm = main.lifespan(main.app)
coro = cm.__aenter__()
try:
    coro.send(None)
except StopIteration:
    pass
print("ENTERED CLEANLY")

coro_exit = cm.__aexit__(None, None, None)
try:
    coro_exit.send(None)
except StopIteration:
    pass
print("EXITED CLEANLY")
