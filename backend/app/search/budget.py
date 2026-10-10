"""Atomic, process-shared monthly SerpApi credit reservation.

Reservation happens BEFORE request dispatch and is never refunded: even failed
provider attempts may be billable. Set a conservative limit below plan quota.
This does not protect clients bypassing this service, nor cover external API usage.
"""
from __future__ import annotations
from datetime import datetime, timezone
from pathlib import Path
import sqlite3
from contextlib import closing


class SharedCreditLedger:
    def __init__(self, path: Path, *, monthly_limit: int = 200):
        if not 1 <= monthly_limit <= 250:
            raise ValueError('INVALID_MONTHLY_CREDIT_LIMIT')
        self.path = Path(path)
        self.monthly_limit = monthly_limit
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.path, timeout=10)) as db:
            db.execute('CREATE TABLE IF NOT EXISTS credits (month TEXT PRIMARY KEY, used INTEGER NOT NULL)')
            db.commit()

    def reserve(self) -> bool:
        month = datetime.now(timezone.utc).strftime('%Y-%m')
        with closing(sqlite3.connect(self.path, timeout=10, isolation_level=None)) as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT used FROM credits WHERE month=?', (month,)).fetchone()
            used = row[0] if row else 0
            if used >= self.monthly_limit:
                db.execute('COMMIT')
                return False
            db.execute('INSERT INTO credits(month, used) VALUES(?, 1) '
                       'ON CONFLICT(month) DO UPDATE SET used=used+1', (month,))
            db.execute('COMMIT')
            return True

    def used(self) -> int:
        month = datetime.now(timezone.utc).strftime('%Y-%m')
        with closing(sqlite3.connect(self.path, timeout=10)) as db:
            row = db.execute('SELECT used FROM credits WHERE month=?', (month,)).fetchone()
        return row[0] if row else 0
