"""BK's Bets - daily odds scan. Writes docs/index.html (served by GitHub Pages)."""

import os
import json
import datetime
import requests

API_KEY = os.environ.get("ODDS_API_KEY", "").strip()

LEAGUES = [
    ("soccer_epl", "Premier League"),
    ("soccer_efl_champ", "Championship"),
    ("soccer_spain_la_liga", "La Liga"),
    ("soccer_italy_serie_a", "Serie A"),
    ("soccer_germany_bundesliga", "Bundesliga"),
    ("soccer_france_ligue_one", "Ligue 1"),
    ("soccer_netherlands_eredivisie", "Eredivisie"),
    ("soccer_portugal_primeira_liga", "Primeira Liga"),
    ("soccer_turkey_super_league", "Super Lig"),
    ("soccer_usa_mls", "MLS"),
    ("soccer_uefa_champs_league", "Champions League"),
    ("soccer_uefa_europa_league", "Europa League"),
    ("soccer_uefa_europa_conference_league", "Conference League"),
]

BASE = "https://api.the-odds-api.com/v4/sports/{sport}/odds/"


def fetch(sport_key):
    """Returns (events, error_text). One credit per call (1 region, 1 market)."""
    try:
        r = requests.get(
            BASE.format(sport=sport_key),
            params={"apiKey": API_KEY, "regions": "uk", "markets": "h2h",
                    "oddsFormat": "decimal", "dateFormat": "iso"},
            timeout=25,
        )
    except requests.RequestException as e:
        return [], "network: " + str(e)[:80]
    if r.status_code == 200:
        return r.json(), None
    return [], "HTTP %d %s" % (r.status_code, r.text[:80].replace("\n", " "))


def consensus(event):
    """Average of bookmaker-margin-free probabilities. Returns dict or None."""
    home, away = event.get("home_team"), event.get("away_team")
    sums = {"h": 0.0, "d": 0.0, "a": 0.0}
    n = 0
    for bm in event.get("bookmakers", []):
        for m in bm.get("markets", []):
            if m.get("key") != "h2h":
                continue
            px = {o["name"]: o["price"] for o in m.get("outcomes", [])}
            if home in px and away in px and "Draw" in px:
                inv = {"h": 1 / px[home], "d": 1 / px["Draw"], "a": 1 / px[away]}
                tot = sum(inv.values())
                for k in sums:
                    sums[k] += inv[k] / tot
                n += 1
    if n == 0:
        return None
    return {k: round(v / n, 4) for k, v in sums.items()}


def scan():
    now = datetime.datetime.now(datetime.timezone.utc)
    limit = now + datetime.timedelta(hours=60)
    fixtures, errors = [], []
    for key, name in LEAGUES:
        events, err = fetch(key)
        if err:
            errors.append("%s (%s)" % (name, err))
            continue
        for ev in events:
            try:
                t = datetime.datetime.fromisoformat(ev["commence_time"].replace("Z", "+00:00"))
            except (KeyError, ValueError):
                continue
            if t < now - datetime.timedelta(hours=3) or t > limit:
                continue
            p = consensus(ev)
            if not p:
                continue
            fixtures.append({"lg": name, "h": ev["home_team"], "a": ev["away_team"],
                             "t": ev["commence_time"], "p": p})
    fixtures.sort(key=lambda f: f["t"])
    return fixtures, errors


