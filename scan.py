"""
Bet Scout — autonomous daily scan.
Runs on GitHub Actions' free servers on a schedule (see .github/workflows/scan.yml).
Fetches live odds, converts them to implied probability, and writes a static
docs/index.html page that GitHub Pages serves for free. Your phone just
displays whatever this last published — no app, no key, no button on the phone.
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


def within_window(commence_iso, hours_back=3, hours_fwd=30):
    try:
        t = datetime.datetime.fromisoformat(commence_iso.replace("Z", "+00:00"))
    except ValueError:
        return False
    now = datetime.datetime.now(datetime.timezone.utc)
    return (now - datetime.timedelta(hours=hours_back)) < t < (now + datetime.timedelta(hours=hours_fwd))


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
    win_picks = []
    btts_picks = []
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
            if not within_window(ev.get("commence_time", "")):
                continue
            home, away = ev.get("home_team"), ev.get("away_team")
            odds_home = best_price(ev.get("bookmakers"), "h2h", home)
            odds_away = best_price(ev.get("bookmakers"), "h2h", away)
            odds_draw = best_price(ev.get("bookmakers"), "h2h", "Draw")
            if odds_home and odds_away:
                p_home, p_away, p_draw = normalize(odds_home, odds_away, odds_draw)
                fav_is_home = p_home >= p_away
                win_picks.append({
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
                        btts_picks.append({
                            "league": league_name,
                            "home": home, "away": away,
                            "kickoff": ev.get("commence_time"),
                            "prob": p_yes,
                            "odds_used": odds_yes,
                        })

    win_picks.sort(key=lambda p: p["fav_prob"], reverse=True)
    btts_picks.sort(key=lambda p: p["prob"], reverse=True)
    return win_picks, btts_picks, league_errors


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
        combos.append(make("Double", pool[:2], "low", "The steadiest combo on today's board — still not a sure thing."))
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


def render(win_picks, btts_picks, league_errors):
    now = datetime.datetime.now(datetime.timezone.utc)
    generated = now.strftime("%a %d %b, %H:%M UTC")

    win_high = [p for p in win_picks if p["fav_prob"] >= 0.70][:6]
    win_med = [p for p in win_picks if 0.55 <= p["fav_prob"] < 0.70][:4]
    btts_high = [p for p in btts_picks if p["prob"] >= 0.65][:6]
    accas = build_accas(win_picks)

    win_html = "".join(match_card(p, "high") for p in win_high) + "".join(match_card(p, "med") for p in win_med)
    if not win_html:
        win_html = '<div class="empty">No standout favourites right now — check back closer to kickoff.</div>'

    btts_html = "".join(match_card(p, "high" if p["prob"] >= 0.75 else "med", "— both teams to score") for p in btts_high)
    btts_section = ""
    if btts_html:
        btts_section = f'<div class="section-label">Both teams to score</div>{btts_html}'
    else:
        btts_section = '<div class="section-label">Both teams to score</div><div class="empty">No high-confidence BTTS candidates today, or this market wasn\'t available from the data source for today\'s fixtures.</div>'

    acca_html = "".join(acca_card(c) for c in accas)
    acca_section = ""
    if acca_html:
        acca_section = f"""
        <div class="section-label">Accumulator options</div>
        <div class="acca-math"><b>Read this first:</b> every leg has to win, or the whole bet returns nothing. Three legs at 80% each is only about a 51% chance combined, not 80%.</div>
        {acca_html}"""

    errors_note = ""
    if league_errors:
        errors_note = f'<div class="note-line">Couldn\'t reach data for: {", ".join(league_errors)} this run — will retry automatically next scan.</div>'

    return HTML_TEMPLATE.format(
        generated=generated,
        win_html=win_html,
        btts_section=btts_section,
        acca_section=acca_section,
        errors_note=errors_note,
    )


HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<meta name="apple-mobile-web-app-title" content="Bet Scout">
<title>Bet Scout — Auto-updated</title>
<style>
:root{{--pitch-dark:#0d1f14;--pitch:#12291a;--pitch-light:#1c3d26;--line:#2c5236;--chalk:#f2f5f0;--chalk-dim:#b9c7bc;--flood:#d8ff5e;--amber:#ffb648;--red-card:#e0554a;--font-head:'Oswald','Arial Narrow',sans-serif;--font-body:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;}}
*{{box-sizing:border-box;}}
html,body{{margin:0;padding:0;background:var(--pitch-dark);color:var(--chalk);font-family:var(--font-body);}}
body{{min-height:100vh;padding:env(safe-area-inset-top) env(safe-area-inset-right) env(safe-area-inset-bottom) env(safe-area-inset-left);background-image:repeating-linear-gradient(90deg,rgba(255,255,255,0.02) 0px,rgba(255,255,255,0.02) 1px,transparent 1px,transparent 64px),radial-gradient(circle at 50% -10%,var(--pitch-light),var(--pitch-dark) 65%);}}
.wrap{{max-width:520px;margin:0 auto;padding:28px 18px 60px;}}
header{{display:flex;align-items:flex-end;justify-content:space-between;margin-bottom:10px;border-bottom:1px solid var(--line);padding-bottom:16px;}}
.kick{{width:34px;height:34px;border-radius:50%;border:2px solid var(--flood);position:relative;margin-bottom:8px;}}
.kick::before,.kick::after{{content:"";position:absolute;background:var(--flood);}}
.kick::before{{width:14px;height:2px;top:50%;left:50%;transform:translate(-50%,-50%) rotate(20deg);}}
.kick::after{{width:2px;height:14px;top:50%;left:50%;transform:translate(-50%,-50%) rotate(20deg);}}
h1{{font-family:var(--font-head);font-weight:600;font-size:26px;letter-spacing:0.3px;margin:0;text-transform:uppercase;}}
.sub{{color:var(--chalk-dim);font-size:13px;margin-top:2px;}}
.generated{{font-size:11px;color:var(--flood);text-align:right;text-transform:uppercase;letter-spacing:0.5px;}}
.disclaimer{{background:rgba(224,85,74,0.08);border:1px solid rgba(224,85,74,0.35);border-radius:10px;padding:12px 14px;font-size:13px;line-height:1.5;color:var(--chalk-dim);margin:18px 0 26px;}}
.disclaimer strong{{color:var(--chalk);}}
.section-label{{font-family:var(--font-head);text-transform:uppercase;font-size:13px;letter-spacing:2px;color:var(--chalk-dim);margin:34px 0 14px;display:flex;align-items:center;gap:10px;}}
.section-label::after{{content:"";flex:1;height:1px;background:var(--line);}}
.match{{background:linear-gradient(180deg,var(--pitch-light),var(--pitch));border:1px solid var(--line);border-radius:14px;padding:18px;margin-bottom:16px;position:relative;overflow:hidden;}}
.match::before{{content:"";position:absolute;left:0;top:0;bottom:0;width:4px;}}
.match.high::before{{background:var(--flood);}}
.match.med::before{{background:var(--amber);}}
.match-top{{display:flex;justify-content:space-between;align-items:flex-start;gap:10px;}}
.league{{font-size:11px;text-transform:uppercase;letter-spacing:1.5px;color:var(--chalk-dim);}}
.kickoff{{font-size:11px;color:var(--chalk-dim);white-space:nowrap;}}
.teams{{font-family:var(--font-head);font-size:21px;margin:6px 0 12px;letter-spacing:0.3px;}}
.teams .vs{{color:var(--chalk-dim);font-size:15px;margin:0 6px;}}
.pick-row{{display:flex;align-items:center;justify-content:space-between;background:rgba(0,0,0,0.25);border-radius:9px;padding:10px 12px;margin-bottom:10px;}}
.pick-label{{font-size:11px;text-transform:uppercase;letter-spacing:1px;color:var(--chalk-dim);margin-bottom:2px;}}
.pick-value{{font-family:var(--font-head);font-size:16px;color:var(--flood);}}
.conf{{display:flex;flex-direction:column;align-items:flex-end;}}
.conf-bar{{width:70px;height:5px;border-radius:3px;background:rgba(255,255,255,0.12);margin-top:5px;overflow:hidden;}}
.conf-fill{{height:100%;background:var(--flood);border-radius:3px;}}
.med .pick-value{{color:var(--amber);}}
.med .conf-fill{{background:var(--amber);}}
.why{{font-size:13px;line-height:1.55;color:var(--chalk-dim);}}
.why b{{color:var(--chalk);font-weight:600;}}
.empty{{text-align:center;padding:30px 20px;color:var(--chalk-dim);font-size:14px;line-height:1.6;}}
.acca{{background:linear-gradient(180deg,var(--pitch-light),var(--pitch));border:1px solid var(--line);border-radius:14px;padding:18px;margin-bottom:16px;}}
.acca-top{{display:flex;justify-content:space-between;align-items:center;margin-bottom:4px;}}
.acca-name{{font-family:var(--font-head);font-size:16px;text-transform:uppercase;letter-spacing:0.5px;}}
.risk-tag{{font-size:10.5px;text-transform:uppercase;letter-spacing:1px;padding:3px 9px;border-radius:20px;font-family:var(--font-head);}}
.risk-low{{background:rgba(216,255,94,0.15);color:var(--flood);}}
.risk-med{{background:rgba(255,182,72,0.15);color:var(--amber);}}
.risk-high{{background:rgba(224,85,74,0.15);color:var(--red-card);}}
.acca-legs{{list-style:none;padding:0;margin:12px 0;border-top:1px solid var(--line);border-bottom:1px solid var(--line);}}
.acca-legs li{{padding:8px 0;font-size:13px;display:flex;justify-content:space-between;border-bottom:1px solid rgba(255,255,255,0.04);}}
.acca-legs li:last-child{{border-bottom:none;}}
.acca-legs .leg-prob{{color:var(--chalk-dim);font-size:12px;}}
.acca-stats{{display:flex;justify-content:space-between;margin-top:12px;}}
.acca-stat .l{{font-size:10.5px;text-transform:uppercase;letter-spacing:1px;color:var(--chalk-dim);margin-bottom:2px;}}
.acca-stat .v{{font-family:var(--font-head);font-size:19px;}}
.acca-stat.combo-prob .v{{color:var(--amber);}}
.acca-stat.combo-odds .v{{color:var(--flood);}}
.acca-stat.combo-return .v{{color:var(--chalk);font-size:15px;}}
.acca-warning{{font-size:11.5px;color:var(--chalk-dim);margin-top:12px;line-height:1.5;border-top:1px dashed var(--line);padding-top:10px;}}
.acca-math{{background:rgba(255,182,72,0.06);border:1px solid rgba(255,182,72,0.25);border-radius:12px;padding:14px 16px;font-size:12.5px;line-height:1.6;color:var(--chalk-dim);margin-bottom:20px;}}
.note-line{{font-size:11.5px;color:var(--chalk-dim);margin-top:30px;line-height:1.6;}}
footer{{margin-top:34px;text-align:center;font-size:11.5px;color:var(--chalk-dim);line-height:1.7;}}
</style>
</head>
<body>
<div class="wrap">
  <header>
    <div>
      <div class="kick"></div>
      <h1>Bet Scout</h1>
      <div class="sub">Auto-updated · no app needed</div>
    </div>
    <div class="generated">Updated<br>{generated}</div>
  </header>
  <div class="disclaimer"><strong>No pick here is a sure thing.</strong> These come straight from live bookmaker odds, converted to probability. Odds move — check the live price before backing anything, and stake only what you're fine losing.</div>
  <div class="section-label">Win market</div>
  {win_html}
  {btts_section}
  {acca_section}
  {errors_note}
  <footer>Published automatically by a scheduled scan · not financial advice · bet responsibly</footer>
</div>
</body>
</html>
"""


def main():
    os.makedirs("docs", exist_ok=True)
    if not API_KEY:
        with open("docs/index.html", "w") as f:
            f.write("<h1>ODDS_API_KEY secret not set.</h1><p>Add it in repo Settings &gt; Secrets and variables &gt; Actions.</p>")
        return
    win_picks, btts_picks, errors = scan()
    html = render(win_picks, btts_picks, errors)
    with open("docs/index.html", "w") as f:
        f.write(html)


if __name__ == "__main__":
    main()
