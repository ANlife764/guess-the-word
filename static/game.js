const $ = id => document.getElementById(id);
const grid = $("grid"), form = $("guessForm"), input = $("guess"), startBtn = $("startBtn");
const MAX = 5;

async function api(url, method = "GET", body) {
  const r = await fetch(url, {method, headers: {"Content-Type": "application/json"},
                              body: body ? JSON.stringify(body) : undefined});
  const d = await r.json();
  if (!r.ok) throw new Error(d.error || "Something went wrong.");
  return d;
}
function showError(m) { $("error").textContent = m || ""; $("error").hidden = !m; }
function drawGrid(guesses) {
  grid.innerHTML = "";
  for (let r = 0; r < MAX; r++) for (let c = 0; c < 5; c++) {
    const t = document.createElement("div"), g = guesses[r];
    t.className = "tile" + (g ? " " + g.result[c] : "");
    t.textContent = g ? g.letters[c] : "";
    grid.appendChild(t);
  }
}
function render(s) {
  const active = s.game && s.game.status === "active";
  $("info").textContent = `Words played today: ${s.games_today}/${s.max_games}`;
  drawGrid(active ? s.game.guesses : []);
  form.hidden = !active;
  startBtn.hidden = active || s.games_today >= s.max_games;
  if (!active && s.games_today >= s.max_games) showError("Daily limit reached. Come back tomorrow!");
  if (active) input.focus();
}
async function load() { try { render(await api("/api/game")); } catch (e) { showError(e.message); } }

startBtn.onclick = async () => { showError(); try { render(await api("/api/game/start", "POST")); } catch (e) { showError(e.message); } };
input.oninput = () => input.value = input.value.toUpperCase().replace(/[^A-Z]/g, "");
form.onsubmit = async ev => {
  ev.preventDefault(); showError();
  try {
    const d = await api("/api/game/guess", "POST", {guess: input.value});
    input.value = ""; drawGrid(d.guesses);
    if (d.status !== "active") {
      $("modalText").textContent = d.status === "won"
        ? "Congratulations! You guessed the word!"
        : `Better luck next time! The word was ${d.word}.`;
      $("modal").hidden = false; form.hidden = true;
    }
  } catch (e) { showError(e.message); }
};
$("okBtn").onclick = () => { $("modal").hidden = true; load(); };
load();
