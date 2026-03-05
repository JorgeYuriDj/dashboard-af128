import streamlit as st
import gspread
from google.oauth2.service_account import Credentials
import pandas as pd
import plotly.graph_objects as go
from datetime import datetime, date
import json

# ─── CONFIG ────────────────────────────────────────────────────────────────────
# ID da planilha no Google Sheets (da URL: /spreadsheets/d/{ID}/edit)
ID_PLANILHA = "1n_5bYyusiKQmce_Vvu7eq5gq8arMvsomvb4yKoHGcKw"

# Metas da campanha (do regulamento AFEET 2026)
META_COLETIVA     = 325_159.91
META_MINIMA_FLEX  = 243_869.93
BONUS_META        = 406_449.89
SUPER_META        = 447_094.87
META_TX_CONVERSAO = 18.89

# ─── CONEXÃO COM GOOGLE SHEETS ────────────────────────────────────────────────
@st.cache_resource
def conectar_sheets():
    creds_dict = st.secrets["gcp_service_account"]
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets.readonly",
        "https://www.googleapis.com/auth/drive.readonly",
    ]
    creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
    return gspread.authorize(creds)

# ─── LEITURA DOS DADOS ────────────────────────────────────────────────────────
@st.cache_data(ttl=60)
def carregar_dados():
    gc     = conectar_sheets()
    sh     = gc.open_by_key(ID_PLANILHA)

    # ── Aba VENDEDORES ──────────────────────────────────────────────────────
    ws_v   = sh.worksheet("VENDEDORES")
    dados_v = ws_v.get_all_values()

    hoje       = date.today()
    dias_mes   = 31 if hoje.month in (1,3,5,7,8,10,12) else (28 if hoje.month == 2 else 30)

    def to_float(val):
        try:
            return float(str(val).replace("R$","").replace(".","").replace(",",".").strip())
        except:
            return 0.0

    vendedores = []
    for row in dados_v[3:10]:   # linhas 4-10 (0-indexed: 3-9)
        if len(row) < 8:
            continue
        nome = row[2]
        if not nome or "LOJA" in nome.upper():
            continue
        meta  = to_float(row[3])
        feito = to_float(row[4])
        hiiss = to_float(row[6])
        total = to_float(row[7]) or (feito + hiiss)
        at_pct = (total / meta * 100) if meta else 0
        proj   = (total / max(hoje.day, 1)) * dias_mes

        vendedores.append({
            "nome":      nome.split()[0].capitalize(),
            "nome_full": nome,
            "meta":      meta,
            "feito":     feito,
            "hiiss":     hiiss,
            "total":     total,
            "at_pct":    round(at_pct, 1),
            "projecao":  round(proj, 2),
        })

    # Linha 11 = total loja
    row_loja  = dados_v[10] if len(dados_v) > 10 else []
    fat_meta  = to_float(row_loja[3]) if len(row_loja) > 3 else META_COLETIVA
    fat_total = to_float(row_loja[7]) if len(row_loja) > 7 else sum(v["total"] for v in vendedores)

    # ── Aba KPIs ────────────────────────────────────────────────────────────
    kpis = {
        "fat_meta":      fat_meta or META_COLETIVA,
        "fat_total":     fat_total,
        "tx_conv_meta":  META_TX_CONVERSAO,
        "tx_conv_feito": 0,
        "pa_meta":       1.47, "pa_feito":     0,
        "ticket_meta":   900,  "ticket_feito": 0,
        "hiiss_meta":    56_000, "hiiss_feito": 0,
    }
    try:
        ws_k    = sh.worksheet("KPIs")
        dados_k = ws_k.get_all_values()
        if len(dados_k) >= 32:
            kpis["tx_conv_feito"]  = to_float(dados_k[16][3])  # D17
            kpis["pa_feito"]       = to_float(dados_k[21][3])  # D22
            kpis["ticket_feito"]   = to_float(dados_k[26][3])  # D27
            kpis["hiiss_feito"]    = to_float(dados_k[31][3])  # D32
            kpis["tx_conv_meta"]   = to_float(dados_k[16][2]) or META_TX_CONVERSAO
            kpis["pa_meta"]        = to_float(dados_k[21][2]) or 1.47
            kpis["ticket_meta"]    = to_float(dados_k[26][2]) or 900
            kpis["hiiss_meta"]     = to_float(dados_k[31][2]) or 56_000
    except Exception:
        pass

    return vendedores, kpis, hoje, dias_mes

