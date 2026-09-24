"""Operator-provided credentials; never generated, logged or bundled."""
import os
from pathlib import Path
import stat


def private_seed(item,root):
    if item.get('private_key_env'):
        value=os.environ.get(item['private_key_env'])
        if value:return value
    if item.get('private_key_file'):
        path=Path(item['private_key_file']).expanduser()
        if not path.is_absolute():path=Path(root)/path
        # Open without following a final symlink, then inspect the opened file.
        fd=os.open(path,os.O_RDONLY | getattr(os,'O_NOFOLLOW',0))
        with os.fdopen(fd) as f:
            meta=os.fstat(f.fileno())
            if not stat.S_ISREG(meta.st_mode) or meta.st_mode & 0o077 or meta.st_uid!=os.getuid():
                raise ValueError('private-key file must be owner-owned and accessible only to its owner (chmod 600)')
            value=f.read(4097).strip()
        if len(value)>4096 or not value:raise ValueError('invalid private-key file')
        return value
    raise ValueError('trusted signing credential unavailable')
