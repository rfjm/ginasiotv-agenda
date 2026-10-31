"""Gerar imagens "Agenda Semanal" (Instagram, 1080x1350) a partir do calendário FPB.

Uso:
    py agenda_post.py                    # um post por cada dia com jogos nos próximos 7 dias
    py agenda_post.py --date 2026-11-07  # apenas esse dia
    py agenda_post.py --cached           # reutiliza os jogos da última extração (sem abrir a FPB)
"""

from __future__ import annotations

import argparse
import base64
import html
import json
import re
from dataclasses import asdict
from datetime import date, datetime, timedelta
from pathlib import Path

from scrapeData import ScrapedGame, club_names, is_club_team, scrape_games

WEEKDAYS = ["SEGUNDA-FEIRA", "TERÇA-FEIRA", "QUARTA-FEIRA", "QUINTA-FEIRA", "SEXTA-FEIRA", "SÁBADO", "DOMINGO"]
SENIOR_MARKERS = ("divisão", "proliga", "taça", "sénior", "senior", "liga")
# Formas jurídicas/siglas genéricas retiradas do nome do adversário.
OPPONENT_STRIP = {"SC", "CB", "CBQ", "BC", "ACD", "CF", "SL", "CD", "GD", "AD", "S.B.C.", "CLUBE", "BASKET", "BASQUETEBOL"}
OWN_CLUB_TOKENS = {"GINÁSIO", "GCO", "C.O.", "CO"}


def category(competition: str) -> str | None:
    """Escalão a partir da competição (ex.: "CRS16M" -> "SUB16 M"); None para seniores."""
    text = competition.casefold()
    gender = ""
    match = re.search(r"(?:sub|crs)\s*-?\s*(\d{2})\s*([mf])?", text)
    if match:
        label, gender = f"SUB{match.group(1)}", match.group(2) or ""
    else:
        match = re.search(r"(?:mini\s*|m)(8|10|12)\s*([mf])?", text)
        if not match:
            return None
        label, gender = f"MINI{match.group(1)}", match.group(2) or ""
    if not gender:
        gender = "f" if "fem" in text else "m" if "mas" in text else ""
    return f"{label} {gender.upper()}".strip()


def own_team_parts(name: str, competition: str) -> tuple[str, str]:
    """Devolve (texto principal, patrocinador) para uma equipa do clube."""
    tokens = re.findall(r'"[^"]*"|\S+', name)
    letter, sponsor = "", []
    for token in tokens:
        clean = token.strip('"').strip()
        if not clean or clean.upper() in OWN_CLUB_TOKENS:
            continue
        if len(clean) == 1 and clean.isalpha():
            letter = clean.upper()
        else:
            sponsor.append(clean)
    base = category(competition)
    if base is None or any(marker in competition.casefold() for marker in SENIOR_MARKERS):
        base = "GINÁSIO"
    main = f"{base} {letter}".strip()
    return main, " ".join(sponsor).upper()


def opponent_name(name: str, aliases: dict) -> str:
    clean = " ".join(name.split())
    if clean in aliases:
        return aliases[clean]
    tokens = [token.strip('"') for token in re.findall(r'"[^"]*"|\S+', clean)]
    tokens = [token for token in tokens if token and token != "-" and token.upper() not in OPPONENT_STRIP]
    if not tokens:
        return clean.upper()
    # Patrocinadores em maiúsculas depois do nome do clube (ex.: "Imortal CAFÉ OCEANO").
    kept = [tokens[0]] + [t for t in tokens[1:] if not (t.isupper() and len(t) > 3)]
    return " ".join(kept).upper()


def short_venue(venue: str, aliases: dict) -> str:
    place = venue.split(",")[0].strip()
    if place in aliases:
        return aliases[place]
    place = re.sub(r"^Pavilhão\s+(?:Municipal|Desportivo|Gimnodesportivo)?\s*(?:(?:dos|das|de|do|da)\s+)?", "Pav. ", place)
    place = re.sub(r"\bDesportiv[oa]\b", "Desp.", place)
    place = re.sub(r"\bDr\.\s*", "", place)
    return " ".join(place.split())


