"""
🤖 Ultra Scalping Bot v5.0 - Clean Edition
مضاربة احترافية | Twelve Data | Yahoo Finance | Finnhub
"""
import os, logging, asyncio, aiohttp, time
from datetime import datetime, timezone, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters

# ══════════════════════════════════════════════
# CONFIG — ضع مفاتيحك هنا أو في Railway Variables
# ══════════════════════════════════════════════
TELEGRAM_TOKEN  = os.getenv("TELEGRAM_BOT_TOKEN", "")
ANTHROPIC_KEY   = os.getenv("ANTHROPIC_API_KEY",  "")
FINNHUB_KEY     = os.getenv("FINNHUB_API_KEY",    "")
TWELVE_KEY      = os.getenv("TWELVE_DATA_KEY",    "")

ALERT_CHATS: list[int] = []
MIN_SCORE     = 72
MIN_CONFIRMS  = 5
SCAN_SEC      = 240
MAX_HR        = 12
COOLDOWN_MIN  = 90
DANGER_SC     = 65

WATCHLIST = [
    "AAPL","MSFT","NVDA","GOOGL","AMZN","META","TSLA","AVGO","ORCL","CRM",
    "AMD","INTC","QCOM","MU","AMAT","LRCX","MRVL","SMCI","ARM","KLAC",
    "JPM","BAC","WFC","GS","MS","BLK","V","MA","AXP","SCHW",
    "LLY","JNJ","UNH","ABBV","MRK","PFE","AMGN","GILD","REGN","VRTX",
    "MRNA","ISRG","DXCM","ABT","COST","WMT","HD","MCD","NKE","TGT",
    "XOM","CVX","COP","SLB","EOG","OXY","HAL","CAT","DE","BA",
    "NFLX","DIS","SNAP","RBLX","SPOT","NOW","SNOW","PLTR","DDOG","CRWD",
    "MSTR","COIN","HOOD","SOFI","AFRM","RKLB","IONQ","UBER","ABNB","DASH",
    "RIVN","NIO","LI","XPEV","SQ","PYPL","MELI","NET","MDB","ADBE",
    "SPY","QQQ","IWM","XLF","XLK","XLE","SOXL","TQQQ","ARKK","DIA",
]

logging.basicConfig(format="%(asctime)s | %(levelname)s | %(message)s", level=logging.INFO)
log = logging.getLogger(__name__)

alert_count = 0; hour_reset = time.time()
alerted: dict[str,float] = {}; danger_alerted: dict[str,float] = {}
active = True
stats = {"scanned":0,"found":0,"sent":0,"danger":0,"rejected":0,"time":"","last":"—"}
fg_cache = {"value":50,"label":"محايد","ts":0}
trades: list[dict] = []


# ══════════════════════════════════════════════
# SESSION
# ══════════════════════════════════════════════
def session():
    m = datetime.now(timezone.utc).hour*60 + datetime.now(timezone.utc).minute
    if 780<=m<810:    return "🌅 Pre-Market"
    elif 810<=m<1200: return "📈 Regular"
    elif 1200<=m<1440:return "🌙 After-Hours"
    else:             return "🌃 Overnight"


# ══════════════════════════════════════════════
# DATA
# ══════════════════════════════════════════════
async def get_candles(sym: str, interval: str, count: int = 80) -> dict:
    """Twelve Data — شموع 15 دقيقة أو ساعة"""
    url = "https://api.twelvedata.com/time_series"
    params = {
        "symbol": sym, "interval": interval,
        "outputsize": count, "apikey": TWELVE_KEY,
        "format": "JSON", "order": "ASC"
    }
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(url, params=params, timeout=aiohttp.ClientTimeout(total=12)) as r:
                data = await r.json()
        if data.get("status") == "error" or "values" not in data:
            return {}
        vals = data["values"]
        c=[float(v["close"]) for v in vals]; o=[float(v["open"]) for v in vals]
        h=[float(v["high"]) for v in vals];  l=[float(v["low"]) for v in vals]
        vol=[float(v.get("volume",0)) for v in vals]
        if len(c) < 20: return {}
        return {"c":c,"o":o,"h":h,"l":l,"v":vol}
    except Exception as e:
        log.debug(f"TD {sym} {interval}: {e}"); return {}


async def get_daily(sym: str) -> dict:
    """Yahoo Finance — يومي للاتجاه العام"""
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}"
    hdr = {"User-Agent":"Mozilla/5.0","Accept":"application/json"}
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(url, params={"interval":"1d","range":"2mo"},
                             headers=hdr, timeout=aiohttp.ClientTimeout(total=10)) as r:
                data = await r.json()
        res=data["chart"]["result"][0]; q=res["indicators"]["quote"][0]
        cl=lambda x:[i for i in x if i is not None]
        c=cl(q.get("close",[])); h=cl(q.get("high",[]))
        l=cl(q.get("low",[]));   v=cl(q.get("volume",[]))
        n=min(len(c),len(h),len(l),len(v))
        if n<15: return {}
        return {"c":c[-n:],"h":h[-n:],"l":l[-n:],"v":v[-n:],
                "name":res.get("meta",{}).get("shortName",sym)}
    except Exception as e:
        log.debug(f"Yahoo {sym}: {e}"); return {}


async def get_fg() -> dict:
    global fg_cache
    if time.time()-fg_cache["ts"] < 3600: return fg_cache
    try:
        url = "https://production.dataviz.cnn.io/index/fearandgreed/graphdata"
        async with aiohttp.ClientSession() as s:
            async with s.get(url, headers={"User-Agent":"Mozilla/5.0"},
                             timeout=aiohttp.ClientTimeout(total=8)) as r:
                d = await r.json()
        v = float(d["fear_and_greed"]["score"])
        lb = ("😱 خوف شديد" if v<=25 else "😟 خوف" if v<=45
              else "😐 محايد" if v<=55 else "😊 طمع" if v<=75 else "🤑 طمع شديد")
        fg_cache = {"value":v,"label":lb,"ts":time.time()}
    except: pass
    return fg_cache