TEMPLATE = r"""<!DOCTYPE html>
<html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-title" content="BK's Bets">
<meta name="theme-color" content="#0a0a0a">
<title>BK's Bets</title>
<style>
:root{--bg:#0a0a0a;--card:#161616;--line:#2a2a2a;--text:#f5f5f5;--dim:#8f8f94;--acc:#fff}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--text);font:16px/1.4 -apple-system,BlinkMacSystemFont,"Helvetica Neue",Arial,sans-serif;padding:env(safe-area-inset-top) 16px 40px}
.wrap{max-width:560px;margin:0 auto}
header{padding:22px 0 10px}
h1{margin:0;font-size:26px;letter-spacing:-.5px}
.sub{color:var(--dim);font-size:13px;margin-top:2px}
.panel{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:14px;margin:14px 0}
.row{display:flex;gap:10px}
.row>div{flex:1}
label{display:block;font-size:12px;color:var(--dim);margin-bottom:5px;text-transform:uppercase;letter-spacing:.6px}
select{width:100%;background:#0f0f0f;color:var(--text);border:1px solid var(--line);border-radius:10px;padding:12px;font-size:16px;appearance:none}
button{width:100%;margin-top:12px;background:var(--acc);color:#000;border:0;border-radius:10px;padding:14px;font-size:16px;font-weight:700}
button.ghost{background:transparent;color:var(--text);border:1px solid var(--line);margin-top:8px}
.bet h2{margin:0 0 4px;font-size:18px}
.leg{display:flex;justify-content:space-between;gap:10px;padding:10px 0;border-top:1px solid var(--line)}
.leg b{display:block}
.leg small{color:var(--dim)}
.pct{font-weight:700;white-space:nowrap}
.sum{display:flex;justify-content:space-between;padding-top:12px;border-top:1px solid var(--line);font-weight:700}
.note{color:var(--dim);font-size:12px;margin-top:8px}
h3{margin:24px 0 6px;font-size:13px;text-transform:uppercase;letter-spacing:.8px;color:var(--dim)}
.fx{display:flex;justify-content:space-between;gap:10px;padding:10px 0;border-top:1px solid var(--line);font-size:15px}
.fx.off{opacity:.4}
.empty{color:var(--dim);padding:10px 0}
.err{color:var(--dim);font-size:12px;margin-top:20px}
footer{color:var(--dim);font-size:12px;text-align:center;margin-top:30px}
</style></head><body><div class="wrap">
<header><h1>BK's Bets</h1><div class="sub">Updated %%GENERATED%%</div></header>

<div class="panel">
  <div class="row">
    <div><label>Bet size</label><select id="fold"></select></div>
    <div><label>Games</label><select id="scope"><option value="today">Today</option><option value="tomorrow">Tomorrow</option><option value="all">Today + Tomorrow</option></select></div>
  </div>
  <button id="build">Build bet</button>
  <button class="ghost" id="again" style="display:none">Build a different one</button>
</div>

<div id="result"></div>

<h3>Today</h3><div id="today"></div>
<h3>Tomorrow</h3><div id="tomorrow"></div>
%%ERRORS%%
<footer>Odds-based estimates, not guarantees. Every leg must win. Not financial advice. 18+ Bet responsibly.</footer>
</div>
<script type="application/json" id="data">%%DATA%%</script>
<script>
(function(){
var FX = JSON.parse(document.getElementById('data').textContent);
var el = function(i){return document.getElementById(i)};
var names = {2:'Double',3:'Treble',4:'4-fold',5:'5-fold'};
var fold = el('fold');
for (var n=2;n<=20;n++){var o=document.createElement('option');o.value=n;o.textContent=n+'-fold'+(names[n]&&n<4?' ('+names[n]+')':'');fold.appendChild(o);}
fold.value=3;

function esc(s){return String(s).replace(/[&<>]/g,function(c){return {'&':'&amp;','<':'&lt;','>':'&gt;'}[c]});}
function dayKey(d){return d.getFullYear()+'-'+d.getMonth()+'-'+d.getDate();}
function bucket(t){
  var now=new Date(), d=new Date(t), tm=new Date(now.getTime()+86400000);
  if(dayKey(d)===dayKey(now))return 'today';
  if(dayKey(d)===dayKey(tm))return 'tomorrow';
  return null;
}
function tm(t){return new Date(t).toLocaleTimeString([], {hour:'2-digit',minute:'2-digit'});}
function started(f){return new Date(f.t).getTime()<=Date.now();}
function pick(f){
  var p=f.p, best='h', team=f.h;
  if(p.a>p[best]){best='a';team=f.a;}
  return {team:team, prob:p[best]};
}
function list(day){
  var rows=FX.filter(function(f){return bucket(f.t)===day;});
  if(!rows.length)return '<div class="empty">No games found.</div>';
  return rows.map(function(f){
    var k=pick(f);
    return '<div class="fx'+(started(f)?' off':'')+'"><span>'+esc(f.h)+' v '+esc(f.a)+'<br><small style="color:#8f8f94">'+esc(f.lg)+' &middot; '+tm(f.t)+'</small></span><span class="pct">'+esc(k.team)+' '+Math.round(k.prob*100)+'%</span></div>';
  }).join('');
}
el('today').innerHTML=list('today');
el('tomorrow').innerHTML=list('tomorrow');

var lastIds=null;
function build(shuffle){
  var scope=el('scope').value, n=parseInt(fold.value,10);
  var pool=FX.filter(function(f){
    if(started(f))return false;
    var b=bucket(f.t);
    return scope==='all'?!!b:b===scope;
  }).map(function(f){var k=pick(f);return {f:f,team:k.team,prob:k.prob};});
  pool.sort(function(a,b){return b.prob-a.prob;});
  var res=el('result');
  if(pool.length<n){
    res.innerHTML='<div class="panel">Only '+pool.length+' game'+(pool.length===1?'':'s')+' left to bet on. Pick a smaller bet size'+(scope!=='all'?' or choose Today + Tomorrow':'')+'.</div>';
    el('again').style.display='none';return;
  }
  var legs;
  if(shuffle){
    var wide=pool.slice(0,Math.min(pool.length,n+Math.max(3,n)));
    for(var i=wide.length-1;i>0;i--){var j=Math.floor(Math.random()*(i+1));var t=wide[i];wide[i]=wide[j];wide[j]=t;}
    legs=wide.slice(0,n);
  } else legs=pool.slice(0,n);
  legs.sort(function(a,b){return new Date(a.f.t)-new Date(b.f.t);});
  var comb=legs.reduce(function(a,l){return a*l.prob;},1);
  var html='<div class="panel bet"><h2>'+n+'-fold</h2>'+legs.map(function(l){
    return '<div class="leg"><span><b>'+esc(l.team)+' to win</b><small>'+esc(l.f.h)+' v '+esc(l.f.a)+' &middot; '+esc(l.f.lg)+' &middot; '+tm(l.f.t)+'</small></span><span class="pct">'+Math.round(l.prob*100)+'%</span></div>';
  }).join('')+'<div class="sum"><span>Chance all '+n+' win</span><span>'+(comb>=0.1?Math.round(comb*100):(comb*100).toFixed(1))+'%</span></div><div class="note">Built from games that have not kicked off. Every leg must win.</div></div>';
  res.innerHTML=html;
  el('again').style.display='block';
}
el('build').onclick=function(){build(false);};
el('again').onclick=function(){build(true);};
})();
</script></body></html>
"""


