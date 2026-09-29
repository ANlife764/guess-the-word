import sqlite3
import pytest
from app import create_app, score, validate_password, validate_username


@pytest.fixture
def app(tmp_path):
    return create_app({"TESTING": True, "DATABASE": str(tmp_path / "t.db")})


def signup(c, u="Player", p="pass$1"):
    c.post("/register", data={"username": u, "password": p})
    return c.post("/login", data={"username": u, "password": p})


def force_word(app, word):
    db = sqlite3.connect(app.config["DATABASE"])
    wid = db.execute("SELECT id FROM words WHERE word=?", (word,)).fetchone()[0]
    db.execute("UPDATE games SET word_id=? WHERE status='active'", (wid,))
    db.commit(); db.close()


def test_twenty_words_seeded(app):
    db = sqlite3.connect(app.config["DATABASE"])
    assert db.execute("SELECT COUNT(*) FROM words").fetchone()[0] == 20


@pytest.mark.parametrize("u,ok", [("abcd", False), ("abcde", True), ("ab1de", False), ("AbCdEf", True)])
def test_username_rules(u, ok):
    assert (validate_username(u) is None) == ok


@pytest.mark.parametrize("p,ok", [("ab$1", False), ("abcde$", False), ("abcde1", False),
                                  ("12345$", False), ("abc1$", True), ("abc1%", True), ("abc1*", True)])
def test_password_rules(p, ok):
    assert (validate_password(p) is None) == ok


def test_score_colours():
    assert score("HOMER", "TOWER") == ["X", "G", "X", "G", "G"]
    assert score("AUDIO", "TOWER") == ["X", "X", "X", "X", "O"]
    assert score("SPEED", "ABIDE") == ["X", "X", "O", "X", "O"]  # duplicate letters


def test_win_flow(app):
    c = app.test_client(); signup(c)
    assert c.post("/api/game/guess", json={"guess": "HELLO"}).status_code == 400  # no game
    c.post("/api/game/start"); force_word(app, "TOWER")
    assert c.post("/api/game/guess", json={"guess": "tower"}).status_code == 400  # upper case only
    assert c.post("/api/game/guess", json={"guess": "ABC"}).status_code == 400
    r = c.post("/api/game/guess", json={"guess": "HOMER"}).get_json()
    assert r["status"] == "active" and r["word"] is None
    r = c.post("/api/game/guess", json={"guess": "TOWER"}).get_json()
    assert r["status"] == "won" and len(r["guesses"]) == 2


def test_lose_after_five_and_daily_cap(app):
    c = app.test_client(); signup(c)
    for _ in range(3):
        c.post("/api/game/start"); force_word(app, "TOWER")
        for _ in range(5):
            r = c.post("/api/game/guess", json={"guess": "AUDIO"}).get_json()
        assert r["status"] == "lost" and r["word"] == "TOWER"
    assert c.post("/api/game/start").status_code == 400  # 4th word blocked


def test_admin_reports_and_access(app):
    p = app.test_client(); signup(p)
    p.post("/api/game/start"); force_word(app, "TOWER")
    p.post("/api/game/guess", json={"guess": "TOWER"})
    assert p.get("/admin").status_code == 302  # player cannot see admin
    a = app.test_client()
    a.post("/login", data={"username": "admin", "password": "Admin$123"})
    page = a.get("/admin?username=Player").get_data(as_text=True)
    assert "<b>1</b>" in page and "Player" in page
    assert a.get("/api/game").status_code == 403


def test_duplicate_username_case_insensitive(app):
    c = app.test_client(); signup(c, "Player")
    r = c.post("/register", data={"username": "PLAYER", "password": "pass$1"}, follow_redirects=True)
    assert b"already registered" in r.data
    # Only one row exists for the name, no matter how many times registration is retried.
    db = sqlite3.connect(app.config["DATABASE"])
    assert db.execute("SELECT COUNT(*) FROM users WHERE username='Player'").fetchone()[0] == 1


def test_repeated_registration_attempts_never_create_duplicates(app):
    """Simulates a double form-submit: same username posted twice in a row."""
    c = app.test_client()
    r1 = c.post("/register", data={"username": "Racer", "password": "pass$1"})
    r2 = c.post("/register", data={"username": "Racer", "password": "pass$1"})
    assert r1.status_code in (200, 302) and r2.status_code == 302  # both handled, no crash
    db = sqlite3.connect(app.config["DATABASE"])
    assert db.execute("SELECT COUNT(*) FROM users WHERE username='Racer'").fetchone()[0] == 1


def test_dictionary_check_rejects_non_words_without_using_a_guess(app):
    c = app.test_client(); signup(c)
    c.post("/api/game/start"); force_word(app, "TOWER")
    r = c.post("/api/game/guess", json={"guess": "ZZZZZ"})
    assert r.status_code == 400 and b"not in the word list" in r.data
    assert len(c.get("/api/game").get_json()["game"]["guesses"]) == 0  # not counted
    assert c.post("/api/game/guess", json={"guess": "HOUSE"}).status_code == 200
