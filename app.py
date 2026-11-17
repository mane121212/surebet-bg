"""Surebet BG 2.0 — responsive Streamlit multi-league 1/X/2 odds analyser."""
import os
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed
import requests
import streamlit as st
from engine import demo_events, parse_events, stakes

API = "https://api.the-odds-api.com/v4"
st.set_page_config(page_title="Surebet BG 2.0", page_icon="⚽", layout="wide", initial_sidebar_state="auto")
st.markdown("""<style>
.stApp {background:#0c111c;color:#f2f6fc}
[data-testid="stMetric"] {background:#172235;border-radius:14px;padding:14px}
.stButton button[kind="primary"] {background:#13a67a;color:white}
[data-testid="stSidebar"] {background:#191c20}
[data-testid="stVerticalBlockBorderWrapper"] {border-radius:14px}
</style>""",unsafe_allow_html=True)

FALLBACK = {
    "Англия · Висша лига":"soccer_epl", "Испания · Ла Лига":"soccer_spain_la_liga",
    "Германия · Бундеслига":"soccer_germany_bundesliga", "Италия · Серия А":"soccer_italy_serie_a",
    "Франция · Лига 1":"soccer_france_ligue_one", "Шампионска лига":"soccer_uefa_champs_league",
    "Лига Европа":"soccer_uefa_europa_league", "Конферентна лига":"soccer_uefa_europa_conference_league",
    "Нидерландия · Ередивизи":"soccer_netherlands_eredivisie", "Португалия · Примейра лига":"soccer_portugal_primeira_liga",
    "Шотландия · Премиършип":"soccer_spl", "Белгия · Първа дивизия":"soccer_belgium_first_div",
    "Турция · Суперлига":"soccer_turkey_super_league", "Гърция · Суперлига":"soccer_greece_super_league",
    "Австрия · Бундеслига":"soccer_austria_bundesliga", "Швейцария · Суперлига":"soccer_switzerland_superleague",
    "Полша · Екстракласа":"soccer_poland_ekstraklasa", "Дания · Суперлига":"soccer_denmark_superliga",
    "Норвегия · Елитсериен":"soccer_norway_eliteserien", "Швеция · Алсвенскан":"soccer_sweden_allsvenskan",
}

def get_key():
    value = os.getenv("ODDS_API_KEY", "").strip()
    if value: return value
    try: return str(st.secrets.get("ODDS_API_KEY", "")).strip()
    except (KeyError, FileNotFoundError): return ""

@st.cache_data(ttl=3600, show_spinner=False)
def available_soccer(key):
    """The sports list is free and shows currently supported/active keys."""
    response = requests.get(f"{API}/sports",params={"apiKey":key},timeout=15)
    response.raise_for_status()
    return [s for s in response.json() if s.get("key","").startswith("soccer_") and s.get("active",False)]

def get_live(key, sport, region):
    r=requests.get(f"{API}/sports/{sport}/odds",params={"apiKey":key,"regions":region,
        "markets":"h2h","oddsFormat":"decimal","dateFormat":"iso"},timeout=22)
    try: data=r.json()
    except ValueError: data={}
    if not r.ok:
        message=data.get("message", "Няма подробности") if isinstance(data,dict) else "Невалиден отговор"
        raise RuntimeError(f"HTTP {r.status_code}: {message}")
    if not isinstance(data,list): raise RuntimeError("Неочакван API формат")
    return data, r.headers.get("x-requests-remaining", "?"),r.headers.get("x-requests-last","?")

def is_fresh(item, max_minutes):
    if max_minutes <= 0: return True
    stamp=item.get("updated", "")
    if not stamp:return False
    try:
        dt=datetime.fromisoformat(stamp.replace("Z","+00:00"))
        return 0 <= (datetime.now(timezone.utc)-dt.astimezone(timezone.utc)).total_seconds()/60 <= max_minutes
    except (ValueError,TypeError):return False

