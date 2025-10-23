import os, math, requests
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
from apscheduler.schedulers.background import BackgroundScheduler
from datetime import datetime
from typing import Optional

load_dotenv()
API_KEY = os.getenv('API_KEY')
BASE_URL = os.getenv('BASE_URL', 'https://api-football-v1.p.rapidapi.com/v3')
ODDSPORTAL_KEY = os.getenv('ODDSPORTAL_KEY')
ODDSPORTAL_URL = os.getenv('ODDSPORTAL_URL', 'https://api.oddsportal.example')
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
UPDATE_INTERVAL = int(os.getenv('UPDATE_INTERVAL_MINUTES', '10'))

HEADERS = {
    "x-rapidapi-key": API_KEY,
    "x-rapidapi-host": "api-football-v1.p.rapidapi.com"
}

app = FastAPI(title='DenisPredicts v6')

app.add_middleware(
    CORSMiddleware,
    allow_origins=['*'],
    allow_credentials=True,
    allow_methods=['*'],
    allow_headers=['*'],
)

STORE = {'last_update': None, 'predictions': []}

def safe_get(d, *keys, default=None):
    cur = d
    for k in keys:
        if isinstance(cur, dict) and k in cur:
            cur = cur[k]
        else:
            return default
    return cur

def fetch(path, params=None, base=BASE_URL, headers=HEADERS):
    url = f"{base.rstrip('/')}/{path.lstrip('/')}"
    try:
        r = requests.get(url, headers=headers, params=params or {}, timeout=15)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        return {'error': str(e)}

def fetch_odds_oddsportal(fixture):
    team_home = safe_get(fixture, 'teams', 'home', 'name')
    team_away = safe_get(fixture, 'teams', 'away', 'name')
    try:
        params = {'home': team_home, 'away': team_away, 'api_key': ODDSPORTAL_KEY}
        r = requests.get(f"{ODDSPORTAL_URL}/match", params=params, timeout=10)
        r.raise_for_status()
        data = r.json()
        return {'source': 'OddsPortal', 'data': data}
    except Exception as e:
        return {'error': f'OddsPortal fetch error: {e}'}

def odds_to_prob(odds):
    try:
        return 1.0 / float(odds) if odds and float(odds) > 0 else None
    except:
        return None

def normalize_probs(probs_dict):
    s = sum([v for v in probs_dict.values() if v is not None])
    if s == 0:
        return probs_dict
    return {k: round(v/s,3) for k,v in probs_dict.items()}

def compute_market_probs(fixture_id, fixture):
    market = {'home': None, 'draw': None, 'away': None, 'sources': []}
    try:
        resp = fetch('odds', params={'fixture': fixture_id})
        if isinstance(resp, dict) and 'response' in resp:
            bookies = resp.get('response', [])
            if bookies:
                for b in bookies:
                    markets = b.get('bookmakers') or b.get('bookmaker') or []
                    for bk in markets:
                        markets_inner = bk.get('markets') or bk.get('markets', [])
                        for m in markets_inner:
                            if m.get('key') in ('h2h','1x2'):
                                outcomes = m.get('outcomes') or []
                                temp = {}
                                for o in outcomes:
                                    name = o.get('name','').lower()
                                    price = o.get('price') or o.get('odd') or o.get('odds')
                                    if 'home' in name or '1' in name:
                                        temp['home'] = odds_to_prob(price)
                                    elif 'draw' in name or 'x' in name:
                                        temp['draw'] = odds_to_prob(price)
                                    elif 'away' in name or '2' in name:
                                        temp['away'] = odds_to_prob(price)
                                if temp:
                                    market['sources'].append({'source':'api-football','raw':temp})
                                    break
    except Exception:
        pass
    op = fetch_odds_oddsportal(fixture)
    if op and isinstance(op, dict) and 'data' in op:
        d = op.get('data') or {}
        h = d.get('home_odds') or d.get('odds', {}).get('home')
        x = d.get('draw_odds') or d.get('odds', {}).get('draw')
        a = d.get('away_odds') or d.get('odds', {}).get('away')
        p = {'home': odds_to_prob(h), 'draw': odds_to_prob(x), 'away': odds_to_prob(a)}
        market['sources'].append({'source':'oddsportal','raw':p})
    sums = {'home':0.0,'draw':0.0,'away':0.0}
    counts = {'home':0,'draw':0,'away':0}
    for s in market['sources']:
        raw = s.get('raw',{})
        for k in ('home','draw','away'):
            v = raw.get(k)
            if v:
                sums[k] += v
                counts[k] += 1
    avg = {}
    for k in ('home','draw','away'):
        if counts[k] > 0:
            avg[k] = round(sums[k]/counts[k],4)
        else:
            avg[k] = None
    if any(avg[k] for k in avg):
        norm = normalize_probs({k:avg[k] if avg[k] else 0 for k in avg})
        market['market_prob'] = norm
    else:
        market['market_prob'] = {'home':0.45,'draw':0.25,'away':0.30}
    return market

