"""Offline software regression; does not verify live services."""
import socket,sys,pytest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
_original=socket.getaddrinfo
def guarded(host,*args,**kwargs):
    if host not in (None,"localhost","127.0.0.1","::1",b"localhost",b"127.0.0.1"):
        raise OSError("External networking disabled for offline regression")
    return _original(host,*args,**kwargs)
socket.getaddrinfo=guarded
sys.exit(pytest.main(sys.argv[1:]))