async def get_sentiment(sym: str) -> tuple[float,int]:
    try:
        url = f"https://finnhub.io/api/v1/news-sentiment?symbol={sym}&token={FINNHUB_KEY}"
        async with aiohttp.ClientSession() as s:
            async with s.get(url, timeout=aiohttp.ClientTimeout(total=5)) as r:
                d = await r.json()
        return d.get("companyNewsScore",0.5), d.get("buzz",{}).get("articlesInLastWeek",0)
    except: return 0.5, 0


async def get_news(sym: str) -> list:
    try:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        url = f"https://finnhub.io/api/v1/company-news?symbol={sym}&from={today}&to={today}&token={FINNHUB_KEY}"
        async with aiohttp.ClientSession() as s:
            async with s.get(url, timeout=aiohttp.ClientTimeout(total=5)) as r:
                d = await r.json()
        return d[:3] if isinstance(d,list) else []
    except: return []


# ══════════════════════════════════════════════
# INDICATORS
# ══════════════════════════════════════════════
def calc_rsi(p, n=14):
    if len(p)<n+1: return 50.0
    g=[max(p[i]-p[i-1],0) for i in range(1,len(p))]
    l=[max(p[i-1]-p[i],0) for i in range(1,len(p))]
    ag=sum(g[-n:])/n; al=sum(l[-n:])/n
    return round(100-(100/(1+ag/al)),2) if al else 100.0

def calc_ema(p, n):
    if len(p)<n: return p
    k=2/(n+1); e=[sum(p[:n])/n]
    for x in p[n:]: e.append(x*k+e[-1]*(1-k))
    return e

def calc_macd(p):
    if len(p)<26: return None,None,None
    e12=calc_ema(p,12); e26=calc_ema(p,26); n=min(len(e12),len(e26))
    ml=[e12[-n+i]-e26[-n+i] for i in range(n)]; sg=calc_ema(ml,9)
    return (round(ml[-1],5),round(sg[-1],5),round(ml[-1]-sg[-1],5)) if sg else (None,None,None)

def calc_bb(p, n=20):
    if len(p)<n: return None,None,None
    r=p[-n:]; m=sum(r)/n; std=(sum((x-m)**2 for x in r)/n)**0.5
    return round(m+2*std,4), round(m,4), round(m-2*std,4)

def calc_stoch(h, l, c, n=14):
    if len(c)<n: return 50.0,50.0
    rh=max(h[-n:]); rl=min(l[-n:])
    if rh==rl: return 50.0,50.0
    k=((c[-1]-rl)/(rh-rl))*100
    rh2=max(h[-n-1:-1]) if len(h)>n else rh
    rl2=min(l[-n-1:-1]) if len(l)>n else rl
    k2=((c[-2]-rl2)/(rh2-rl2))*100 if rh2!=rl2 and len(c)>n else k
    return round(k,2), round((k+k2)/2,2)

def calc_atr(h, l, c, n=14):
    if len(c)<n+1: return 0.0
    trs=[max(h[i]-l[i],abs(h[i]-c[i-1]),abs(l[i]-c[i-1])) for i in range(1,len(c))]
    return round(sum(trs[-n:])/n, 5)

def calc_vwap(h, l, c, v):
    if not v or sum(v)==0: return c[-1]
    tp=[(h[i]+l[i]+c[i])/3 for i in range(len(c))]
    return round(sum(tp[i]*v[i] for i in range(len(c)))/sum(v), 4)

def calc_wr(h, l, c, n=14):
    if len(c)<n: return -50.0
    rh=max(h[-n:]); rl=min(l[-n:])
    return round(((rh-c[-1])/(rh-rl))*-100, 2) if rh!=rl else -50.0

def calc_cci(h, l, c, n=14):
    if len(c)<n: return 0.0
    tp=[(h[i]+l[i]+c[i])/3 for i in range(len(c))]
    tp_n=tp[-n:]; mean=sum(tp_n)/n
    mad=sum(abs(x-mean) for x in tp_n)/n
    return round((tp[-1]-mean)/(0.015*mad), 2) if mad else 0.0

def calc_adx(h, l, c, n=14):
    if len(c)<n+2: return 25.0,0.0,0.0
    trl=[]; dmp=[]; dmm=[]
    for i in range(1,len(c)):
        tr=max(h[i]-l[i],abs(h[i]-c[i-1]),abs(l[i]-c[i-1]))
        trl.append(tr)
        up=h[i]-h[i-1]; dn=l[i-1]-l[i]
        dmp.append(up if up>dn and up>0 else 0)
        dmm.append(dn if dn>up and dn>0 else 0)
    at=sum(trl[-n:])/n if trl else 1
    dip=100*(sum(dmp[-n:])/n)/at if at else 0
    dim=100*(sum(dmm[-n:])/n)/at if at else 0
    dx=100*abs(dip-dim)/(dip+dim) if (dip+dim)>0 else 0
    return round(dx,2), round(dip,2), round(dim,2)

def calc_momentum(c, n=10):
    if len(c)<n+1: return 0.0
    return round((c[-1]-c[-n])/c[-n]*100, 3)

def calc_breakout(h, l, c, v, n=20):
    if len(c)<n+2: return "NONE", 0, 1.0
    res=max(h[-n-1:-1]); sup=min(l[-n-1:-1])
    avg_v=sum(v[-n-1:-1])/n if n>0 else 1
    vr=round(v[-1]/avg_v, 1) if avg_v else 1
    if c[-1]>res*1.002 and vr>=1.5: return "BULL", min(int((c[-1]/res-1)*500+vr*10),50), vr
    elif c[-1]<sup*0.998 and vr>=1.5: return "BEAR", 40, vr
    return "NONE", 0, vr