def team_parts(name: str, game: ScrapedGame, names: list[str], cfg: dict) -> tuple[str, str]:
    """(texto principal, patrocinador) como aparece no post; adversários não têm patrocinador."""
    if is_club_team(name, names):
        return own_team_parts(name, game.competition)
    return opponent_name(name, cfg.get("team_aliases", {})), ""


def team_html(name: str, game: ScrapedGame, names: list[str], cfg: dict) -> str:
    main, sponsor = team_parts(name, game, names, cfg)
    sponsor_html = f" <em>{html.escape(sponsor)}</em>" if sponsor else ""
    return f"{html.escape(main)}{sponsor_html}"


def _row(time_text: str, venue: str, body_html: str) -> tuple[str, str]:
    hour = time_text[1:] if time_text.startswith("0") else time_text
    meta = html.escape(hour) + (" - " + html.escape(venue) if venue else "")
    return time_text, f'<div class="game"><div class="meta">{meta}</div><div class="match"><span>{body_html}</span></div></div>'


def render_html(day: date, games: list[ScrapedGame], cfg: dict, names: list[str], logo_path: Path,
                extras: list[dict] | None = None) -> str:
    """`extras`: eventos manuais (ex.: convívios) com `time`, `venue` e `text`."""
    logo = ""
    if logo_path.exists():
        logo = "data:image/png;base64," + base64.b64encode(logo_path.read_bytes()).decode("ascii")
    entries = []
    for game in games:
        venue = short_venue(game.venue, cfg.get("venue_aliases", {})) if game.venue else ""
        entries.append(_row(game.time, venue, f'{team_html(game.home_team, game, names, cfg)} <i class="vs">vs</i> '
                                              f'{team_html(game.away_team, game, names, cfg)}'))
    for event in extras or []:
        entries.append(_row(event["time"], event.get("venue", ""), html.escape(event["text"].upper())))
    rows = [row for _, row in sorted(entries, key=lambda entry: entry[0])]
    return f"""<!doctype html>
<html><head><meta charset="utf-8">
<link href="https://fonts.googleapis.com/css2?family=Bebas+Neue&family=Oswald:wght@500&display=block" rel="stylesheet">
<style>
  html, body {{ margin: 0; background: #ddd; }}
  #post {{
    position: relative; width: 1080px; height: 1350px; overflow: hidden; box-sizing: border-box;
    padding: 40px 56px 40px 56px; font-family: 'Bebas Neue', sans-serif; color: #1d6b2c;
    background: radial-gradient(ellipse at 20% 15%, #ffffff 0%, #f1f1f1 45%, #e2e2e2 100%);
  }}
  #post::before {{  /* textura de mármore */
    content: ""; position: absolute; inset: 0; opacity: .55; pointer-events: none;
    background-image: url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='1080' height='1350'><filter id='m'><feTurbulence type='fractalNoise' baseFrequency='0.004 0.012' numOctaves='5' seed='7'/><feColorMatrix values='0 0 0 0 0.55  0 0 0 0 0.55  0 0 0 0 0.55  0 0 0 -2.2 1.15'/></filter><rect width='100%' height='100%' filter='url(%23m)'/></svg>");
  }}
  .head {{ position: relative; text-align: center; }}
  .logo {{ height: 92px; filter: drop-shadow(0 2px 4px rgba(0,0,0,.25)); }}
  .day {{ font-family: 'Oswald', sans-serif; font-size: 40px; letter-spacing: 10px; color: #222; margin-top: 6px; }}
  .day .date {{ color: #1d6b2c; letter-spacing: 4px; margin-left: 18px; padding-left: 22px; border-left: 3px solid #1d6b2c; }}
  .day::before, .day::after {{ content: ""; display: inline-block; width: 46px; border-top: 3px solid #222; vertical-align: middle; margin: 0 22px; }}
  .title {{ font-size: 150px; line-height: .95; letter-spacing: 16px; margin-right: -16px; white-space: nowrap; color: #1d6b2c;
           text-shadow: 0 0 18px rgba(64, 190, 90, .55), 0 3px 2px rgba(0,0,0,.18); }}
  .games {{ position: relative; text-align: right; margin-top: 26px; }}
  .game {{ margin-bottom: var(--gap, 18px); }}
  .meta {{ font-family: 'Oswald', sans-serif; font-size: var(--meta, 34px); color: #1d6b2c; line-height: 1.15; }}
  .match {{ font-size: var(--match, 74px); line-height: 1.05; white-space: nowrap; text-shadow: 0 2px 2px rgba(0,0,0,.15); }}
  .match span {{ display: inline-block; }}
  .match em {{ color: #47b14f; font-style: italic; padding-right: .12em; }}
  .vs {{ font-style: normal; font-size: .82em; }}
</style></head>
<body><div id="post">
  <div class="head">
    {f'<img class="logo" src="{logo}">' if logo else ''}
    <div class="day">{WEEKDAYS[day.weekday()]}<span class="date">{day:%d/%m}</span></div>
    <div class="title">AGENDA SEMANAL</div>
  </div>
  <div class="games">{''.join(rows)}</div>
</div>
<script>
  // Reduz tamanhos até todos os jogos caberem no post; encolhe linhas demasiado largas.
  function fit() {{
    const post = document.getElementById('post'), list = document.querySelector('.games');
    const title = document.querySelector('.title');
    while (title.scrollWidth > title.clientWidth + 16) {{
      title.style.fontSize = (parseFloat(getComputedStyle(title).fontSize) - 4) + 'px';
    }}
    let match = 74, meta = 34, gap = 18;
    const apply = () => {{ post.style.setProperty('--match', match + 'px'); post.style.setProperty('--meta', meta + 'px'); post.style.setProperty('--gap', gap + 'px'); }};
    apply();
    while (list.offsetTop + list.offsetHeight > post.clientHeight - 40 && match > 30) {{
      match -= 2; meta = Math.max(20, meta - 1); gap = Math.max(6, gap - 1); apply();
    }}
    const width = list.clientWidth;
    document.querySelectorAll('.match span').forEach(s => {{
      if (s.offsetWidth > width) s.style.fontSize = (match * width / s.offsetWidth) + 'px';
    }});
    document.body.dataset.ready = '1';
  }}
  document.fonts.ready.then(fit);
</script>
</body></html>"""