# ─── HELPERS ──────────────────────────────────────────────────────────────────
def calcular_premio_individual(at_pct):
    if at_pct < 25:  return 0.0,  "—"
    if at_pct < 50:  return 0.5,  "Faixa 1"
    if at_pct < 75:  return 0.75, "Faixa 2"
    if at_pct < 100: return 1.0,  "Faixa 3"
    if at_pct < 110: return 1.25, "Faixa 4"
    if at_pct < 120: return 1.5,  "Faixa 5"
    if at_pct < 150: return 2.0,  "Faixa 6"
    return 2.5, "Faixa 7"

def cor(pct):
    if pct >= 100: return "#22c55e"
    if pct >= 75:  return "#f59e0b"
    return "#ef4444"

def emoji(pct):
    if pct >= 100: return "🟢"
    if pct >= 75:  return "🟡"
    return "🔴"

def gauge(valor, meta, titulo, prefixo="R$", sufixo=""):
    pct = min((valor / meta * 100) if meta else 0, 150)
    fig = go.Figure(go.Indicator(
        mode="gauge+number+delta",
        value=valor,
        delta={"reference": meta, "valueformat": ",.0f"},
        number={"prefix": prefixo, "valueformat": ",.0f", "suffix": sufixo},
        title={"text": titulo, "font": {"size": 14}},
        gauge={
            "axis": {"range": [0, meta * 1.5], "tickformat": ",.0f"},
            "bar":  {"color": cor(pct)},
            "steps": [
                {"range": [0, meta * 0.75],  "color": "#fecaca"},
                {"range": [meta * 0.75, meta],"color": "#fef08a"},
                {"range": [meta, meta * 1.5], "color": "#bbf7d0"},
            ],
            "threshold": {"line": {"color": "#1e40af", "width": 3}, "value": meta},
        }
    ))
    fig.update_layout(height=220, margin=dict(t=30, b=10, l=20, r=20))
    return fig