def detect_patterns(o, h, l, c):
    if len(c)<3: return []
    pts=[]
    p,ph,pl,po = c[-1],h[-1],l[-1],o[-1]
    p2,ph2,pl2,po2 = c[-2],h[-2],l[-2],o[-2]
    body=abs(p-po); rng=ph-pl
    body2=abs(p2-po2); rng2=ph2-pl2
    if body>0 and rng>0:
        lw=min(p,po)-pl; uw=ph-max(p,po)
        if lw>=body*2 and uw<=body*0.3 and p>po: pts.append("Hammer🔨")
        if uw>=body*2 and lw<=body*0.3 and p<po: pts.append("ShootingStar💫")
    if rng>0 and body/rng<0.1: pts.append("Doji✙")
    if p>po and p2<po2 and p>po2 and po<p2: pts.append("BullEngulf🕯️")
    if p<po and p2>po2 and p<po2 and po>p2: pts.append("BearEngulf🕯️")
    if len(c)>=3:
        p3=c[-3]; po3=o[-3]
        if p3<po3 and body2/max(rng2,0.001)<0.3 and p>po and p>(p3+po3)/2:
            pts.append("MorningStar⭐")
        if p3>po3 and body2/max(rng2,0.001)<0.3 and p<po and p<(p3+po3)/2:
            pts.append("EveningStar🌙")
        if p>po and p2>po2 and p3>po3 and p>p2>p3: pts.append("3Soldiers💪")
        if p<po and p2<po2 and p3<po3 and p<p2<p3: pts.append("3Crows🐦")
    return pts


def analyze(d: dict) -> dict:
    if not d: return {}
    c=d.get("c",[]); o=d.get("o",c)
    h=d.get("h",[]); l=d.get("l",[]); v=d.get("v",[])
    if len(c)<20: return {}
    MC,MS,MH = calc_macd(c)
    BU,BM,BL = calc_bb(c)
    SK,SD    = calc_stoch(h,l,c)
    AT       = calc_atr(h,l,c)
    VP       = calc_vwap(h,l,c,v)
    WR       = calc_wr(h,l,c)
    CC       = calc_cci(h,l,c)
    ADX,DIP,DIM = calc_adx(h,l,c)
    MOM      = calc_momentum(c)
    PTS      = detect_patterns(o,h,l,c)
    BRK,BS,BV= calc_breakout(h,l,c,v)
    e9  = round(calc_ema(c,9)[-1],4)  if len(c)>=9  else None
    e21 = round(calc_ema(c,21)[-1],4) if len(c)>=21 else None
    e50 = round(calc_ema(c,50)[-1],4) if len(c)>=50 else None
    avg_v=sum(v[-20:])/20 if len(v)>=20 else 1
    vr=round(v[-1]/avg_v,2) if avg_v else 1.0
    rv5=round(v[-1]/(sum(v[-5:])/5),2) if len(v)>=5 and sum(v[-5:])>0 else 1.0
    chg=round((c[-1]-c[-2])/c[-2]*100,3) if len(c)>1 else 0
    sp=sum(1 for i in range(min(5,len(c)-1)) if c[-i-1]<o[-i-1])/min(5,len(c)-1)*100 if len(c)>1 else 0
    return dict(
        price=round(c[-1],4), chg=chg, high=round(h[-1],4), low=round(l[-1],4),
        rsi=calc_rsi(c), macd=MC, macd_sig=MS, macd_hist=MH,
        bb_u=BU, bb_m=BM, bb_l=BL, atr=AT, sk=SK, sd=SD, vwap=VP,
        wr=WR, cci=CC, adx=ADX, di_plus=DIP, di_minus=DIM, mom=MOM,
        e9=e9, e21=e21, e50=e50,
        sup=round(min(l[-20:]),4), res=round(max(h[-20:]),4),
        vr=vr, rv5=rv5, vol=int(v[-1]) if v else 0,
        pts=PTS, brk=BRK, brk_str=BS, brk_vr=BV, sell_press=sp,
        trend=sum(1 for i in range(1,min(8,len(c))) if c[-i]>c[-i-1])
    )


# ══════════════════════════════════════════════
# SCORING — نظام التقييم
# ══════════════════════════════════════════════
def score_tf(t: dict, label: str) -> tuple[int, list, int]:
    if not t: return 0, [], 0
    s=0; R=[]; conf=0; p=t.get("price",0)
    r=t.get("rsi",50)
    if r<25:   s+=20; R.append(f"[{label}] RSI={r} 🔥 ذروة بيع"); conf+=1
    elif r<35: s+=14; R.append(f"[{label}] RSI={r} شراء"); conf+=1
    elif r<45: s+=7
    elif r>75: s-=18
    elif r>65: s-=10
    mh=t.get("macd_hist"); mc=t.get("macd"); ms=t.get("macd_sig")
    if mh is not None:
        if mh>0 and mc and ms and mc>ms: s+=16; R.append(f"[{label}] MACD ✅"); conf+=1
        elif mh>0: s+=8
        elif mh<0: s-=10
    k=t.get("sk",50); d=t.get("sd",50)
    if k<15 and d<15:  s+=15; R.append(f"[{label}] Stoch={k:.0f} 🔥"); conf+=1
    elif k<25:         s+=9; conf+=1
    elif k>d and k<40: s+=6
    elif k>80:         s-=12
    bl=t.get("bb_l"); bu=t.get("bb_u")
    if bl and p<=bl:        s+=15; R.append(f"[{label}] تحت BB 🎯"); conf+=1
    elif bl and p<=bl*1.01: s+=9; conf+=1
    elif bu and p>=bu*0.99: s-=14
    w=t.get("wr",-50)
    if w<-80:  s+=9; R.append(f"[{label}] WR={w}"); conf+=1
    elif w<-60:s+=5
    elif w>-20:s-=8
    cc=t.get("cci",0)
    if cc<-150: s+=9; R.append(f"[{label}] CCI={cc:.0f}"); conf+=1
    elif cc<-100:s+=5
    ax=t.get("adx",25); dip=t.get("di_plus",0); dim=t.get("di_minus",0)
    if ax>=30 and dip>dim: s+=10; R.append(f"[{label}] ADX={ax} 💪"); conf+=1
    elif ax>=25: s+=4
    mom=t.get("mom",0)
    if mom>1.5: s+=8; R.append(f"[{label}] Mom={mom}%")
    elif mom>0: s+=3
    elif mom<-2:s-=8
    e9=t.get("e9"); e21=t.get("e21"); e50=t.get("e50")
    if e9 and e21 and e9>e21: s+=6; R.append(f"[{label}] EMA9>21")
    if e21 and e50 and e21>e50:s+=4
    vp=t.get("vwap")
    if vp and p>vp: s+=7; conf+=1
    elif vp and p<vp*0.99: s-=5
    sup=t.get("sup"); res=t.get("res")
    if sup and p<=sup*1.015: s+=8; R.append(f"[{label}] دعم ${sup}"); conf+=1
    if res and p>=res*0.985: s-=8
    vr=t.get("vr",1); rv=t.get("rv5",1)
    if vr>=3 and rv>=2:  s+=15; R.append(f"[{label}] حجم {vr:.1f}x 🔥🔥🔥"); conf+=1
    elif vr>=2:          s+=10; R.append(f"[{label}] حجم {vr:.1f}x 🔥🔥")
    elif vr>=1.5:        s+=6;  R.append(f"[{label}] حجم {vr:.1f}x 🔥")
    elif vr<0.5:         s-=10
    brk=t.get("brk","NONE")
    if brk=="BULL": s+=14; R.append(f"[{label}] 🚀 Breakout {t.get('brk_vr')}x"); conf+=1
    elif brk=="BEAR":s-=12
    bull_pts=[x for x in t.get("pts",[]) if any(b in x for b in ["Hammer","BullEngulf","MorningStar","3Soldiers"])]
    if bull_pts: s+=min(len(bull_pts)*6,12); R.append(f"[{label}] {' '.join(bull_pts)}"); conf+=1
    return min(s,100), R, conf


