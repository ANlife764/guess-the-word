# Guess the Word

A Wordle-style game built with **Python, Flask and SQLite**.

## Features
- Register / log in (username: 5+ letters; password: 5+ chars with a letter, a digit and one of `$ % *`)
- 20 five-letter words seeded in the database; a random one is chosen per game
- Max 3 words per user per day, max 5 guesses per word, upper-case guesses only
- Guesses must be real English words (checked against `data/valid_words.txt`, ~15k five-letter words); invalid words are rejected without using up a guess
- Green = right letter/right spot, orange = right letter/wrong spot, grey = not in word
- Win / lose messages with an OK button; earlier guesses stay on the board (unfinished games survive refresh)
- Words given and guesses made are saved with the date
- Admin reports: per-day (users, correct guesses) and per-user (date, words tried, correct guesses)

## Run
```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python app.py            # open http://127.0.0.1:5000
```
Default admin (created on first run): `admin` / `Admin$123`. Players register from the UI.
Set `SECRET_KEY` in the environment for any real deployment.

## Test
```bash
pytest -v
```

## Database tables
`users`, `words`, `games` (user, word, date, status), `guesses` (game, guess text, time).
