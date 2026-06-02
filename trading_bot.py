"""
🤖 Ultra Scalping Bot v5.0
مضاربة احترافية — صفقات ساعات إلى أسبوع
بيانات 15 دقيقة + ساعة + يومي
"""
import os, logging, asyncio, aiohttp, time
from datetime import datetime, timezone
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters

# ══════════════════════════════════════════════
# CONFIG
# ══════════════════════════════════════════════
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
ANTHROPIC_API_KEY  = os.getenv("ANTHROPIC_API_KEY",  "")
FINNHUB_API_KEY    = os.getenv("FINNHUB_API_KEY",    "")
ALPHA_VANTAGE_KEY  = os.getenv("ALPHA_VANTAGE_KEY",  "")
TWELVE_DATA_KEY    = os.getenv("TWELVE_DATA_KEY",    "")

ALERT_CHAT_IDS: list[int] = []
MIN_SCORE         = 75      # نقاط من 100
MIN_CONFIRMS      = 5       # تأكيدات كحد أدنى
SCAN_INTERVAL     = 180     # فحص كل 3 دقائق
MAX_ALERTS_HOUR   = 15
COOLDOWN_MIN      = 90      # لا تكرر نفس السهم قبل 90 دقيقة

# أكبر قائمة مضاربة — أكثر سيولة وحركة في السوق الأمريكي
WATCHLIST = [
    # Mega Cap
    "AAPL","MSFT","NVDA","GOOGL","AMZN","META","TSLA","AVGO","ORCL","CRM",
    # Semis
    "AMD","INTC","QCOM","MU","AMAT","LRCX","MRVL","SMCI","ARM","KLAC",
    "WOLF","ON","SWKS","MPWR","ENTG","TER","COHU","TSM","ASML","ASML",
    # Finance
    "JPM","BAC","WFC","GS","MS","BLK","V","MA","AXP","SCHW","C","USB",
    # Health
    "LLY","JNJ","UNH","ABBV","MRK","PFE","AMGN","GILD","REGN","VRTX",
    "MRNA","BNTX","BIIB","ILMN","ISRG","DXCM","ABT","EW","IDXX","ZBH",
    # Consumer
    "COST","WMT","HD","MCD","SBUX","NKE","TGT","LOW","TJX","BABA",
    # Energy
    "XOM","CVX","COP","SLB","EOG","PSX","MPC","VLO","OXY","HAL",
    "VIST","CVE","HES","FANG","DVN","MRO","CIVI","SM","NOG","APA",
    # Industrial
    "CAT","DE","BA","HON","GE","RTX","LMT","NOC","UPS","FDX",
    # Tech/Cloud
    "NFLX","DIS","CMCSA","SNAP","PINS","RBLX","SPOT","NOW","SNOW",
    "PLTR","DDOG","ZS","CRWD","NET","MDB","GTLB","PATH","ADBE","INTU",
    "PANW","FTNT","CYBR","S","VRNS","QLYS","TENB","TWLO","OKTA","BILL",
    # High Beta / Momentum
    "MSTR","COIN","HOOD","SOFI","UPST","AFRM","RKLB","IONQ","QUBT","LUNR",
    "UBER","LYFT","ABNB","DASH","ROKU","ZM","DOCN","COUR","DUOL","CPNG",
    "RIVN","LCID","NIO","LI","XPEV","CHPT","EVGO","SQ","PYPL","MELI",
    "AMT","PLD","EQIX","NEE","DUK","SE","GRAB","RELY","FLYW","NOG",
    # ETFs (للمضاربة)
    "SPY","QQQ","IWM","XLF","XLK","XLE","XLV","SOXL","TQQQ","SPXL",
    "UVXY","VIX","ARKK","DIA","GLD","SLV","TLT","HYG","XBI","LABU",
]

logging.basicConfig(format="%(asctime)s | %(levelname)s | %(message)s", level=logging.INFO)
log = logging.getLogger(__name__)

alert_count  = 0
hour_reset   = time.time()
alerted: dict[str,float] = {}
active       = True
stats        = {"scanned":0,"found":0,"sent":0,"rejected":0,"time":"","last":"—"}
fg_cache     = {"value":50,"label":"محايد","ts":0}


# ══════════════════════════════════════════════
# SESSION
# ══════════════════════════════════════════════
def session():
    m = datetime.now(timezone.utc).hour*60 + datetime.now(timezone.utc).minute
    if 780<=m<810:    return "🌅 Pre"
    elif 810<=m<1200: return "📈 Regular"
    elif 1200<=m<1440:return "🌙 After"
    else:             return "🌃 Night"

def is_market_hours():
    m = datetime.now(timezone.utc).hour*60 + datetime.now(timezone.utc).minute
    return 780 <= m < 1200  # Pre + Regular