def get_recent_team_matches(team_id: int, last: int = 8):
    data = fetch('fixtures', params={'team': team_id, 'last': last})
    return data.get('response', []) if isinstance(data, dict) else []

def compute_goal_avg(team_id: Optional[int], last=8):
    if not team_id:
        return 1.1
    matches = get_recent_team_matches(team_id, last=last)
    total = 0
    count = 0
    for m in matches:
        home_id = safe_get(m, 'teams', 'home', 'id')
        away_id = safe_get(m, 'teams', 'away', 'id')
        home_goals = safe_get(m, 'goals', 'home')
        away_goals = safe_get(m, 'goals', 'away')
        if home_goals is None or away_goals is None:
            home_goals = safe_get(m, 'score', 'fulltime', 'home')
            away_goals = safe_get(m, 'score', 'fulltime', 'away')
        if home_goals is None or away_goals is None:
            continue
        if team_id == home_id:
            total += home_goals
            count += 1
        elif team_id == away_id:
            total += away_goals
            count += 1
    return (total / count) if count > 0 else 1.1

def compute_yellow_cards_avg(team_id: Optional[int], last=8):
    if not team_id:
        return 1.3
    matches = get_recent_team_matches(team_id, last=last)
    total = 0
    count = 0
    for m in matches:
        fixture_id = safe_get(m, 'fixture', 'id')
        ev = fetch(f'fixtures/events', params={'fixture': fixture_id})
        events = ev.get('response', []) if isinstance(ev, dict) else []
        yc = 0
        for e in events:
            if safe_get(e, 'type') in ('Card','Yellow Card','Yellow') or safe_get(e,'detail') in ('Yellow Card',):
                t = safe_get(e, 'team', 'id')
                if t == team_id:
                    yc += 1
        total += yc
        count += 1
    return (total / count) if count>0 else 1.3

def poisson_prob(k, lam):
    return (lam**k) * math.exp(-lam) / math.factorial(k)

def poisson_matrix(lambda_home, lambda_away, max_goals=6):
    probs = {}
    for i in range(max_goals+1):
        for j in range(max_goals+1):
            probs[f"{i}:{j}"] = poisson_prob(i, lambda_home) * poisson_prob(j, lambda_away)
    sorted_scores = sorted(probs.items(), key=lambda x: x[1], reverse=True)
    return sorted_scores

def derive_1x2(lambda_home, lambda_away, max_goals=6):
    scores = poisson_matrix(lambda_home, lambda_away, max_goals=max_goals)
    p_home = p_away = p_draw = 0.0
    for s,prob in scores:
        h,a = map(int, s.split(':'))
        if h>a: p_home += prob
        elif a>h: p_away += prob
        else: p_draw += prob
    total = p_home + p_away + p_draw
    if total==0:
        return {'home':0.45,'draw':0.25,'away':0.30}
    return {'home': round(p_home/total,3), 'draw': round(p_draw/total,3), 'away': round(p_away/total,3)}