def pretty_date(value):
    try:return datetime.fromisoformat(value.replace("Z","+00:00")).astimezone().strftime("%d.%m.%Y %H:%M")
    except (ValueError,AttributeError):return str(value)

st.title("⚽ Surebet BG 2.0")
st.caption("Много първенства · футболен пазар 1 / X / 2 · анализ, без автоматично залагане")
key=get_key()
if not key: st.info("За реални коефициенти въведи ODDS_API_KEY в Streamlit Cloud → Settings → Secrets.")

with st.sidebar:
    st.header("⚙️ Настройки")
    mode=st.radio("Данни",["Реални коефициенти","Демо"],index=0 if key else 1)
    if mode=="Реални коефициенти" and key:
        try:
            active=available_soccer(key)
            sports={s.get("title",s["key"]):s["key"] for s in active}
            if not sports:raise RuntimeError("Няма активни футболни първенства")
            st.caption(f"Доставчикът връща {len(sports)} активни футболни турнира.")
        except (requests.RequestException,ValueError,RuntimeError) as exc:
            st.warning(f"Списъкът на активните лиги не се зареди: {exc}. Показвам резервен списък.")
            sports=FALLBACK
    else:sports=FALLBACK
    defaults=[name for name,code in sports.items() if code in {
        "soccer_epl","soccer_spain_la_liga","soccer_germany_bundesliga",
        "soccer_italy_serie_a","soccer_france_ligue_one"}][:5]
    chosen=st.multiselect("Първенства (до 20)",options=list(sports),default=defaults,
                          help="Избери 1–20 активни турнира. При всяко сканиране се прави заявка за всяка лига.")
    region=st.selectbox("Регион на букмейкърите",["eu","uk","eu,uk"],index=0)
    budget=st.number_input("Общ бюджет (€)",min_value=10.0,max_value=1_000_000.0,value=1000.0,step=50.0)
    minimum=st.number_input("Минимална възвръщаемост (%)",min_value=0.0,max_value=100.0,value=1.0,step=0.25)
    max_age=st.selectbox("Максимална възраст на котировката",[0,5,15,30,60],index=0,
        format_func=lambda v: "Без филтър" if v==0 else f"{v} минути",
        help="Проверява времевите маркери, когато са предоставени. Не гарантира наличност на коефициентите.")
    show_all=st.checkbox("Покажи и срещи без арбитраж")
    book_filter=st.text_input("Букмейкъри (незадължително)",placeholder="Betfair, Pinnacle",
        help="Разделени със запетая. Анализира само тези букмейкъри. Остави празно за всички.")
    st.caption(f"Избрани: {len(chosen)} лиги · приблизително {len(chosen)*(2 if region=='eu,uk' else 1)} кредита при налични коефициенти; реалното таксуване зависи от API.")
    scan=st.button("🔍 Сканирай избраните лиги",type="primary",use_container_width=True,disabled=not chosen or len(chosen)>20 or (mode=="Реални коефициенти" and not key))
    if len(chosen)>20:st.error("Може да избереш максимум 20 първенства.")
    st.caption("Няма автоматично сканиране. Натискай бутона ръчно, за да контролираш API кредита.")

# Only the explicit scan button triggers paid odds calls. Widget changes never trigger re-fetches.
if scan:
    errors=[]; results=[]; remaining="?"; spent=0
    with st.spinner(f"Проверявам {len(chosen)} първенства…"):
        if mode=="Демо":
            results=parse_events(demo_events(),"Демонстрация")
            remaining="демо"
        else:
            with ThreadPoolExecutor(max_workers=4) as pool:
                futures={pool.submit(get_live,key,sports[name],region): name for name in chosen}
                for fut in as_completed(futures):
                    name=futures[fut]
                    try:
                        events, left, last=fut.result()
                        results.extend(parse_events(events,name))
                        remaining=left # completion order; not a reliable final credit balance
                        try: spent+=int(last)
                        except (ValueError,TypeError):pass
                    except (requests.RequestException,RuntimeError) as exc:
                        errors.append(f"{name}: {exc}")
    st.session_state["latest"]={"rows":results,"mode":mode,"leagues":list(chosen),"region":region,
        "when":datetime.now().astimezone().strftime("%d.%m.%Y %H:%M:%S"),"errors":errors,
        "spent":spent,"remaining":remaining}