# ══════════════════════════════════════════════
# DATA — Twelve Data (15min + 1h)
# ══════════════════════════════════════════════
async def td_candles(sym:str, interval:str, count:int=80) -> dict:
    """Twelve Data — شموع 15 دقيقة أو ساعة"""
    url = "https://api.twelvedata.com/time_series"
    params = {
        "symbol": sym, "interval": interval,
        "outputsize": count, "apikey": TWELVE_DATA_KEY,
        "format": "JSON", "order": "ASC"
    }
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(url, params=params, timeout=aiohttp.ClientTimeout(total=12)) as r:
                data = await r.json()
        if data.get("status") == "error" or "values" not in data:
            return {}
        vals = data["values"]
        c=[float(v["close"])  for v in vals]
        o=[float(v["open"])   for v in vals]
        h=[float(v["high"])   for v in vals]
        l=[float(v["low"])    for v in vals]
        vol=[float(v.get("volume",0)) for v in vals]
        if len(c)<20: return {}
        return {"c":c,"o":o,"h":h,"l":l,"v":vol}
    except Exception as e:
        log.debug(f"TD {sym} {interval}: {e}"); return {}


async def yahoo_daily(sym:str) -> dict:
    """Yahoo Finance — يومي للاتجاه العام"""
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}"
    hdr = {"User-Agent":"Mozilla/5.0","Accept":"application/json"}
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(url, params={"interval":"1d","range":"2mo"}, headers=hdr,
                             timeout=aiohttp.ClientTimeout(total=10)) as r:
                data = await r.json()
        res=data["chart"]["result"][0]; q=res["indicators"]["quote"][0]
        def cl(x): return [i for i in x if i is not None]
        c=cl(q.get("close",[])); h=cl(q.get("high",[])); l=cl(q.get("low",[])); v=cl(q.get("volume",[]))
        n=min(len(c),len(h),len(l),len(v))
        if n<15: return {}
        meta=res.get("meta",{})
        return {"c":c[-n:],"h":h[-n:],"l":l[-n:],"v":v[-n:],
                "name":meta.get("shortName",sym)}
    except Exception as e:
        log.debug(f"Yahoo {sym}: {e}"); return {}


async def get_fg():
    global fg_cache
    if time.time()-fg_cache["ts"]<3600: return fg_cache
    try:
        url="https://production.dataviz.cnn.io/index/fearandgreed/graphdata"
        async with aiohttp.ClientSession() as s:
            async with s.get(url,headers={"User-Agent":"Mozilla/5.0"},
                             timeout=aiohttp.ClientTimeout(total=8)) as r:
                d=await r.json()
        v=float(d["fear_and_greed"]["score"])
        lb="😱 خوف شديد" if v<=25 else "😟 خوف" if v<=45 else "😐 محايد" if v<=55 else "😊 طمع" if v<=75 else "🤑 طمع شديد"
        fg_cache={"value":v,"label":lb,"ts":time.time()}
    except: pass
    return fg_cache


async def get_sentiment(sym:str) -> float:
    try:
        url=f"https://finnhub.io/api/v1/news-sentiment?symbol={sym}&token={FINNHUB_API_KEY}"
        async with aiohttp.ClientSession() as s:
            async with s.get(url,timeout=aiohttp.ClientTimeout(total=5)) as r:
                d=await r.json()
        return d.get("companyNewsScore",0.5)
    except: return 0.5


# ══════════════════════════════════════════════
# INDICATORS
# ══════════════════════════════════════════════
def rsi(p,n=14):
    if len(p)<n+1: return 50.0
    g=[max(p[i]-p[i-1],0) for i in range(1,len(p))]
    l=[max(p[i-1]-p[i],0) for i in range(1,len(p))]
    ag=sum(g[-n:])/n; al=sum(l[-n:])/n
    return round(100-(100/(1+ag/al)),2) if al else 100.0

def ema(p,n):
    if len(p)<n: return p
    k=2/(n+1); e=[sum(p[:n])/n]
    for x in p[n:]: e.append(x*k+e[-1]*(1-k))
    return e

def macd(p):
    if len(p)<26: return None,None,None
    e12=ema(p,12); e26=ema(p,26); n=min(len(e12),len(e26))
    ml=[e12[-n+i]-e26[-n+i] for i in range(n)]; sg=ema(ml,9)
    return (round(ml[-1],5),round(sg[-1],5),round(ml[-1]-sg[-1],5)) if sg else (None,None,None)

def bb(p,n=20):
    if len(p)<n: return None,None,None
    r=p[-n:]; m=sum(r)/n; std=(sum((x-m)**2 for x in r)/n)**0.5
    return round(m+2*std,4),round(m,4),round(m-2*std,4)

def stoch(h,l,c,n=14):
    if len(c)<n: return 50.0,50.0
    rh=max(h[-n:]); rl=min(l[-n:])
    if rh==rl: return 50.0,50.0
    k=((c[-1]-rl)/(rh-rl))*100
    rh2=max(h[-n-1:-1]) if len(h)>n else rh; rl2=min(l[-n-1:-1]) if len(l)>n else rl
    k2=((c[-2]-rl2)/(rh2-rl2))*100 if rh2!=rl2 and len(c)>n else k
    return round(k,2),round((k+k2)/2,2)

def atr(h,l,c,n=14):
    if len(c)<n+1: return 0.0
    trs=[max(h[i]-l[i],abs(h[i]-c[i-1]),abs(l[i]-c[i-1])) for i in range(1,len(c))]
    return round(sum(trs[-n:])/n,5)

