"""Surebet BG 2.1 — football odds comparison, no betting execution."""
import os
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed
import requests
import streamlit as st
from engine import analyze_events, allocate, demo_events, theoretical_roi, quote_age_minutes, OUTCOMES

API = 'https://api.the-odds-api.com/v4'
st.set_page_config(page_title='Surebet BG 2.1', page_icon='⚽', layout='wide')
st.markdown('''<style>.stApp{background:#0c111c;color:#f1f5fc}
[data-testid="stMetric"]{background:#172235;border-radius:14px;padding:14px}
[data-testid="stSidebar"]{background:#1b1e24}</style>''',unsafe_allow_html=True)

CATALOG = {
    '1xBet': 'onexbet', 'Betfair Exchange (EU)': 'betfair_ex_eu',
    'Betfair Exchange (UK)': 'betfair_ex_uk', 'Betfair Sportsbook (UK)': 'betfair_sb_uk',
    'Matchbook': 'matchbook', 'Pinnacle': 'pinnacle', 'Betsson': 'betsson',
    'NordicBet': 'nordicbet', 'Marathonbet': 'marathonbet', 'Coolbet': 'coolbet',
    '888sport': 'sport888', 'BetVictor': 'betvictor', 'William Hill': 'williamhill',
    'Unibet (FR)': 'unibet_fr', 'Unibet (NL)': 'unibet_nl', 'Unibet (SE)': 'unibet_se',
    'Betclic (FR)': 'betclic_fr', 'BetAnySports': 'betanysports',
    'Betway': 'betway', 'Smarkets': 'smarkets', 'Sky Bet': 'skybet',
    'Paddy Power': 'paddypower', 'Coral': 'coral', 'Ladbrokes (UK)': 'ladbrokes_uk',
    'Betfred (UK)': 'betfred_uk', 'Winamax (FR)': 'winamax_fr',
    'Winamax (DE)': 'winamax_de', 'Tipico (DE)': 'tipico_de',
    'LeoVegas (SE)': 'leovegas_se', 'BetOnline': 'betonlineag'
}
FALLBACK = {
    'Англия · Premier League': 'soccer_epl', 'Испания · Ла Лига':'soccer_spain_la_liga',
    'Германия · Bundesliga':'soccer_germany_bundesliga',
    'Италия · Serie A':'soccer_italy_serie_a', 'Франция · Ligue 1':'soccer_france_ligue_one',
    'Шампионска лига':'soccer_uefa_champs_league',
    'Лига Европа':'soccer_uefa_europa_league',
    'Нидерландия · Eredivisie':'soccer_netherlands_eredivisie',
    'Португалия · Primeira Liga':'soccer_portugal_primeira_liga',
    'Турция · Süper Lig':'soccer_turkey_super_league',
    'Шотландия · Premiership':'soccer_spl', 'Белгия · First Division':'soccer_belgium_first_div',
    'Гърция · Super League':'soccer_greece_super_league',
    'Австрия · Bundesliga':'soccer_austria_bundesliga',
    'Швейцария · Super League':'soccer_switzerland_superleague',
    'Дания · Superliga':'soccer_denmark_superliga',
    'Полша · Ekstraklasa':'soccer_poland_ekstraklasa',
    'Норвегия · Eliteserien':'soccer_norway_eliteserien',
    'Швеция · Allsvenskan':'soccer_sweden_allsvenskan',
    'Конферентна лига':'soccer_uefa_europa_conference_league',
}

def api_key():
    key = os.environ.get('ODDS_API_KEY','').strip()
    if key:return key
    try: return str(st.secrets.get('ODDS_API_KEY','')).strip()
    except (FileNotFoundError, KeyError):return ''

@st.cache_data(ttl=3600,show_spinner=False)
def sports_catalog(key):
    r=requests.get(API+'/sports',headers={'x-api-key':key},timeout=15)
    r.raise_for_status()
    return {s['title']: s['key'] for s in r.json() if s.get('key','').startswith('soccer_') and s.get('active')}

def fetch_odds(key, sport, region):
    r=requests.get(f'{API}/sports/{sport}/odds',headers={'x-api-key':key},params={
        'regions':region,'markets':'h2h','oddsFormat':'decimal','dateFormat':'iso'},timeout=25)
    if not r.ok:
        try: msg=r.json().get('message',r.text[:100])
        except ValueError:msg=r.text[:100]
        raise RuntimeError(f'HTTP {r.status_code}: {msg}')
    data=r.json()
    if not isinstance(data,list):raise RuntimeError('Непознат API отговор')
    return data, r.headers.get('x-requests-remaining','?'),r.headers.get('x-requests-last','?')

def nice_time(raw):
    if not raw:return 'неизвестно'
    try:return datetime.fromisoformat(raw.replace('Z','+00:00')).astimezone().strftime('%d.%m.%Y %H:%M')
    except (ValueError,TypeError):return 'неизвестно'

