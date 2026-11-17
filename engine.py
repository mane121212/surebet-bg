"""Surebet BG 3.0: 1/X/2 BACK-only analysis, without bet placement."""
import math
from datetime import datetime, timezone

OUTCOMES = ('1', 'X', '2')
EXCHANGE_KEYS = {'betfair_ex_eu', 'betfair_ex_uk', 'betfair_ex_au', 'matchbook', 'smarkets'}


def parse_time(value):
    if not isinstance(value, str) or not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
        return dt.astimezone(timezone.utc) if dt.tzinfo else None
    except ValueError:
        return None


def quote_age_minutes(quote, now=None):
    dt = parse_time(quote.get('updated'))
    if not dt:
        return None
    return ((now or datetime.now(timezone.utc)) - dt).total_seconds() / 60


def effective_odd(odd, fee_percent=0):
    odd, fee_percent = float(odd), float(fee_percent)
    if not math.isfinite(odd) or odd <= 1 or not math.isfinite(fee_percent) or not 0 <= fee_percent < 100:
        raise ValueError('Невалиден коефициент или комисиона')
    # Simplified BACK fee model: % on positive winnings, not returned stake.
    return 1 + (odd - 1) * (1 - fee_percent / 100)


def get_quotes(event, selected_books=None, max_age=5, now=None):
    """Selected bookmakers and only h2h BACK. Ignore h2h_lay and unmatched outcomes."""
    home, away = event.get('home_team'), event.get('away_team')
    result = {key: [] for key in OUTCOMES}
    if not home or not away or home == away:
        return result
    allowed = set(selected_books) if selected_books is not None else None
    now = now or datetime.now(timezone.utc)
    for book in event.get('bookmakers') or []:
        book_key = book.get('key', '')
        if allowed is not None and book_key not in allowed:
            continue
        for market in book.get('markets') or []:
            if market.get('key') != 'h2h':
                continue
            stamp = market.get('last_update') or book.get('last_update')
            for outcome in market.get('outcomes') or []:
                name = outcome.get('name')
                key = '1' if name == home else '2' if name == away else 'X' if name == 'Draw' else None
                if key is None:
                    continue
                try:
                    odd = float(outcome['price'])
                except (KeyError, ValueError, TypeError):
                    continue
                if not math.isfinite(odd) or odd <= 1:
                    continue
                quote = {'odd': odd, 'bookmaker': book.get('title') or book_key,
                         'bookmaker_key': book_key, 'updated': stamp or '', 'market': 'h2h'}
                age = quote_age_minutes(quote, now)
                if max_age and (age is None or age < -1 or age > max_age):
                    continue
                result[key].append(quote)
    return result


def theoretical_roi(odds):
    odds = [float(v) for v in odds]
    if len(odds) != 3 or any(not math.isfinite(v) or v <= 1 for v in odds):
        raise ValueError('Нужни са три валидни коефициента над 1.00.')
    return (1 / sum(1 / v for v in odds) - 1) * 100


def allocate(odds, budget):
    odds = [float(x) for x in odds]
    theoretical_roi(odds)
    if not math.isfinite(budget) or budget <= 0:
        raise ValueError('Невалиден бюджет')
    total_cents = round(budget * 100)
    invs = [1 / o for o in odds]
    denominator = sum(invs)
    target = [total_cents * x / denominator for x in invs]
    base = [math.floor(x) for x in target]
    missing = total_cents - sum(base)
    for i in sorted(range(3), key=lambda i: target[i] - base[i], reverse=True)[:missing]:
        base[i] += 1
    amounts = [x / 100 for x in base]
    profits = [round(a * o - total_cents / 100, 2) for a, o in zip(amounts, odds)]
    return amounts, profits


def analyze_events(events, league='', selected_books=None, max_age=5, commissions=None, now=None):
    commissions = commissions or {}
    now = now or datetime.now(timezone.utc)
    out = []
    for event in events:
        kickoff = parse_time(event.get('commence_time'))
        # Only upcoming matches for pre-match 90-min h2h checks; do not present started matches.
        if kickoff is None or kickoff <= now:
            continue
        quotes = get_quotes(event, selected_books, max_age, now)
        if any(not quotes[k] for k in OUTCOMES):
            continue
        best = {}
        for k in OUTCOMES:
            def net(q):
                return effective_odd(q['odd'], commissions.get(q['bookmaker_key'], 0))
            chosen = max(quotes[k], key=net)
            best[k] = dict(chosen, effective_odd=net(chosen),
                           fee=float(commissions.get(chosen['bookmaker_key'], 0)))
        margin = theoretical_roi([best[k]['effective_odd'] for k in OUTCOMES])
        out.append({'id': event.get('id', ''), 'league': league,
                    'sport_key': event.get('sport_key', ''),
                    'match': f"{event.get('home_team')} – {event.get('away_team')}",
                    'kickoff': event.get('commence_time', ''), 'best': best, 'margin': margin})
    return out


def liquidity_check(odds, budget, available):
    """Unknown liquidity does not mean verified. Supplied numbers are user checked, not API."""
    stakes, profits = allocate(odds, budget)
    if len(available) != 3:
        raise ValueError('Нужни са три стойности за ликвидност')
    enough = all(v is not None and float(v) >= stakes[i] for i, v in enumerate(available))
    return {'stakes': stakes, 'profits': profits, 'enough': enough,
            'unknown': any(v is None for v in available)}


def demo_events():
    now = datetime.now(timezone.utc)
    from datetime import timedelta
    h, a = 'ДЕМО: Сини', 'ДЕМО: Червени'
    def book(key, title, p1, px, p2):
        return {'key': key, 'title': title, 'last_update': now.isoformat(),
                'markets': [{'key': 'h2h', 'last_update': now.isoformat(),
                             'outcomes': [{'name': h, 'price': p1},
                                          {'name': 'Draw', 'price': px},
                                          {'name': a, 'price': p2}]}]}
    return [{'id': 'demo1', 'home_team': h, 'away_team': a,
             'commence_time': (now + timedelta(days=1)).isoformat(),
             'bookmakers': [book('onexbet', '1xBet', 2.8, 3.1, 2.3),
                            book('matchbook', 'Matchbook', 2.4, 3.8, 2.5),
                            book('betfair_ex_eu', 'Betfair Exchange', 2.5, 3.0, 2.7)]}]