def vwap(h,l,c,v):
    if not v or sum(v)==0: return c[-1]
    tp=[(h[i]+l[i]+c[i])/3 for i in range(len(c))]
    return round(sum(tp[i]*v[i] for i in range(len(c)))/sum(v),4)

def wr(h,l,c,n=14):
    if len(c)<n: return -50.0
    rh=max(h[-n:]); rl=min(l[-n:])
    return round(((rh-c[-1])/(rh-rl))*-100,2) if rh!=rl else -50.0

def cci(h,l,c,n=14):
    if len(c)<n: return 0.0
    tp=[(h[i]+l[i]+c[i])/3 for i in range(len(c))]
    tp_n=tp[-n:]; mean=sum(tp_n)/n
    mad=sum(abs(x-mean) for x in tp_n)/n
    return round((tp[-1]-mean)/(0.015*mad),2) if mad else 0.0

def momentum(c,n=10):
    if len(c)<n+1: return 0.0
    return round((c[-1]-c[-n])/c[-n]*100,3)

def adx(h,l,c,n=14):
    """Average Directional Index — قوة الاتجاه"""
    if len(c)<n+2: return 25.0
    tr_list=[]; dm_plus=[]; dm_minus=[]
    for i in range(1,len(c)):
        tr=max(h[i]-l[i],abs(h[i]-c[i-1]),abs(l[i]-c[i-1]))
        tr_list.append(tr)
        up=h[i]-h[i-1]; dn=l[i-1]-l[i]
        dm_plus.append(up if up>dn and up>0 else 0)
        dm_minus.append(dn if dn>up and dn>0 else 0)
    atr_n=sum(tr_list[-n:])/n if n<=len(tr_list) else 1
    di_plus=100*(sum(dm_plus[-n:])/n)/atr_n if atr_n else 0
    di_minus=100*(sum(dm_minus[-n:])/n)/atr_n if atr_n else 0
    dx=100*abs(di_plus-di_minus)/(di_plus+di_minus) if (di_plus+di_minus)>0 else 0
    return round(dx,2)

def breakout(h,l,c,v,n=20):
    if len(c)<n+2: return "NONE",0,0
    res=max(h[-n-1:-1]); sup=min(l[-n-1:-1])
    avg_v=sum(v[-n-1:-1])/n if n>0 else 1
    vr=round(v[-1]/avg_v,1) if avg_v else 1
    if c[-1]>res*1.002 and vr>=1.5:
        str_=min(int((c[-1]/res-1)*500+vr*10),50)
        return "BULL",str_,vr
    elif c[-1]<sup*0.998 and vr>=1.5:
        return "BEAR",30,vr
    return "NONE",0,vr

def patterns(o,h,l,c):
    if len(c)<3: return []
    pts=[]
    p,ph,pl,po=c[-1],h[-1],l[-1],o[-1]
    p2,ph2,pl2,po2=c[-2],h[-2],l[-2],o[-2]
    body=abs(p-po); rng=ph-pl; body2=abs(p2-po2); rng2=ph2-pl2
    if body>0 and rng>0:
        lw=min(p,po)-pl; uw=ph-max(p,po)
        if lw>=body*2 and uw<=body*0.3 and p>po: pts.append("Hammer🔨")
    if rng>0 and body/rng<0.1: pts.append("Doji✙")
    if p>po and p2<po2 and p>po2 and po<p2: pts.append("Engulf🕯️")
    if len(c)>=3:
        p3=c[-3]; po3=o[-3]; ph3=h[-3]; pl3=l[-3]
        if p3<po3 and body2/max(rng2,0.001)<0.3 and p>po and p>(p3+po3)/2:
            pts.append("MorningStar⭐")
        if p>po and p2>po2 and p3>po3 and p>p2>p3:
            pts.append("3Soldiers💪")
    return pts


# ══════════════════════════════════════════════
# ANALYZE TIMEFRAME
# ══════════════════════════════════════════════
def analyze(d:dict, is_intraday=False) -> dict:
    if not d: return {}
    c=d.get("c",[]); o=d.get("o",c)
    h=d.get("h",[]); l=d.get("l",[]); v=d.get("v",[])
    if len(c)<20: return {}

    MC,MS,MH=macd(c); BU,BM,BL=bb(c)
    SK,SD=stoch(h,l,c); AT=atr(h,l,c)
    VP=vwap(h,l,c,v); WR=wr(h,l,c)
    CC=cci(h,l,c); MOM=momentum(c)
    ADX=adx(h,l,c); PTS=patterns(o,h,l,c)
    BRK,BRK_STR,BRK_VR=breakout(h,l,c,v)

    e9 =round(ema(c,9)[-1],4)  if len(c)>=9  else None
    e21=round(ema(c,21)[-1],4) if len(c)>=21 else None
    e50=round(ema(c,50)[-1],4) if len(c)>=50 else None
    s20=round(sum(c[-20:])/20,4) if len(c)>=20 else None

    avg_v=sum(v[-20:])/20 if len(v)>=20 else 1
    vr_=round(v[-1]/avg_v,2) if avg_v else 1.0
    rvol5=round(v[-1]/(sum(v[-5:])/5),2) if len(v)>=5 and sum(v[-5:])>0 else 1.0
    chg=round((c[-1]-c[-2])/c[-2]*100,3) if len(c)>1 else 0

    sup=round(min(l[-20:]),4); res_=round(max(h[-20:]),4)
    ts=sum(1 for i in range(1,min(8,len(c))) if c[-i]>c[-i-1])

    return dict(
        price=round(c[-1],4), chg=chg,
        high=round(h[-1],4), low=round(l[-1],4),
        rsi=rsi(c), macd=MC, macd_sig=MS, macd_hist=MH,
        bb_u=BU, bb_m=BM, bb_l=BL,
        atr=AT, sk=SK, sd=SD, vwap=VP,
        wr=WR, cci=CC, mom=MOM, adx=ADX,
        e9=e9, e21=e21, e50=e50, s20=s20,
        sup=sup, res=res_,
        vr=vr_, rvol5=rvol5, vol=int(v[-1]) if v else 0,
        pts=PTS, brk=BRK, brk_str=BRK_STR, brk_vr=BRK_VR,
        trend=round(ts/min(7,len(c)-1)*100)
    )


