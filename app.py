"""Guess the Word - a Wordle-style game (Flask + SQLite)."""
import os
import random
import re
import sqlite3
from datetime import date
from functools import wraps

from flask import (Flask, flash, g, jsonify, redirect, render_template,
                   request, session, url_for)
from werkzeug.security import check_password_hash, generate_password_hash

WORDS = ("TOWER HOUSE PLANT RIVER CLOUD BREAD STONE LIGHT MUSIC TABLE "
         "CHAIR WATER EARTH FLAME GRASS OCEAN SMILE DREAM BEACH TRAIN").split()
DICTIONARY_FILE = os.path.join(os.path.dirname(__file__), "data", "valid_words.txt")
with open(DICTIONARY_FILE) as _f:
    VALID_WORDS = {line.strip().upper() for line in _f if line.strip()}
MAX_GUESSES = 5
MAX_GAMES_PER_DAY = 3
SCHEMA = """
CREATE TABLE IF NOT EXISTS users(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  username TEXT NOT NULL UNIQUE COLLATE NOCASE,
  password_hash TEXT NOT NULL,
  role TEXT NOT NULL CHECK(role IN ('admin','player')));
CREATE TABLE IF NOT EXISTS words(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  word TEXT NOT NULL UNIQUE);
CREATE TABLE IF NOT EXISTS games(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL REFERENCES users(id),
  word_id INTEGER NOT NULL REFERENCES words(id),
  play_date TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','won','lost')),
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS guesses(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  game_id INTEGER NOT NULL REFERENCES games(id),
  guess TEXT NOT NULL,
  guessed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
"""


# ---------- pure helpers (easy to unit test) ----------
def validate_username(u):
    if not re.fullmatch(r"[A-Za-z]{5,}", u or ""):
        return "Username must be at least 5 letters (A-Z, a-z only)."


def validate_password(p):
    p = p or ""
    if (len(p) < 5 or not re.search(r"[A-Za-z]", p)
            or not re.search(r"\d", p) or not re.search(r"[$%*]", p)):
        return ("Password must be at least 5 characters with a letter, "
                "a digit and one of $ % *.")


def score(guess, word):
    """Return per-letter result: G (green), O (orange), X (grey)."""
    result, remaining = ["X"] * 5, {}
    for i in range(5):
        if guess[i] == word[i]:
            result[i] = "G"
        else:
            remaining[word[i]] = remaining.get(word[i], 0) + 1
    for i in range(5):
        if result[i] != "G" and remaining.get(guess[i], 0) > 0:
            result[i] = "O"
            remaining[guess[i]] -= 1
    return result