def multi_score(t15, t1h, t1d, fg, sent) -> tuple[int, str, list, int]:
    if not t15: return 0,"NONE",[],0
    s15,r15,c15 = score_tf(t15,"15m")
    s1h,r1h,c1h = score_tf(t1h,"1h") if t1h else (0,[],0)
    s1d,r1d,c1d = score_tf(t1d,"1D") if t1d else (0,[],0)
    total = round(s15*0.5 + s1h*0.3 + s1d*0.2)
    conf  = c15 + (c1h//2) + (c1d//3)
    reasons = r15[:4] + r1h[:2] + r1d[:1]
    fgv=fg.get("value",50)
    if fgv<=25:   total+=10; reasons.append(f"😱 خوف شديد {fgv:.0f}"); conf+=1
    elif fgv<=40: total+=5;  reasons.append(f"😟 خوف {fgv:.0f}")
    elif fgv>=80: total-=12
    elif fgv>=65: total-=5
    if sent>0.65:   total+=6; reasons.append("📰 أخبار إيجابية")
    elif sent<0.35: total-=8
    all_bull=(t15.get("rsi",50)<50 and
              (not t1h or t1h.get("rsi",50)<55) and
              (not t1d or t1d.get("rsi",50)<60))
    if all_bull: total+=8; reasons.append("✅ توافق 3 أطر"); conf+=1
    sig="NONE"
    if total>=MIN_SCORE and conf>=MIN_CONFIRMS:
        brk=t15.get("brk","NONE"); r=t15.get("rsi",50)
        mh=t15.get("macd_hist"); vr=t15.get("vr",1)
        pts=t15.get("pts",[])
        if brk=="BULL": sig="BREAKOUT"
        elif r<30 and t15.get("bb_l") and t15["price"]<=t15["bb_l"]*1.01: sig="REVERSAL"
        elif mh and mh>0 and vr>=1.5: sig="MOMENTUM"
        elif any("Hammer" in x or "BullEngulf" in x for x in pts): sig="PATTERN"
        else: sig="BUY"
    return min(total,100), sig, reasons, conf


def danger_score(t15, t1h, sent, news_count) -> tuple[int, list]:
    if not t15: return 0,[]
    s=0; R=[]
    r=t15.get("rsi",50); p=t15.get("price",0)
    if r>80:   s+=22; R.append(f"RSI={r} 🔴 ذروة شراء")
    elif r>72: s+=14; R.append(f"RSI={r} ذروة شراء")
    elif r>65: s+=7
    mh=t15.get("macd_hist")
    if mh is not None:
        if mh<0 and t15.get("macd",0)<t15.get("macd_sig",0): s+=15; R.append("MACD هابط 🔴")
        elif mh<0: s+=8
    k=t15.get("sk",50)
    if k>85:   s+=14; R.append(f"Stoch={k:.0f} 🔴")
    elif k>75: s+=8
    bu=t15.get("bb_u")
    if bu and p>=bu:        s+=14; R.append("🔴 فوق BB العلوي")
    elif bu and p>=bu*0.99: s+=8
    w=t15.get("wr",-50)
    if w>-10: s+=10; R.append(f"WR={w} 🔴")
    elif w>-20:s+=5
    brk=t15.get("brk","NONE")
    if brk=="BEAR": s+=18; R.append(f"🔴 Breakdown! {t15.get('brk_vr')}x")
    vr=t15.get("vr",1); chg=t15.get("chg",0)
    if vr>=3 and chg<-1: s+=16; R.append(f"🔴 بيع {vr:.1f}x")
    elif vr>=2 and chg<0:s+=10; R.append(f"🔴 بيع {vr:.1f}x")
    bear_pts=[x for x in t15.get("pts",[]) if any(b in x for b in ["BearEngulf","EveningStar","3Crows","ShootingStar"])]
    if bear_pts: s+=12; R.append(f"🔴 {' '.join(bear_pts)}")
    if sent<0.3:  s+=12; R.append("🔴 أخبار سلبية")
    elif sent<0.4:s+=6
    if news_count>10: s+=6; R.append(f"📰 {news_count} خبر")
    if t1h:
        r1h=t1h.get("rsi",50); mh1h=t1h.get("macd_hist")
        if r1h>70: s+=8; R.append(f"1h RSI={r1h}")
        if mh1h and mh1h<0: s+=8
    adx_v=t15.get("adx",25); dim=t15.get("di_minus",0); dip=t15.get("di_plus",0)
    if adx_v>25 and dim>dip: s+=10; R.append(f"ADX هبوطي")
    if chg<-3:   s+=15; R.append(f"🔴 هبوط {chg}%")
    elif chg<-2: s+=10; R.append(f"🔴 هبوط {chg}%")
    elif chg<-1: s+=5
    return min(s,100), R


def calc_targets(t15: dict) -> dict:
    p=t15.get("price",0); at=t15.get("atr",p*0.005)
    bl=t15.get("bb_l",p*0.99); sup=t15.get("sup",p*0.99)
    sl=round(min(p-at*1.5, bl*0.998, sup*0.998), 4)
    risk=max(p-sl, p*0.003)
    return dict(
        entry=p, sl=sl,
        tp1=round(p+risk*1.0,4),
        tp2=round(p+risk*1.8,4),
        tp3=round(p+risk*3.0,4),
        risk_pct=round(risk/p*100,3),
        rr=round(risk*3.0/risk,1)
    )


# ══════════════════════════════════════════════
# CLAUDE AI
# ══════════════════════════════════════════════
async def claude_buy(sym, t15, sc, conf, reasons, tgt, fg_val, sent) -> tuple[str,bool]:
    prompt=(
        f"سهم {sym} | {sc}/100 | {conf} تأكيد | {session()}\n"
        f"RSI:{t15.get('rsi')} MACD:{t15.get('macd_hist')} Stoch:{t15.get('sk')} "
        f"Vol:{t15.get('vr')}x ADX:{t15.get('adx')} Brk:{t15.get('brk')}\n"
        f"SL:{tgt['sl']} TP1:{tgt['tp1']} TP2:{tgt['tp2']} TP3:{tgt['tp3']}\n"
        f"F&G:{fg_val:.0f} Sent:{sent:.2f}\n"
        f"أسباب:{' | '.join(reasons[:3])}\n\n"
        f"سطرين فقط:\n1. ✅ادخل / ⚠️انتظر / ❌تجنب + سبب\n2. أهم مخاطرة"
    )
    try:
        async with aiohttp.ClientSession() as s:
            async with s.post("https://api.anthropic.com/v1/messages",
                headers={"x-api-key":ANTHROPIC_KEY,"anthropic-version":"2023-06-01","content-type":"application/json"},
                json={"model":"claude-haiku-4-5-20251001","max_tokens":100,
                      "messages":[{"role":"user","content":prompt}]},
                timeout=aiohttp.ClientTimeout(total=20)) as r:
                d=await r.json()
        if "content" not in d: return "⚠️ AI غير متاح", True
        txt=d["content"][0]["text"]
        return txt, ("تجنب" not in txt and "❌" not in txt[:30])
    except Exception as e:
        return f"⚠️ {e}", True


async def claude_danger(sym, t15, d_sc, reasons, sent, news) -> str:
    news_titles=" | ".join(n.get("headline","")[:40] for n in news[:2]) if news else ""
    prompt=(
        f"خطر على {sym} | {d_sc}/100\n"
        f"RSI:{t15.get('rsi')} Vol:{t15.get('vr')}x Chg:{t15.get('chg')}%\n"
        f"Sent:{sent:.2f} | أخبار:{news_titles}\n"
        f"أسباب:{' | '.join(reasons[:3])}\n\n"
        f"سطر واحد: هل يجب البيع الآن؟"
    )
    try:
        async with aiohttp.ClientSession() as s:
            async with s.post("https://api.anthropic.com/v1/messages",
                headers={"x-api-key":ANTHROPIC_KEY,"anthropic-version":"2023-06-01","content-type":"application/json"},
                json={"model":"claude-haiku-4-5-20251001","max_tokens":80,
                      "messages":[{"role":"user","content":prompt}]},
                timeout=aiohttp.ClientTimeout(total=15)) as r:
                d=await r.json()
        return d["content"][0]["text"] if "content" in d else "⚠️ تحقق يدوياً"
    except Exception as e:
        return f"⚠️ {e}"


# ══════════════════════════════════════════════
# FORMATTERS
# ══════════════════════════════════════════════
def fmt_buy(sym, t15, t1h, t1d, sc, sig, conf, reasons, tgt, ai, fg):
    em={"BREAKOUT":"🚀","REVERSAL":"🔄","MOMENTUM":"⚡","PATTERN":"🕯️","BUY":"📈"}.get(sig,"📈")
    grade="A+" if sc>=88 else "A" if sc>=80 else "B+"
    p=tgt['entry']; pct=lambda x:f"+{round((x-p)/p*100,2)}%"
    fgv=fg.get("value",50)
    fg_em="😱" if fgv<=25 else "😟" if fgv<=40 else "😐" if fgv<=55 else "😊"
    tf=""
    if t1h: tf+=f"1h:{t1h.get('rsi','—')} "
    if t1d: tf+=f"1D:{t1d.get('rsi','—')}"
    top_r=[r.split("] ")[-1] for r in reasons if "15m" in r][:3]
    return (
        f"{em} *{sym}* | {grade} {sc}/100 | {session()}\n"
        f"✅ {conf} تأكيد | {fg_em}{fgv:.0f}\n"
        f"💵 `${p}` {'+' if t15.get('chg',0)>=0 else ''}{t15.get('chg')}%"
        f" | Vol:{t15.get('vr')}x\n\n"
        f"🥉 TP1 `${tgt['tp1']}` ({pct(tgt['tp1'])})\n"
        f"🥈 TP2 `${tgt['tp2']}` ({pct(tgt['tp2'])})\n"
        f"💎 TP3 `${tgt['tp3']}` ({pct(tgt['tp3'])})\n"
        f"🛑 SL `${tgt['sl']}` (-{tgt['risk_pct']}%) | R:R 1:{tgt['rr']}\n\n"
        f"15m RSI:{t15.get('rsi')} MACD:{t15.get('macd_hist')} Stoch:{t15.get('sk')}"
        +(f" | {tf}" if tf else "")
        +(f"\n🚀 Breakout {t15.get('brk_vr')}x" if t15.get('brk')=="BULL" else "")
        +(f"\n🕯️ {' '.join(t15.get('pts',[]))}" if t15.get('pts') else "")
        +f"\n🧠 {ai}"
        +("\n"+"".join(f"• {r}\n" for r in top_r) if top_r else "")
    )


def fmt_danger(sym, t15, sc, reasons, ai, news):
    level="🔴🔴🔴 خطر شديد" if sc>=80 else "🔴🔴 خطر عالي" if sc>=65 else "🟡 تحذير"
    news_line=f"📰 {news[0].get('headline','')[:55]}" if news else ""
    return (
        f"🚨 *تنبيه خطر — {sym}*\n{'━'*18}\n"
        f"{level} | {sc}/100 | {session()}\n"
        f"💵 `${t15.get('price')}` | {t15.get('chg')}% | Vol:{t15.get('vr')}x\n\n"
        f"⚠️ *أسباب:*\n"
        +"\n".join(f"  🔴 {r}" for r in reasons[:4])
        +f"\nRSI:{t15.get('rsi')} Stoch:{t15.get('sk')} MACD:{t15.get('macd_hist')}\n"
        +(f"🕯️ {' '.join(t15.get('pts',[]))}\n" if t15.get('pts') else "")
        +(f"{news_line}\n" if news_line else "")
        +f"\n🧠 {ai}\n*⚡ فكّر في البيع أو تضييق SL*"
    )


# ══════════════════════════════════════════════
# TRADE TRACKER
# ══════════════════════════════════════════════
def record_trade(sym, entry, sl, tp1, tp2, tp3, sig, sc):
    trades.append({
        "sym":sym,"entry":entry,"sl":sl,"tp1":tp1,"tp2":tp2,"tp3":tp3,
        "sig":sig,"sc":sc,"status":"OPEN","result":None,"pnl":None,
        "time":datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
    })

def update_trades(sym, price):
    for t in trades:
        if t["sym"]==sym and t["status"]=="OPEN":
            t["pnl"]=round((price-t["entry"])/t["entry"]*100,2)
            if price<=t["sl"]:   t["status"]="CLOSED"; t["result"]="❌ SL"
            elif price>=t["tp3"]:t["status"]="CLOSED"; t["result"]="💎 TP3"
            elif price>=t["tp2"]:t["result"]="🥈 TP2 ✅"
            elif price>=t["tp1"]:t["result"]="🥉 TP1 ✅"

def trades_summary():
    if not trades: return "لا توجد صفقات بعد."
    closed=[t for t in trades if t["status"]=="CLOSED"]
    open_=[t for t in trades if t["status"]=="OPEN"]
    wins=[t for t in closed if t.get("result","") and "TP" in t["result"]]
    losses=[t for t in closed if t.get("result","") and "SL" in t["result"]]
    wr=round(len(wins)/len(closed)*100) if closed else 0
    avg=round(sum(t["pnl"] for t in closed if t["pnl"])/len(closed),2) if closed else 0
    return (
        f"📊 *الصفقات*\n\n"
        f"إجمالي:{len(trades)} | مفتوحة:{len(open_)}\n"
        f"✅ رابحة:{len(wins)} | ❌ خاسرة:{len(losses)}\n"
        f"نسبة النجاح: *{wr}%* | متوسط P&L: *{avg}%*\n\n"
        +("*آخر 5:*\n"+"\n".join(
            f"{'🟢' if t.get('result') and 'TP' in t.get('result','') else '🔴' if t.get('result') and 'SL' in t.get('result','') else '⏳'}"
            f" {t['sym']} {t.get('result','مفتوحة')} {t.get('pnl',0)}% [{t['time'][:10]}]"
            for t in trades[-5:][::-1]) if trades else "")
    )


# ══════════════════════════════════════════════
# SCANNER
# ══════════════════════════════════════════════
async def run_scanner(app):
    global alert_count, hour_reset, active, stats
    log.info("🚀 Ultra Scalping Bot v5.0 started")

    while True:
        if not active: await asyncio.sleep(60); continue
        if time.time()-hour_reset>3600: alert_count=0; hour_reset=time.time()

        fg=await get_fg()
        log.info(f"🔍 Scanning {len(WATCHLIST)} | {session()} | F&G:{fg['value']:.0f}")
        t0=time.time(); found=0; sent_c=0; danger_c=0; rej=0

        for i in range(0, len(WATCHLIST), 5):
            if alert_count>=MAX_HR: break
            batch=WATCHLIST[i:i+5]

            for sym in batch:
                try:
                    d15=await get_candles(sym, "15min", 80)
                    if not d15: continue
                    t15=analyze(d15)
                    if not t15: continue

                    r=t15.get("rsi",50); vr=t15.get("vr",1)
                    sent_val, news_count = await get_sentiment(sym)

                    # فحص الخطر
                    d_pre,_=danger_score(t15,{},sent_val,news_count)
                    if d_pre>=DANGER_SCORE:
                        if time.time()-danger_alerted.get(sym,0)>3600:
                            d1h=await get_candles(sym,"1h",50)
                            t1h=analyze(d1h) if d1h else {}
                            news=await get_news(sym)
                            d_sc,d_reasons=danger_score(t15,t1h,sent_val,news_count)
                            if d_sc>=DANGER_SCORE:
                                ai_d=await claude_danger(sym,t15,d_sc,d_reasons,sent_val,news)
                                msg=fmt_danger(sym,t15,d_sc,d_reasons,ai_d,news)
                                for cid in ALERT_CHATS:
                                    try: await app.bot.send_message(cid,msg,parse_mode="Markdown")
                                    except: pass
                                danger_alerted[sym]=time.time(); danger_c+=1
                                log.info(f"🚨 DANGER: {sym} {d_sc}")

                    # فلتر سريع للشراء
                    if r>65 and vr<1.1: continue
                    if r>55 and t15.get("macd_hist",0)<0: continue

                    sc_pre,sig_pre,_,c_pre=multi_score(t15,{},{},fg,sent_val)
                    if sc_pre<MIN_SCORE-12: continue
                    found+=1

                    if time.time()-alerted.get(sym,0)<COOLDOWN_MIN*60: continue

                    d1h,d1d=await asyncio.gather(
                        get_candles(sym,"1h",50), get_daily(sym),
                        return_exceptions=True)
                    t1h=analyze(d1h) if d1h and not isinstance(d1h,Exception) else {}
                    t1d=analyze(d1d) if d1d and not isinstance(d1d,Exception) else {}

                    sc,sig,reasons,conf=multi_score(t15,t1h,t1d,fg,sent_val)
                    if sc<MIN_SCORE or sig=="NONE" or conf<MIN_CONFIRMS: continue

                    tgt=calc_targets(t15)
                    ai,approved=await claude_buy(sym,t15,sc,conf,reasons,tgt,fg["value"],sent_val)
                    if not approved: rej+=1; continue

                    msg=fmt_buy(sym,t15,t1h,t1d,sc,sig,conf,reasons,tgt,ai,fg)
                    ok=False
                    for cid in ALERT_CHATS:
                        try: await app.bot.send_message(cid,msg,parse_mode="Markdown"); ok=True
                        except Exception as e: log.error(f"send {cid}: {e}")
                    if ok:
                        alerted[sym]=time.time(); alert_count+=1; sent_c+=1
                        record_trade(sym,tgt["entry"],tgt["sl"],tgt["tp1"],tgt["tp2"],tgt["tp3"],sig,sc)
                        log.info(f"✅ BUY: {sym} sc={sc} sig={sig} conf={conf}")

                    update_trades(sym, t15["price"])

                except Exception as e:
                    log.debug(f"Error {sym}: {e}")

            await asyncio.sleep(1.5)

        elapsed=round(time.time()-t0)
        now=datetime.now(timezone.utc).strftime("%H:%M")
        stats={"scanned":len(WATCHLIST),"found":found,"sent":sent_c,
               "danger":danger_c,"rejected":rej,"time":f"{elapsed}s","last":now}
        log.info(f"✅ found={found} sent={sent_c} danger={danger_c} rej={rej} {elapsed}s")
        await asyncio.sleep(SCAN_SEC)


# ══════════════════════════════════════════════
# TELEGRAM HANDLERS
# ══════════════════════════════════════════════
async def start(update, ctx):
    cid=update.effective_chat.id
    kb=[[InlineKeyboardButton("📡 تفعيل التنبيهات",callback_data="sub"),
         InlineKeyboardButton("🔕 إيقاف",callback_data="unsub")],
        [InlineKeyboardButton("🔍 فحص الآن",callback_data="scan"),
         InlineKeyboardButton("📊 الحالة",callback_data="status")],
        [InlineKeyboardButton("📈 نتائج الصفقات",callback_data="results"),
         InlineKeyboardButton("😱 Fear & Greed",callback_data="fg")],
        [InlineKeyboardButton("⚙️ إعدادات",callback_data="cfg")]]
    await update.message.reply_text(
        f"🤖 *Ultra Scalping Bot v5.0*\n\n"
        f"⚡ مضاربة: ساعات → أسبوع\n"
        f"🔍 {len(WATCHLIST)} سهم | كل {SCAN_SEC//60} دقائق\n"
        f"📊 3 أطر: 15m + 1h + 1D\n"
        f"🧠 12 مؤشر + Claude AI\n"
        f"🚨 تنبيه خطر تلقائي\n"
        f"📈 تتبع نتائج الصفقات\n"
        f"✅ {MIN_CONFIRMS}+ تأكيد | {MIN_SCORE}+ نقطة\n\n"
        f"🆔 Chat ID: `{cid}`\n\n"
        f"👇 اضغط *تفعيل التنبيهات* للبدء",
        parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb))


