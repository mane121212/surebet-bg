"""Calculation and parsing for 3-way football arbitrage."""
from datetime import datetime, timezone
import math


def parse_events(events, sport_title="Футбол"):
    results = []
    for event in events:
        home, away = event.get("home_team"), event.get("away_team")
        if not home or not away or home == away:
            continue
        best = {"1": None, "X": None, "2": None}
        for book in event.get("bookmakers", []):
            for market in book.get("markets", []):
                if market.get("key") != "h2h":
                    continue
                for outcome in market.get("outcomes", []):
                    name = outcome.get("name")
                    key = "1" if name == home else "2" if name == away else "X" if name == "Draw" else None
                    try:
                        odd = float(outcome.get("price"))
                    except (TypeError, ValueError):
                        continue
                    if not key or not math.isfinite(odd) or odd <= 1:
                        continue
                    item = {"odd": odd, "bookmaker": book.get("title", "Непознат"), "updated": market.get("last_update", book.get("last_update", ""))}
                    if best[key] is None or odd > best[key]["odd"]:
                        best[key] = item
        if any(best[k] is None for k in ("1", "X", "2")):
            continue  # 3-way only; missing draws must never look like a 2-way surebet
        reciprocal = sum(1 / best[k]["odd"] for k in ("1", "X", "2"))
        margin = (1 / reciprocal - 1) * 100
        results.append({"id": event.get("id", ""), "sport": sport_title,
                        "match": f"{home} – {away}", "kickoff": event.get("commence_time", ""),
                        "best": best, "margin": margin, "reciprocal": reciprocal})
    return results


def stakes(best, budget):
    """Exact proportional stakes; round for display and recalculate outcome returns."""
    odds = [best[k]["odd"] for k in ("1", "X", "2")]
    inv = sum(1 / odd for odd in odds)
    raw = [budget / (odd * inv) for odd in odds]
    # cents-preserving adjustment, so displayed stakes sum to the budget
    cents = [int(round(raw[0] * 100)), int(round(raw[1] * 100))]
    cents.append(int(round(budget * 100)) - sum(cents))
    amounts = [v / 100 for v in cents]
    profits = [round(a * o - budget, 2) for a, o in zip(amounts, odds)]
    return amounts, profits


def demo_events():
    def book(name, h, x, a):
        return {"title": name, "markets": [{"key": "h2h", "outcomes": [
            {"name": "Домакин", "price": h}, {"name": "Draw", "price": x},
            {"name": "Гост", "price": a}]}]}
    specs = [
        ("ДЕМО: Сините", "ДЕМО: Червените", [("Букмейкър A", 2.80, 3.30, 2.30), ("Букмейкър B", 2.45, 3.80, 2.50), ("Букмейкър C", 2.50, 3.25, 2.70)]),
        ("ДЕМО: Север", "ДЕМО: Юг", [("Букмейкър A", 2.60, 3.10, 2.75), ("Букмейкър B", 2.55, 3.30, 2.65)]),
        ("ДЕМО: Изток", "ДЕМО: Запад", [("Букмейкър A", 2.20, 3.60, 3.80), ("Букмейкър B", 2.35, 3.55, 3.60), ("Букмейкър C", 2.15, 3.80, 3.65)]),
    ]
    events = []
    for i, (home, away, quotes) in enumerate(specs):
        bookmakers = []
        for name, h, x, a in quotes:
            b = book(name, h, x, a)
            b["markets"][0]["outcomes"][0]["name"] = home
            b["markets"][0]["outcomes"][2]["name"] = away
            bookmakers.append(b)
        events.append({"id": f"demo-{i}", "home_team": home, "away_team": away,
                       "commence_time": "", "bookmakers": bookmakers})
    return events
