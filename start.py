#!/usr/bin/env python3
"""Container entry: make the two owner mounts usable by the app user, then drop root for good.

Runtipi creates app-data and media folders as root. The app itself never runs as root: this only
creates/chowns the top-level data folder (CHOWN/SETUID/SETGID are the only capabilities
granted) and then switches to uid/gid 1000 before importing any app code."""
import os, sys
UID = int(os.environ.get('CINEQUEUE_UID', '1000'))
GID = int(os.environ.get('CINEQUEUE_GID', '1000'))
if os.geteuid() == 0:
    for d in (os.environ.get('CINEQUEUE_DATA', '/data'),):
        try:
            os.makedirs(d, exist_ok=True)
            if os.stat(d).st_uid != UID:
                os.chown(d, UID, GID)
        except OSError as e:
            print(f'start: could not prepare {d}: {e}', file=sys.stderr, flush=True)
    os.setgroups([])
    os.setgid(GID)
    os.setuid(UID)
os.chdir('/app')
os.execv(sys.executable, [sys.executable, '-m', 'cinequeue'])