def analyze_fixture(f):
    fid = safe_get(f, 'fixture', 'id')
    home = safe_get(f, 'teams', 'home', 'name', default='Home')
    away = safe_get(f, 'teams', 'away', 'name', default='Away')
    home_id = safe_get(f, 'teams', 'home', 'id')
    away_id = safe_get(f, 'teams', 'away', 'id')
    home_avg = compute_goal_avg(home_id, last=8)
    away_avg = compute_goal_avg(away_id, last=8)
    lambda_home = home_avg * 1.06
    lambda_away = away_avg
    top_scores = poisson_matrix(lambda_home, lambda_away, max_goals=6)[:6]
    probs = derive_1x2(lambda_home, lambda_away, max_goals=6)
    exp_total = lambda_home + lambda_away
    total_pred = 'ТБ(2.5)' if exp_total >= 2.5 else 'ТМ(2.5)'
    home_yc = compute_yellow_cards_avg(home_id, last=8)
    away_yc = compute_yellow_cards_avg(away_id, last=8)
    avg_yc = round(home_yc + away_yc,2)
    yc_pred = 'ТБ(3.5)' if avg_yc >= 3.5 else 'ТМ(3.5)'
    market = compute_market_probs(fid, f)
    market_probs = market.get('market_prob', {'home':0.45,'draw':0.25,'away':0.30})
    ai_top = max(probs, key=lambda k: probs[k])
    ai_top_prob = probs[ai_top]
    market_top_prob = market_probs.get(ai_top, 0)
    value_index = round(ai_top_prob - market_top_prob,3)
    return {
        'fixture_id': fid,
        'home': home,
        'away': away,
        'lambda_home': round(lambda_home,2),
        'lambda_away': round(lambda_away,2),
        'exp_total': round(exp_total,2),
        'total_pred': total_pred,
        'probabilities': probs,
        'top_scores': [(s, round(p,4)) for s,p in top_scores],
        'confidence': max(probs['home'], probs['away']),
        'avg_yellow_cards': avg_yc,
        'yc_pred': yc_pred,
        'market': market,
        'value_index': value_index
    }

def update_all():
    print(f'[{datetime.utcnow().isoformat()}] Updating predictions (v6)...')
    data = fetch('fixtures', params={'next':40})
    fixtures = data.get('response', []) if isinstance(data, dict) else []
    preds = []
    for f in fixtures:
        try:
            preds.append(analyze_fixture(f))
        except Exception as e:
            print('analyze error', e)
    STORE['last_update'] = datetime.utcnow().isoformat()
    STORE['predictions'] = preds
    print(f'Updated {len(preds)} items')

scheduler = BackgroundScheduler()
scheduler.add_job(update_all, 'interval', minutes=UPDATE_INTERVAL, next_run_time=datetime.utcnow())
scheduler.start()

@app.get('/')
def root():
    return {'message':'DenisPredicts v6'}

@app.get('/predictions')
def predictions():
    return STORE

@app.get('/analyze/{fixture_id}')
def analyze_route(fixture_id: int):
    data = fetch('fixtures', params={'fixture': fixture_id})
    fixtures = data.get('response', []) if isinstance(data, dict) else []
    if not fixtures:
        raise HTTPException(status_code=404, detail='Матч не найден')
    return analyze_fixture(fixtures[0])

@app.get('/ai/explain/{fixture_id}')
def ai_explain(fixture_id: int):
    preds = STORE.get('predictions', [])
    pred = next((p for p in preds if p.get('fixture_id')==fixture_id), None)
    if not pred:
        raise HTTPException(status_code=404, detail='Прогноз не найден')
    if OPENAI_API_KEY:
        try:
            import openai
            openai.api_key = OPENAI_API_KEY
            prompt = f"Дай подробное объяснение прогноза на русском для матча {pred['home']} vs {pred['away']}.\nДанные: {pred}\nПоясни почему такой прогноз и дай рекомендации по ставкам кратко."
            resp = openai.ChatCompletion.create(model='gpt-4o-mini', messages=[{'role':'user','content':prompt}], max_tokens=400)
            text = resp['choices'][0]['message']['content']
            return {'explanation': text}
        except Exception as e:
            return {'explanation': f'Ошибка OpenAI: {e}', 'data': pred}
    lines = []
    lines.append(f"Прогноз на матч {pred['home']} — {pred['away']}: {pred['total_pred']}, 1X2: хозяева {int(pred['probabilities']['home']*100)}%, ничья {int(pred['probabilities']['draw']*100)}%, гости {int(pred['probabilities']['away']*100)}%.")
    lines.append(f"Value Index: {pred.get('value_index')}")
    lines.append('Рекомендация: сравнивать с линией букмекера и учитывать корреляцию событий.')
    return {'explanation': '\n'.join(lines)}
