"""穴馬候補検出モジュール

オッズデータから複勝乖離率・オッズ妙味度・複勝オッズ幅を組み合わせて
穴馬候補をスコアリングする。
"""


def _normalize(value: float, min_val: float, max_val: float) -> float:
    """値を0〜100の範囲に正規化する。"""
    if max_val == min_val:
        return 50.0
    clamped = max(min_val, min(max_val, value))
    return (clamped - min_val) / (max_val - min_val) * 100


def _calc_fukusho_kairi(horse: dict, popularity_rank: int) -> tuple[float, float]:
    """複勝乖離率を算出する。

    Returns:
        (正規化スコア, 生の乖離率)
    """
    # 1〜3番人気は穴馬対象外なのでスコア0
    if popularity_rank <= 3:
        return 0.0, 0.0

    win_implied_prob = 1.0 / horse["win_odds"]
    place_odds_avg = (horse["place_odds_min"] + horse["place_odds_max"]) / 2.0
    place_implied_prob = 1.0 / place_odds_avg

    # 乖離率: 複勝暗黙確率 / 単勝暗黙確率（高いほど穴馬の可能性）
    kairi = place_implied_prob / win_implied_prob

    # 乖離率の正規化: 1.0〜5.0 の範囲を 0〜100 にマッピング
    score = _normalize(kairi, 1.0, 5.0)
    return score, kairi


def _calc_odds_miryoku(horse: dict) -> tuple[float, list[str]]:
    """オッズ妙味度を算出する。

    単勝オッズが10〜100倍の範囲にある馬にボーナス。
    最適ゾーンは15〜50倍。
    """
    odds = horse["win_odds"]
    reasons = []

    if odds < 10.0:
        # 人気馬なので穴馬ではない
        return 0.0, reasons
    elif odds > 100.0:
        # さすがに来ない可能性が高い
        return 5.0, reasons

    # 最適ゾーン: 15〜50倍 → スコア80〜100
    if 15.0 <= odds <= 50.0:
        score = _normalize(odds, 15.0, 50.0)
        # 中央付近（30倍前後）が最も高くなるよう山型に
        center = 32.5
        distance = abs(odds - center) / (50.0 - 15.0)
        score = (1.0 - distance) * 100.0
        reasons.append("オッズ妙味ゾーン")
    elif 10.0 <= odds < 15.0:
        score = _normalize(odds, 10.0, 15.0) * 0.6  # 最大60
    else:
        # 50 < odds <= 100
        score = (1.0 - _normalize(odds, 50.0, 100.0)) * 0.6 * 100  # 逓減
        score = max(score, 10.0)

    return score, reasons


def _calc_fukusho_haba(horse: dict) -> float:
    """複勝オッズの幅スコアを算出する。

    幅が小さいほど安定して3着以内に来ると見られている。
    """
    haba = horse["place_odds_max"] - horse["place_odds_min"]

    # 幅0〜5.0の範囲を逆転して正規化（小さいほど高スコア）
    score = (1.0 - _normalize(haba, 0.0, 5.0) / 100.0) * 100.0
    return score


def _detect_avoid(horses: list[dict]) -> list[dict]:
    """過剰人気で避けるべき馬を検出する。

    単勝オッズが2.0未満 = 過剰人気で期待値が低い馬。
    """
    avoid = []
    for h in horses:
        if h["win_odds"] < 2.0:
            avoid.append({
                "number": h["number"],
                "name": h["name"],
                "win_odds": h["win_odds"],
                "reason": "過剰人気（期待値が低い）",
            })
    return avoid


def analyze_anauma(race_data: dict) -> dict:
    """穴馬候補を検出する。

    Args:
        race_data: scraper.pyが出力するレースデータ辞書。

    Returns:
        穴馬候補リストと過剰人気馬リストを含む辞書。
    """
    horses = race_data["horses"]

    # 単勝オッズ昇順でソートして人気順位を付与
    sorted_by_odds = sorted(horses, key=lambda h: h["win_odds"])
    popularity_rank_map = {}
    for i, h in enumerate(sorted_by_odds, start=1):
        popularity_rank_map[h["number"]] = i

    # 重み
    w_kairi = 0.40
    w_miryoku = 0.30
    w_haba = 0.30

    candidates = []

    for horse in horses:
        pop_rank = popularity_rank_map[horse["number"]]

        # 1. 複勝乖離率
        kairi_score, kairi_raw = _calc_fukusho_kairi(horse, pop_rank)

        # 2. オッズ妙味度
        miryoku_score, miryoku_reasons = _calc_odds_miryoku(horse)

        # 3. 複勝オッズの幅
        haba_score = _calc_fukusho_haba(horse)

        # 重み付き合計
        total_score = (
            kairi_score * w_kairi
            + miryoku_score * w_miryoku
            + haba_score * w_haba
        )
        total_score = round(total_score, 1)

        if total_score < 50:
            continue

        # 理由を構築
        reasons = []
        if kairi_raw >= 1.5:
            reasons.append(
                f"複勝オッズが単勝に比べ低い（乖離率{kairi_raw:.1f}）"
            )
        reasons.extend(miryoku_reasons)
        haba = horse["place_odds_max"] - horse["place_odds_min"]
        if haba <= 1.5:
            reasons.append("複勝オッズ幅が狭く安定感あり")

        candidates.append({
            "number": horse["number"],
            "name": horse["name"],
            "jockey": horse["jockey"],
            "win_odds": horse["win_odds"],
            "place_odds_min": horse["place_odds_min"],
            "place_odds_max": horse["place_odds_max"],
            "score": total_score,
            "reasons": reasons,
            "rank": 0,  # 後でソート後に振り直す
        })

    # スコア降順でソートし、rankを振る
    candidates.sort(key=lambda c: c["score"], reverse=True)
    for i, c in enumerate(candidates, start=1):
        c["rank"] = i

    # 過剰人気馬の検出
    avoid = _detect_avoid(horses)

    return {
        "race_name": race_data["race_name"],
        "candidates": candidates,
        "avoid": avoid,
    }