def render(fixtures, errors):
    gen = datetime.datetime.now(datetime.timezone.utc).strftime("%a %d %b %H:%M UTC")
    err_html = ""
    if errors:
        err_html = '<div class="err">Could not load: ' + "; ".join(errors).replace("<", "") + "</div>"
    data = json.dumps(fixtures).replace("</", "<\\/")
    return (TEMPLATE.replace("%%GENERATED%%", gen)
            .replace("%%ERRORS%%", err_html)
            .replace("%%DATA%%", data))


def main():
    os.makedirs("docs", exist_ok=True)
    now = datetime.datetime.now(datetime.timezone.utc)
    # The 12:00 run is skipped unless forced, to save free API credits.
    if os.environ.get("GITHUB_EVENT_NAME") == "schedule" and now.hour >= 10 and os.path.exists("docs/index.html"):
        print("Afternoon run skipped to save credits.")
        return
    if not API_KEY:
        fixtures, errors = [], ["ODDS_API_KEY secret not set"]
    else:
        fixtures, errors = scan()
    with open("docs/index.html", "w", encoding="utf-8") as f:
        f.write(render(fixtures, errors))
    print("fixtures:", len(fixtures), "errors:", errors)


if __name__ == "__main__":
    main()
"""
BK's Bets — autonomous daily scan.
Runs on GitHub Actions' free servers on a schedule (see .github/workflows/scan.yml).
Fetches live odds, converts them to implied probability, and writes a static
docs/index.html page that GitHub Pages serves for free.
"""

import os
import json
import datetime
import requests

API_KEY = os.environ.get("ODDS_API_KEY", "").strip()

LEAGUES = [
    ("soccer_epl", "Premier League"),
    ("soccer_spain_la_liga", "La Liga"),
    ("soccer_italy_serie_a", "Serie A"),
    ("soccer_germany_bundesliga", "Bundesliga"),
    ("soccer_france_ligue_one", "Ligue 1"),
    ("soccer_netherlands_eredivisie", "Eredivisie"),
    ("soccer_turkey_super_league", "Süper Lig"),
    ("soccer_usa_mls", "MLS"),
    ("soccer_uefa_champs_league", "Champions League"),
    ("soccer_uefa_europa_league", "Europa League"),
    ("soccer_portugal_primeira_liga", "Primeira Liga"),
    ("soccer_efl_champ", "Championship"),
]

BASE = "https://api.the-odds-api.com/v4/sports/{sport}/odds/"


def fetch(sport_key, markets):
    """Fetch odds for one league. Returns [] on any failure (never crashes the run)."""
    try:
        r = requests.get(
            BASE.format(sport=sport_key),
            params={
                "apiKey": API_KEY,
                "regions": "uk,eu",
                "markets": markets,
                "oddsFormat": "decimal",
                "dateFormat": "iso",
            },
            timeout=20,
        )
        if r.status_code == 200:
            return r.json()
        return []
    except requests.RequestException:
        return []


def day_bucket(commence_iso):
    """Classifies a kickoff time as 'today', 'tomorrow', or None (too old / too far out).
    Uses UTC calendar days — close enough for a personal UK tool."""
    try:
        t = datetime.datetime.fromisoformat(commence_iso.replace("Z", "+00:00"))
    except ValueError:
        return None
    now = datetime.datetime.now(datetime.timezone.utc)
    if t < now - datetime.timedelta(hours=3):
        return None
    if t.date() == now.date():
        return "today"
    if t.date() == (now.date() + datetime.timedelta(days=1)):
        return "tomorrow"
    return None


def best_price(bookmakers, market_key, outcome_name):
    best = None
    for bm in bookmakers or []:
        for m in bm.get("markets", []):
            if m.get("key") != market_key:
                continue
            for o in m.get("outcomes", []):
                if o.get("name") == outcome_name:
                    if best is None or o["price"] > best:
                        best = o["price"]
    return best


def normalize(*odds):
    """Remove the bookmaker's margin: convert a set of decimal odds into
    probabilities that sum to 1."""
    invs = [1 / o for o in odds if o]
    total = sum(invs)
    if total == 0:
        return [0 for _ in odds]
    return [(1 / o) / total if o else 0 for o in odds]


