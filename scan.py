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
    best = {"h": 0.0, "a": 0.0}
    b365 = {}
    n = 0
    for bm in event.get("bookmakers", []):
        for m in bm.get("markets", []):
            if m.get("key") != "h2h":
                continue
            px = {o["name"]: o["price"] for o in m.get("outcomes", [])}
            if home in px and away in px and "Draw" in px:
                best["h"] = max(best["h"], px[home])
                best["a"] = max(best["a"], px[away])
                if bm.get("key") == "bet365":
                    b365 = {"h": px[home], "a": px[away]}
                inv = {"h": 1 / px[home], "d": 1 / px["Draw"], "a": 1 / px[away]}
                tot = sum(inv.values())
                for k in sums:
                    sums[k] += inv[k] / tot
                n += 1
    if n == 0:
        return None
    odds = b365 if b365 else best
    return {k: round(v / n, 4) for k, v in sums.items()}, odds


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
            res = consensus(ev)
            if not res:
                continue
            p, o = res
            fixtures.append({"lg": name, "h": ev["home_team"], "a": ev["away_team"],
                             "t": ev["commence_time"], "p": p, "o": o})
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
.stake{display:flex;align-items:center;gap:8px;padding-top:12px}
.stake input{width:90px;background:#0f0f0f;color:var(--text);border:1px solid var(--line);border-radius:10px;padding:10px;font-size:16px}
.stake .ret{margin-left:auto;font-size:20px;font-weight:700}
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
  var o=f.o&&f.o[best]?f.o[best]:Math.round(100/p[best])/100;
  return {team:team, prob:p[best], odds:o};
}
function list(day){
  var rows=FX.filter(function(f){return bucket(f.t)===day;});
  if(!rows.length)return '<div class="empty">No games found.</div>';
  return rows.map(function(f){
    var k=pick(f);
    return '<div class="fx'+(started(f)?' off':'')+'"><span>'+esc(f.h)+' v '+esc(f.a)+'<br><small style="color:#8f8f94">'+esc(f.lg)+' &middot; '+tm(f.t)+'</small></span><span class="pct">'+esc(k.team)+' '+k.odds.toFixed(2)+'</span></div>';
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
  }).map(function(f){var k=pick(f);return {f:f,team:k.team,prob:k.prob,odds:k.odds};});
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
  var total=legs.reduce(function(a,l){return a*l.odds;},1);
  var html='<div class="panel bet"><h2>'+n+'-fold</h2>'+legs.map(function(l){
    return '<div class="leg"><span><b>'+esc(l.team)+' to win</b><small>'+esc(l.f.h)+' v '+esc(l.f.a)+' &middot; '+esc(l.f.lg)+' &middot; '+tm(l.f.t)+'</small></span><span class="pct">'+l.odds.toFixed(2)+'</span></div>';
  }).join('')+'<div class="sum"><span>Total odds</span><span>'+total.toFixed(2)+'</span></div><div class="stake"><span>Stake &pound;</span><input id="stake" type="number" inputmode="decimal" value="10" min="0"><span class="ret" id="ret"></span></div><div class="note">Odds are a guide and can differ on Bet365. Built from games that have not kicked off. Every leg must win.</div></div>';
  res.innerHTML=html;
  var upd=function(){var v=parseFloat(el('stake').value)||0;el('ret').textContent='Returns £'+(v*total).toFixed(2);};
  el('stake').oninput=upd;upd();
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
