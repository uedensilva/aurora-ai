import os, time
from datetime import datetime, timezone
import requests
import pandas as pd
import streamlit as st
import plotly.graph_objects as go

st.set_page_config(page_title="AURORA AI | Paper Trading", page_icon="🌌", layout="wide")
st.markdown("""
<style>
.stApp{background:#080d18;color:#edf3ff}
section[data-testid="stSidebar"]{background:#101a2a}
div[data-testid="stMetric"]{background:#111c2e;border:1px solid #293b58;padding:12px;border-radius:12px}
</style>""", unsafe_allow_html=True)

st.title("🌌 AURORA AI")
st.caption("MARKET INTELLIGENCE • PAPER TRADING • SEM ORDENS REAIS")

# ---- Session state: virtual ledger only ----
defaults = {"cash":30.0, "position":None, "trades":[], "starting_cash":30.0, "paused":False}
for k,v in defaults.items():
    if k not in st.session_state: st.session_state[k]=v

with st.sidebar:
    st.header("Configuração")
    market = st.selectbox("Mercado", ["Criptomoedas (Binance)", "Ações / Forex / Metais (Twelve Data)"])
    if market.startswith("Cripto"):
        symbol = st.selectbox("Ativo", ["BTCUSDT","ETHUSDT","BNBUSDT","SOLUSDT","XRPUSDT","ADAUSDT"])
        interval = st.selectbox("Período", ["1m","5m","15m","1h","4h"], index=2)
    else:
        symbol = st.selectbox("Ativo", ["AAPL","MSFT","NVDA","EUR/USD","GBP/USD","XAU/USD","WTI/USD"])
        interval = st.selectbox("Período", ["1min","5min","15min","30min","1h","1day"], index=2)
        st.caption("Insira a chave Twelve Data apenas neste campo privado. Não a envie no chat.")
        td_key = st.text_input("Twelve Data API key", type="password", value=os.getenv("TWELVE_DATA_API_KEY",""))
    refresh = st.selectbox("Atualização do painel", ["15 segundos","30 segundos","60 segundos"], index=1)
    refresh_s = {"15 segundos":15,"30 segundos":30,"60 segundos":60}[refresh]
    st.divider()
    st.metric("Saldo virtual disponível", f"£{st.session_state.cash:.2f}")
    st.caption("£30 é apenas saldo de simulação. Não há conexão com corretora.")

def fetch_binance(sym, iv):
    url="https://api.binance.com/api/v3/klines"
    r=requests.get(url, params={"symbol":sym,"interval":iv,"limit":200}, timeout=12)
    r.raise_for_status()
    raw=r.json()
    df=pd.DataFrame(raw,columns=["open_time","open","high","low","close","volume","close_time","qav","trades","tbb","tbq","ignore"])
    df["time"]=pd.to_datetime(df["open_time"],unit="ms",utc=True)
    for c in ["open","high","low","close","volume"]: df[c]=pd.to_numeric(df[c],errors="coerce")
    return df[["time","open","high","low","close","volume"]], "Binance public market data"

def fetch_twelvedata(sym, iv, key):
    if not key: raise RuntimeError("Adicione sua chave Twelve Data na barra lateral.")
    url="https://api.twelvedata.com/time_series"
    r=requests.get(url,params={"symbol":sym,"interval":iv,"outputsize":200,"apikey":key},timeout=15)
    r.raise_for_status()
    js=r.json()
    if "values" not in js: raise RuntimeError(js.get("message","Erro Twelve Data"))
    df=pd.DataFrame(js["values"])
    df["time"]=pd.to_datetime(df["datetime"],utc=True)
    for c in ["open","high","low","close","volume"]:
        if c in df: df[c]=pd.to_numeric(df[c],errors="coerce")
    df=df.sort_values("time")
    if "volume" not in df: df["volume"]=0
    return df[["time","open","high","low","close","volume"]], "Twelve Data API"