latest=st.session_state.get("latest")
if not latest:
    st.info("Избери първенства от менюто вляво (на телефон натисни ») и натисни „🔍 Сканирай избраните лиги“.")
    st.stop()
if latest["mode"] != mode or latest["region"] != region or latest["leagues"] != list(chosen):
    st.warning("Променил си настройките след последното сканиране. Резултатите по-долу са от предишните настройки. Сканирай отново.")
if latest["mode"]=="Демо":st.warning("🧪 ДЕМО — всички коефициенти и мачове са измислени!")
else:st.success("📡 Последното сканиране използва реалния API. Коефициентите не са потвърдени при букмейкърите.")

books={x.strip().casefold() for x in book_filter.split(",") if x.strip()}
rows=[]
for row in latest["rows"]:
    if books and any(row["best"][k]["bookmaker"].casefold() not in books for k in ("1","X","2")):
        continue
    if max_age and not all(is_fresh(row["best"][k],max_age) for k in ("1","X","2")):
        continue
    rows.append(row)
# Do not pretend subset-of-bookmakers filter recalculates best prices. It filters only results
# where each globally-best quote belongs to the selected list; honest wording above.
opps=sorted((r for r in rows if r["margin"]>0 and r["margin"]>=minimum),key=lambda r:-r["margin"])
cols=st.columns(3)
cols[0].metric("Мачове с 3 изхода",len(rows))
cols[1].metric("Арбитражи над прага",len(opps))
cols[2].metric("Най-добър ROI",f"{max((r['margin'] for r in opps),default=0):.2f}%")
st.caption(f"Последно сканиране: {latest['when']} · Проверени лиги: {len(latest['leagues'])} · Приблизително отчетени API кредити: {latest['spent']} · Последен отчетен остатък: {latest['remaining']} (при паралелни заявки може да не е крайният)")
if latest["errors"]:
    with st.expander(f"⚠️ Грешки от {len(latest['errors'])} лиги"):
        for err in latest["errors"]:st.write(err)

visible=sorted(rows,key=lambda r:-r["margin"]) if show_all else opps
if not visible:st.info("Няма резултати с избраните филтри. Това не означава, че има гарантиран арбитраж в други лиги.")
for r in visible:
    margin=r["margin"]
    with st.container(border=True):
        st.subheader(r["match"])
        st.caption(f"{r['sport']} · Начало (местно време): {pretty_date(r['kickoff'])}")
        st.markdown(f"**Теоретичен ROI: {margin:+.2f}%** {'✅' if margin>0 else '— няма арбитраж'}")
        amounts,profits=stakes(r["best"],budget)
        for i,outcome in enumerate(("1","X","2")):
            item=r["best"][outcome]
            st.write(f"**{outcome} · {item['odd']:.2f}** — {item['bookmaker']} · залог **{amounts[i]:.2f} €** · резултат {profits[i]:+.2f} €")
            if item.get("updated"):st.caption(f"Обновено: {pretty_date(item['updated'])}")
        st.caption(f"Минимален резултат след закръгляване: {min(profits):+.2f} € върху общо {budget:.2f} € (преди комисиони)")
        st.caption("⚠️ Увери се, че пазарите имат еднакви правила (90 минути), провери дали залозите са достъпни, лимитите, таксите и промените в коефициентите. Арбитражът не гарантира печалба.")
st.divider()
st.caption("Информационен инструмент. Не поставя залози и не заобикаля лимити. Източник: The Odds API.")