def scan():
    picks = {
        "today": {"win": [], "btts": []},
        "tomorrow": {"win": [], "btts": []},
    }
    league_errors = []

    for sport_key, league_name in LEAGUES:
        events = fetch(sport_key, "h2h")
        if not events:
            league_errors.append(league_name)
            continue

        # Try to also pull BTTS ("both teams to score") for this league in a
        # second call. Not every free-tier odds source publishes this market —
        # if it's missing, we just skip BTTS for that league rather than fail.
        btts_events = fetch(sport_key, "btts")
        btts_by_id = {e["id"]: e for e in btts_events} if btts_events else {}

        for ev in events:
            bucket = day_bucket(ev.get("commence_time", ""))
            if bucket is None:
                continue
            home, away = ev.get("home_team"), ev.get("away_team")
            odds_home = best_price(ev.get("bookmakers"), "h2h", home)
            odds_away = best_price(ev.get("bookmakers"), "h2h", away)
            odds_draw = best_price(ev.get("bookmakers"), "h2h", "Draw")
            if odds_home and odds_away:
                p_home, p_away, p_draw = normalize(odds_home, odds_away, odds_draw)
                fav_is_home = p_home >= p_away
                picks[bucket]["win"].append({
                    "league": league_name,
                    "home": home, "away": away,
                    "kickoff": ev.get("commence_time"),
                    "fav_team": home if fav_is_home else away,
                    "fav_prob": max(p_home, p_away),
                    "odds_used": odds_home if fav_is_home else odds_away,
                })

            btts_ev = btts_by_id.get(ev["id"])
            if btts_ev:
                odds_yes = best_price(btts_ev.get("bookmakers"), "btts", "Yes")
                odds_no = best_price(btts_ev.get("bookmakers"), "btts", "No")
                if odds_yes and odds_no:
                    p_yes, p_no = normalize(odds_yes, odds_no)
                    if p_yes >= 0.55:
                        picks[bucket]["btts"].append({
                            "league": league_name,
                            "home": home, "away": away,
                            "kickoff": ev.get("commence_time"),
                            "prob": p_yes,
                            "odds_used": odds_yes,
                        })

    for bucket in picks.values():
        bucket["win"].sort(key=lambda p: p["fav_prob"], reverse=True)
        bucket["btts"].sort(key=lambda p: p["prob"], reverse=True)

    return picks, league_errors


def build_accas(win_picks):
    pool = [p for p in win_picks if p["fav_prob"] >= 0.60]
    combos = []

    def make(name, legs, risk, note):
        if len(legs) < 2:
            return None
        odds = 1.0
        prob = 1.0
        for l in legs:
            odds *= l["odds_used"]
            prob *= l["fav_prob"]
        return {"name": name, "legs": legs, "odds": odds, "prob": prob, "risk": risk, "note": note}

    if len(pool) >= 2:
        combos.append(make("Double", pool[:2], "low", "The steadiest combo on the board — still not a sure thing."))
    if len(pool) >= 3:
        combos.append(make("Treble", pool[:3], "med", "Notice how much the combined chance drops for one extra leg."))
    if len(pool) >= 5:
        combos.append(make("5-Fold reach", pool[:5], "high", "A genuinely minority-chance outcome — small stake only, if at all."))
    return [c for c in combos if c]


def fmt_pct(p):
    return f"{p*100:.1f}" if p * 100 < 1 else f"{round(p*100)}"


def fmt_time(iso):
    try:
        t = datetime.datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return t.strftime("%H:%M UTC")
    except Exception:
        return ""


def match_card(p, tier, market_label="to win"):
    pct = fmt_pct(p.get("fav_prob", p.get("prob")))
    team_line = p.get("fav_team", "Both teams to score")
    return f"""
    <div class="match {tier}">
      <div class="match-top">
        <span class="league">{p['league']}</span>
        <span class="kickoff">{fmt_time(p['kickoff'])}</span>
      </div>
      <div class="teams">{p['home']} <span class="vs">v</span> {p['away']}</div>
      <div class="pick-row {tier}">
        <div>
          <div class="pick-label">Market</div>
          <div class="pick-value">{team_line} {market_label}</div>
        </div>
        <div class="conf">
          <div class="pick-label">Implied prob.</div>
          <div class="conf-bar"><div class="conf-fill" style="width:{pct}%"></div></div>
        </div>
      </div>
      <div class="why">Best available price {p['odds_used']:.2f} implies roughly <b>{pct}%</b> after removing the bookmaker's margin.</div>
    </div>"""


def acca_card(c):
    pct = fmt_pct(c["prob"])
    risk_class = {"low": "risk-low", "med": "risk-med", "high": "risk-high"}[c["risk"]]
    risk_text = {"low": "Lower risk", "med": "Higher risk", "high": "Long shot"}[c["risk"]]
    legs_html = "".join(
        f'<li><span class="leg-name">{l["fav_team"]} ({l["league"]})</span><span class="leg-prob">{round(l["fav_prob"]*100)}%</span></li>'
        for l in c["legs"]
    )
    stake = 10
    returns = stake * c["odds"]
    return f"""
    <div class="acca">
      <div class="acca-top"><span class="acca-name">{c['name']}</span><span class="risk-tag {risk_class}">{risk_text}</span></div>
      <ul class="acca-legs">{legs_html}</ul>
      <div class="acca-stats">
        <div class="acca-stat combo-prob"><div class="l">Combined chance</div><div class="v">{pct}%</div></div>
        <div class="acca-stat combo-odds"><div class="l">Combined odds</div><div class="v">{c['odds']:.2f}</div></div>
        <div class="acca-stat combo-return"><div class="l">£{stake} returns</div><div class="v">£{returns:.2f}</div></div>
      </div>
      <div class="acca-warning">{c['note']} All {len(c['legs'])} legs must win — one loss voids the entire acca.</div>
    </div>"""