st.title('⚽ Surebet BG 2.1')
st.caption('Избор на букмейкъри · много първенства · реална проверка · само анализ')
key=api_key()
if not key: st.warning('За реални данни добави ODDS_API_KEY в Streamlit Cloud → App settings → Secrets.')
with st.sidebar:
    st.header('⚙️ Настройки')
    mode=st.radio('Режим',['Реални коефициенти','Демо'],index=0 if key else 1)
    if mode=='Реални коефициенти' and key:
        try:sports=sports_catalog(key)
        except (requests.RequestException,ValueError,KeyError) as exc:
            st.warning('Не успях да обновя списъка с лиги. Ползвам резервен списък.')
            sports=FALLBACK
    else:sports=FALLBACK
    default_leagues=[name for name,code in sports.items() if code in {'soccer_epl','soccer_spain_la_liga','soccer_germany_bundesliga'}]
    leagues=st.multiselect('Първенства (до 20)',list(sports),default=default_leagues[:3])
    region=st.selectbox('Региони',['eu','uk','eu,uk'],index=2)
    st.subheader('🏦 Избери букмейкъри')
    st.caption('Празен избор = всички от региона. При избор арбитражът се преизчислява САМО от избраните. Регионът ограничава какво връща API.')
    books=st.multiselect('Букмейкъри',list(CATALOG),default=[],placeholder='Избери 1xBet, Matchbook, Betfair…')
    only_keys=[CATALOG[b] for b in books]
    st.caption('Избрани: '+(', '.join(books) if books else 'всички от региона'))
    st.subheader('💶 Изчисления')
    budget=st.number_input('Общ бюджет (€)',min_value=10.0,max_value=1_000_000.0,value=1000.0,step=50.0)
    min_roi=st.number_input('Минимален ROI (%)',min_value=0.0,max_value=100.0,value=1.0,step=0.25)
    max_age=st.selectbox('Максимална възраст на API котировката',[0,2,5,10,15,30,60],index=0,
                           format_func=lambda x:'Без ограничение' if x==0 else f'{x} минути')
    st.caption('При неизвестно време и активен филтър котировката се изключва.')
    st.subheader('💸 Комисиони върху печалбата')
    betfair_fee=st.number_input('Betfair Exchange (%)',0.0,20.0,2.0,0.5)
    matchbook_fee=st.number_input('Matchbook (%)',0.0,20.0,2.0,0.5)
    other_fee=st.number_input('Други борси (%)',0.0,20.0,0.0,0.5)
    fees={'betfair_ex_eu':betfair_fee,'betfair_ex_uk':betfair_fee,
          'betfair_ex_au':betfair_fee,'matchbook':matchbook_fee,'smarkets':other_fee}
    st.caption('Посочените проценти са ПРИМЕРНИ. Сложи реалната комисиона за твоя акаунт. Моделът е за BACK залози; не моделира Lay.')
    show_all=st.checkbox('Покажи и мачове без арбитраж')
    estimated=len(leagues)*(2 if region=='eu,uk' else 1)
    st.caption(f'Ориентировъчно до ~{estimated} API кредита при налични h2h котировки. Реалните кредити се отчитат от API.')
    scan=st.button('🔎 Сканирай сега',type='primary',use_container_width=True,
        disabled=not leagues or len(leagues)>20 or (mode=='Реални коефициенти' and not key))
    if len(leagues)>20:st.error('Избери максимум 20 лиги.')

# Paid API endpoints called ONLY after a deliberate click.
if scan:
    events=[]; errors=[]; counts=[]; usage=[]
    with st.spinner('Зареждам коефициентите…'):
        if mode=='Демо':
            events=[('Демо',demo_events())]
        else:
            with ThreadPoolExecutor(max_workers=3) as pool:
                pending={pool.submit(fetch_odds,key,sports[name],region):name for name in leagues}
                for fut in as_completed(pending):
                    league=pending[fut]
                    try:
                        data,remaining,last=fut.result()
                        events.append((league,data))
                        usage.append((remaining,last))
                    except (requests.RequestException,RuntimeError,ValueError) as exc:
                        errors.append(f'{league}: {exc}')
    st.session_state['snapshot']={'events':events,'errors':errors,'usage':usage,
        'mode':mode,'regions':region,'leagues':[sports[n] for n in leagues],
        'time':datetime.now(timezone.utc).isoformat()}

snapshot=st.session_state.get('snapshot')
if not snapshot:
    st.info('Отвори ⚙️ настройките, избери първенства и букмейкъри и натисни „Сканирай сега“.')
