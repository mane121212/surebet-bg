"""Pure calculations for Surebet BG 2.1; no live wagering/execution."""
import math
from datetime import datetime, timezone

OUTCOMES = ('1', 'X', '2')


def quote_age_minutes(quote, now=None):
    stamp = quote.get('updated')
    if not stamp:
        return None
    try:
        parsed = datetime.fromisoformat(stamp.replace('Z', '+00:00'))
        if parsed.tzinfo is None:
            return None
        now = now or datetime.now(timezone.utc)
        return (now - parsed.astimezone(timezone.utc)).total_seconds() / 60
    except (TypeError, ValueError):
        return None


def get_quotes(event, selected_books=None, max_age=0, now=None):
    """Filter source bookmakers BEFORE choosing best odds; uses exact API bookmaker keys."""
    home, away = event.get('home_team'), event.get('away_team')
    result = {key: [] for key in OUTCOMES}
    if not home or not away or home == away:
        return result
    allowed = set(selected_books) if selected_books is not None else None
    for book in event.get('bookmakers', []):
        book_key = book.get('key', '')
        if allowed is not None and book_key not in allowed:
            continue
        for market in book.get('markets', []):
            if market.get('key') != 'h2h':
                continue
            for outcome in market.get('outcomes', []):
                name = outcome.get('name')
                key = '1' if name == home else '2' if name == away else 'X' if name == 'Draw' else None
                if not key:
                    continue
                try:
                    odd = float(outcome['price'])
                except (KeyError, TypeError, ValueError):
                    continue
                if not math.isfinite(odd) or odd <= 1:
                    continue
                quote = {'odd': odd, 'bookmaker': book.get('title', book_key),
                         'bookmaker_key': book_key,
                         'updated': market.get('last_update') or book.get('last_update') or ''}
                age = quote_age_minutes(quote, now=now)
                if max_age and (age is None or age < 0 or age > max_age):
                    continue
                result[key].append(quote)
    return result


def analyze_events(events, league='', selected_books=None, max_age=0, commissions=None):
    """Return games with all 3 outcomes, using net-after-commission effective prices."""
    commissions = commissions or {}
    out = []
    for event in events:
        quotes = get_quotes(event, selected_books, max_age)
        if any(not quotes[k] for k in OUTCOMES):
            continue
        best = {}
        for k in OUTCOMES:
            def effective(q):
                fee = float(commissions.get(q['bookmaker_key'], 0)) / 100
                return 1 + (q['odd'] - 1) * (1 - fee)
            chosen = max(quotes[k], key=effective)
            best[k] = dict(chosen, effective_odd=effective(chosen),
                           fee=float(commissions.get(chosen['bookmaker_key'], 0)))
        margin = theoretical_roi([best[k]['effective_odd'] for k in OUTCOMES])
        out.append({'id': event.get('id', ''), 'league': league,
                    'match': f"{event.get('home_team')} – {event.get('away_team')}",
                    'kickoff': event.get('commence_time', ''), 'best': best, 'margin': margin})
    return out


def theoretical_roi(odds):
    odds = [float(v) for v in odds]
    if len(odds) != 3 or any(not math.isfinite(v) or v <= 1 for v in odds):
        raise ValueError('Нужни са три валидни коефициента над 1.00.')
    return (1 / sum(1 / v for v in odds) - 1) * 100


def allocate(odds, budget):
    """Cents rounded stakes, effective odds including fee on net winnings."""
    odds = [float(x) for x in odds]
    theoretical_roi(odds)
    if not math.isfinite(budget) or budget <= 0:
        raise ValueError('Невалиден бюджет')
    total_cents = round(budget * 100)
    invs = [1/o for o in odds]
    denominator = sum(invs)
    target = [total_cents * x / denominator for x in invs]
    base = [math.floor(x) for x in target]
    missing = total_cents - sum(base)
    for i in sorted(range(3), key=lambda i: target[i]-base[i], reverse=True)[:missing]:
        base[i] += 1
    amounts = [x/100 for x in base]
    profits = [round(a*o-total_cents/100, 2) for a,o in zip(amounts, odds)]
    return amounts, profits


def demo_events():
    h, a = 'ДЕМО: Сини', 'ДЕМО: Червени'
    def book(key, title, p1, px, p2):
        return {'key': key, 'title': title, 'last_update': datetime.now(timezone.utc).isoformat(),
                'markets': [{'key': 'h2h', 'outcomes': [{'name': h, 'price': p1},
                                                    {'name': 'Draw','price': px}, {'name': a,'price': p2}]}]}
    return [{'id':'demo1', 'home_team':h,'away_team':a,'commence_time':'',
             'bookmakers':[book('onexbet','1xBet',2.8,3.1,2.3),
                           book('matchbook','Matchbook',2.4,3.8,2.5),
                           book('betfair_ex_eu','Betfair Exchange',2.5,3.0,2.7)]}]
