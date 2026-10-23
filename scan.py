"""BK's Bets - daily odds scan. Writes docs/index.html (served by GitHub Pages)."""

import os
import re
import math
import json
import difflib
import unicodedata
import datetime
import requests

API_KEY = os.environ.get("ODDS_API_KEY", "").strip()

LEAGUES = [
    ("soccer_epl", "Premier League"),
    ("soccer_efl_champ", "Championship"), ("soccer_england_league1", "League One"), ("soccer_england_league2", "League Two"),
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

# Free public results feed (no key) used for each team's last-5 form.
ESPN_SLUGS = ["eng.1", "eng.2", "esp.1", "ita.1", "ger.1", "fra.1", "ned.1", "por.1",
              "tur.1", "usa.1", "eng.3", "eng.4", "uefa.champions", "uefa.europa", "uefa.europa.conf"]
ESPN_URL = "https://site.api.espn.com/apis/site/v2/sports/soccer/{slug}/scoreboard"
EXCHANGES = {"betfair_ex_uk", "smarkets", "matchbook"}
ALIASES = {"slavia praha": "slavia prague"}
DROP = {"fc", "cf", "afc", "sc", "ac", "ssc", "cd", "ud", "rc", "sv", "fk", "bk", "calcio"}


def norm(name):
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    s = s.replace("&", " and ")
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    return " ".join(t for t in s.split() if t not in DROP)


def load_form():
    """Returns (names, games): names maps normalised name -> team id,
    games maps team id -> list of (date, both_teams_scored), newest first."""
    names, games = {}, {}
    now = datetime.datetime.now(datetime.timezone.utc)
    seen = set()
    for slug in ESPN_SLUGS:
        try:
            r = requests.get(ESPN_URL.format(slug=slug),
                             params={"dates": str(now.year), "limit": 1000}, timeout=30)
            events = r.json().get("events", []) if r.status_code == 200 else []
        except (requests.RequestException, ValueError):
            events = []
        for ev in events:
            try:
                comp = ev["competitions"][0]
                if not ev["status"]["type"]["completed"]:
                    continue
                if ev["id"] in seen:
                    continue
                seen.add(ev["id"])
                cs = comp["competitors"]
                scores = [int(c["score"]) for c in cs]
                btts = all(x > 0 for x in scores)
                if len(cs) != 2:
                    continue
                for i, c in enumerate(cs):
                    t = c["team"]
                    for key in (t.get("displayName"), t.get("shortDisplayName")):
                        if key:
                            names[norm(key)] = t["id"]
                    mine, theirs = scores[i], scores[1 - i]
                    pts = 3 if mine > theirs else (1 if mine == theirs else 0)
                    games.setdefault(t["id"], []).append(
                        {"d": ev["date"], "b": btts, "p": pts, "f": mine, "a": theirs,
                         "o": cs[1 - i]["team"]["id"]})
            except (KeyError, ValueError, IndexError, TypeError):
                continue
    for tid in games:
        games[tid].sort(key=lambda g: g["d"], reverse=True)
    return names, games


def team_form(name, names, games):
    """Returns (both_scored_count, games_counted) over last 5, or None."""
    n = norm(name)
    n = ALIASES.get(n, n)
    tid = names.get(n)
    if tid is None:
        close = difflib.get_close_matches(n, list(names), n=1, cutoff=0.86)
        if close:
            tid = names[close[0]]
    if tid is None:
        # Word-overlap fallback: "kasimpasa sk" matches "kasimpasa".
        mine = set(n.split())
        best, best_ids = 0, set()
        for key, kid in names.items():
            theirs = set(key.split())
            if theirs <= mine or mine <= theirs:
                score = len(mine & theirs)
                if score > best:
                    best, best_ids = score, {kid}
                elif score == best and score > 0:
                    best_ids.add(kid)
        if len(best_ids) == 1:
            tid = next(iter(best_ids))
    if tid is None or tid not in games:
        return None
    if len(games[tid]) < 5:
        return None
    return tid


TABLE_URL = "https://site.api.espn.com/apis/v2/sports/soccer/{slug}/standings"


def load_tables():
    """Returns team id -> {"r": rank, "n": teams in table, "pl": played, "pts": points}.
    Domestic league tables take priority over European ones."""
    tab = {}
    for slug in ESPN_SLUGS:
        try:
            r = requests.get(TABLE_URL.format(slug=slug), timeout=30)
            data = r.json() if r.status_code == 200 else {}
        except (requests.RequestException, ValueError):
            data = {}
        for ch in data.get("children", []):
            entries = ch.get("standings", {}).get("entries", [])
            for e in entries:
                try:
                    st = {x["name"]: x.get("value") for x in e.get("stats", [])}
                    tid = e["team"]["id"]
                    if tid in tab:
                        continue
                    tab[tid] = {"r": int(st.get("rank") or 0), "n": len(entries),
                                "pl": int(st.get("gamesPlayed") or 0),
                                "pts": int(st.get("points") or 0)}
                except (KeyError, ValueError, TypeError):
                    continue
    return tab


GRID = [round(0.2 + 0.05 * i, 2) for i in range(64)]
PMF = {l: [math.exp(-l) * l ** k / math.factorial(k) for k in range(9)] for l in GRID}
CDF = {l: [sum(PMF[l][:k + 1]) for k in range(9)] for l in GRID}


def fit_goals(ph, pa):
    """Finds expected goals (home, away) whose Poisson win probabilities best match
    the market's home and away win chances. Standard 'goal expectancy' method."""
    best, best_err = (1.4, 1.1), 9.0
    for lh in GRID:
        for la in GRID:
            hw = sum(PMF[lh][i] * CDF[la][i - 1] for i in range(1, 9))
            aw = sum(PMF[la][i] * CDF[lh][i - 1] for i in range(1, 9))
            err = (hw - ph) ** 2 + (aw - pa) ** 2
            if err < best_err:
                best, best_err = (lh, la), err
    return best


def form_letters(gl):
    return "".join("W" if g["p"] == 3 else ("D" if g["p"] == 1 else "L") for g in reversed(gl[:5]))


def analyse(hid, aid, games, tab, p):
    """Adjusts market probabilities for form, league position and head-to-head,
    and estimates both-teams-to-score chance. Returns (new_p, info)."""
    gh, ga = games[hid], games[aid]
    fp_h, fp_a = sum(g["p"] for g in gh[:5]), sum(g["p"] for g in ga[:5])
    adj = 0.06 * (fp_h - fp_a) / 15.0
    th, ta = tab.get(hid), tab.get(aid)
    if th and ta and th["pl"] > 0 and ta["pl"] > 0:
        adj += 0.05 * (th["pts"] / th["pl"] - ta["pts"] / ta["pl"]) / 3.0
    meet = [g for g in gh if g["o"] == aid][:5]
    w = sum(1 for g in meet if g["p"] == 3)
    d = sum(1 for g in meet if g["p"] == 1)
    lo = len(meet) - w - d
    if len(meet) >= 2:
        adj += 0.04 * (w - lo) / len(meet)
    adj = max(-0.07, min(0.07, adj))
    new_p = {"h": round(max(0.02, p["h"] + adj), 4), "d": p["d"],
             "a": round(max(0.02, p["a"] - adj), 4)}

    def scored(gl):
        return sum(1 for g in gl[:5] if g["f"] > 0) / 5.0

    def conceded(gl):
        return sum(1 for g in gl[:5] if g["a"] > 0) / 5.0

    bp = ((scored(gh) + conceded(ga)) / 2.0) * ((scored(ga) + conceded(gh)) / 2.0)
    if len(meet) >= 2:
        bp = 0.75 * bp + 0.25 * (sum(1 for g in meet if g["b"]) / len(meet))
    # Last-5 form alone overstates both-teams-to-score, so it is shrunk toward the
    # normal rate and blended with the goals the betting market itself implies.
    bp_form = 0.5 + 0.6 * (bp - 0.5)
    lh, la = fit_goals(new_p["h"], new_p["a"]); gfa = lambda gl: sum(g["f"] for g in gl[:10]) / len(gl[:10]); gaa = lambda gl: sum(g["a"] for g in gl[:10]) / len(gl[:10]); sh, ch, sa, ca = [0.7 * v + 0.42 for v in (gfa(gh), gaa(gh), gfa(ga), gaa(ga))]; bp_goals = (1 - math.exp(-(sh + ca) / 2)) * (1 - math.exp(-(sa + ch) / 2))
    bp_model = (1 - math.exp(-lh)) * (1 - math.exp(-la))
    bp = 0.5 * bp_model + 0.2 * bp_form + 0.3 * bp_goals + (0.04 if th and ta and th["r"] <= max(3, th["n"] // 5) and ta["r"] <= max(3, ta["n"] // 5) else 0) + (0.06 if (lambda u, f: sum(1 for g in u[:5] if g["f"] > 0) >= 4 and sum(g["p"] for g in u[:5]) >= 7 and sum(1 for g in f[:5] if g["f"] > 0) >= 4)(*((ga, gh) if new_p["h"] >= new_p["a"] else (gh, ga))) else 0)
    info = {"hf": form_letters(gh), "af": form_letters(ga),
            "hr": th["r"] if th else None, "ar": ta["r"] if ta else None,
            "h2h": [w, d, lo] if meet else None, "bp": round(bp, 2),
            "eg": [round(lh, 1), round(la, 1)]}
    return new_p, info


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
    books = {}
    n = 0
    for bm in event.get("bookmakers", []):
        for m in bm.get("markets", []):
            if m.get("key") != "h2h":
                continue
            px = {o["name"]: o["price"] for o in m.get("outcomes", [])}
            if home in px and away in px and "Draw" in px:
                if bm.get("key") not in EXCHANGES:
                    books[bm.get("key", "?")] = {"h": px[home], "a": px[away],
                                                 "t": bm.get("title", bm.get("key", "?"))}
                inv = {"h": 1 / px[home], "d": 1 / px["Draw"], "a": 1 / px[away]}
                tot = sum(inv.values())
                for k in sums:
                    sums[k] += inv[k] / tot
                n += 1
    if n == 0:
        return None
    if not books:
        return None
    odds = dict(books)
    odds["avg"] = {"h": round(sum(b["h"] for b in books.values()) / len(books), 2),
                   "a": round(sum(b["a"] for b in books.values()) / len(books), 2)}
    return {k: round(v / n, 4) for k, v in sums.items()}, odds


def scan():
    now = datetime.datetime.now(datetime.timezone.utc)
    limit = now + datetime.timedelta(hours=96)
    fixtures, errors = [], []
    try:
        names, games = load_form()
    except Exception:
        names, games = {}, {}
    try:
        tab = load_tables()
    except Exception:
        tab = {}
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
            if t <= now or t > limit:
                continue
            res = consensus(ev)
            if not res:
                continue
            p, o = res
            hid = team_form(ev["home_team"], names, games)
            aid = team_form(ev["away_team"], names, games)
            fx = {"lg": name, "h": ev["home_team"], "a": ev["away_team"],
                  "t": ev["commence_time"], "p": p, "o": o}
            if hid and aid:
                fx["p"], fx["x"] = analyse(hid, aid, games, tab, p)
                fx["b"] = {"h": sum(1 for g in games[hid][:5] if g["b"]),
                           "a": sum(1 for g in games[aid][:5] if g["b"])}
            fixtures.append(fx)
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
header{padding:34px 0 16px;text-align:center}
header::after{content:"";display:block;width:70px;height:2px;margin:16px auto 0;background:linear-gradient(90deg,transparent,#fff,transparent)}
h1{margin:0;font-family:Georgia,"Times New Roman",serif;font-size:40px;font-weight:700;font-style:italic;letter-spacing:1px;background:linear-gradient(180deg,#fff 35%,#7a7a80);-webkit-background-clip:text;background-clip:text;-webkit-text-fill-color:transparent;color:transparent}
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
    <div><label>Games</label><select id="scope"><option value="today">Today</option><option value="tomorrow">Tomorrow</option><option value="all">Today + Tomorrow</option><option value="upcoming">All upcoming games</option></select></div>
  </div>
  <input type="hidden" id="book" value="avg">
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
var BN={bet365:'Bet365',paddypower:'Paddy Power',williamhill:'William Hill',ladbrokes:'Ladbrokes',skybet:'Sky Bet',coral:'Coral',betfred:'Betfred',betway:'Betway'};
var seen={};
FX.forEach(function(f){Object.keys(f.o||{}).forEach(function(k){if(k!=='avg'&&!seen[k])seen[k]=f.o[k].t||k;});});
var order=['bet365','paddypower','williamhill','ladbrokes','skybet','coral','betfred','betway'];
var keys=order.filter(function(k){return seen[k];}).concat(Object.keys(seen).filter(function(k){return order.indexOf(k)<0;}));
var bsel=el('book');
keys.forEach(function(k){var o=document.createElement('option');o.value=k;o.textContent=BN[k]||seen[k];bsel.appendChild(o);});
var oa=document.createElement('option');oa.value='avg';oa.textContent='Average of bookmakers';bsel.appendChild(oa);
var saved='';try{saved=localStorage.getItem('bkbook')||'';}catch(e){}
bsel.value=(saved&&(saved==='avg'||seen[saved]))?saved:(seen.bet365?'bet365':(seen.paddypower?'paddypower':'avg'));
function oddsFor(f,side){
  var b='avg', o=f.o||{};
  if(o[b]&&o[b][side])return {v:o[b][side],fb:false};
  if(o.avg&&o.avg[side])return {v:o.avg[side],fb:b!=='avg'};
  return {v:Math.round(100/f.p[side])/100,fb:true};
}

function esc(s){return String(s).replace(/[&<>]/g,function(c){return {'&':'&amp;','<':'&lt;','>':'&gt;'}[c]});}
function dayKey(d){return d.getFullYear()+'-'+d.getMonth()+'-'+d.getDate();}
function bucket(t){
  var now=new Date(), d=new Date(t), tm=new Date(now.getTime()+86400000);
  if(dayKey(d)===dayKey(now))return 'today';
  if(dayKey(d)===dayKey(tm))return 'tomorrow';
  return null;
}
function tm(t){var d=new Date(t);return (dayKey(d)===dayKey(new Date())?'':d.toLocaleDateString([],{weekday:'short'})+' ')+d.toLocaleTimeString([], {hour:'2-digit',minute:'2-digit'});}
function started(f){return new Date(f.t).getTime()<=Date.now();}
function ord(n){var s=['th','st','nd','rd'],v=n%100;return n+(s[(v-20)%10]||s[v]||s[0]);}
function why(f){
  var x=f.x; if(!x)return '';
  var t='Form '+x.hf+' v '+x.af;
  if(x.hr&&x.ar)t+=' · '+ord(x.hr)+' v '+ord(x.ar);
  if(x.eg)t+=' · Exp. goals '+x.eg[0]+'-'+x.eg[1];
  if(x.h2h)t+=' · H2H '+f.h+' '+x.h2h[0]+'W '+x.h2h[1]+'D '+x.h2h[2]+'L';
  return t;
}
function pick(f,noB){
  var p=f.p, best='h', team=f.h;
  if(p.a>p[best]){best='a';team=f.a;}
  var og=oddsFor(f,best), o=og.v;
  var ps=[],bk=f.o||{};
  Object.keys(bk).forEach(function(k){if(k!=='avg'&&bk[k][best])ps.push(bk[k][best]);});
  var mean=ps.reduce(function(a,b){return a+b;},0)/(ps.length||1);
  var sd=Math.sqrt(ps.reduce(function(a,b){return a+(b-mean)*(b-mean);},0)/(ps.length||1));
  var cv=mean?sd/mean:0;
  var sc=(p[best]*Math.sqrt(o)-0.6*Math.max(0,p.d-0.24))*(1-Math.min(0.1,cv));
  var r={team:team+' to win', prob:p[best], odds:o, fb:og.fb, btts:false, form:'', why:why(f), score:sc};
  var b=f.b;
  if(b){
    r.form=f.h+' '+b.h+'/5, '+f.a+' '+b.a+'/5 both scored';
    var more=false;if(noB)return r;
    if(f.x){
      var bp=f.x.bp,bs=Math.sqrt(0.97*bp);
      if(bp>=0.5&&bs>sc){r.team='Both teams to score';r.prob=bp;r.odds=null;r.btts=true;r.score=bs;}
    }
  }
  return r;
}
function list(day){
  var rows=FX.filter(function(f){return bucket(f.t)===day;}).sort(function(a,b){
    var sa=started(a)?-1:pick(a).score, sb=started(b)?-1:pick(b).score; return sb-sa;});
  if(!rows.length)return '<div class="empty">No games found.</div>';
  return rows.map(function(f){
    var k=pick(f);
    return '<div class="fx'+(started(f)?' off':'')+'"><span>'+esc(f.h)+' v '+esc(f.a)+'<br><small style="color:#8f8f94">'+esc(f.lg)+' &middot; '+tm(f.t)+'</small></span><span class="pct">'+esc(k.team.replace(' to win',''))+(k.btts?'':' '+k.odds.toFixed(2))+'</span></div>';
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
    return scope==='upcoming'?true:(scope==='all'?!!b:b===scope);
  }).map(function(f){var k=pick(f);return {f:f,team:k.team,prob:k.prob,odds:k.odds,btts:k.btts,form:k.form,why:k.why,fb:k.fb,score:k.score};});
  var good=pool.filter(function(l){return l.btts||(l.odds>=1.15&&l.prob>=0.45);});
  if(good.length>=n)pool=good;
  pool.sort(function(a,b){return b.score-a.score;});
  var res=el('result');
  if(pool.length<n){
    res.innerHTML='<div class="panel">Only '+pool.length+' game'+(pool.length===1?'':'s')+' left to bet on. Pick a smaller bet size'+(scope!=='upcoming'?' or choose All upcoming games':'')+'.</div>';
    el('again').style.display='none';return;
  }
  var legs;
  if(shuffle){
    var wide=pool.slice(0,Math.min(pool.length,n+Math.max(3,n)));
    for(var i=wide.length-1;i>0;i--){var j=Math.floor(Math.random()*(i+1));var t=wide[i];wide[i]=wide[j];wide[j]=t;}
    legs=wide.slice(0,n);
  } else legs=pool.slice(0,n);var cap=Math.max(1,n),nb=0;legs=legs.map(function(l){if(!l.btts||++nb<=cap)return l;var k=pick(l.f,true);return {f:l.f,team:k.team,prob:k.prob,odds:k.odds,btts:false,form:'',why:k.why,fb:k.fb,score:k.score};});
  legs.sort(function(a,b){return b.score-a.score;});
  var hasB=legs.some(function(l){return l.btts;});
  var hasFb=legs.some(function(l){return !l.btts&&l.fb;});
  var total=legs.reduce(function(a,l){return l.btts?a:a*l.odds;},1);
  var chance=legs.reduce(function(a,l){return a*l.prob;},1);
  var html='<div class="panel bet"><h2>'+n+'-fold</h2>'+legs.map(function(l){
    return '<div class="leg"><span><b>'+esc(l.team)+'</b><small>'+esc(l.f.h)+' v '+esc(l.f.a)+' &middot; '+esc(l.f.lg)+' &middot; '+tm(l.f.t)+(l.btts?'<br>'+esc(l.form):'')+(l.why?'<br>'+esc(l.why):'')+'</small></span><span class="pct">'+(l.btts?'check odds':l.odds.toFixed(2))+'</span></div>';
  }).join('')+'<div class="sum"><span>Total odds'+(hasB?' (without both-teams legs)':'')+'</span><span>'+total.toFixed(2)+'</span></div><div class="sum" style="border-top:0;padding-top:6px"><span>Chance all '+n+' win</span><span>'+(chance>=0.1?Math.round(chance*100):(chance*100).toFixed(1))+'%</span></div><div class="stake"><span>Stake &pound;</span><input id="stake" type="number" inputmode="decimal" value="10" min="0"><span class="ret" id="ret"></span></div><div class="note">'+(n>=4?'Each extra leg lowers the chance. 3 or 4 legs land far more often. ':'')+'Picks use bookmaker odds adjusted for form, league position and head-to-head. Prices are the average of UK bookmakers from the last scan and can change.'+(hasFb?' Some legs use average prices because the chosen bookmaker has none.':'')+' Built from games that have not kicked off. Every leg must win.</div></div>';
  res.innerHTML=html;
  var upd=function(){var v=parseFloat(el('stake').value)||0;el('ret').textContent='Returns £'+(v*total).toFixed(2);};
  el('stake').oninput=upd;upd();
  el('again').style.display='block';
}
el('build').onclick=function(){build(false);};

bsel.onchange=function(){
  try{localStorage.setItem('bkbook',bsel.value);}catch(e){}
  el('today').innerHTML=list('today');el('tomorrow').innerHTML=list('tomorrow');
  if(el('again').style.display==='block')build(false);
};
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
