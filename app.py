import pandas as pd
import streamlit as st
import yfinance as yf

st.set_page_config(page_title="Painel de Ações", layout="wide")

RACIOS = [
    ("P/E", "trailingPE", False),
    ("P/E esperado", "forwardPE", False),
    ("P/B", "priceToBook", False),
    ("EV/EBITDA", "enterpriseToEbitda", False),
    ("Margem líquida", "profitMargins", True),
    ("Margem operacional", "operatingMargins", True),
    ("ROE", "returnOnEquity", True),
    ("ROA", "returnOnAssets", True),
    ("Crescimento da receita", "revenueGrowth", True),
    ("Dívida/Capital próprio (%)", "debtToEquity", False),
    ("Liquidez corrente", "currentRatio", False),
    ("Beta", "beta", False),
]


@st.cache_data(ttl=3600, show_spinner="A obter dados...")
def carregar(ticker):
    t = yf.Ticker(ticker)
    return {
        "info": t.info,
        "income": t.income_stmt,
        "balance": t.balance_sheet,
        "cashflow": t.cashflow,
        "hist": t.history(period="5y"),
    }


@st.cache_data(ttl=3600)
def so_info(ticker):
    return yf.Ticker(ticker).info


def linha(df, nome):
    try:
        return df.loc[nome].dropna().sort_index()
    except KeyError:
        return None


def fmt(v, pct=False):
    if v is None or pd.isna(v):
        return "n/d"
    return f"{v:.1%}" if pct else f"{v:,.2f}"


def tabela(infos):
    return pd.DataFrame(
        {t: {l: fmt(i.get(k), p) for l, k, p in RACIOS} for t, i in infos.items()}
    )


def dcf(fcf, cresc, anos, g_term, taxa, acoes, div_liq):
    fluxos = [fcf * (1 + cresc) ** i for i in range(1, anos + 1)]
    vp = sum(f / (1 + taxa) ** i for i, f in enumerate(fluxos, 1))
    vt = fluxos[-1] * (1 + g_term) / (taxa - g_term) / (1 + taxa) ** anos
    return (vp + vt - div_liq) / acoes


# ---------- Barra lateral ----------
st.sidebar.title("Painel de Ações")
ticker = st.sidebar.text_input("Ticker", "AAPL").upper().strip()
peers_txt = st.sidebar.text_input("Concorrentes (separados por vírgula)", "MSFT, GOOGL")
st.sidebar.caption("Exemplos: EDP.LS, GALP.LS (Lisboa) · ASML.AS (Amesterdão) · SAP.DE (Frankfurt)")

# ---------- Dados ----------
try:
    d = carregar(ticker)
    info = d["info"]
    price = info.get("currentPrice") or info.get("regularMarketPrice")
except Exception:
    price = None
if price is None:
    st.error(f"Não consegui obter dados para '{ticker}'. Confirma o ticker (ex.: EDP.LS).")
    st.stop()

st.title(f"{info.get('longName', ticker)} ({ticker})")
c1, c2, c3, c4 = st.columns(4)
c1.metric("Preço", f"{price:,.2f} {info.get('currency', '')}")
c2.metric("Market cap (mil milhões)", f"{(info.get('marketCap') or 0) / 1e9:,.1f}")
c3.metric("Setor", info.get("sector", "n/d"))
c4.metric("Indústria", info.get("industry", "n/d"))

t1, t2, t3, t4, t5 = st.tabs(
    ["Resumo", "Financials", "Rácios", "Valor intrínseco", "Concorrentes"]
)

with t1:
    st.write(info.get("longBusinessSummary", "Sem descrição disponível."))
    st.line_chart(d["hist"]["Close"])

with t2:
    rec, lucro = linha(d["income"], "Total Revenue"), linha(d["income"], "Net Income")
    if rec is not None and lucro is not None:
        st.bar_chart(pd.DataFrame({"Receita": rec, "Lucro líquido": lucro}))
    for nome, chave in [
        ("Demonstração de resultados", "income"),
        ("Balanço", "balance"),
        ("Fluxos de caixa", "cashflow"),
    ]:
        with st.expander(nome):
            st.dataframe(d[chave])

with t3:
    st.dataframe(tabela({ticker: info}), use_container_width=True)

with t4:
    fcf_s = linha(d["cashflow"], "Free Cash Flow")
    fcf = fcf_s.iloc[-1] if fcf_s is not None and len(fcf_s) else info.get("freeCashflow")
    acoes = info.get("sharesOutstanding")
    div_liq = (info.get("totalDebt") or 0) - (info.get("totalCash") or 0)

    if info.get("currency") != info.get("financialCurrency"):
        st.warning("A moeda do preço e a dos relatórios são diferentes. Converte antes de confiar no resultado.")

    st.caption("O resultado depende inteiramente dos pressupostos abaixo. Ajusta-os com critério.")
    a, b, c, e = st.columns(4)
    cresc = a.slider("Crescimento anual do FCF (%)", -5, 30, 8)
    anos = b.slider("Anos de projeção", 5, 15, 10)
    g = c.slider("Crescimento perpétuo (%)", 0.0, 4.0, 2.5, 0.5)
    taxa = e.slider("Taxa de desconto (%)", 6.0, 15.0, 9.0, 0.5)
    ms = st.slider("Margem de segurança (%)", 0, 50, 25)

    if not fcf or fcf <= 0 or not acoes:
        st.warning("FCF negativo ou indisponível: este DCF simples não se aplica a esta empresa.")
    else:
        st.write(f"FCF mais recente: **{fcf / 1e9:,.2f} mil milhões** · Dívida líquida: **{div_liq / 1e9:,.2f} mil milhões**")
        cenarios = {
            "Pessimista": (cresc - 4, taxa + 1),
            "Base": (cresc, taxa),
            "Otimista": (cresc + 4, taxa - 1),
        }
        linhas, base = [], None
        for nome, (cr, tx) in cenarios.items():
            v = dcf(fcf, cr / 100, anos, g / 100, tx / 100, acoes, div_liq)
            base = v if nome == "Base" else base
            linhas.append({
                "Cenário": nome,
                "Crescimento FCF": f"{cr}%",
                "Taxa desconto": f"{tx}%",
                "Valor intrínseco/ação": round(v, 2),
                "Preço atual": round(price, 2),
                "Diferença": f"{v / price - 1:+.0%}",
            })
        st.dataframe(pd.DataFrame(linhas), hide_index=True, use_container_width=True)
        st.metric(
            f"Preço de compra com {ms}% de margem de segurança (cenário base)",
            f"{base * (1 - ms / 100):,.2f} {info.get('currency', '')}",
        )

with t5:
    infos = {ticker: info}
    for p in [x.strip().upper() for x in peers_txt.split(",") if x.strip()]:
        try:
            infos[p] = so_info(p)
        except Exception:
            st.warning(f"Sem dados para {p}.")
    st.dataframe(tabela(infos), use_container_width=True)
