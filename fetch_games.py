"""Ler o calendário FPB e gravar games.json para a página da Agenda Semanal.

Corre no GitHub Actions (ver .github/workflows/update-games.yml). Os nomes já saem
formatados como no post (escalão, patrocinador, adversário e pavilhão abreviados).

    py fetch_games.py                         # extrai da FPB
    py fetch_games.py --from-cache jogos.json # usa uma extração existente (lista de jogos)
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from agenda_post import short_venue, team_parts
from scrapeData import ScrapedGame, club_names, scrape_games


def to_json(games: list[ScrapedGame], config: dict) -> dict:
    post_cfg = config.get("agenda_post", {})
    names = club_names(config["scraper"])
    items = []
    for game in sorted(games, key=lambda g: (g.date, g.time)):
        home, home_sponsor = team_parts(game.home_team, game, names, post_cfg)
        away, away_sponsor = team_parts(game.away_team, game, names, post_cfg)
        # `raw`/`venue_raw`: nomes originais da FPB, para a página aplicar nomes abreviados do browser.
        items.append({
            "date": game.date, "time": game.time,
            "venue": short_venue(game.venue, post_cfg.get("venue_aliases", {})) if game.venue else "",
            "venue_raw": game.venue.split(",")[0].strip(),
            "home": {"text": home, "sponsor": home_sponsor, "raw": " ".join(game.home_team.split())},
            "away": {"text": away, "sponsor": away_sponsor, "raw": " ".join(game.away_team.split())},
        })
    timezone = ZoneInfo(config.get("timezone", "Europe/Lisbon"))
    return {"updated_at": datetime.now(timezone).isoformat(timespec="minutes"), "games": items}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="agenda_config.json")
    parser.add_argument("--output", default="games.json")
    parser.add_argument("--from-cache", help="Ficheiro JSON com jogos já extraídos")
    args = parser.parse_args()

    config = json.loads(Path(args.config).read_text(encoding="utf-8"))
    if args.from_cache:
        games = [ScrapedGame(**item) for item in json.loads(Path(args.from_cache).read_text(encoding="utf-8"))]
    else:
        games = scrape_games({**config["scraper"], "only_home_games": False})
    if not games:
        raise SystemExit("A FPB não devolveu jogos; games.json não foi alterado.")
    Path(args.output).write_text(json.dumps(to_json(games, config), ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{len(games)} jogos gravados em {args.output}")


if __name__ == "__main__":
    main()