def open_driver(scraper_cfg: dict):
    from selenium import webdriver
    from selenium.webdriver.firefox.options import Options
    from selenium.webdriver.firefox.service import Service as FirefoxService

    options = Options()
    options.add_argument("-headless")
    if scraper_cfg.get("firefox_binary"):
        options.binary_location = scraper_cfg["firefox_binary"]
    driver_path = scraper_cfg.get("geckodriver_path")
    service = FirefoxService(executable_path=driver_path) if driver_path else FirefoxService()
    driver = webdriver.Firefox(service=service, options=options)
    driver.set_window_size(1300, 1700)
    return driver


def screenshot(driver, html_path: Path, png_path: Path) -> None:
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait

    driver.get(html_path.resolve().as_uri())
    WebDriverWait(driver, 30).until(lambda d: d.find_element(By.TAG_NAME, "body").get_attribute("data-ready") == "1")
    driver.find_element(By.ID, "post").screenshot(str(png_path))


def output_dir(config: dict) -> Path:
    path = Path(config.get("agenda_post", {}).get("output_dir", "posts"))
    path.mkdir(parents=True, exist_ok=True)
    return path


def load_games(config: dict, *, refresh: bool) -> list[ScrapedGame]:
    """Jogos FPB (casa e fora). Sem `refresh`, reutiliza a última extração se existir."""
    cache = output_dir(config) / "agenda_games.json"
    if not refresh and cache.exists():
        return [ScrapedGame(**item) for item in json.loads(cache.read_text(encoding="utf-8"))]
    # A agenda inclui jogos fora de casa, ao contrário da sincronização do YouTube.
    games = scrape_games({**config["scraper"], "only_home_games": False})
    cache.write_text(json.dumps([asdict(g) for g in games], ensure_ascii=False, indent=2), encoding="utf-8")
    return games


