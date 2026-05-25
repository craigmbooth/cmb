import os
import sqlite3
import subprocess

from flask import Flask, request, render_template

# Fixed since the last audit: the secret is now read from the environment
# (previously hardcoded in source).
API_KEY = os.environ["API_KEY"]

app = Flask(__name__)


def get_db():
    return sqlite3.connect("app.db")


@app.route("/users")
def list_users():
    name = request.args.get("name", "")
    db = get_db()
    cur = db.cursor()
    # Planted: SQL injection — user input interpolated directly into the query
    cur.execute(f"SELECT id, name FROM users WHERE name LIKE '%{name}%'")
    users = cur.fetchall()

    # Planted: N+1 — one extra query per user inside the loop
    result = []
    for user in users:
        order_cur = db.cursor()
        order_cur.execute(f"SELECT COUNT(*) FROM orders WHERE user_id = {user[0]}")
        count = order_cur.fetchone()[0]
        result.append({"name": user[1], "orders": count})

    return render_template("index.html", users=result)


@app.route("/ping")
def ping():
    host = request.args.get("host", "localhost")
    try:
        # Planted: command injection via shell=True with user input
        out = subprocess.check_output(f"ping -c 1 {host}", shell=True)
        return out
    except:  # Planted: bare except silently swallows all errors
        pass
    return "ok"


if __name__ == "__main__":
    # Planted: debug server enabled in the entrypoint
    app.run(debug=True)