# ══════════════════════════════════════════════
# MULTI-TIMEFRAME SCORING
# ══════════════════════════════════════════════
def score_tf(t:dict, label:str) -> tuple[int,list,int]:
    """تقييم طبقة زمنية واحدة — يرجع نقاط وأسباب وتأكيدات"""
    if not t: return 0,[],0
    s=0; R=[]; conf=0; p=t.get("price",0)
    r=t.get("rsi",50)

    # RSI
    if r<25:   s+=20; R.append(f"[{label}] RSI={r} 🔥 ذروة بيع"); conf+=1
    elif r<35: s+=14; R.append(f"[{label}] RSI={r} منطقة شراء"); conf+=1
    elif r<45: s+=7
    elif r>75: s-=18
    elif r>65: s-=10

    # MACD
    mh=t.get("macd_hist"); mc=t.get("macd"); ms=t.get("macd_sig")
    if mh is not None:
        if mh>0 and mc and ms and mc>ms: s+=16; R.append(f"[{label}] MACD تقاطع صاعد ✅"); conf+=1
        elif mh>0:  s+=8
        elif mh<0:  s-=10

    # Stochastic
    k=t.get("sk",50); d=t.get("sd",50)
    if k<15 and d<15:  s+=15; R.append(f"[{label}] Stoch={k:.0f} ذروة بيع 🔥"); conf+=1
    elif k<25:         s+=9;  R.append(f"[{label}] Stoch={k:.0f} شراء"); conf+=1
    elif k>d and k<40: s+=6
    elif k>80:         s-=12

    # Bollinger
    bl=t.get("bb_l"); bu=t.get("bb_u")
    if bl and p<=bl:        s+=15; R.append(f"[{label}] تحت BB السفلي 🎯"); conf+=1
    elif bl and p<=bl*1.01: s+=9;  R.append(f"[{label}] عند BB السفلي"); conf+=1
    elif bu and p>=bu*0.99: s-=14

    # Williams %R
    w=t.get("wr",-50)
    if w<-80:  s+=9;  R.append(f"[{label}] WR={w} ذروة بيع"); conf+=1
    elif w<-60:s+=5
    elif w>-20:s-=8

    # CCI
    cc=t.get("cci",0)
    if cc<-150: s+=9; R.append(f"[{label}] CCI={cc:.0f} ذروة بيع"); conf+=1
    elif cc<-100:s+=5
    elif cc>150:s-=8

    # ADX — قوة الاتجاه
    ax=t.get("adx",25)
    if ax>=30: s+=8; R.append(f"[{label}] ADX={ax} اتجاه قوي 💪"); conf+=1
    elif ax>=25:s+=4

    # Momentum
    mom=t.get("mom",0)
    if mom>1.5:  s+=8; R.append(f"[{label}] Momentum={mom}% قوي")
    elif mom>0:  s+=3
    elif mom<-2: s-=8

    # EMA
    e9=t.get("e9"); e21=t.get("e21"); e50=t.get("e50")
    if e9 and e21 and e9>e21: s+=6; R.append(f"[{label}] EMA9>EMA21")
    if e21 and e50 and e21>e50:s+=4

    # VWAP
    vp=t.get("vwap")
    if vp and p>vp: s+=7; conf+=1
    elif vp and p<vp*0.99: s-=5

    # Support
    sup=t.get("sup"); res=t.get("res")
    if sup and p<=sup*1.015: s+=8; R.append(f"[{label}] قرب دعم ${sup} 🛡️"); conf+=1
    if res and p>=res*0.985: s-=8

    # Volume
    vr=t.get("vr",1); rv=t.get("rvol5",1)
    if vr>=3 and rv>=2:  s+=15; R.append(f"[{label}] حجم {vr:.1f}x 🔥🔥🔥"); conf+=1
    elif vr>=2:          s+=10; R.append(f"[{label}] حجم {vr:.1f}x 🔥🔥")
    elif vr>=1.5:        s+=6;  R.append(f"[{label}] حجم {vr:.1f}x 🔥")
    elif vr<0.5:         s-=10

    # Breakout
    brk=t.get("brk","NONE")
    if brk=="BULL": s+=14; R.append(f"[{label}] 🚀 Breakout! {t.get('brk_vr')}x"); conf+=1
    elif brk=="BEAR":s-=10

    # Patterns
    pts=t.get("pts",[])
    if pts: s+=min(len(pts)*5,12); R.append(f"[{label}] {' '.join(pts)}"); conf+=1

    return min(s,100), R, conf