# ─── MAIN ──────────────────────────────────────────────────────────────────────
def main():
    st.set_page_config(
        page_title="Dashboard AF128 - Grupo AFEET",
        page_icon="📊",
        layout="wide",
        initial_sidebar_state="collapsed",
    )

    st.markdown("""
    <style>
        .block-container{padding-top:1rem;padding-bottom:1rem}
        .metric-card{background:white;border-radius:12px;padding:16px 20px;
                     box-shadow:0 1px 4px rgba(0,0,0,.08);margin-bottom:8px}
        .big-number{font-size:2rem;font-weight:700}
        .badge{display:inline-block;padding:4px 12px;border-radius:20px;font-size:13px;font-weight:600}
        .verde{background:#dcfce7;color:#15803d}
        .amarelo{background:#fef9c3;color:#a16207}
        .vermelho{background:#fee2e2;color:#b91c1c}
    </style>
    """, unsafe_allow_html=True)

    # Header
    c1, c2, c3 = st.columns([3, 1, 1])
    with c1: st.markdown("## 📊 Dashboard AF128 — Grupo AFEET")
    with c2:
        if st.button("🔄 Atualizar"):
            st.cache_data.clear()
            st.rerun()
    with c3: st.markdown(f"**Hoje:** {date.today().strftime('%d/%m/%Y')}")

    try:
        vendedores, kpis, hoje, dias_mes = carregar_dados()
    except Exception as e:
        import traceback
        st.error(f"❌ Erro ao conectar com Google Sheets: [{type(e).__name__}] {e}")
        st.code(traceback.format_exc())
        return

    fat_total = kpis["fat_total"]
    fat_meta  = kpis["fat_meta"]
    fat_pct   = (fat_total / fat_meta * 100) if fat_meta else 0
    projecao  = (fat_total / max(hoje.day, 1)) * dias_mes if fat_total else 0

    st.divider()

    # ── Status da Campanha ────────────────────────────────────────────────────
    st.markdown("### 🏆 Status da Campanha")
    metas_camp = [
        ("Meta Mínima Flex", META_MINIMA_FLEX, "Bônus Coletivo 0,5%"),
        ("Meta Coletiva",    META_COLETIVA,    "Bônus Coletivo 0,75%"),
        ("Bônus Meta",       BONUS_META,       "Gerente/Sub majorados"),
        ("Super Meta",       SUPER_META,       "Maior prêmio"),
    ]
    for col, (label, v_meta, desc) in zip(st.columns(4), metas_camp):
        atingiu = fat_total >= v_meta
        projetou = projecao >= v_meta
        cls  = "verde" if atingiu else ("amarelo" if projetou else "vermelho")
        icon = "✅" if atingiu else ("📈" if projetou else "⚠️")
        txt  = "ATINGIDA" if atingiu else ("Na projeção" if projetou else "Em risco")
        with col:
            st.markdown(f"""
            <div class="metric-card" style="text-align:center">
                <div style="font-size:11px;color:#6b7280;margin-bottom:4px">{label}</div>
                <div style="font-size:20px;font-weight:700">R$ {v_meta:,.0f}</div>
                <div style="margin-top:6px"><span class="badge {cls}">{icon} {txt}</span></div>
                <div style="font-size:11px;color:#9ca3af;margin-top:4px">{desc}</div>
            </div>""", unsafe_allow_html=True)

    st.divider()

    # ── KPIs Gauges ───────────────────────────────────────────────────────────
    st.markdown("### 📈 KPIs da Loja")
    g1, g2, g3, g4 = st.columns(4)
    with g1: st.plotly_chart(gauge(fat_total, fat_meta, "Faturamento"), use_container_width=True)
    with g2: st.plotly_chart(gauge(kpis["tx_conv_feito"], kpis["tx_conv_meta"], "Taxa de Conversão", "", ""), use_container_width=True)
    with g3: st.plotly_chart(gauge(kpis["pa_feito"],      kpis["pa_meta"],      "PA (Peças/Atend.)",  "", ""), use_container_width=True)
    with g4: st.plotly_chart(gauge(kpis["hiiss_feito"],   kpis["hiiss_meta"],   "HIISS + Catálogo"), use_container_width=True)

    p1, p2 = st.columns(2)
    with p1:
        pct_proj = projecao / fat_meta * 100 if fat_meta else 0
        st.markdown(f"""
        <div class="metric-card">
            <div style="font-size:12px;color:#6b7280">📅 Dia {hoje.day} de {dias_mes} | Projeção do mês</div>
            <div class="big-number" style="color:{cor(pct_proj)}">R$ {projecao:,.2f}</div>
            <div style="font-size:13px;color:#6b7280">{emoji(pct_proj)}
                {"No caminho para bater a meta!" if projecao >= fat_meta else f"Faltam R$ {fat_meta - projecao:,.0f} para a meta"}
            </div>
        </div>""", unsafe_allow_html=True)
    with p2:
        pct_t = (kpis["ticket_feito"] / kpis["ticket_meta"] * 100) if kpis["ticket_meta"] else 0
        st.markdown(f"""
        <div class="metric-card">
            <div style="font-size:12px;color:#6b7280">🎟️ Ticket Médio</div>
            <div class="big-number" style="color:{cor(pct_t)}">R$ {kpis["ticket_feito"]:,.2f}</div>
            <div style="font-size:13px;color:#6b7280">{emoji(pct_t)} Meta: R$ {kpis["ticket_meta"]:,.2f} ({pct_t:.0f}%)</div>
        </div>""", unsafe_allow_html=True)

    st.divider()

    # ── Vendedores ────────────────────────────────────────────────────────────
    st.markdown("### 👥 Desempenho dos Vendedores")
    if vendedores:
        df = pd.DataFrame(vendedores).sort_values("at_pct", ascending=False).reset_index(drop=True)
        col_bar, col_det = st.columns([3, 2])

        with col_bar:
            fig = go.Figure(go.Bar(
                x=df["at_pct"], y=df["nome"], orientation="h",
                marker_color=[cor(p) for p in df["at_pct"]],
                text=[f"{p:.0f}%" for p in df["at_pct"]], textposition="outside",
            ))
            fig.add_vline(x=100, line_dash="dash", line_color="#1e40af",
                          annotation_text="Meta", annotation_position="top")
            fig.update_layout(
                xaxis=dict(range=[0, max(df["at_pct"].max()*1.2, 120)],
                           ticksuffix="%", showgrid=True, gridcolor="#f3f4f6"),
                yaxis=dict(autorange="reversed"),
                plot_bgcolor="white",
                height=max(250, len(df)*48),
                margin=dict(l=10, r=60, t=10, b=10),
                showlegend=False,
            )
            st.plotly_chart(fig, use_container_width=True)

        with col_det:
            st.markdown("**Prêmio Estimado**")
            for _, v in df.iterrows():
                pct_p, faixa = calcular_premio_individual(v["at_pct"])
                premio = v["total"] * pct_p / 100
                c = cor(v["at_pct"])
                st.markdown(f"""
                <div style="display:flex;justify-content:space-between;align-items:center;
                            padding:8px 12px;border-left:4px solid {c};
                            background:#f9fafb;margin-bottom:6px;border-radius:0 8px 8px 0">
                    <div>
                        <div style="font-weight:600;font-size:14px">{v['nome']}</div>
                        <div style="font-size:11px;color:#6b7280">{faixa} • {v['at_pct']:.0f}%</div>
                    </div>
                    <div style="text-align:right">
                        <div style="font-weight:700;color:{c}">R$ {premio:,.0f}</div>
                        <div style="font-size:11px;color:#9ca3af">{pct_p:.2f}%</div>
                    </div>
                </div>""", unsafe_allow_html=True)

    st.divider()

    # ── Prêmios ───────────────────────────────────────────────────────────────
    st.markdown("### 💰 Estimativa de Prêmios")
    m1, m2 = st.columns(2)
    pct_col = 0.75 if fat_total >= META_COLETIVA else (0.50 if fat_total >= META_MINIMA_FLEX else 0.0)
    label_col = ("Meta Coletiva ✅" if fat_total >= META_COLETIVA
                 else ("Meta Flex 🟡" if fat_total >= META_MINIMA_FLEX else "Não atingida 🔴"))
    with m1:
        st.markdown(f"""
        <div class="metric-card">
            <div style="font-size:13px;color:#6b7280">🏪 Prêmio Coletivo da Loja</div>
            <div class="big-number">R$ {fat_total * pct_col / 100:,.2f}</div>
            <div style="font-size:12px;color:#6b7280;margin-top:4px">{label_col} ({pct_col:.2f}%)</div>
        </div>""", unsafe_allow_html=True)
    with m2:
        total_ind = sum(v["total"] * calcular_premio_individual(v["at_pct"])[0] / 100
                       for v in vendedores) if vendedores else 0
        st.markdown(f"""
        <div class="metric-card">
            <div style="font-size:13px;color:#6b7280">👤 Prêmio Individual Total</div>
            <div class="big-number">R$ {total_ind:,.2f}</div>
            <div style="font-size:12px;color:#6b7280;margin-top:4px">Soma dos prêmios individuais (vendedores)</div>
        </div>""", unsafe_allow_html=True)

    st.markdown(f"""<div style="text-align:center;font-size:11px;color:#9ca3af;margin-top:16px">
        Campanha Grupo AFEET 2026 • AF128 Shopping Taguatinga •
        Atualizado: {datetime.now().strftime('%d/%m/%Y %H:%M')}
    </div>""", unsafe_allow_html=True)

if __name__ == "__main__":
    main()
