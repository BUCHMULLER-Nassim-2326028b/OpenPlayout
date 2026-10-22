"""Offline, validated SQLite restore. Keeps a copy of the replaced database."""
import argparse
from contextlib import closing
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import zipfile


def restore(archive_path: Path, data_dir: Path):
    data_dir = data_dir.resolve()
    target = data_dir / 'openplayout.db'
    data_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive_path) as archive:
        if set(archive.namelist()) != {'openplayout.db','manifest.json'}:
            raise ValueError('Archive must contain only openplayout.db and manifest.json')
        if json.loads(archive.read('manifest.json')).get('version') != 1:
            raise ValueError('Unsupported backup version')
        if archive.getinfo('openplayout.db').file_size > 2_000_000_000:
            raise ValueError('Backup database exceeds the 2 GB restore limit')
        content = archive.read('openplayout.db')
    staging = data_dir / 'restore-pending.sqlite'
    # Exclusive creation prevents overwriting another pending restore.
    with staging.open('xb') as stream:
        stream.write(content)
    try:
        with closing(sqlite3.connect(staging)) as db:
            if db.execute('PRAGMA integrity_check').fetchone()[0] != 'ok' or db.execute('PRAGMA foreign_key_check').fetchall():
                raise ValueError('Backup failed database integrity validation')
            if not db.execute("SELECT name FROM sqlite_master WHERE name='alembic_version'").fetchone():
                raise ValueError('Not an OpenPlayout backup')
        if target.exists():
            with closing(sqlite3.connect(target, timeout=0)) as db:
                db.execute('BEGIN EXCLUSIVE')
                # Holding another application connection usually keeps these sidecars alive.
                db.rollback()
            if any(Path(str(target)+suffix).exists() for suffix in ('-wal','-shm')):
                raise ValueError('Stop OpenPlayout and close database connections before restoring')
            saved = data_dir / ('before-restore-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f')+'.sqlite')
            target.replace(saved)
        staging.replace(target)
    finally:
        if staging.exists():
            staging.unlink()
    return target


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('archive',type=Path)
    parser.add_argument('--data-dir',type=Path,required=True)
    parser.add_argument('--confirm-stopped',action='store_true',required=True)
    args=parser.parse_args()
    print(restore(args.archive,args.data_dir))