# ---------- app factory ----------
def create_app(config=None):
    app = Flask(__name__)
    app.config.update(
        SECRET_KEY=os.environ.get("SECRET_KEY", "dev-only-change-me"),
        DATABASE=os.path.join(app.instance_path, "game.db"))
    if config:
        app.config.update(config)
    os.makedirs(app.instance_path, exist_ok=True)

    def get_db():
        if "db" not in g:
            g.db = sqlite3.connect(app.config["DATABASE"])
            g.db.row_factory = sqlite3.Row
        return g.db

    @app.teardown_appcontext
    def close_db(_):
        db = g.pop("db", None)
        if db:
            db.close()

    def init_db():
        db = sqlite3.connect(app.config["DATABASE"])
        db.executescript(SCHEMA)
        if not db.execute("SELECT 1 FROM words").fetchone():
            db.executemany("INSERT INTO words(word) VALUES(?)", [(w,) for w in WORDS])
        if not db.execute("SELECT 1 FROM users WHERE role='admin'").fetchone():
            db.execute("INSERT INTO users(username,password_hash,role) VALUES(?,?,'admin')",
                       ("admin", generate_password_hash("Admin$123")))
        db.commit()
        db.close()

    init_db()

    # ----- auth helpers -----
    def login_required(role=None):
        def deco(fn):
            @wraps(fn)
            def wrapper(*a, **kw):
                if "user_id" not in session:
                    if request.path.startswith("/api/"):
                        return jsonify(error="Please log in."), 401
                    return redirect(url_for("login"))
                if role and session.get("role") != role:
                    if request.path.startswith("/api/"):
                        return jsonify(error="Not allowed."), 403
                    return redirect(url_for("home"))
                return fn(*a, **kw)
            return wrapper
        return deco

    @app.route("/")
    def home():
        if "user_id" not in session:
            return redirect(url_for("login"))
        return redirect(url_for("admin" if session["role"] == "admin" else "play"))

    @app.route("/register", methods=["GET", "POST"])
    def register():
        if request.method == "POST":
            u = request.form.get("username", "").strip()
            p = request.form.get("password", "")
            error = validate_username(u) or validate_password(p)
            if not error:
                db = get_db()
                existing = db.execute(
                    "SELECT 1 FROM users WHERE username=? COLLATE NOCASE", (u,)).fetchone()
                if existing:
                    error = (f"'{u}' is already registered (usernames are not case-sensitive). "
                             "Try logging in, or pick a different username.")
                else:
                    try:
                        db.execute(
                            "INSERT INTO users(username,password_hash,role) VALUES(?,?,'player')",
                            (u, generate_password_hash(p)))
                        db.commit()
                        flash("Registered. Please log in.", "ok")
                        return redirect(url_for("login"))
                    except sqlite3.IntegrityError:
                        db.rollback()
                        error = (f"'{u}' is already registered. Try logging in, or pick a "
                                 "different username.")
            flash(error, "error")
            return redirect(url_for("register"))
        return render_template("register.html")

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if request.method == "POST":
            row = get_db().execute("SELECT * FROM users WHERE username=?",
                                   (request.form.get("username", "").strip(),)).fetchone()
            if row and check_password_hash(row["password_hash"], request.form.get("password", "")):
                session.clear()
                session.update(user_id=row["id"], username=row["username"], role=row["role"])
                return redirect(url_for("home"))
            flash("Invalid username or password.", "error")
        return render_template("login.html")

    @app.route("/logout")
    def logout():
        session.clear()
        return redirect(url_for("login"))

    # ----- game -----
    @app.route("/play")
    @login_required("player")
    def play():
        return render_template("play.html")

    def games_today(uid):
        return get_db().execute(
            "SELECT COUNT(*) FROM games WHERE user_id=? AND play_date=?",
            (uid, date.today().isoformat())).fetchone()[0]

    def active_game(uid):
        return get_db().execute(
            "SELECT g.id, w.word FROM games g JOIN words w ON w.id=g.word_id "
            "WHERE g.user_id=? AND g.status='active'", (uid,)).fetchone()

    def state(uid):
        db = get_db()
        game = db.execute(
            "SELECT g.id, g.status, w.word FROM games g JOIN words w ON w.id=g.word_id "
            "WHERE g.user_id=? ORDER BY g.id DESC LIMIT 1", (uid,)).fetchone()
        used = games_today(uid)
        out = {"game": None, "games_today": used, "max_games": MAX_GAMES_PER_DAY,
               "max_guesses": MAX_GUESSES}
        if game and game["status"] == "active":
            rows = db.execute("SELECT guess FROM guesses WHERE game_id=? ORDER BY id",
                              (game["id"],)).fetchall()
            out["game"] = {"status": "active",
                           "guesses": [{"letters": r["guess"],
                                        "result": score(r["guess"], game["word"])}
                                       for r in rows]}
        return out

    @app.get("/api/game")
    @login_required("player")
    def api_game():
        return jsonify(state(session["user_id"]))

    @app.post("/api/game/start")
    @login_required("player")
    def api_start():
        uid, db = session["user_id"], get_db()
        if active_game(uid):
            return jsonify(state(uid))
        if games_today(uid) >= MAX_GAMES_PER_DAY:
            return jsonify(error="Daily limit of 3 words reached. Come back tomorrow!"), 400
        word = random.choice(db.execute("SELECT id FROM words").fetchall())
        db.execute("INSERT INTO games(user_id,word_id,play_date) VALUES(?,?,?)",
                   (uid, word["id"], date.today().isoformat()))
        db.commit()
        return jsonify(state(uid))

    @app.post("/api/game/guess")
    @login_required("player")
    def api_guess():
        uid, db = session["user_id"], get_db()
        game = active_game(uid)
        if not game:
            return jsonify(error="No active game. Start a new word."), 400
        guess = (request.get_json(silent=True) or {}).get("guess", "")
        if not re.fullmatch(r"[A-Z]{5}", guess):
            return jsonify(error="Enter exactly 5 letters (A-Z, upper case)."), 400
        if guess not in VALID_WORDS:
            return jsonify(error=f"{guess} is not in the word list. Try another word."), 400
        db.execute("INSERT INTO guesses(game_id,guess) VALUES(?,?)", (game["id"], guess))
        count = db.execute("SELECT COUNT(*) FROM guesses WHERE game_id=?",
                           (game["id"],)).fetchone()[0]
        status = "won" if guess == game["word"] else ("lost" if count >= MAX_GUESSES else "active")
        db.execute("UPDATE games SET status=? WHERE id=?", (status, game["id"]))
        db.commit()
        rows = db.execute("SELECT guess FROM guesses WHERE game_id=? ORDER BY id",
                          (game["id"],)).fetchall()
        return jsonify(status=status,
                       guesses=[{"letters": r["guess"], "result": score(r["guess"], game["word"])}
                                for r in rows],
                       word=game["word"] if status != "active" else None)

    # ----- admin reports -----
    @app.route("/admin")
    @login_required("admin")
    def admin():
        db = get_db()
        day = request.args.get("date") or date.today().isoformat()
        daily = db.execute(
            "SELECT COUNT(DISTINCT user_id) AS users, COALESCE(SUM(status='won'),0) AS correct "
            "FROM games WHERE play_date=?", (day,)).fetchone()
        players = [r["username"] for r in db.execute(
            "SELECT username FROM users WHERE role='player' ORDER BY username")]
        username = request.args.get("username") or (players[0] if players else "")
        per_user = db.execute(
            "SELECT play_date, COUNT(*) AS tried, SUM(status='won') AS correct FROM games g "
            "JOIN users u ON u.id=g.user_id WHERE u.username=? GROUP BY play_date "
            "ORDER BY play_date", (username,)).fetchall()
        return render_template("admin.html", day=day, daily=daily, players=players,
                               username=username, per_user=per_user)

    return app


if __name__ == "__main__":
    create_app().run(debug=True)