async def btn(update, ctx):
    q=update.callback_query; await q.answer(); cid=q.message.chat_id

    if q.data=="sub":
        if cid not in ALERT_CHATS: ALERT_CHATS.append(cid)
        await q.edit_message_text(
            f"✅ *تم التفعيل!*\n\n"
            f"⚡ {len(WATCHLIST)} سهم | كل {SCAN_SEC//60} دق\n"
            f"🚨 تنبيهات خطر مفعّلة\n"
            f"📈 تتبع الصفقات مفعّل\n\n"
            f"انتظر أول تنبيه 🎯", parse_mode="Markdown")

    elif q.data=="unsub":
        if cid in ALERT_CHATS: ALERT_CHATS.remove(cid)
        await q.edit_message_text("🔕 تم إيقاف التنبيهات.")

    elif q.data=="fg":
        fg=await get_fg(); v=fg["value"]; lb=fg["label"]
        adv="🟢 ممتاز للشراء" if v<=25 else "🟡 جيد" if v<=40 else "🔴 تحذر" if v>=75 else "⚪ محايد"
        await q.edit_message_text(
            f"😱 *Fear & Greed Index*\n\n{v:.0f}/100\n{lb}\n{adv}",
            parse_mode="Markdown")

    elif q.data=="results":
        await q.edit_message_text(trades_summary(), parse_mode="Markdown")

    elif q.data=="status":
        fg=await get_fg(); st=stats
        await q.edit_message_text(
            f"📊 *حالة البوت v5.0*\n\n"
            f"⏰ {session()} | F&G:{fg['value']:.0f}\n"
            f"📡 {'🟢 نشط' if active else '🔴 متوقف'}\n"
            f"🔔 تنبيهات/ساعة: {alert_count}/{MAX_HR}\n\n"
            f"آخر فحص {st.get('last','—')}:\n"
            f"فُحص:{st.get('scanned',0)} | فرص:{st.get('found',0)}\n"
            f"شراء:{st.get('sent',0)} | 🚨خطر:{st.get('danger',0)}\n"
            f"رُفض:{st.get('rejected',0)} | وقت:{st.get('time','—')}\n\n"
            f"📈 صفقات:{len(trades)} مفتوحة:{sum(1 for t in trades if t['status']=='OPEN')}",
            parse_mode="Markdown")

    elif q.data=="cfg":
        await q.edit_message_text(
            f"⚙️ *الإعدادات*\n\n"
            f"📊 الحد: {MIN_SCORE}/100 | تأكيدات: {MIN_CONFIRMS}+\n"
            f"🚨 حد الخطر: {DANGER_SC}/100\n"
            f"⏱️ مسح: {SCAN_SEC//60} دق | كولداون: {COOLDOWN_MIN} دق\n"
            f"🔔 حد/ساعة: {MAX_HR}\n\n"
            f"*المصادر:*\n"
            f"Twelve Data 15m+1h ✅\n"
            f"Yahoo Finance 1D ✅\n"
            f"Finnhub Sentiment ✅\n"
            f"CNN Fear & Greed ✅",
            parse_mode="Markdown")

    elif q.data=="scan":
        await q.edit_message_text("⏳ فحص سريع لـ 30 سهم...")
        fg=await get_fg(); found=[]
        for sym in WATCHLIST[:30]:
            d15=await get_candles(sym,"15min",80)
            if not d15: continue
            t15=analyze(d15)
            if not t15: continue
            sc,sig,_,conf=multi_score(t15,{},{},fg,0.5)
            d_sc,_=danger_score(t15,{},0.5,0)
            em={"BREAKOUT":"🚀","MOMENTUM":"⚡","REVERSAL":"🔄","PATTERN":"🕯️"}.get(sig,"📈")
            if sc>=MIN_SCORE-8 and sig!="NONE":
                found.append((sc,f"{em} *{sym}* {sc}/100 RSI:{t15.get('rsi')} Vol:{t15.get('vr')}x"))
            elif d_sc>=DANGER_SC:
                found.append((0,f"🚨 *{sym}* خطر {d_sc}/100 {t15.get('chg')}%"))
        found.sort(key=lambda x:-x[0])
        msg=(f"🔍 *النتائج:*\n\n"+"\n".join(x[1] for x in found[:8])+"\n\n_أرسل رمز للتحليل الكامل_") if found else "🔍 لا توجد فرص حالياً."
        await q.edit_message_text(msg, parse_mode="Markdown")


