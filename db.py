"""
データベース初期化 — 仮想投資シミュレーター専用
実際の証券口座接続・実注文は一切行いません
"""
import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'portfolio.db')
INITIAL_CASH = 10_000_000


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_connection()
    c = conn.cursor()

    c.execute('''CREATE TABLE IF NOT EXISTS cash (
        id INTEGER PRIMARY KEY,
        balance REAL NOT NULL
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS holdings (
        ticker TEXT PRIMARY KEY,
        company_name TEXT,
        shares INTEGER NOT NULL,
        avg_buy_price REAL NOT NULL
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS transactions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        datetime TEXT NOT NULL,
        type TEXT NOT NULL,
        ticker TEXT NOT NULL,
        company_name TEXT,
        shares INTEGER NOT NULL,
        price REAL NOT NULL,
        total REAL NOT NULL,
        reason TEXT
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS candidates (
        ticker TEXT PRIMARY KEY,
        company_name TEXT NOT NULL,
        sector TEXT,
        score INTEGER,
        reason TEXT,
        added_date TEXT
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS performance_history (
        date TEXT PRIMARY KEY,
        value REAL NOT NULL
    )''')

    # マイグレーション（古いDBへの列追加）
    for sql in [
        "ALTER TABLE transactions ADD COLUMN reason TEXT",
    ]:
        try:
            c.execute(sql)
        except Exception:
            pass

    if not c.execute('SELECT id FROM cash').fetchone():
        c.execute('INSERT INTO cash VALUES (1, ?)', (INITIAL_CASH,))

    conn.commit()
    conn.close()