else:
    if (snapshot['mode']!=mode or snapshot['regions']!=region or
        snapshot['leagues']!=[sports[n] for n in leagues]):
        st.warning('Резултатите са от предишното сканиране. Сканирай отново при промяна на лигите/регионите.')
    if mode=='Демо' or snapshot['mode']=='Демо':st.warning('🧪 ДЕМО: измислени коефициенти — не използвай за залози.')
    else:st.success('📡 Данните са получени от The Odds API. НЕ са потвърдени като изпълними залози.')
    if snapshot['errors']:
        with st.expander(f'⚠️ Грешки при {len(snapshot["errors"])} лиги'):
            for error in snapshot['errors']:st.write(error)
    selected=set(only_keys) if books else None
    results=[]
    for league,events in snapshot['events']:
        results+=analyze_events(events,league,selected_books=selected,max_age=max_age,commissions=fees)
    results.sort(key=lambda r:r['margin'],reverse=True)
    wins=[r for r in results if r['margin']>=min_roi and r['margin']>0]
    c1,c2,c3=st.columns(3)
    c1.metric('Мачове с 3 изхода',len(results))
    c2.metric('Арбитражи над прага',len(wins))
    c3.metric('Най-добър ROI',f'{max([r["margin"] for r in wins],default=0):.2f}%')
    st.caption('Последно извличане: '+nice_time(snapshot['time'])+' · Букмейкъри: '+(', '.join(books) if books else 'всички'))
    if snapshot['usage']:
        st.caption('Остатък API според отделните отговори: '+', '.join(str(v[0]) for v in snapshot['usage'])+
                   '. При паралелни заявки стойностите не са непременно крайният остатък.')
    shown=results if show_all else wins
    if not shown:st.info('Няма достатъчно актуални котировки от избраните букмейкъри или няма арбитраж над прага.')
    for r in shown:
        with st.container(border=True):
            st.subheader(r['match'])
            st.caption(r['league']+' · Начало: '+nice_time(r['kickoff']))
            st.markdown(f'**Теоретичен ROI след зададените комисиони: {r["margin"]:+.2f}%**')
            odds=[r['best'][out]['effective_odd'] for out in OUTCOMES]
            amounts,profits=allocate(odds,budget)
            for idx,out in enumerate(OUTCOMES):
                q=r['best'][out]
                st.write(f'**{out}: {q["odd"]:.3f} — {q["bookmaker"]}** · {amounts[idx]:.2f} € · резултат {profits[idx]:+.2f} €')
                age=quote_age_minutes(q)
                st.caption('Обновено: '+nice_time(q['updated'])+' · '+
                           ('възраст неизвестна' if age is None else f'{age:.1f} мин. назад')+
                           f' · такса в модела: {q["fee"]:.1f}%')
            st.caption(f'Минимален резултат: {min(profits):+.2f} € при бюджет {budget:.2f} € (преди други такси/лимити).')
            st.warning('⚠️ Само информативно. Данните могат да са забавени; на борсата може да няма достатъчна ликвидност. '
                       'Увери се, че това е BACK за същия 90-минутен пазар, че коефициентите са налични и че имаш право да използваш съответния оператор.')

st.divider()
st.subheader('🧮 Проверка на реални коефициенти')
st.caption('Въведи коефициентите, които виждаш в букмейкърите СЕГА. Изчислението не харчи API кредити.')
cc1,cc2,cc3=st.columns(3)
with cc1:odd1=st.number_input('1 — домакин',min_value=1.01,value=1.195,step=0.01,format='%.3f')
with cc2:oddx=st.number_input('X — равен',min_value=1.01,value=8.8,step=0.1,format='%.3f')
with cc3:odd2=st.number_input('2 — гост',min_value=1.01,value=15.5,step=0.1,format='%.3f')
fee1=st.number_input('Комисиона върху печалбата на 1 (%)',0.0,20.0,0.0,0.5,key='manual1')
feex=st.number_input('Комисиона върху печалбата на X (%)',0.0,20.0,0.0,0.5,key='manualx')
fee2=st.number_input('Комисиона върху печалбата на 2 (%)',0.0,20.0,2.0,0.5,key='manual2')
effective=[1+(odd-1)*(1-fee/100) for odd,fee in zip([odd1,oddx,odd2],[fee1,feex,fee2])]
manual_roi=theoretical_roi(effective)
a,p=allocate(effective,budget)
st.metric('ROI при въведените коефициенти',f'{manual_roi:+.2f}%')
st.write('Залози: 1 = **%.2f €** · X = **%.2f €** · 2 = **%.2f €**' % tuple(a))
st.write('Минимален резултат: **%+.2f €**' % min(p))
limit=st.number_input('Налична сума за BACK на изход 2 (€), 0 = неизвестна',min_value=0.0,value=0.0,step=1.0)
if limit and a[2]>limit:st.error(f'Недостатъчна видима ликвидност за 2: нужни {a[2]:.2f} €, налични {limit:.2f} €.')
st.caption('Това е изчисление за три BACK залога, без автоматично залагане, без гаранция за наличност и без отчитане на данъци/други такси.')