def manual_events_path(config: dict) -> Path:
    return Path(config.get("agenda_post", {}).get("manual_events_path", "manual_events.json"))


def load_manual_events(config: dict) -> list[dict]:
    path = manual_events_path(config)
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else []


def save_manual_events(config: dict, events: list[dict]) -> None:
    events = sorted(events, key=lambda e: (e["date"], e["time"]))
    manual_events_path(config).write_text(json.dumps(events, ensure_ascii=False, indent=2), encoding="utf-8")


def generate_posts(config: dict, start: date, end: date, *, refresh: bool) -> list[tuple[date, Path, int]]:
    """Cria um PNG por dia com jogos ou eventos manuais entre `start` e `end` (inclusive)."""
    post_cfg = config.get("agenda_post", {})
    games = load_games(config, refresh=refresh)
    names = club_names(config["scraper"])
    by_day: dict[date, tuple[list[ScrapedGame], list[dict]]] = {}
    for game in games:
        day = date.fromisoformat(game.date)
        if start <= day <= end:
            by_day.setdefault(day, ([], []))[0].append(game)
    for event in load_manual_events(config):
        day = date.fromisoformat(event["date"])
        if start <= day <= end:
            by_day.setdefault(day, ([], []))[1].append(event)
    if not by_day:
        return []

    folder = output_dir(config)
    logo_path = Path(post_cfg.get("logo_path", "assets/GCO.png"))
    results = []
    driver = open_driver(config["scraper"])
    try:
        for day in sorted(by_day):
            day_games, extras = by_day[day]
            html_path = folder / f"agenda-{day.isoformat()}.html"
            png_path = folder / f"agenda-{day.isoformat()}.png"
            html_path.write_text(render_html(day, day_games, post_cfg, names, logo_path, extras), encoding="utf-8")
            screenshot(driver, html_path, png_path)
            results.append((day, png_path, len(day_games) + len(extras)))
    finally:
        driver.quit()
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="Gerar posts 'Agenda Semanal' para o Instagram")
    parser.add_argument("--config", default="sync_config.json")
    parser.add_argument("--date", help="Primeiro dia (AAAA-MM-DD). Por omissão: hoje")
    parser.add_argument("--to", help="Último dia (AAAA-MM-DD). Por omissão: igual a --date, ou 7 dias a partir de hoje")
    parser.add_argument("--days", type=int, default=7, help="Número de dias a partir de hoje (predefinição: 7)")
    parser.add_argument("--cached", action="store_true", help="Reutilizar a última extração em vez de abrir a FPB")
    args = parser.parse_args()

    config = json.loads(Path(args.config).read_text(encoding="utf-8"))
    if args.date:
        start = date.fromisoformat(args.date)
        end = date.fromisoformat(args.to) if args.to else start
    else:
        start = datetime.now().date()
        end = date.fromisoformat(args.to) if args.to else start + timedelta(days=args.days - 1)

    results = generate_posts(config, start, end, refresh=not args.cached)
    if not results:
        print("Sem jogos nos dias pedidos.")
    for day, png_path, count in results:
        print(f"POST {png_path} | {WEEKDAYS[day.weekday()]} {day:%d/%m} | {count} jogos")


if __name__ == "__main__":
    main()