def multi_tf_score(t15:dict, t1h:dict, t1d:dict, fg:dict, sent:float) -> tuple[int,str,list,int]:
    """تقييم متعدد الأطر الزمنية — القرار النهائي"""
    if not t15: return 0,"NONE",[],0

    # تقييم كل طبقة
    s15,r15,c15 = score_tf(t15,"15m")
    s1h,r1h,c1h = score_tf(t1h,"1h") if t1h else (0,[],0)
    s1d,r1d,c1d = score_tf(t1d,"1D") if t1d else (0,[],0)

    # الوزن: 15m أهم (50%) + 1h (30%) + 1d (20%)
    total = round(s15*0.5 + s1h*0.3 + s1d*0.2)
    conf  = c15 + (c1h//2) + (c1d//3)  # تأكيدات مرجحة

    # جمع الأسباب
    reasons = r15[:4] + r1h[:2] + r1d[:1]

    # Fear & Greed
    fgv=fg.get("value",50)
    if fgv<=25:   total+=10; reasons.append(f"😱 خوف شديد {fgv:.0f}"); conf+=1
    elif fgv<=40: total+=5;  reasons.append(f"😟 خوف {fgv:.0f}")
    elif fgv>=80: total-=10
    elif fgv>=65: total-=5

    # Sentiment
    if sent>0.65:   total+=6; reasons.append("📰 أخبار إيجابية")
    elif sent<0.35: total-=6; reasons.append("📰 أخبار سلبية")

    # توافق الأطر الزمنية (أقوى إشارة)
    all_bullish = (t15.get("rsi",50)<50 and
                   (not t1h or t1h.get("rsi",50)<55) and
                   (not t1d or t1d.get("rsi",50)<60))
    if all_bullish: total+=8; reasons.append("✅ توافق كل الأطر"); conf+=1

    # تحديد نوع الصفقة
    sig="NONE"
    if total>=MIN_SCORE and conf>=MIN_CONFIRMS:
        brk=t15.get("brk","NONE")
        r15v=t15.get("rsi",50)
        mh=t15.get("macd_hist")
        vr=t15.get("vr",1)
        if brk=="BULL":                sig="BREAKOUT"
        elif r15v<30 and t15.get("bb_l") and t15["price"]<=t15["bb_l"]*1.01: sig="REVERSAL"
        elif mh and mh>0 and vr>=1.5: sig="MOMENTUM"
        elif t15.get("pts"):           sig="PATTERN"
        else:                          sig="BUY"

    return min(total,100), sig, reasons, conf


def targets(t15:dict, t1d:dict) -> dict:
    p=t15.get("price",0)
    at=t15.get("atr",p*0.005)  # ATR صغير للمضاربة
    bl=t15.get("bb_l",p*0.99)
    sup=t15.get("sup",p*0.99)
    sl=round(min(p-at*1.5, bl*0.998, sup*0.998),4)
    risk=max(p-sl, p*0.003)
    # أهداف مضاربة قريبة
    tp1=round(p+risk*1.0,4)  # R:R 1:1
    tp2=round(p+risk*1.8,4)  # R:R 1:1.8
    tp3=round(p+risk*3.0,4)  # R:R 1:3
    res=t15.get("res")
    if res and p<res: tp2=round(min(tp2,res*0.998),4)
    return dict(
        entry=p, sl=sl, tp1=tp1, tp2=tp2, tp3=tp3,
        risk_pct=round(risk/p*100,3),
        rr=round(risk*3.0/risk,1)
    )


# ══════════════════════════════════════════════
# CLAUDE AI — حكم مختصر وسريع
# ══════════════════════════════════════════════
async def claude_verdict(sym,t15,sc,conf,reasons,tgt,fg_val,sent) -> tuple[str,bool]:
    prompt=(
        f"سهم {sym} | نقاط {sc}/100 | تأكيدات {conf} | {session()}\n"
        f"السعر ${t15.get('price')} | 15m RSI:{t15.get('rsi')} MACD_H:{t15.get('macd_hist')} "
        f"Stoch:{t15.get('sk')} Vol:{t15.get('vr')}x Brk:{t15.get('brk')}\n"
        f"BB_L:{t15.get('bb_l')} VWAP:{t15.get('vwap')} ADX:{t15.get('adx')}\n"
        f"SL:{tgt['sl']} TP1:{tgt['tp1']} TP2:{tgt['tp2']} TP3:{tgt['tp3']} R:R=1:{tgt['rr']}\n"
        f"F&G:{fg_val:.0f} | مشاعر:{sent:.2f}\n"
        f"أسباب:{' | '.join(reasons[:4])}\n\n"
        f"أجب بسطرين فقط:\n"
        f"1. ✅ادخل / ⚠️انتظر / ❌تجنب — سبب واحد\n"
        f"2. أهم مخاطرة"
    )
    try:
        async with aiohttp.ClientSession() as s:
            async with s.post("https://api.anthropic.com/v1/messages",
                headers={"x-api-key":ANTHROPIC_API_KEY,"anthropic-version":"2023-06-01","content-type":"application/json"},
                json={"model":"claude-haiku-4-5-20251001","max_tokens":120,
                      "messages":[{"role":"user","content":prompt}]},
                timeout=aiohttp.ClientTimeout(total=20)) as r:
                d=await r.json()
        if "content" not in d: return "⚠️ AI غير متاح",True
        txt=d["content"][0]["text"]
        approved="تجنب" not in txt and "❌" not in txt[:30]
        return txt,approved
    except Exception as e:
        return f"⚠️ {e}",True


# ══════════════════════════════════════════════
# ALERT — مختصر وواضح
# ══════════════════════════════════════════════
def fmt(sym,t15,t1h,t1d,sc,sig,conf,reasons,tgt,ai,fg):
    ses=session()
    sig_em={"BREAKOUT":"🚀","REVERSAL":"🔄","MOMENTUM":"⚡","PATTERN":"🕯️","BUY":"📈"}.get(sig,"📈")
    grade="A+" if sc>=88 else "A" if sc>=80 else "B+"
    p=tgt['entry']; pct=lambda x:f"+{round((x-p)/p*100,2)}%"
    fgv=fg.get("value",50)
    fg_em="😱" if fgv<=25 else "😟" if fgv<=40 else "😐" if fgv<=55 else "😊" if fgv<=75 else "🤑"

    # إشارات الأطر
    tf_line=""
    if t1h: tf_line+=f"1h RSI:{t1h.get('rsi','—')} "
    if t1d: tf_line+=f"1D RSI:{t1d.get('rsi','—')}"

    top_reasons=[r for r in reasons if "15m" in r][:3]

    return (
        f"{sig_em} *{sym}* | {grade} {sc}/100 | {ses}\n"
        f"✅ {conf} تأكيد | {sig_em} {sig}\n"
        f"💵 `${p}` | {'+' if t15.get('chg',0)>=0 else ''}{t15.get('chg')}%"
        f" | Vol:{t15.get('vr')}x | {fg_em}{fgv:.0f}\n\n"
        f"🎯 *TP1* `${tgt['tp1']}` ({pct(tgt['tp1'])})\n"
        f"🎯 *TP2* `${tgt['tp2']}` ({pct(tgt['tp2'])})\n"
        f"🎯 *TP3* `${tgt['tp3']}` ({pct(tgt['tp3'])})\n"
        f"🛑 *SL* `${tgt['sl']}` (-{tgt['risk_pct']}%) | R:R 1:{tgt['rr']}\n\n"
        f"📊 15m: RSI:{t15.get('rsi')} MACD:{t15.get('macd_hist')} Stoch:{t15.get('sk')}\n"
        +(f"⏱️ {tf_line}\n" if tf_line else "")
        +(f"🕯️ {' '.join(t15.get('pts',[]))}\n" if t15.get('pts') else "")
        +(f"🚀 Breakout {t15.get('brk_vr')}x\n" if t15.get('brk')=="BULL" else "")
        +f"\n🧠 {ai}\n\n"
        +"\n".join(f"• {r.split('] ')[-1]}" for r in top_reasons)
    )


# ══════════════════════════════════════════════
# SCANNER
# ══════════════════════════════════════════════
async def scan_symbol(sym:str, fg:dict):
    try:
        # جلب 15 دقيقة أولاً (الأهم)
        d15=await td_candles(sym,"15min",80)
        if not d15: return None
        t15=analyze(d15,True)
        if not t15: return None

        # فلتر سريع
        r=t15.get("rsi",50); vr=t15.get("vr",1)
        if r>65 and vr<1.1: return None
        if r>55 and t15.get("macd_hist",0)<0: return None

        # تقييم أولي بدون أطر أخرى
        sc_pre,_,__,conf_pre=multi_tf_score(t15,{},{},fg,0.5)
        if sc_pre<MIN_SCORE-12: return None

        return t15, sc_pre
    except Exception as e:
        log.debug(f"scan {sym}: {e}"); return None


async def run_scanner(app):
    global alert_count,hour_reset,active,stats
    log.info("🚀 Ultra Scalping Scanner v5.0 started")

    while True:
        if not active: await asyncio.sleep(60); continue
        if time.time()-hour_reset>3600: alert_count=0; hour_reset=time.time()

        ses=session(); fg=await get_fg()
        log.info(f"🔍 Scanning {len(WATCHLIST)} | {ses} | F&G:{fg['value']:.0f}")
        t0=time.time(); found=0; sent=0; rej=0

        for i in range(0,len(WATCHLIST),8):
            if alert_count>=MAX_ALERTS_HOUR: break
            batch=WATCHLIST[i:i+8]
            results=await asyncio.gather(*[scan_symbol(s,fg) for s in batch],return_exceptions=True)

            for sym,res in zip(batch,results):
                if not res or isinstance(res,Exception): continue
                t15,sc_pre=res; found+=1

                if time.time()-alerted.get(sym,0)<COOLDOWN_MIN*60: continue

                # جلب الأطر الأخرى فقط للمؤهلين
                d1h,d1d,sent_score=await asyncio.gather(
                    td_candles(sym,"1h",50),
                    yahoo_daily(sym),
                    get_sentiment(sym),
                    return_exceptions=True
                )
                t1h=analyze(d1h) if d1h and not isinstance(d1h,Exception) else {}
                t1d=analyze(d1d) if d1d and not isinstance(d1d,Exception) else {}
                if isinstance(sent_score,Exception): sent_score=0.5

                sc,sig,reasons,conf=multi_tf_score(t15,t1h,t1d,fg,sent_score)
                if sc<MIN_SCORE or sig=="NONE" or conf<MIN_CONFIRMS: continue

                tgt=targets(t15,t1d)
                ai,approved=await claude_verdict(sym,t15,sc,conf,reasons,tgt,fg["value"],sent_score)
                if not approved: rej+=1; log.info(f"🚫 {sym}"); continue

                msg=fmt(sym,t15,t1h,t1d,sc,sig,conf,reasons,tgt,ai,fg)
                ok=False
                for cid in ALERT_CHAT_IDS:
                    try: await app.bot.send_message(cid,msg,parse_mode="Markdown"); ok=True
                    except Exception as e: log.error(f"send {cid}: {e}")
                if ok:
                    alerted[sym]=time.time(); alert_count+=1; sent+=1
                    log.info(f"✅ {sym} sc={sc} sig={sig} conf={conf}")

            await asyncio.sleep(1.5)

        elapsed=round(time.time()-t0)
        now=datetime.now(timezone.utc).strftime("%H:%M")
        stats={"scanned":len(WATCHLIST),"found":found,"sent":sent,
               "rejected":rej,"time":f"{elapsed}s","last":now}
        log.info(f"✅ found={found} sent={sent} rej={rej} {elapsed}s")
        await asyncio.sleep(SCAN_INTERVAL)


# ══════════════════════════════════════════════
# TELEGRAM
# ══════════════════════════════════════════════
async def start(update,ctx):
    cid=update.effective_chat.id
    kb=[[InlineKeyboardButton("📡 تفعيل",callback_data="sub"),
         InlineKeyboardButton("🔕 إيقاف",callback_data="unsub")],
        [InlineKeyboardButton("🔍 فحص الآن",callback_data="scan"),
         InlineKeyboardButton("📊 الحالة",callback_data="status")],
        [InlineKeyboardButton("😱 F&G",callback_data="fg"),
         InlineKeyboardButton("⚙️ إعدادات",callback_data="cfg")]]
    await update.message.reply_text(
        f"🤖 *Ultra Scalping Bot v5.0*\n\n"
        f"⚡ صفقات مضاربة: ساعات → أسبوع\n"
        f"🔍 {len(WATCHLIST)} سهم | فحص كل {SCAN_INTERVAL//60} دقائق\n"
        f"📊 3 أطر زمنية: 15m + 1h + 1D\n"
        f"🧠 ADX + Breakout + Divergence + Patterns\n"
        f"✅ {MIN_CONFIRMS}+ تأكيدات | {MIN_SCORE}+ نقطة\n"
        f"🆔 `{cid}`\n\n_اضغط تفعيل للبدء_ 👇",
        parse_mode="Markdown",reply_markup=InlineKeyboardMarkup(kb))


async def btn(update,ctx):
    q=update.callback_query
    # تأكيد الاستلام الفوري وتنبيه المستخدم بنص خفيف أعلى الشاشة
    await q.answer("جاري المعالجة...") 
    cid=q.message.chat_id

    if q.data=="sub":
        if cid not in ALERT_CHAT_IDS: ALERT_CHAT_IDS.append(cid)
        await q.edit_message_text(
            f"✅ *تم التفعيل!*\n\n"
            f"⚡ {len(WATCHLIST)} سهم | كل {SCAN_INTERVAL//60} دقائق\n"
            f"📊 15m + 1h + 1D | {MIN_SCORE}+ نقطة | {MIN_CONFIRMS}+ تأكيد\n"
            f"🎯 TP1/TP2/TP3 + SL + R:R\n\nسيصلك تنبيه عند الفرصة 🚀",
            parse_mode="Markdown")
            
    elif q.data=="unsub":
        if cid in ALERT_CHAT_IDS: ALERT_CHAT_IDS.remove(cid)
        await q.edit_message_text("🔕 تم الإيقاف.")
        
    elif q.data=="fg":
        fg=await get_fg(); v=fg["value"]; lb=fg["label"]
        adv="🟢 ممتاز للشراء" if v<=25 else "🟡 جيد" if v<=40 else "🔴 تحذر" if v>=75 else "⚪ محايد"
        await q.edit_message_text(f"😱 *Fear & Greed*\n\n{v:.0f}/100 — {lb}\n{adv}",parse_mode="Markdown")
        
    elif q.data=="status":
        fg=await get_fg(); st=stats
        await q.edit_message_text(
            f"📊 *الحالة*\n\n"
            f"⏰ {session()} | F&G:{fg['value']:.0f}\n"
            f"📡 {'🟢' if active else '🔴'} | تنبيهات/ساعة:{alert_count}/{MAX_ALERTS_HOUR}\n\n"
            f"آخر فحص {st.get('last','—')}:\n"
            f"فُحص:{st.get('scanned',0)} فرص:{st.get('found',0)} "
            f"أُرسل:{st.get('sent',0)} رُفض:{st.get('rejected',0)} "
            f"وقت:{st.get('time','—')}",
            parse_mode="Markdown")
            
    elif q.data=="cfg":
        await q.edit_message_text(
            f"⚙️ *الإعدادات*\n\n"
            f"📊 الحد: {MIN_SCORE}/100 | تأكيدات: {MIN_CONFIRMS}+\n"
            f"⏱️ مسح: {SCAN_INTERVAL//60} دق | كولداون: {COOLDOWN_MIN} دق\n"
            f"🔔 حد/ساعة: {MAX_ALERTS_HOUR}\n\n"
            f"*المصادر:*\n"
            f"Twelve Data 15m+1h ✅\n"
            f"Yahoo Finance 1D ✅\n"
            f"Finnhub Sentiment ✅\n"
            f"CNN Fear&Greed ✅\n\n"
            f"*المؤشرات:* RSI MACD Stoch BB WR CCI ADX VWAP Momentum Breakout Patterns",
            parse_mode="Markdown")
            
    elif q.data=="scan":
        await q.edit_message_text("⏳ جاري الفحص السريع لأعلى 10 أسهم سيولة...")
        fg=await get_fg(); found=[]
        
        # تم تقليص العدد لـ 10 وفحصهم بالتوازي (Async) لمنع تعليق الزر وحظر الـ API
        batch = WATCHLIST[:10]
        results = await asyncio.gather(*[scan_symbol(sym, fg) for sym in batch], return_exceptions=True)
        
        for sym, res in zip(batch, results):
            if res and not isinstance(res, Exception):
                t15, sc = res
                found.append((sc, f"📈 *{sym}* {sc}/100 | ${t15['price']} RSI:{t15.get('rsi')} Vol:{t15.get('vr')}x"))
                
        found.sort(key=lambda x: -x[0])
        msg = ("🔍 *أفضل الفرص الحالية (Top 10):*\n\n" + "\n".join(x[1] for x in found[:5]) + "\n\n_أرسل رمز السهم للتحليل الكامل_") if found else "🔍 لا توجد فرص محققة للشروط في هذه اللحظة."
        await q.edit_message_text(msg, parse_mode="Markdown")

async def analyze_cmd(update,ctx):
    sym=update.message.text.strip().upper()
    if not sym.isalpha() or len(sym)>6: return
    msg=await update.message.reply_text(f"⏳ تحليل *{sym}*...",parse_mode="Markdown")
    try:
        fg=await get_fg()
        d15,d1h,d1d,sent=await asyncio.gather(
            td_candles(sym,"15min",80),td_candles(sym,"1h",50),
            yahoo_daily(sym),get_sentiment(sym),return_exceptions=True)
        if isinstance(d15,Exception) or not d15:
            await msg.edit_text(f"❌ لا بيانات لـ `{sym}`"); return
        t15=analyze(d15,True)
        if not t15:
            await msg.edit_text(f"❌ بيانات غير كافية"); return
        t1h=analyze(d1h) if d1h and not isinstance(d1h,Exception) else {}
        t1d=analyze(d1d) if d1d and not isinstance(d1d,Exception) else {}
        if isinstance(sent,Exception): sent=0.5
        sc,sig,reasons,conf=multi_tf_score(t15,t1h,t1d,fg,sent)
        tgt=targets(t15,t1d)
        ai,_=await claude_verdict(sym,t15,sc,conf,reasons,tgt,fg["value"],sent)
        if sc>=MIN_SCORE and sig!="NONE":
            await msg.edit_text(fmt(sym,t15,t1h,t1d,sc,sig,conf,reasons,tgt,ai,fg),parse_mode="Markdown")
        else:
            await msg.edit_text(
                f"📊 *{sym}* | {session()}\n"
                f"💵 `${t15['price']}` | {t15.get('chg')}%\n"
                f"RSI:{t15.get('rsi')} MACD:{t15.get('macd_hist')} Vol:{t15.get('vr')}x\n"
                f"ADX:{t15.get('adx')} Brk:{t15.get('brk')}\n\n"
                f"⚠️ *{sc}/100* | تأكيدات:{conf}/{MIN_CONFIRMS}\n"
                f"🧠 {ai}",parse_mode="Markdown")
    except Exception as e:
        await msg.edit_text(f"❌ `{e}`",parse_mode="Markdown")


async def post_init(app):
    asyncio.create_task(run_scanner(app))
    log.info("✅ Ultra Scalping Bot v5.0 ready")

def main():
    app=Application.builder().token(TELEGRAM_BOT_TOKEN).post_init(post_init).build()
    app.add_handler(CommandHandler("start",start))
    app.add_handler(CommandHandler("help",start))
    app.add_handler(CallbackQueryHandler(btn))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND,analyze_cmd))
    log.info("🤖 Ultra Scalping Bot v5.0")
    app.run_polling(drop_pending_updates=True)

if __name__=="__main__":
    main()
