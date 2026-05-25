import logging
import os
import sqlite3

from flask import Flask, render_template, request

logger = logging.getLogger(__name__)

app = Flask(__name__)

# Secret read from the environment, never committed to source.
API_KEY = os.environ["SEARCH_API_KEY"]


def get_db():
    conn = sqlite3.connect("app.db")
    conn.row_factory = sqlite3.Row
    return conn


@app.route("/users")
def list_users():
    name = request.args.get("name", "")
    db = get_db()
    try:
        # Parameterized query (no injection) and a single JOIN + GROUP BY
        # instead of a per-user query (no N+1).
        rows = db.execute(
            """
            SELECT u.id, u.name, COUNT(o.id) AS order_count
            FROM users u
            LEFT JOIN orders o ON o.user_id = u.id
            WHERE u.name LIKE ?
            GROUP BY u.id, u.name
            """,
            (f"%{name}%",),
        ).fetchall()
    except sqlite3.DatabaseError:
        logger.exception("failed to list users")
        return render_template("index.html", users=[]), 500
    finally:
        db.close()

    users = [{"name": r["name"], "orders": r["order_count"]} for r in rows]
    return render_template("index.html", users=users)
