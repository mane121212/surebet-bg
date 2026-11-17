import os
from datetime import datetime
import requests
import streamlit as st
from engine import demo_events, parse_events, stakes

st.set_page_config(page_title="Surebet BG · Футбол", page_icon="⚽", layout="wide")
st.markdown("""<style>
.stApp {background: #0c111c; color: #f2f6fc;}
[data-testid="stMetric"] {background:#172235;padding:14px;border-radius:12px;}
.stButton button[kind="primary"] {background:#17a879;color:white;}
</style>""", unsafe_allow_html=True)

SPORTS = {
    "Висша лига · Англия": "soccer_epl",
    "Ла Лига · Испания": "soccer_spain_la_liga",
    "Бундеслига · Германия": "soccer_germany_bundesliga",
    "Серия А · Италия": "soccer_italy_serie_a",
    "Лига 1 · Франция": "soccer_france_ligue_one",
    "Шампионска лига": "soccer_uefa_champs_league",
    "Лига Европа": "soccer_uefa_europa_league",
}


def get_key():
    env_key = os.getenv("ODDS_API_KEY", "").strip()
    if env_key:
        return env_key
    try:
        return str(st.secrets.get("ODDS_API_KEY", "")).strip()
    except (FileNotFoundError, KeyError):
        return ""


def get_live(sport, key, region):
    url = f"https://api.the-odds-api.com/v4/sports/{sport}/odds"
    response = requests.get(url, params={"apiKey": key, "regions": region, "markets": "h2h",
                                         "oddsFormat": "decimal", "dateFormat": "iso"}, timeout=20)
    try:
        info = response.json()
    except ValueError:
        info = {}
    if not response.ok:
        msg = info.get("message", "Грешка от доставчика") if isinstance(info, dict) else "Грешка от доставчика"
        raise RuntimeError(f"API HTTP {response.status_code}: {msg}")
    if not isinstance(info, list):
        raise RuntimeError("Неочакван формат на API отговора")
    return info, response.headers.get("x-requests-remaining", "неизвестно")

st.title("⚽ Surebet BG")
st.caption("Скенер за арбитражи 1 / X / 2 · Само анализ — без автоматично залагане")
key = get_key()
with st.sidebar:
    st.header("⚙️ Настройки")
    mode = st.radio("Режим", ["Демо", "Реални коефициенти"], index=0)
    league = st.selectbox("Първенство", list(SPORTS))
    region = st.selectbox("Регион на букмейкърите", ["eu", "uk", "eu,uk"], index=0)
    budget = st.number_input("Общ бюджет (€)", min_value=10.0, max_value=1000000.0, value=1000.0, step=50.0)
    minimum = st.number_input("Минимална възвръщаемост (%)", min_value=0.0, max_value=100.0, value=0.0, step=0.25)
    show_all = st.checkbox("Покажи и мачове без арбитраж")
    scan = st.button("🔍 Сканирай сега", type="primary", use_container_width=True)
    st.caption("Демо резултатите са измислени. Реалните данни изискват API ключ.")

if mode == "Реални коефициенти" and not key:
    st.warning("Няма ODDS_API_KEY. Добави ключ в настройките на хостинга (Secrets) или като локална променлива на средата.")
    st.info("За да пробваш веднага, избери режим „Демо“.")
    st.stop()

signature = (mode, league, region)
if scan or st.session_state.get("signature") != signature or "records" not in st.session_state:
    if mode == "Демо":
        events, remaining = demo_events(), "демо"
    else:
        try:
            with st.spinner("Изтеглям коефициенти…"):
                events, remaining = get_live(SPORTS[league], key, region)
        except (requests.RequestException, RuntimeError) as exc:
            st.error(f"Неуспешно зареждане: {exc}")
            st.stop()
    st.session_state.records = parse_events(events, league)
    st.session_state.signature = signature
    st.session_state.remaining = remaining
    st.session_state.last_scan = datetime.now().astimezone().strftime("%d.%m.%Y %H:%M:%S %Z")

records = st.session_state.records
opps = sorted((r for r in records if r["margin"] > 0 and r["margin"] >= minimum), key=lambda r: -r["margin"])
col1, col2, col3 = st.columns(3)
col1.metric("Проверени мачове (3 изхода)", len(records))
col2.metric("Арбитражи над прага", len(opps))
col3.metric("Най-добър ROI", f"{max((r['margin'] for r in opps), default=0):.2f}%")
st.caption(f"Последна проверка: {st.session_state.last_scan} · Оставащи API заявки: {st.session_state.remaining} · Не е непрекъснат поток")
if mode == "Демо":
    st.warning("🧪 ДЕМО РЕЖИМ — всички мачове и коефициенти са измислени. Не ги използвай за реални залози.")

visible = sorted(records, key=lambda r: -r["margin"]) if show_all else opps
if not visible:
    st.info("Няма намерени арбитражи при този праг. Това не е грешка: реалните арбитражи са редки, а не всички букмейкъри са обхванати.")

for result in visible:
    m = result["margin"]
    with st.container(border=True):
        st.subheader(result["match"])
        st.caption(f"{result['sport']} · Начало: {result['kickoff'] or 'демо'}")
        st.markdown(f"**Теоретична възвръщаемост: {m:+.2f}%** {'✅' if m > 0 else '❌ Няма арбитраж'}")
        amounts, profits = stakes(result["best"], budget)
        cols = st.columns(3)
        for i, outcome in enumerate(("1", "X", "2")):
            b = result["best"][outcome]
            with cols[i]:
                st.markdown(f"**{outcome} · {b['odd']:.2f}**")
                st.write(b["bookmaker"])
                st.write(f"Залог: **{amounts[i]:.2f} €**")
                st.caption(f"Печалба при този изход: {profits[i]:+.2f} €")
        st.caption(f"Минимална печалба след закръгляване: {min(profits):+.2f} € · При общ залог {budget:.2f} €")
        if m > 0:
            st.caption("⚠️ Проверявай един и същ пазар/правила (90 мин., продължения, анулиране), лимити, актуални коефициенти и такси. Положителен ROI не гарантира реална печалба.")

st.divider()
st.caption("Информационен инструмент. Не поставя залози, не гарантира печалба и не заобикаля ограничения на букмейкърите.")