def render_day_content(win_picks, btts_picks):
    """Builds the Win market / BTTS / Accumulators HTML for one day's picks.
    Used both for the server-rendered initial view and mirrored in JS for the
    client-side 'Get fresh picks' recompute."""
    win_high = [p for p in win_picks if p["fav_prob"] >= 0.70][:6]
    win_med = [p for p in win_picks if 0.55 <= p["fav_prob"] < 0.70][:4]
    btts_high = [p for p in btts_picks if p["prob"] >= 0.65][:6]
    accas = build_accas(win_picks)

    win_html = "".join(match_card(p, "high") for p in win_high) + "".join(match_card(p, "med") for p in win_med)
    if not win_html:
        win_html = '<div class="empty">No standout favourites right now.</div>'

    btts_html = "".join(match_card(p, "high" if p["prob"] >= 0.75 else "med", "— both teams to score") for p in btts_high)
    if btts_html:
        btts_section = f'<div class="section-label">Both teams to score</div>{btts_html}'
    else:
        btts_section = '<div class="section-label">Both teams to score</div><div class="empty">No high-confidence BTTS candidates right now.</div>'

    acca_html = "".join(acca_card(c) for c in accas)
    acca_section = ""
    if acca_html:
        acca_section = f"""
        <div class="section-label">Accumulator options</div>
        <div class="acca-math"><b>Read this first:</b> every leg has to win, or the whole bet returns nothing. Three legs at 80% each is only about a 51% chance combined, not 80%.</div>
        {acca_html}"""

    return f"""<div class="section-label">Win market</div>
      {win_html}
      {btts_section}
      {acca_section}"""


def render(picks, league_errors):
    now = datetime.datetime.now(datetime.timezone.utc)
    generated = now.strftime("%a %d %b, %H:%M UTC")

    today_content = render_day_content(picks["today"]["win"], picks["today"]["btts"])
    tomorrow_content = render_day_content(picks["tomorrow"]["win"], picks["tomorrow"]["btts"])

    errors_note = ""
    if league_errors:
        errors_note = f'<div class="note-line">Couldn\'t reach data for: {", ".join(league_errors)} this run — will retry automatically next scan.</div>'

    # Full (untruncated) today's win/BTTS lists, embedded for the client-side
    # "Get fresh picks" button to re-filter against the visitor's real clock.
    today_data_json = json.dumps(picks["today"]).replace("</", "<\\/")

    html = HTML_TEMPLATE
    html = html.replace("%%GENERATED%%", generated)
    html = html.replace("%%TODAY_CONTENT%%", today_content)
    html = html.replace("%%TOMORROW_CONTENT%%", tomorrow_content)
    html = html.replace("%%ERRORS_NOTE%%", errors_note)
    html = html.replace("%%TODAY_DATA_JSON%%", today_data_json)
    return html


HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<meta name="apple-mobile-web-app-title" content="BK's Bets">
<title>BK's Bets</title>
<style>
:root{--pitch-dark:#0a0a0a;--pitch:#141414;--pitch-light:#1c1c1c;--line:#2e2e2e;--chalk:#f5f5f5;--chalk-dim:#96969a;--flood:#ffffff;--amber:#c9c9c9;}
*{box-sizing:border-box;-webkit-tap-highlight-color:transparent;}
html,body{margin:0;padding:0;background:var(--pitch-dark);color:var(--chalk);font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;}
body{min-height:100vh;padding:env(safe-area-inset-top) env(safe-area-inset-right) env(safe-area-inset-bottom) env(safe-area-inset-left);}
.wrap{max-width:520px;margin:0 auto;padding:24px 18px 60px;}
header{display:flex;align-items:center;justify-content:space-between;gap:14px;margin-bottom:18px;}
.brand{display:flex;align-items:center;gap:12px;}
.logo-mark{width:38px;height:38px;border-radius:10px;background:var(--chalk);color:var(--pitch-dark);display:flex;align-items:center;justify-content:center;font-family:'Oswald','Arial Narrow',sans-serif;font-weight:700;font-size:14px;letter-spacing:-0.5px;flex-shrink:0;}
h1{font-family:'Oswald','Arial Narrow',sans-serif;font-weight:600;font-size:20px;letter-spacing:0.2px;margin:0;}
.generated{font-size:11px;color:var(--chalk-dim);text-align:right;line-height:1.5;white-space:nowrap;}
.disclaimer{background:rgba(255,255,255,0.04);border:1px solid var(--line);border-radius:10px;padding:12px 14px;font-size:12.5px;line-height:1.5;color:var(--chalk-dim);margin-bottom:18px;}
.disclaimer strong{color:var(--chalk);}
.tabs{display:flex;gap:4px;background:rgba(255,255,255,0.04);border:1px solid var(--line);border-radius:10px;padding:4px;margin-bottom:16px;}
.tab{flex:1;text-align:center;padding:9px 0;border-radius:7px;font-family:'Oswald','Arial Narrow',sans-serif;font-size:13px;font-weight:500;letter-spacing:0.3px;color:var(--chalk-dim);background:transparent;border:none;cursor:pointer;}
.tab.active{background:var(--chalk);color:var(--pitch-dark);}
.refresh-row{margin-bottom:22px;}
.btn-refresh{width:100%;background:transparent;border:1px solid var(--line);color:var(--chalk);padding:11px 16px;border-radius:9px;font-family:'Oswald','Arial Narrow',sans-serif;font-size:13px;font-weight:500;letter-spacing:0.3px;cursor:pointer;}
.btn-refresh:active{background:rgba(255,255,255,0.08);}
.refresh-status{font-size:11.5px;color:var(--chalk-dim);margin-top:9px;line-height:1.5;text-align:center;}
.section-label{font-family:'Oswald','Arial Narrow',sans-serif;text-transform:uppercase;font-size:12.5px;letter-spacing:1.5px;color:var(--chalk-dim);margin:28px 0 12px;display:flex;align-items:center;gap:10px;}
.section-label:first-child{margin-top:0;}
.section-label::after{content:"";flex:1;height:1px;background:var(--line);}
.match{background:var(--pitch-light);border:1px solid var(--line);border-radius:12px;padding:16px;margin-bottom:12px;position:relative;overflow:hidden;}
.match::before{content:"";position:absolute;left:0;top:0;bottom:0;width:3px;}
.match.high::before{background:var(--flood);}
.match.med::before{background:var(--amber);opacity:0.5;}
.match-top{display:flex;justify-content:space-between;align-items:flex-start;gap:10px;}
.league{font-size:11px;text-transform:uppercase;letter-spacing:1px;color:var(--chalk-dim);}
.kickoff{font-size:11px;color:var(--chalk-dim);white-space:nowrap;font-variant-numeric:tabular-nums;}
.teams{font-family:'Oswald','Arial Narrow',sans-serif;font-size:19px;margin:6px 0 12px;letter-spacing:0.2px;}
.teams .vs{color:var(--chalk-dim);font-size:14px;margin:0 6px;}
.pick-row{display:flex;align-items:center;justify-content:space-between;background:rgba(0,0,0,0.3);border-radius:8px;padding:10px 12px;margin-bottom:10px;}
.pick-label{font-size:10.5px;text-transform:uppercase;letter-spacing:0.8px;color:var(--chalk-dim);margin-bottom:2px;}
.pick-value{font-family:'Oswald','Arial Narrow',sans-serif;font-size:15px;color:var(--flood);}
.conf{display:flex;flex-direction:column;align-items:flex-end;}
.conf-bar{width:64px;height:4px;border-radius:2px;background:rgba(255,255,255,0.12);margin-top:5px;overflow:hidden;}
.conf-fill{height:100%;background:var(--flood);border-radius:2px;}
.med .pick-value{color:var(--amber);}
.med .conf-fill{background:var(--amber);}
.why{font-size:12.5px;line-height:1.5;color:var(--chalk-dim);}
.why b{color:var(--chalk);font-weight:600;}
.empty{text-align:center;padding:26px 20px;color:var(--chalk-dim);font-size:13.5px;line-height:1.6;}
.acca{background:var(--pitch-light);border:1px solid var(--line);border-radius:12px;padding:16px;margin-bottom:12px;}
.acca-top{display:flex;justify-content:space-between;align-items:center;margin-bottom:4px;}
.acca-name{font-family:'Oswald','Arial Narrow',sans-serif;font-size:15px;letter-spacing:0.2px;}
.risk-tag{font-size:10px;text-transform:uppercase;letter-spacing:0.8px;padding:3px 9px;border-radius:20px;font-family:'Oswald','Arial Narrow',sans-serif;}
.risk-low{background:rgba(255,255,255,0.12);color:var(--chalk);}
.risk-med{background:rgba(255,255,255,0.07);color:var(--chalk-dim);}
.risk-high{background:var(--chalk);color:var(--pitch-dark);}
.acca-legs{list-style:none;padding:0;margin:12px 0;border-top:1px solid var(--line);border-bottom:1px solid var(--line);}
.acca-legs li{padding:8px 0;font-size:13px;display:flex;justify-content:space-between;border-bottom:1px solid rgba(255,255,255,0.04);}
.acca-legs li:last-child{border-bottom:none;}
.acca-legs .leg-prob{color:var(--chalk-dim);font-size:12px;font-variant-numeric:tabular-nums;}
.acca-stats{display:flex;justify-content:space-between;margin-top:12px;}
.acca-stat .l{font-size:10px;text-transform:uppercase;letter-spacing:0.8px;color:var(--chalk-dim);margin-bottom:2px;}
.acca-stat .v{font-family:'Oswald','Arial Narrow',sans-serif;font-size:18px;font-variant-numeric:tabular-nums;}
.acca-stat.combo-prob .v{color:var(--amber);}
.acca-stat.combo-odds .v{color:var(--flood);}
.acca-stat.combo-return .v{color:var(--chalk);font-size:14px;}
.acca-warning{font-size:11px;color:var(--chalk-dim);margin-top:12px;line-height:1.5;border-top:1px dashed var(--line);padding-top:10px;}
.acca-math{background:rgba(255,255,255,0.03);border:1px solid var(--line);border-radius:10px;padding:13px 15px;font-size:12px;line-height:1.6;color:var(--chalk-dim);margin-bottom:16px;}
.note-line{font-size:11px;color:var(--chalk-dim);margin-top:26px;line-height:1.6;}
footer{margin-top:32px;text-align:center;font-size:11px;color:var(--chalk-dim);line-height:1.7;}
</style>
</head>
<body>
<div class="wrap">
  <header>
    <div class="brand">
      <div class="logo-mark">BK</div>
      <h1>BK's Bets</h1>
    </div>
    <div class="generated">Updated<br>%%GENERATED%%</div>
  </header>
  <div class="disclaimer"><strong>These are odds-based estimates, not guarantees.</strong> Every percentage reflects live bookmaker prices with the margin removed. Odds move — check the current price before staking, and only bet what you can afford to lose.</div>
  <div class="tabs">
    <button class="tab active" id="tab-today" type="button">Today</button>
    <button class="tab" id="tab-tomorrow" type="button">Tomorrow</button>
  </div>
  <div id="panel-today" class="panel">
    <div class="refresh-row">
      <button class="btn-refresh" id="refresh-btn" type="button">Get fresh picks</button>
      <div class="refresh-status" id="refresh-status">Picks below are from the last scheduled scan.</div>
    </div>
    <div id="today-content">
      %%TODAY_CONTENT%%
    </div>
  </div>
  <div id="panel-tomorrow" class="panel" style="display:none">
    %%TOMORROW_CONTENT%%
  </div>
  %%ERRORS_NOTE%%
  <footer>BK's Bets · Live odds, updated automatically · Not financial advice · 18+ · Bet responsibly</footer>
</div>
<script id="today-data" type="application/json">%%TODAY_DATA_JSON%%</script>
<script>
(function(){
  var dataEl = document.getElementById('today-data');
  var TODAY_DATA = { win: [], btts: [] };
  try { TODAY_DATA = JSON.parse(dataEl.textContent); } catch (e) {}

  function fmtPct(p){
    return (p*100) < 1 ? (p*100).toFixed(1) : Math.round(p*100).toString();
  }
  function fmtTime(iso){
    try {
      var d = new Date(iso);
      var h = String(d.getUTCHours()).padStart(2,'0');
      var m = String(d.getUTCMinutes()).padStart(2,'0');
      return h + ':' + m + ' UTC';
    } catch (e) { return ''; }
  }
  function esc(s){
    return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
  }
  function matchCardHtml(p, tier, marketLabel){
    marketLabel = marketLabel || 'to win';
    var pct = fmtPct(p.fav_prob !== undefined ? p.fav_prob : p.prob);
    var teamLine = p.fav_team || 'Both teams to score';
    return '' +
      '<div class="match ' + tier + '">' +
        '<div class="match-top">' +
          '<span class="league">' + esc(p.league) + '</span>' +
          '<span class="kickoff">' + fmtTime(p.kickoff) + '</span>' +
        '</div>' +
        '<div class="teams">' + esc(p.home) + ' <span class="vs">v</span> ' + esc(p.away) + '</div>' +
        '<div class="pick-row ' + tier + '">' +
          '<div>' +
            '<div class="pick-label">Market</div>' +
            '<div class="pick-value">' + esc(teamLine) + ' ' + esc(marketLabel) + '</div>' +
          '</div>' +
          '<div class="conf">' +
            '<div class="pick-label">Implied prob.</div>' +
            '<div class="conf-bar"><div class="conf-fill" style="width:' + pct + '%"></div></div>' +
          '</div>' +
        '</div>' +
        '<div class="why">Best available price ' + p.odds_used.toFixed(2) + ' implies roughly <b>' + pct + '%</b> after removing the bookmaker margin.</div>' +
      '</div>';
  }
  function buildAccas(winPicks){
    var pool = winPicks.filter(function(p){ return p.fav_prob >= 0.60; });
    var combos = [];
    function make(name, legs, risk, note){
      if (legs.length < 2) return null;
      var odds = 1, prob = 1;
      legs.forEach(function(l){ odds *= l.odds_used; prob *= l.fav_prob; });
      return { name: name, legs: legs, odds: odds, prob: prob, risk: risk, note: note };
    }
    if (pool.length >= 2) combos.push(make('Double', pool.slice(0,2), 'low', 'The steadiest combo on the board — still not a sure thing.'));
    if (pool.length >= 3) combos.push(make('Treble', pool.slice(0,3), 'med', 'Notice how much the combined chance drops for one extra leg.'));
    if (pool.length >= 5) combos.push(make('5-Fold reach', pool.slice(0,5), 'high', 'A genuinely minority-chance outcome — small stake only, if at all.'));
    return combos.filter(Boolean);
  }
  function accaCardHtml(c){
    var pct = fmtPct(c.prob);
    var riskClass = { low: 'risk-low', med: 'risk-med', high: 'risk-high' }[c.risk];
    var riskText = { low: 'Lower risk', med: 'Higher risk', high: 'Long shot' }[c.risk];
    var legsHtml = c.legs.map(function(l){
      return '<li><span class="leg-name">' + esc(l.fav_team) + ' (' + esc(l.league) + ')</span><span class="leg-prob">' + Math.round(l.fav_prob*100) + '%</span></li>';
    }).join('');
    var stake = 10, returns = stake * c.odds;
    return '' +
      '<div class="acca">' +
        '<div class="acca-top"><span class="acca-name">' + c.name + '</span><span class="risk-tag ' + riskClass + '">' + riskText + '</span></div>' +
        '<ul class="acca-legs">' + legsHtml + '</ul>' +
        '<div class="acca-stats">' +
          '<div class="acca-stat combo-prob"><div class="l">Combined chance</div><div class="v">' + pct + '%</div></div>' +
          '<div class="acca-stat combo-odds"><div class="l">Combined odds</div><div class="v">' + c.odds.toFixed(2) + '</div></div>' +
          '<div class="acca-stat combo-return"><div class="l">£' + stake + ' returns</div><div class="v">£' + returns.toFixed(2) + '</div></div>' +
        '</div>' +
        '<div class="acca-warning">' + c.note + ' All ' + c.legs.length + ' legs must win — one loss voids the entire acca.</div>' +
      '</div>';
  }
  function renderDayContent(winPicks, bttsPicks){
    var winHigh = winPicks.filter(function(p){ return p.fav_prob >= 0.70; }).slice(0,6);
    var winMed = winPicks.filter(function(p){ return p.fav_prob >= 0.55 && p.fav_prob < 0.70; }).slice(0,4);
    var bttsHigh = bttsPicks.filter(function(p){ return p.prob >= 0.65; }).slice(0,6);
    var accas = buildAccas(winPicks);

    var winHtml = winHigh.map(function(p){ return matchCardHtml(p, 'high'); }).join('') +
                  winMed.map(function(p){ return matchCardHtml(p, 'med'); }).join('');
    if (!winHtml) winHtml = '<div class="empty">No standout favourites left today.</div>';

    var bttsHtml = bttsHigh.map(function(p){ return matchCardHtml(p, p.prob >= 0.75 ? 'high' : 'med', '— both teams to score'); }).join('');
    var bttsSection;
    if (bttsHtml) {
      bttsSection = '<div class="section-label">Both teams to score</div>' + bttsHtml;
    } else {
      bttsSection = '<div class="section-label">Both teams to score</div><div class="empty">No high-confidence BTTS candidates left today.</div>';
    }

    var accaHtml = accas.map(accaCardHtml).join('');
    var accaSection = '';
    if (accaHtml) {
      accaSection = '<div class="section-label">Accumulator options</div>' +
        '<div class="acca-math"><b>Read this first:</b> every leg has to win, or the whole bet returns nothing. Three legs at 80% each is only about a 51% chance combined, not 80%.</div>' +
        accaHtml;
    }

    return '<div class="section-label">Win market</div>' + winHtml + bttsSection + accaSection;
  }

  var refreshBtn = document.getElementById('refresh-btn');
  var statusEl = document.getElementById('refresh-status');
  var contentEl = document.getElementById('today-content');
  if (refreshBtn) {
    refreshBtn.addEventListener('click', function(){
      var now = Date.now();
      var winRemaining = (TODAY_DATA.win || []).filter(function(p){ return new Date(p.kickoff).getTime() > now; });
      var bttsRemaining = (TODAY_DATA.btts || []).filter(function(p){ return new Date(p.kickoff).getTime() > now; });
      contentEl.innerHTML = renderDayContent(winRemaining, bttsRemaining);
      var nowStr = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
      statusEl.textContent = 'Refreshed at ' + nowStr + ' — ' + winRemaining.length + ' fixture' + (winRemaining.length === 1 ? '' : 's') + ' still to kick off today.';
    });
  }

  var tabToday = document.getElementById('tab-today');
  var tabTomorrow = document.getElementById('tab-tomorrow');
  var panelToday = document.getElementById('panel-today');
  var panelTomorrow = document.getElementById('panel-tomorrow');
  function activate(tab){
    if (tab === 'today') {
      tabToday.classList.add('active'); tabTomorrow.classList.remove('active');
      panelToday.style.display = ''; panelTomorrow.style.display = 'none';
    } else {
      tabTomorrow.classList.add('active'); tabToday.classList.remove('active');
      panelTomorrow.style.display = ''; panelToday.style.display = 'none';
    }
  }
  if (tabToday && tabTomorrow) {
    tabToday.addEventListener('click', function(){ activate('today'); });
    tabTomorrow.addEventListener('click', function(){ activate('tomorrow'); });
  }
})();
</script>
</body>
</html>
"""


def main():
    os.makedirs("docs", exist_ok=True)
    if not API_KEY:
        with open("docs/index.html", "w") as f:
            f.write("<h1>ODDS_API_KEY secret not set.</h1><p>Add it in repo Settings &gt; Secrets and variables &gt; Actions.</p>")
        return
    picks, errors = scan()
    html = render(picks, errors)
    with open("docs/index.html", "w") as f:
        f.write(html)


if __name__ == "__main__":
    main()
