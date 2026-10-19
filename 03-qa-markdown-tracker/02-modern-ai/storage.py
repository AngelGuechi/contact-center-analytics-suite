"""Local demo storage. Shared deployment requires a separate authenticated service."""
import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo


class Store:
    def __init__(self,path):
        Path(path).parent.mkdir(parents=True,exist_ok=True)
        self.path=str(path)
        with self.connect() as db:
            db.executescript('''
            CREATE TABLE IF NOT EXISTS snapshot (id INTEGER PRIMARY KEY CHECK(id=1), data TEXT);
            CREATE TABLE IF NOT EXISTS coaching (id TEXT PRIMARY KEY, data TEXT);
            CREATE TABLE IF NOT EXISTS drafts (id TEXT PRIMARY KEY, data TEXT);
            CREATE TABLE IF NOT EXISTS usage (id TEXT PRIMARY KEY, month TEXT, model TEXT, cost REAL, state TEXT);
            ''')

    @contextmanager
    def connect(self):
        db=sqlite3.connect(self.path,timeout=15)
        try:
            with db:
                yield db
        finally:
            db.close()

    def publish(self,data):
        with self.connect() as db:
            db.execute('INSERT OR REPLACE INTO snapshot VALUES(1,?)',(json.dumps(data,ensure_ascii=False),))

    def snapshot(self):
        with self.connect() as db:
            row=db.execute('SELECT data FROM snapshot WHERE id=1').fetchone()
        return json.loads(row[0]) if row else None

    def save_coaching(self,entry):
        if not entry['action'].strip():
            raise ValueError('Enter the agreed action.')
        if entry['follow_up'] and entry['follow_up'] < entry['date']:
            raise ValueError('Follow-up must be on or after the coaching date.')
        with self.connect() as db:
            db.execute('INSERT INTO coaching VALUES(?,?)',(uuid.uuid4().hex,json.dumps(entry,ensure_ascii=False)))

    def coaching(self):
        with self.connect() as db:
            return [json.loads(r[0]) for r in db.execute('SELECT data FROM coaching')]

    def cached(self,ident):
        with self.connect() as db:
            row=db.execute('SELECT data FROM drafts WHERE id=?',(ident,)).fetchone()
        return json.loads(row[0]) if row else None

    def cache(self,ident,draft):
        with self.connect() as db:
            db.execute('INSERT OR REPLACE INTO drafts VALUES(?,?)',(ident,json.dumps(draft,ensure_ascii=False)))

    @staticmethod
    def month():
        return datetime.now(ZoneInfo('America/Mexico_City')).strftime('%Y-%m')

    def spend(self):
        with self.connect() as db:
            return db.execute('SELECT COALESCE(SUM(cost),0) FROM usage WHERE month=?',(self.month(),)).fetchone()[0]

    def reserve(self,model,amount,budget):
        ident=uuid.uuid4().hex
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            spent=db.execute('SELECT COALESCE(SUM(cost),0) FROM usage WHERE month=?',(self.month(),)).fetchone()[0]
            if spent+amount > budget:
                raise ValueError('The monthly AI budget would be exceeded. Adjust the budget or use the rule-based guidance.')
            db.execute('INSERT INTO usage VALUES(?,?,?,?,?)',(ident,self.month(),model,amount,'Reserved'))
        return ident

    def settle(self,ident,amount,state):
        with self.connect() as db:
            db.execute('UPDATE usage SET cost=?,state=? WHERE id=?',(amount,state,ident))

    def ledger(self):
        with self.connect() as db:
            return [dict(zip(['Request','Month','Model','USD','State'],r)) for r in db.execute('SELECT * FROM usage ORDER BY rowid DESC')]
