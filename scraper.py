"""netkeibaからオッズデータを取得するスクレイパーモジュール"""

import re
import time
from urllib.parse import parse_qs, urlparse

import requests
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "ja,en-US;q=0.7,en;q=0.3",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Referer": "https://race.netkeiba.com/",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "same-origin",
    "Sec-Fetch-User": "?1",
    "Upgrade-Insecure-Requests": "1",
}

SESSION = requests.Session()
SESSION.headers.update(HEADERS)


def _extract_race_id(url: str) -> str:
    """URLからrace_idを抽出する"""
    qs = parse_qs(urlparse(url).query)
    race_ids = qs.get("race_id")
    if not race_ids:
        raise ValueError(f"URLにrace_idが含まれていません: {url}")
    return race_ids[0]


def _get(url: str) -> BeautifulSoup:
    """ページを取得してBeautifulSoupオブジェクトを返す"""
    resp = SESSION.get(url, timeout=15)
    resp.raise_for_status()
    resp.encoding = resp.apparent_encoding
    return BeautifulSoup(resp.text, "lxml")


def _fetch_shutuba(race_id: str) -> dict:
    """出馬表ページからレース名・馬情報を取得する"""
    url = f"https://race.netkeiba.com/race/shutuba.html?race_id={race_id}"
    soup = _get(url)

    # レース名
    race_name_tag = soup.select_one(".RaceName")
    race_name = race_name_tag.get_text(strip=True) if race_name_tag else "不明"

    # レース番号・場所
    race_data_tag = soup.select_one(".RaceData01")
    if race_data_tag:
        race_num_text = race_data_tag.get_text(strip=True)
        race_name = race_num_text.split("/")[0].strip() + " " + race_name if race_num_text else race_name

    horses = {}
    rows = soup.select(".HorseList")
    for row in rows:
        # 馬番
        num_tag = row.select_one("td.Umaban")
        if not num_tag:
            continue
        try:
            number = int(num_tag.get_text(strip=True))
        except (ValueError, TypeError):
            continue

        # 枠番
        frame_tag = row.select_one("td.Waku span")
        try:
            frame = int(frame_tag.get_text(strip=True)) if frame_tag else 0
        except (ValueError, TypeError):
            frame = 0

        # 馬名
        horse_name_tag = row.select_one(".HorseName a")
        horse_name = horse_name_tag.get_text(strip=True) if horse_name_tag else "不明"

        # 騎手名
        jockey_tag = row.select_one(".Jockey a")
        jockey = jockey_tag.get_text(strip=True) if jockey_tag else "不明"

        horses[number] = {
            "number": number,
            "frame": frame,
            "name": horse_name,
            "jockey": jockey,
            "win_odds": None,
            "place_odds_min": None,
            "place_odds_max": None,
        }

    return {"race_name": race_name, "horses": horses}


def _fetch_win_odds(race_id: str, horses: dict) -> None:
    """単勝オッズを取得してhorsesに反映する"""
    url = f"https://race.netkeiba.com/odds/index.html?type=b1&race_id={race_id}"
    soup = _get(url)

    rows = soup.select("tr.Direct, tr[id^='odds-']")
    if not rows:
        rows = soup.select("table#odds_tan_block tr, table.RaceOdds_HorseList_Table tr")

    for row in rows:
        cells = row.select("td")
        if len(cells) < 2:
            continue

        # 馬番セルを探す
        num_text = cells[0].get_text(strip=True)
        try:
            number = int(num_text)
        except (ValueError, TypeError):
            continue

        # オッズセルを探す（最後のtdまたはodds系クラス）
        odds_tag = row.select_one("td.Odds, td.odds, td:last-child span, td:last-child")
        if not odds_tag:
            continue
        odds_text = odds_tag.get_text(strip=True)
        odds_text = odds_text.replace(",", "")
        try:
            odds_val = float(odds_text)
        except (ValueError, TypeError):
            continue

        if number in horses:
            horses[number]["win_odds"] = odds_val


def _fetch_place_odds(race_id: str, horses: dict) -> None:
    """複勝オッズを取得してhorsesに反映する"""
    url = f"https://race.netkeiba.com/odds/index.html?type=b6&race_id={race_id}"
    soup = _get(url)

    rows = soup.select("tr.Direct, tr[id^='odds-']")
    if not rows:
        rows = soup.select("table.RaceOdds_HorseList_Table tr, table#odds_fuku_block tr")

    for row in rows:
        cells = row.select("td")
        if len(cells) < 2:
            continue

        num_text = cells[0].get_text(strip=True)
        try:
            number = int(num_text)
        except (ValueError, TypeError):
            continue

        # 複勝オッズは「下限 - 上限」形式
        odds_text = ""
        odds_tag = row.select_one("td.Odds, td.odds")
        if odds_tag:
            odds_text = odds_tag.get_text(strip=True)
        else:
            for cell in cells[1:]:
                text = cell.get_text(strip=True)
                if "-" in text or "~" in text:
                    odds_text = text
                    break

        if not odds_text:
            continue

        odds_text = odds_text.replace(",", "").replace("~", "-")
        parts = re.split(r"\s*-\s*", odds_text)
        try:
            odds_min = float(parts[0])
            odds_max = float(parts[1]) if len(parts) > 1 else odds_min
        except (ValueError, TypeError, IndexError):
            continue

        if number in horses:
            horses[number]["place_odds_min"] = odds_min
            horses[number]["place_odds_max"] = odds_max


def fetch_race_data(race_url: str) -> dict:
    """netkeibaのレースURLからオッズデータを取得する

    Args:
        race_url: 出馬表またはレース結果ページのURL

    Returns:
        レース情報とオッズを含むdict
    """
    race_id = _extract_race_id(race_url)

    # 出馬表から基本情報を取得
    try:
        data = _fetch_shutuba(race_id)
    except requests.RequestException as e:
        raise RuntimeError(f"出馬表ページの取得に失敗しました (race_id={race_id}): {e}") from e

    horses = data["horses"]

    if not horses:
        raise RuntimeError(f"馬情報が取得できませんでした (race_id={race_id})")

    # 単勝オッズを取得
    time.sleep(1)
    try:
        _fetch_win_odds(race_id, horses)
    except requests.RequestException as e:
        raise RuntimeError(f"単勝オッズの取得に失敗しました (race_id={race_id}): {e}") from e

    # 複勝オッズを取得
    time.sleep(1)
    try:
        _fetch_place_odds(race_id, horses)
    except requests.RequestException as e:
        raise RuntimeError(f"複勝オッズの取得に失敗しました (race_id={race_id}): {e}") from e

    # オッズが取得できない馬（取消等）をスキップし、馬番順にソート
    valid_horses = [
        h for h in sorted(horses.values(), key=lambda x: x["number"])
        if h["win_odds"] is not None
    ]

    return {
        "race_name": data["race_name"],
        "race_id": race_id,
        "horses": valid_horses,
    }


if __name__ == "__main__":
    import json
    import sys

    if len(sys.argv) < 2:
        print("使い方: python scraper.py <netkeiba_race_url>")
        sys.exit(1)

    result = fetch_race_data(sys.argv[1])
    print(json.dumps(result, ensure_ascii=False, indent=2))
