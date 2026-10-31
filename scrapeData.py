"""Obter e normalizar os jogos do calendário da FPB."""

from __future__ import annotations

import argparse
import csv
import re
import time
import unicodedata
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import Iterable
from urllib.parse import urljoin

MONTHS = {
    "JAN": 1, "FEV": 2, "MAR": 3, "ABR": 4, "MAI": 5, "JUN": 6,
    "JUL": 7, "AGO": 8, "SET": 9, "OUT": 10, "NOV": 11, "DEZ": 12,
}


@dataclass(frozen=True)
class ScrapedGame:
    source_game_id: str
    source_url: str
    date: str
    time: str
    home_team: str
    away_team: str
    competition: str
    venue: str = ""


def current_season(today: date | None = None) -> str:
    today = today or date.today()
    start_year = today.year if today.month >= 7 else today.year - 1
    return f"{start_year}/{start_year + 1}"


def normalize_text(value: str) -> str:
    return " ".join(value.split()).strip()


def slug(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    ascii_value = normalized.encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "-", ascii_value.lower()).strip("-")


def parse_fpb_date(value: str) -> date:
    match = re.search(r"(\d{1,2})\s+([A-ZÇ]{3})\s+(\d{4})", value.upper())
    if not match or match.group(2) not in MONTHS:
        raise ValueError(f"Data FPB não reconhecida: {value!r}")
    return date(int(match.group(3)), MONTHS[match.group(2)], int(match.group(1)))


def normalize_time(value: str) -> str:
    match = re.search(r"(\d{1,2})\s*[H:]\s*(\d{2})", value.upper())
    if not match:
        raise ValueError(f"Hora FPB não reconhecida: {value!r}")
    return f"{int(match.group(1)):02d}:{int(match.group(2)):02d}"


def _source_id(game_element, home: str, away: str, competition: str) -> tuple[str, str]:
    from selenium.webdriver.common.by import By

    for link in game_element.find_elements(By.CSS_SELECTOR, "a[href]"):
        href = link.get_attribute("href") or ""
        # Evita confundir links da equipa/competição com o identificador do jogo.
        if not any(marker in href.casefold() for marker in ("jogo", "game", "jog&", "jog?", "show=jog")):
            continue
        numbers = re.findall(r"\d+", href)
        if numbers:
            return f"fpb-{numbers[-1]}", href
    # Exclui data/hora para uma alteração de horário atualizar o mesmo jogo.
    return f"fallback-{slug(f'{home}|{away}|{competition}')}", ""


def club_names(config: dict) -> list[str]:
    """Nomes a procurar nas equipas: aceita texto único ou lista (ex.: ["Ginásio", "GCO"])."""
    value = config.get("club_name_contains", "Ginásio")
    names = [value] if isinstance(value, str) else list(value)
    return [name.casefold() for name in names if name and name.strip()]


def is_club_team(team: str, names: list[str]) -> bool:
    team = team.casefold()
    return any(name in team for name in names)


def scrape_games(config: dict) -> list[ScrapedGame]:
    from selenium import webdriver
    from selenium.webdriver.common.by import By
    from selenium.webdriver.firefox.options import Options
    from selenium.webdriver.firefox.service import Service as FirefoxService

    season = config.get("season") or current_season()
    club_id = str(config.get("club_id", 23))
    template = config.get(
        "fpb_url_template",
        "https://www.fpb.pt/calendario/clube_{club_id}/?clube={club_id}&epoca={season}&",
    )
    url = template.format(club_id=club_id, season=season)

    options = Options()
    if config.get("headless", True):
        options.add_argument("-headless")
    if config.get("firefox_binary"):
        options.binary_location = config["firefox_binary"]
    driver_path = config.get("geckodriver_path")
    service = FirefoxService(executable_path=driver_path) if driver_path else FirefoxService()

    driver = webdriver.Firefox(service=service, options=options)
    try:
        print(f"A abrir calendário FPB: {url}")
        driver.get(url)
        time.sleep(float(config.get("initial_wait_seconds", 3)))
        previous_height = -1
        stable_rounds = 0
        for _ in range(int(config.get("max_scrolls", 50))):
            height = driver.execute_script("return document.body.scrollHeight")
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(float(config.get("scroll_wait_seconds", 2)))
            new_height = driver.execute_script("return document.body.scrollHeight")
            stable_rounds = stable_rounds + 1 if new_height == height == previous_height else 0
            previous_height = new_height
            if stable_rounds >= 1:
                break

        names = club_names(config)
        only_home = bool(config.get("only_home_games", True))
        results: list[ScrapedGame] = []
        for day_element in driver.find_elements(By.CSS_SELECTOR, "div.day-wrapper"):
            try:
                date_text = day_element.find_element(By.CLASS_NAME, "date").text
                if "A DEFINIR" in date_text.upper():
                    continue
                game_date = parse_fpb_date(date_text)
            except Exception:
                continue
            for game_element in day_element.find_elements(By.CSS_SELECTOR, ".game-wrapper"):
                teams = game_element.find_elements(By.CLASS_NAME, "fullName")
                if len(teams) < 2:
                    continue
                home = normalize_text(teams[0].text)
                away = normalize_text(teams[1].text)
                if only_home and not is_club_team(home, names):
                    continue
                if not only_home and not (is_club_team(home, names) or is_club_team(away, names)):
                    continue
                try:
                    game_time = normalize_time(game_element.find_element(By.TAG_NAME, "h3").text)
                    competition = normalize_text(game_element.find_element(By.CLASS_NAME, "competition").text)
                except Exception as exc:
                    print(f"Aviso: jogo ignorado por dados incompletos: {exc}")
                    continue
                venue_elements = game_element.find_elements(By.CSS_SELECTOR, ".location-wrapper b")
                venue = normalize_text(venue_elements[0].text) if venue_elements else ""
                source_id, source_url = _source_id(game_element, home, away, competition)
                results.append(ScrapedGame(
                    source_game_id=source_id,
                    source_url=urljoin(url, source_url) if source_url else "",
                    date=game_date.isoformat(), time=game_time,
                    home_team=home, away_team=away, competition=competition, venue=venue,
                ))
        return results
    finally:
        driver.quit()


def write_csv(games: Iterable[ScrapedGame], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fields = list(ScrapedGame.__dataclass_fields__)
    with output_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(asdict(game) for game in games)


def main() -> None:
    import json
    parser = argparse.ArgumentParser(description="Extrair calendário do Ginásio na FPB")
    parser.add_argument("--config", default="sync_config.json")
    parser.add_argument("--output", default="scraped_data.csv")
    args = parser.parse_args()
    with open(args.config, encoding="utf-8") as handle:
        config = json.load(handle)["scraper"]
    games = scrape_games(config)
    if not games:
        raise SystemExit("A FPB não devolveu jogos; o CSV anterior não foi substituído.")
    write_csv(games, Path(args.output))
    print(f"{len(games)} jogos guardados em {args.output}")


if __name__ == "__main__":
    main()
