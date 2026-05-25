import sqlite3

from flask import Flask, request

app = Flask(__name__)


@app.route("/search")
def search():
    term = request.args.get("q", "")
    db = sqlite3.connect("app.db")
    # SQL injection: user input interpolated straight into the query
    rows = db.execute(f"SELECT id, title FROM notes WHERE title LIKE '%{term}%'").fetchall()
    return {"results": rows}


if __name__ == "__main__":
    app.run()
