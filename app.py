"""Surebet BG 3.0 — football odds comparison, no betting execution."""
import os
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed
import requests
import streamlit as st
from engine import analyze_events, allocate, demo_events, theoretical_roi, quote_age_minutes, effective_odd, liquidity_check, OUTCOMES

API = 'https://api.the-odds-api.com/v4'
st.set_page_config(page_title='Surebet BG 3.0', page_icon='⚽', layout='wide')
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

def fetch_odds(key, sport, region, bookmaker_keys=None, event_id=None):
    params={'regions':region,'markets':'h2h','oddsFormat':'decimal','dateFormat':'iso'}
    if bookmaker_keys: params['bookmakers']=','.join(bookmaker_keys)
    if event_id: params['eventIds']=str(event_id)
    r=requests.get(f'{API}/sports/{sport}/odds',headers={'x-api-key':key},params=params,timeout=25)
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

st.title('⚽ Surebet BG 3.0')
st.caption('Проверка на свежестта · повторна API проверка · ръчно потвърждение · само анализ')
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
    books=st.multiselect('Букмейкъри',list(CATALOG),default=['1xBet','Betfair Exchange (EU)','Matchbook'],placeholder='Избери букмейкъри…')
    only_keys=[CATALOG[b] for b in books]
    st.caption('Избрани: '+(', '.join(books) if books else 'всички от региона'))
    if not books:st.warning('Няма избрани букмейкъри: ще сравняваме всички от региона.')
    st.subheader('💶 Изчисления')
    budget=st.number_input('Общ бюджет (€)',min_value=10.0,max_value=1_000_000.0,value=1000.0,step=50.0)
    min_roi=st.number_input('Минимален ROI (%)',min_value=0.0,max_value=100.0,value=1.0,step=0.25)
    max_age=st.selectbox('Максимална възраст на API котировката',[2,5,10,15,30,60,0],index=1,
                           format_func=lambda x:'Без ограничение' if x==0 else f'{x} минути')
    st.caption('По подразбиране са 5 минути. Котировки без час на обновяване се изключват при активен филтър.')
    max_snapshot_age=st.selectbox('Максимална възраст на сканирането (минути)',[2,5,10,15],index=1)
    min_kickoff_buffer=st.number_input('Не показвай мачове, започващи след по-малко от (мин.)',0,120,10,5)
    st.subheader('💸 Комисиони върху печалбата')
    betfair_fee=st.number_input('Betfair Exchange (%)',0.0,20.0,2.0,0.5)
    matchbook_fee=st.number_input('Matchbook (%)',0.0,20.0,2.0,0.5)
    other_fee=st.number_input('Други борси (%)',0.0,20.0,0.0,0.5)
    fees={'betfair_ex_eu':betfair_fee,'betfair_ex_uk':betfair_fee,
          'betfair_ex_au':betfair_fee,'matchbook':matchbook_fee,'smarkets':other_fee}
    st.caption('Посочените проценти са ПРИМЕРНИ. Сложи реалната комисиона за твоя акаунт. Моделът е за BACK залози; не моделира Lay.')
    show_all=st.checkbox('Покажи и мачове без арбитраж')
    estimated=len(leagues)*(max(1,(len(only_keys)+9)//10) if only_keys else (2 if region=='eu,uk' else 1))
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
                pending={pool.submit(fetch_odds,key,sports[name],region,only_keys or None):name for name in leagues}
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
        'books':list(only_keys),'time':datetime.now(timezone.utc).isoformat()}

snapshot=st.session_state.get('snapshot')
if not snapshot:
    st.info('Отвори ⚙️ настройките, избери първенства и букмейкъри и натисни „Сканирай сега“.')
else:
    config_changed=(snapshot['mode']!=mode or snapshot['regions']!=region or
        snapshot.get('books',[])!=only_keys or snapshot['leagues']!=[sports[n] for n in leagues])
    if config_changed:
        st.error('⛔ Настройките са променени след последното сканиране. Сканирай отново; старите кандидати са скрити.')
    if mode=='Демо' or snapshot['mode']=='Демо':st.warning('🧪 ДЕМО: измислени коефициенти — не използвай за залози.')
    else:st.success('📡 Данните са получени от The Odds API. НЕ са потвърдени като изпълними залози.')
    if snapshot['errors']:
        with st.expander(f'⚠️ Грешки при {len(snapshot["errors"])} лиги'):
            for error in snapshot['errors']:st.write(error)
    scan_age=quote_age_minutes({'updated':snapshot['time']})
    snapshot_stale=(scan_age is None or scan_age > max_snapshot_age)
    if snapshot_stale:st.error('⛔ Последното API сканиране е остаряло. Не използвай показаните стойности — направи ново сканиране.')
    selected=set(only_keys) if books else None
    results=[]
    for league,events in snapshot['events']:
        results+=analyze_events(events,league,selected_books=selected,max_age=max_age,commissions=fees)
    from datetime import timedelta
    results=[r for r in results if datetime.fromisoformat(r['kickoff'].replace('Z','+00:00'))>datetime.now(timezone.utc)+timedelta(minutes=min_kickoff_buffer)]
    results.sort(key=lambda r:r['margin'],reverse=True)
    wins=[r for r in results if r['margin']>=min_roi and r['margin']>0]
    if snapshot_stale or config_changed:results=[];wins=[]
    c1,c2,c3=st.columns(3)
    c1.metric('Мачове с 3 изхода',len(results))
    c2.metric('Арбитражи над прага',len(wins))
    c3.metric('Най-добър ROI',f'{max([r["margin"] for r in wins],default=0):.2f}%')
    st.caption('Последно извличане: '+nice_time(snapshot['time'])+' · Букмейкъри: '+(', '.join(books) if books else 'всички'))
    if snapshot['usage']:
        st.caption('Остатък API според отделните отговори: '+', '.join(str(v[0]) for v in snapshot['usage'])+
                   '. При паралелни заявки стойностите не са непременно крайният остатък.')
    shown=results if show_all else wins
    if snapshot_stale or config_changed:shown=[]
    if not shown:st.info('Няма достатъчно актуални котировки от избраните букмейкъри или няма арбитраж над прага.')
    for r in shown:
        with st.container(border=True):
            st.subheader(r['match'])
            st.caption('⚠️ API кандидат, НЕ потвърден залог. Дори свеж API час не доказва наличие на коефициента или ликвидност.')
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
            if r['id'] and snapshot['mode']=='Реални коефициенти':
                if st.button('🔄 Провери този мач отново през API (харчи кредити)',key='check_'+str(r['id'])+'_'+str(r['league'])):
                    sport_key=r.get('sport_key') or next((sports[name] for name in leagues if name==r['league']),None)
                    try:
                        if not sport_key:raise ValueError('Липсва код на лигата')
                        data,remaining,_=fetch_odds(key,sport_key,region,only_keys or None,r['id'])
                        fresh=analyze_events(data,r['league'],selected_books=selected,max_age=max_age,commissions=fees)
                        matching=next((x for x in fresh if x['id']==r['id']),None)
                        if not matching:st.error('Мачът/една от трите котировки липсва или е твърде стара при новата API заявка.')
                        else:
                            new_roi=matching['margin']
                            st.write(f'Нов API ROI: **{new_roi:+.2f}%** (предишен: {r["margin"]:+.2f}%). Остатък API: {remaining}')
                            for o in OUTCOMES:
                                old,new=r['best'][o],matching['best'][o]
                                st.write(f'{o}: {old["odd"]:.3f} → **{new["odd"]:.3f}** ({new["bookmaker"]})')
                            if new_roi<=0:st.error('При новата API проверка няма положителен теоретичен арбитраж.')
                            else:st.warning('⚠️ Потвърдено само от API, НЕ от букмейкърите. Провери ръчно трите BACK котировки и суми.')
                    except (requests.RequestException,RuntimeError,ValueError) as exc:st.error('Неуспешна API проверка: '+str(exc))
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
effective=[effective_odd(odd,fee) for odd,fee in zip([odd1,oddx,odd2],[fee1,feex,fee2])]
manual_roi=theoretical_roi(effective)
a,p=allocate(effective,budget)
st.metric('ROI при въведените коефициенти',f'{manual_roi:+.2f}%')
st.write('Залози: 1 = **%.2f €** · X = **%.2f €** · 2 = **%.2f €**' % tuple(a))
st.write('Минимален резултат: **%+.2f €**' % min(p))
st.subheader('🛡️ Ръчно потвърждение на изпълнимостта')
st.caption('За всеки изход въведи наличната максимална сума за BACK на ТОЗИ коефициент. 0 означава неизвестно, не нула наличност.')
limits=[]
for out in OUTCOMES:
    limits.append(st.number_input(f'Налична сума за {out} (€; 0 = неизвестно)',min_value=0.0,value=0.0,step=1.0,key='liquidity_'+out))
check=liquidity_check(effective,budget,[v if v>0 else None for v in limits])
if check['unknown']:st.warning('Непотвърдена ликвидност за поне един изход. Не приемай арбитража за изпълним.')
if any(v>0 and a[i]>v for i,v in enumerate(limits)):
    st.error('⛔ Недостатъчна посочена ликвидност. Нужни залози: '+', '.join(f'{o}: {a[i]:.2f} €' for i,o in enumerate(OUTCOMES)))
elif check['enough'] and manual_roi>0:
    st.info('Въведените суми покриват залозите, но все още провери достъпността, пазара, правилата и лимитите в акаунтите.')
if manual_roi<=0:st.error('⛔ Няма положителен арбитраж при въведените коефициенти.')
st.caption('Това е изчисление за три BACK залога, без автоматично залагане, без гаранция за наличност и без отчитане на данъци/други такси.')