try:
    if market.startswith("Cripto"):
        data, provider=fetch_binance(symbol,interval)
    else:
        data, provider=fetch_twelvedata(symbol,interval,td_key)
    data=data.dropna(subset=["close"]).copy()
    if len(data)<30: raise RuntimeError("Dados insuficientes.")
    data["ema9"]=data.close.ewm(span=9,adjust=False).mean()
    data["ema21"]=data.close.ewm(span=21,adjust=False).mean()
    data["ret"]=data.close.pct_change()
    data["volatility"]=data.ret.rolling(20).std()
    last=data.iloc[-1]; prev=data.iloc[-2]
    if last.ema9>last.ema21 and last.close>last.ema9: signal="BUY"
    elif last.ema9<last.ema21 and last.close<last.ema9: signal="SELL"
    else: signal="WAIT"
    st.success(f"Fonte: {provider} • Último candle: {last.time}")
    c1,c2,c3,c4=st.columns(4)
    c1.metric("Último preço",f'{last.close:,.5f}',f'{(last.close/prev.close-1)*100:+.2f}%')
    c2.metric("Sinal técnico",signal)
    c3.metric("EMA 9",f'{last.ema9:,.5f}')
    c4.metric("Volatilidade 20",f'{last.volatility*100:.3f}%' if pd.notna(last.volatility) else "—")

    fig=go.Figure()
    fig.add_trace(go.Candlestick(x=data.time,open=data.open,high=data.high,low=data.low,close=data.close,name="Preço"))
    fig.add_trace(go.Scatter(x=data.time,y=data.ema9,name="EMA 9",line=dict(width=1.5)))
    fig.add_trace(go.Scatter(x=data.time,y=data.ema21,name="EMA 21",line=dict(width=1.5)))
    fig.update_layout(template="plotly_dark",height=480,xaxis_rangeslider_visible=False,margin=dict(l=10,r=10,t=25,b=10))
    st.plotly_chart(fig,use_container_width=True)

    st.subheader("Simulador automático de sinais")
    risk_per_trade=0.01
    max_stake=min(st.session_state.cash, st.session_state.starting_cash*0.20)
    st.write(f"Risco configurado: 1% do capital inicial por operação. Tamanho máximo de posição: £{max_stake:.2f}.")
    if st.session_state.position is None and not st.session_state.paused:
        if signal=="BUY" and max_stake>=1:
            if st.button("Abrir compra simulada (não envia ordem real)"):
                st.session_state.position={"symbol":symbol,"entry":float(last.close),"stake":float(max_stake),"provider":provider,"time":str(last.time)}
                st.rerun()
    elif st.session_state.position:
        pos=st.session_state.position
        move=float(last.close)/pos["entry"]-1
        st.metric("Resultado não realizado",f'£{pos["stake"]*move:+.2f}',f'{move*100:+.2f}%')
        if st.button("Fechar posição simulada"):
            proceeds=pos["stake"]*(1+move)
            st.session_state.cash += proceeds
            st.session_state.trades.append({"time":datetime.now(timezone.utc).isoformat(),"symbol":pos["symbol"],"entry":pos["entry"],"exit":float(last.close),"pnl":proceeds-pos["stake"],"result":"closed"})
            st.session_state.position=None
            st.rerun()
    st.caption("O sinal é uma regra simples EMA 9/21, não uma previsão. O sistema não abre operações sem clique de confirmação nesta primeira versão.")
except Exception as e:
    st.warning(f"Não foi possível obter dados para este ativo: {e}")
    st.info("Para testar sem chave, selecione Criptomoedas (Binance), que usa dados públicos. Para ações, Forex e metais, configure uma chave Twelve Data.")

st.divider()
pnl=st.session_state.cash-st.session_state.starting_cash
a,b,c=st.columns(3)
a.metric("Saldo virtual",f'£{st.session_state.cash:.2f}')
b.metric("Resultado realizado",f'£{pnl:+.2f}')
c.metric("Operações fechadas",len(st.session_state.trades))
if st.session_state.trades:
    st.dataframe(pd.DataFrame(st.session_state.trades),use_container_width=True)
if st.button("Reiniciar simulação (£30)"):
    st.session_state.cash=30.0; st.session_state.position=None; st.session_state.trades=[]; st.session_state.paused=False
    st.rerun()

st.warning("SEGURANÇA: este projeto é somente para simulação. Não conecta a corretoras, não aceita depósitos e não envia ordens reais. Dados de cripto vêm da API pública Binance; outros mercados exigem chave e plano compatível do provedor. Atualizações dependem dos limites do serviço.")
st.caption("AURORA AI • Protótipo funcional de dados + análise técnica + livro de simulação. Não é aconselhamento financeiro.")