async def analyze_cmd(update, ctx):
    sym=update.message.text.strip().upper()
    if not sym.isalpha() or len(sym)>6: return
    msg=await update.message.reply_text(f"⏳ تحليل *{sym}*...", parse_mode="Markdown")
    try:
        fg=await get_fg()
        d15,d1h,d1d=await asyncio.gather(
            get_candles(sym,"15min",80),
            get_candles(sym,"1h",50),
            get_daily(sym),
            return_exceptions=True)
        if isinstance(d15,Exception) or not d15:
            await msg.edit_text(f"❌ لا بيانات لـ `{sym}`\nتأكد من الرمز مثل: AAPL NVDA TSLA")
            return
        t15=analyze(d15)
        if not t15: await msg.edit_text("❌ بيانات غير كافية"); return
        t1h=analyze(d1h) if d1h and not isinstance(d1h,Exception) else {}
        t1d=analyze(d1d) if d1d and not isinstance(d1d,Exception) else {}
        sent_val,news_count=await get_sentiment(sym)
        news=await get_news(sym)
        sc,sig,reasons,conf=multi_score(t15,t1h,t1d,fg,sent_val)
        d_sc,d_reasons=danger_score(t15,t1h,sent_val,news_count)
        tgt=calc_targets(t15)
        if d_sc>=DANGER_SC and sc<MIN_SCORE:
            ai_d=await claude_danger(sym,t15,d_sc,d_reasons,sent_val,news)
            await msg.edit_text(fmt_danger(sym,t15,d_sc,d_reasons,ai_d,news), parse_mode="Markdown")
        elif sc>=MIN_SCORE and sig!="NONE":
            ai,_=await claude_buy(sym,t15,sc,conf,reasons,tgt,fg["value"],sent_val)
            await msg.edit_text(fmt_buy(sym,t15,t1h,t1d,sc,sig,conf,reasons,tgt,ai,fg), parse_mode="Markdown")
        else:
            await msg.edit_text(
                f"📊 *{sym}* | {session()}\n"
                f"💵 `${t15['price']}` | {t15.get('chg')}% | Vol:{t15.get('vr')}x\n\n"
                f"RSI:{t15.get('rsi')} MACD:{t15.get('macd_hist')} Stoch:{t15.get('sk')}\n"
                f"ADX:{t15.get('adx')} Brk:{t15.get('brk')}\n\n"
                f"🟢 شراء: {sc}/100 ({conf} تأكيد)\n"
                f"🔴 خطر: {d_sc}/100\n"
                f"_لم تصل الحدود المطلوبة بعد_",
                parse_mode="Markdown")
    except Exception as e:
        await msg.edit_text(f"❌ خطأ: `{e}`", parse_mode="Markdown")


async def post_init(app):
    asyncio.create_task(run_scanner(app))
    log.info("✅ Scanner started")

def main():
    app=Application.builder().token(TELEGRAM_TOKEN).post_init(post_init).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help",  start))
    app.add_handler(CallbackQueryHandler(btn))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, analyze_cmd))
    log.info("🤖 Ultra Scalping Bot v5.0")
    app.run_polling(drop_pending_updates=True)

if __name__=="__main__":
    main()
