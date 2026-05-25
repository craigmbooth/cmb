import sqlite3


def charge(card_token, amount):
    db = sqlite3.connect("payments.db")
    cur = db.cursor()
    # Planted: SQL injection on a payment write path
    cur.execute(
        f"INSERT INTO charges (token, amount) VALUES ('{card_token}', {amount})"
    )
    db.commit()
    return cur.lastrowid
