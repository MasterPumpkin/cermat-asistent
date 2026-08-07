"""
Cermat Asistent – Streamlit UI

Kompletní dashboard pro odhad šancí na přijetí na střední školy:
1. Sidebar – profil uchazeče (kraj, obor, body ČJL/MAT, prospěch)
2. Tabulka škol – s barevnými semafory a vysvětlením predikce
3. Doporučení 1.–2.–3. priority – karty s DiPSy strategií
4. Plotly graf – historický trend PR_min + pásmo nejistoty + čára uchazeče
5. Reverzní kalkulačka – kolik bodů potřebuji?
6. Plán B – alternativní obory při nízké šanci
"""

import json
import sqlite3
from pathlib import Path
from typing import Any

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from cermat_asistent.config import DEFAULT_DB_PATH
from cermat_asistent.db import init_db, seed_demo_data, seed_real_2026_data
from cermat_asistent.pdf_export import generate_pdf_report
from cermat_asistent.service import CermatBackendService

# =====================================================================
# Page Configuration
# =====================================================================
st.set_page_config(
    page_title="Cermat Asistent",
    page_icon="🎓",
    layout="wide",
    initial_sidebar_state="expanded",
)


# =====================================================================
# Inicializace backendu (cached)
# =====================================================================
@st.cache_resource
def get_backend_service() -> CermatBackendService:
    """Vytvoří připojení k DB a inicializuje backend. Spustí se pouze jednou."""
    db_path = DEFAULT_DB_PATH
    excel_file = "data/2026/PZ2026_kolo1_skolobory_vysledky.xlsx"

    if not Path(db_path).exists():
        conn = init_db(db_path)
        if Path(excel_file).exists():
            seed_real_2026_data(conn, excel_file)
        else:
            seed_demo_data(conn)
    else:
        conn = sqlite3.connect(db_path, check_same_thread=False)

    return CermatBackendService(conn)


service = get_backend_service()
filters = service.get_available_filters()

# =====================================================================
# Sidebar – Profil uchazeče
# =====================================================================
st.sidebar.markdown("## 📋 Profil uchazeče")

kraj = st.sidebar.selectbox(
    "Kraj",
    options=["Všechny"] + filters["kraje"],
    key="pref_kraj",
)
kategorie = st.sidebar.selectbox(
    "Typ školy",
    options=["Všechny"] + filters["kategorie"],
    key="pref_kategorie",
)

dynamic_filters = service.get_available_filters(kategorie_filter=kategorie)
obor = st.sidebar.selectbox(
    "Preferovaný obor",
    options=["Všechny"] + dynamic_filters["obory"],
    key="pref_obor",
)

st.sidebar.markdown("---")
st.sidebar.markdown("### 📝 Očekávané body z testů")
cjl = st.sidebar.slider("Český jazyk (max 50)", 0, 50, 35, key="pref_cjl")
mat = st.sidebar.slider("Matematika (max 50)", 0, 50, 30, key="pref_mat")

st.sidebar.markdown("---")
st.sidebar.markdown("### 🏫 Školní prospěch")
prospech = st.sidebar.select_slider(
    "Průměr známek na vysvědčení (8. a 9. třída):",
    options=["1.0", "1.1-1.3", "1.4-1.8", "1.9+"],
    value="1.1-1.3",
    key="pref_prospech",
    help=(
        "Upraví váš odhadovaný percentil (až o ±6 %) podle známek. Ředitelé "
        "škol dále udělují body za certifikáty (FCE/PET), olympiády a soutěže "
        "dle vlastních kritérií vydaných do 31. ledna."
    ),
)

dostupna_mesta = service.get_mesta_for_kraj(kraj)
mesta = st.sidebar.multiselect(
    "Preferovaná města / spádová oblast",
    options=dostupna_mesta,
    default=[],
    key="pref_mesta",
    help=(
        "Vyberte města, která jsou pro vás dopravně dostupná (např. Kutná Hora, Kolín, Čáslav). "
        "Školy z těchto měst budou upřednostněny v přehledu, doporučeních DiPSy i v Plánu B."
    ),
)

# =====================================================================
# Vyhodnocení přes backend
# =====================================================================
eval_data = service.evaluate_schools_for_user(
    user_cjl=cjl,
    user_mat=mat,
    prospech_category=prospech,
    kraj_filter=kraj,
    kategorie_filter=kategorie,
    obor_filter=obor,
    mesta_filter=mesta if mesta else None,
)

pr_info = eval_data["pr_info"]
df_schools = eval_data["evaluated_schools"]
recommendation = eval_data["recommendation"]
plan_b_items = eval_data["plan_b"]

if not df_schools.empty:
    def format_school_label(row: pd.Series) -> str:
        pref = "⭐ " if (mesta and row.get("is_preferred_location")) else ""
        return (
            f"{pref}{row['nazev_skoly']} ({row['mesto']}) – {row['obor']} "
            f"[Odhad: {row['pred_min_percentil']:.1f} %]"
        )

    df_schools["skola_s_oborem"] = df_schools.apply(format_school_label, axis=1)

# Sidebar metriky
st.sidebar.markdown("---")
col_s1, col_s2 = st.sidebar.columns(2)
col_s1.metric("Body celkem", f"{cjl + mat} / 100")
col_s2.metric("Percentil", f"{pr_info['effective_pr']:.1f} %")

if pr_info["prospech_delta"] != 0:
    st.sidebar.caption(
        f"Korekce za prospěch: {pr_info['prospech_delta']:+.1f} % "
        f"(základ z testů: {pr_info['base_test_pr']:.1f} %)"
    )

# PDF export & Správa profilu
st.sidebar.markdown("---")
pdf_bytes = generate_pdf_report(
    pr_info=pr_info,
    df_schools=df_schools,
    recommendation=recommendation,
    plan_b_items=plan_b_items,
    cjl=cjl,
    mat=mat,
    prospech=prospech,
    kraj=kraj,
    mesta=mesta if mesta else None,
)
st.sidebar.download_button(
    label="📄 Stáhnout PDF report",
    data=pdf_bytes,
    file_name="cermat_report.pdf",
    mime="application/pdf",
    width="stretch",
)

with st.sidebar.expander("💾 Správa profilu (Uložit / Načíst)"):
    uploaded_profile = st.file_uploader(
        "📂 Načíst profil (.json)",
        type=["json"],
        key="profile_uploader",
        help="Nahrajte dříve uložený profil ve formátu JSON.",
    )
    if uploaded_profile is not None:
        try:
            profile_data = json.load(uploaded_profile)
            if isinstance(profile_data, dict):
                if "kraj" in profile_data:
                    st.session_state["pref_kraj"] = profile_data["kraj"]
                if "kategorie" in profile_data:
                    st.session_state["pref_kategorie"] = profile_data["kategorie"]
                if "obor" in profile_data:
                    st.session_state["pref_obor"] = profile_data["obor"]
                if "cjl" in profile_data:
                    st.session_state["pref_cjl"] = int(profile_data["cjl"])
                if "mat" in profile_data:
                    st.session_state["pref_mat"] = int(profile_data["mat"])
                if "prospech" in profile_data:
                    st.session_state["pref_prospech"] = profile_data["prospech"]
                if "mesta" in profile_data and isinstance(profile_data["mesta"], list):
                    st.session_state["pref_mesta"] = profile_data["mesta"]
                st.success("Profil byl úspěšně načten!")
                st.rerun()
        except Exception as e:
            st.error(f"Chyba při načítání profilu: {e}")

    export_profile = {
        "version": "1.0",
        "kraj": kraj,
        "kategorie": kategorie,
        "obor": obor,
        "cjl": cjl,
        "mat": mat,
        "prospech": prospech,
        "mesta": mesta,
    }
    export_json = json.dumps(export_profile, ensure_ascii=False, indent=2)
    st.download_button(
        label="💾 Uložit profil",
        data=export_json,
        file_name="cermat_profil.json",
        mime="application/json",
        width="stretch",
    )

# =====================================================================
# Hlavní obsah
# =====================================================================
st.title("🎓 Cermat Asistent")
st.caption(
    "Odhad šancí na přijetí a doporučení strategie přihlášek "
    "na základě historických dat Cermat (DiPSy éra 2024+)."
)

# ----- Metodický průvodce & Vysvětlení -----
with st.expander("ℹ️ Jak funguje Cermat Asistent & Průvodce přijímačkami", expanded=False):
    tab1, tab2, tab3, tab4 = st.tabs(
        [
            "📊 Percentil vs. Body",
            "📜 Školní kritéria & Certifikáty",
            "🎯 DiPSy strategie (1.–3. místo)",
            "📈 Predikce a Pásmo nejistoty",
        ]
    )

    with tab1:
        st.markdown("""
        ### Proč v aplikaci pracujeme s percentily místo bodů?
        Obtížnost testů Cermat se meziročně mění (např. 35 bodů v náročném ročníku z matematiky odpovídá 90. percentilu, zatímco v lehčím ročníku znamená stejných 35 bodů pouze 75. percentil).

        **Percentil udává procento uchazečů, kteří dosáhli horšího nebo stejného výsledku jako vy:**
        - **100. percentil** = nejlepší možný výsledek v populaci
        - **50. percentil** = přesný střed (polovina uchazečů měla méně bodů, polovina více)

        Aplikace převádí vaše cvičné body z ČJL a MAT na **aktuální percentil**, což umožňuje objektivní srovnání s hranicemi přijetí z minulých ročníků.
        """)

    with tab2:
        st.markdown("""
        ### Školní kritéria, vysvědčení a dodatkové body
        Podle školského zákona tvoří Jednotná přijímací zkouška (JPZ) **minimálně 60 %** celkového hodnocení uchazeče u 4letých oborů (min. 50 % u 6letých a 8letých gymnázií).

        **Zbývajících až 40 % bodů určují ředitelé jednotlivých škol:**
        - 📄 **Školní prospěch:** Průměr známek z 8. a 9. třídy ZŠ.
        - 🇬🇧 **Jazykové certifikáty:** Body za mezinárodní certifikáty (Cambridge FCE/PET, DELF, Goethe apod.).
        - 🏆 **Olympiády a soutěže:** Vědomostní olympiády (matematická, fyzikální, dějepisná...), mezinárodní a krajské soutěže.
        - 🏃 **Mimoškolní aktivity a sport:** Zájmové kroužky, sportovní reprezentace či umělecké obory (ZUŠ).

        💡 *V aplikaci můžete v Sidebaru nastavit váš **Školní prospěch**, který upraví váš efektivní percentil o ±procentní body. Nezapomeňte si ale vždy ověřit konkrétní kritéria vybrané SŠ vydávaná ředitelem školy do 31. ledna!*
        """)

    with tab3:
        st.markdown("""
        ### Jak funguje algoritmus DiPSy a jak sestavit přihlášku?
        V novém elektronickém systému DiPSy **neexistuje penalizace za uvedení náročné školy na 1. místě**.

        **Pravidla rozřazování:**
        1. Algoritmus nejprve posuzuje všechny uchazeče na jejich **1. prioritě**.
        2. Pokud se na 1. prioritu nedostanete, systém vás posuzuje na **2. prioritě** se **stejnými právy**, jako byste ji měli na 1. místě (rozhoduje pouze váš bodový zisk, nikoliv pořadí školy).
        3. Stejný princip platí pro 3. prioritu.

        **Doporučená strategie tří přihlášek:**
        - 🎯 **1. Priorita (Vysněná):** Škola s vyššími nároky (šance např. 30–60 %). Pokud testy sednou, dostanete se tam.
        - ⚖️ **2. Priorita (Reálná):** Škola plně odpovídající vaší běžné výkonnosti (šance 60–85 %).
        - 🛡️ **3. Priorita (Jistota):** Škola s nižším přetlakem pro případ výpadku u testů (šance > 85 %).
        """)

    with tab4:
        st.markdown("""
        ### Jak rozumět predikci a pásmu nejistoty?
        Model vychází z reálných historických dat Cermat za roky **2024, 2025 a 2026**.

        Protože se demografie a zájem uchazečů meziročně mění, nepočítáme jedno dogmatické číslo, ale **odhad s intervalem spolehlivosti (Pásmem nejistoty)**:
        - 🟢 **Vysoká šance (Jistota):** Váš percentil je bezpečně nad horní hranicí odhadovaného pásma.
        - 🟡 **Střední šance (Reálná):** Váš percentil spadá do pásma nejistoty – výsledek bude záviset na konkrétní formě v den zkoušky.
        - 🔴 **Nízká šance (Riziková):** Váš percentil nedosahuje na spodní hranici odhadovaného pásma.
        """)

# ----- 1. Tabulka škol -----
st.subheader("1. Přehled vyhodnocených škol")

if not df_schools.empty:
    st.caption(
        "🟢 **Jistota** = percentil nad odhadovaným pásmem | "
        "🟡 **Reálná** = v pásmu nejistoty (rozhodne den zkoušky) | "
        "🔴 **Riziková** = pod odhadovanou hranicí"
    )
    show_cols = [
        "chance_label",
        "nazev_skoly",
        "obor",
        "mesto",
        "pretlak_latest",
        "pred_min_percentil",
        "ci_lower",
        "ci_upper",
        "explanation",
    ]
    st.dataframe(
        df_schools[show_cols].rename(
            columns={
                "chance_label": "Šance",
                "nazev_skoly": "Škola",
                "obor": "Obor",
                "mesto": "Město",
                "pretlak_latest": "Přetlak",
                "pred_min_percentil": "Predikce PR min",
                "ci_lower": "CI dolní",
                "ci_upper": "CI horní",
                "explanation": "Důvod predikce",
            }
        ),
        hide_index=True,
        width="stretch",
    )
else:
    st.warning("Žádná škola neodpovídá vybraným filtrům.")

# ----- 2. Doporučení 1.–2.–3. priority -----
st.markdown("---")
st.subheader("2. Doporučená strategie přihlášek (DiPSy)")

if recommendation:
    c1, c2, c3 = st.columns(3)

    p1 = recommendation["p1_target"]
    p2 = recommendation["p2_real"]
    p3 = recommendation["p3_safe"]

    with c1:
        st.info("🎯 **1. Priorita (Vysněná)**")
        st.markdown(f"**{p1['nazev_skoly']} ({p1['mesto']})**")
        st.write(f"Obor: {p1['obor']}")
        st.write(f"Šance: {p1['chance_label']}")
        st.caption("Vyšší nároky. Pokud test sedne, je šance na přijetí.")

    with c2:
        st.success("⚖️ **2. Priorita (Reálná)**")
        st.markdown(f"**{p2['nazev_skoly']} ({p2['mesto']})**")
        st.write(f"Obor: {p2['obor']}")
        st.write(f"Šance: {p2['chance_label']}")
        st.caption("Odpovídá standardním výsledkům uchazeče.")

    with c3:
        st.warning("🛡️ **3. Priorita (Jistota)**")
        st.markdown(f"**{p3['nazev_skoly']} ({p3['mesto']})**")
        st.write(f"Obor: {p3['obor']}")
        st.write(f"Šance: {p3['chance_label']}")
        st.caption("Záchranná síť pro případ nepovedeného testu.")
else:
    st.info("Pro sestavení strategie je potřeba alespoň 3 vyhodnocené školy.")

# ----- 3. Plotly graf – historický trend + pásmo nejistoty -----
if not df_schools.empty:
    st.markdown("---")
    st.subheader("3. Historický vývoj a predikce")

    selected_school = st.selectbox(
        "Vyberte školu a obor pro zobrazení trendu:",
        options=df_schools["skola_s_oborem"].unique(),
        key="trend_school_select",
    )

    school_row = df_schools[df_schools["skola_s_oborem"] == selected_school].iloc[0]
    hist_df = service.get_school_history(
        school_row["redizo"], school_row["kod_oboru"]
    )

    if not hist_df.empty:
        fig = go.Figure()

        # A) Historická data
        fig.add_trace(
            go.Scatter(
                x=hist_df["rok"],
                y=hist_df["min_percentil"],
                mode="lines+markers",
                name="Historie PR min",
                line=dict(color="#1f77b4", width=3),
                marker=dict(size=8),
            )
        )

        # B) Predikovaný bod pro další rok
        pred_year = int(hist_df["rok"].max()) + 1
        fig.add_trace(
            go.Scatter(
                x=[int(hist_df["rok"].iloc[-1]), pred_year],
                y=[
                    hist_df["min_percentil"].iloc[-1],
                    school_row["pred_min_percentil"],
                ],
                mode="lines+markers",
                name=f"Predikce {pred_year}",
                line=dict(color="#ff7f0e", width=3, dash="dash"),
                marker=dict(size=10, symbol="star"),
            )
        )

        # C) Pásmo nejistoty
        fig.add_trace(
            go.Scatter(
                x=[pred_year, pred_year],
                y=[school_row["ci_lower"], school_row["ci_upper"]],
                mode="lines",
                name="Pásmo nejistoty (CI)",
                line=dict(color="rgba(255, 127, 14, 0.4)", width=10),
                hoverinfo="skip",
            )
        )

        # D) Vodorovná čára uchazeče
        user_color = (
            "green"
            if pr_info["effective_pr"] >= school_row["ci_upper"]
            else (
                "orange"
                if pr_info["effective_pr"] >= school_row["ci_lower"]
                else "red"
            )
        )
        fig.add_hline(
            y=pr_info["effective_pr"],
            line_dash="dot",
            line_color=user_color,
            annotation_text=f"Váš percentil ({pr_info['effective_pr']:.1f} %)",
            annotation_position="top left",
        )

        fig.update_layout(
            title=f"Vývoj požadovaného percentilu: {selected_school}",
            xaxis=dict(
                title="Ročník DiPSy",
                tickmode="linear",
                tick0=2024,
                dtick=1,
            ),
            yaxis=dict(title="Minimální percentil (PR min)", range=[0, 100]),
            hovermode="x unified",
            template="plotly_white",
            height=450,
        )

        st.plotly_chart(fig, width="stretch")

        with st.expander("💡 Jak číst tento graf?"):
            st.markdown("""
            - 🔵 **Modrá plná čára:** Skutečný historický minimální percentil přijatých v ročnících **2024, 2025 a 2026**.
            - 🟠 **Oranžová čárkovaná čára a hvězdička:** Odhadovaná hranice přijetí pro nadcházející ročník.
            - 🟧 **Oranžový svislý pruh:** **Pásmo nejistoty (Interval spolehlivosti)** reflektující volatilitu zájmu a kapacit.
            - 🟢/🔴 **Zelená/Červená tečkovaná čára:** Váš aktuálně vypočítaný efektivní percentil.
            """)

# ----- 4. Reverzní kalkulačka -----
if not df_schools.empty:
    st.markdown("---")
    st.subheader("4. 🎯 Reverzní kalkulačka: Kolik bodů potřebuji?")
    st.caption(
        "💡 Školy jsou v nabídce řazeny přednostně podle vaší preferované spádové oblasti (označené ⭐) "
        "a dále od nejnáročnějších oborů po méně náročné."
    )

    col_r1, col_r2 = st.columns(2)

    with col_r1:
        target_school_name = st.selectbox(
            "Vyberte cílovou školu a obor:",
            options=df_schools["skola_s_oborem"].unique(),
            key="rev_calc_school",
        )
        target_row = df_schools[
            df_schools["skola_s_oborem"] == target_school_name
        ].iloc[0]

        strategy = st.radio(
            "Požadovaná úroveň jistoty:",
            [
                "🟢 Sázka na jistotu (cca 95 % šance)",
                "🟡 Reálná šance (cca 50 % šance)",
            ],
            index=0,
        )
        safety_key = "Safe" if "jistotu" in strategy else "Realistic"

    with col_r2:
        mode = st.radio(
            "Styl přípravy:",
            [
                "Vyvážený (cílové body z obou předmětů)",
                "Zadám své silnější ČJL a dopočteme MAT",
            ],
        )

        custom_cjl: float | None = None
        if "silnější" in mode:
            custom_cjl = float(
                st.slider(
                    "Moje očekávané body z ČJL:",
                    0,
                    50,
                    40,
                    key="rev_calc_cjl",
                )
            )

    req_res = service.calculate_required_points_for_school(
        redizo=target_row["redizo"],
        kod_oboru=target_row["kod_oboru"],
        safety_level=safety_key,
        fixed_cjl_points=custom_cjl,
    )

    st.info(
        f"Pro přijetí na **{target_school_name}** ({strategy.split('(')[0].strip()}) "
        f"potřebujete dosáhnout celkového percentilu cca **{req_res['target_pr']:.1f} %**."
    )

    m1, m2, m3 = st.columns(3)
    m1.metric("Potřebné body ČJL", f"{req_res['req_cjl_points']} / 50 b.")
    m2.metric("Potřebné body MAT", f"{req_res['req_mat_points']} / 50 b.")
    m3.metric("Celkem bodů z JPZ", f"{req_res['total_points']} / 100 b.")

    with st.expander("💡 Jak funguje reverzní kalkulačka?"):
        st.markdown("""
        - **Vyvážený styl:** Předpokládá vyrovnaný výkon v obou předmětech (stejný percentil z ČJL i MAT).
        - **Kompenzační styl:** Zadáte vaše očekávané body z ČJL a kalkulačka dopočítá, kolik **nejméně** musíte získat z matematiky pro dosažení potřebného celkového percentilu.
        """)

# ----- 5. Plán B -----
st.markdown("---")
st.subheader("5. 💡 Plán B: Příbuzné obory s vysokou šancí na přijetí")

with st.expander("💡 Jak funguje a jak číst Plán B?"):
    st.markdown("""
    ### Co je to Plán B?
    Pokud má vámi vybraná škola nebo obor vysokou bodovou náročnost a vaší odhadovanou šancí je **🔴 Nízká (Riziková)**, systém automaticky prohledá databázi ve vašem kraji a najde **příbuzné obory podle Klasifikace kmenových oborů vzdělání (KKOV)**.

    **Příklady párování příbuzných oborů:**
    - 🖥️ **Informační technologie (18-20-M/01)** → *Technické lyceum*, *Elektrotechnika*, *Telekomunikace*.
    - 🏛️ **Gymnázium (79-41-K/41)** → *Kombinované lyceum*, *Ekonomické lyceum*, *Přírodovědné lyceum*.
    - ⚙️ **Strojírenství (23-41-M/01)** → *Elektrotechnika*, *Technické lyceum*.
    - 📈 **Obchodní akademie (63-41-M/02)** → *Ekonomické lyceum*.

    **Jak tyto karty číst:**
    - **📌 Náhrada za [Škola A]:** Riziková škola z vašeho výběru.
    - **Doporučená alternativa:** Název příbuzné školy a města ve vašem kraji s nižší bodovou náročností.
    - **Obor:** Přesný název příbuzného oboru.
    - **Důvod doporučení:** Vyčíslení procentních bodů, o kolik je tento obor méně náročný.
    - **Šance na přijetí:** Odhadovaná šance na přijetí pro tuto alternativu (🟢 Jistota nebo 🟡 Reálná).
    """)

if plan_b_items:
    st.caption(
        "💡 Plán B automaticky generuje příbuzné alternativy pro **všechny školy z vašeho přehledu (Sekce 1)**, "
        "u kterých máte na základě zadaných bodů **🔴 Nízkou (Rizikovou) šanci** na přijetí."
    )

    for item in plan_b_items:
        with st.expander(
            f"📌 Náhrada za {item['original_school']} ({item['original_obor']})"
        ):
            col_b1, col_b2 = st.columns([2, 1])
            with col_b1:
                st.markdown(
                    f"**Doporučená alternativa:** {item['alt_school']} "
                    f"({item['alt_mesto']})"
                )
                st.markdown(f"**Obor:** {item['alt_obor']}")
                st.caption(item["reason"])
            with col_b2:
                st.metric("Šance na přijetí", item["alt_chance"])
else:
    st.info(
        "💡 **Plán B:** Žádná z filtrovaných škol pro váš profil nevyžaduje aktivaci Plánu B "
        "(buď máte u vybraných oborů dostatečně vysokou šanci, nebo v databázi pro zadaná kritéria "
        "nejsou evidovány rizikové obory s příbuznými alternativami KKOV)."
    )
# ----- 6. Co kdyby… – porovnání scénářů -----
if not df_schools.empty:
    st.markdown("---")
    st.subheader("6. 🔄 Co kdyby… – Porovnání dvou scénářů")
    st.caption(
        "💡 Zadejte dva různé bodové výkony (např. slabší den vs. silnější den) "
        "a porovnejte, jak se změní vaše šance u jednotlivých škol."
    )

    with st.expander("💡 Jak funguje porovnání scénářů?"):
        st.markdown("""
        ### K čemu slouží porovnání scénářů?
        Tato sekce vám pomůže odpovědět na otázku: **„Co když se mi test povede lépe nebo hůře o pár bodů?"**

        **Jak s tím pracovat:**
        1. **Scénář A** (levý sloupec) – nastavte body pro *pesimistický* odhad (slabší den, těžší test).
        2. **Scénář B** (pravý sloupec) – nastavte body pro *optimistický* odhad (povedený den, jednodušší test).
        3. Ve srovnávací tabulce uvidíte u každé školy, jak se změní vaše šance.

        **Jak číst tabulku výsledků:**
        - **✅ Zlepšení** – Škola, u které se šance ve Scénáři B posune z rizikové/reálné na jistotu.
        - **⬇️ Zhoršení** – Škola, u které se šance ve Scénáři B posune z jistoty/reálné na rizikovou.
        - **Beze změny** – Šance zůstává stejná v obou scénářích.

        💡 *Díky tomuto porovnání zjistíte, na kterých školách záleží na každém bodu, a kde máte bezpečnou rezervu i při horším dni.*
        """)

    col_sc_a, col_sc_b = st.columns(2)

    with col_sc_a:
        st.markdown("##### Scénář A")
        sc_a_cjl = st.slider("ČJL (Scénář A)", 0, 50, max(0, cjl - 5), key="sc_a_cjl")
        sc_a_mat = st.slider("MAT (Scénář A)", 0, 50, max(0, mat - 5), key="sc_a_mat")

    with col_sc_b:
        st.markdown("##### Scénář B")
        sc_b_cjl = st.slider("ČJL (Scénář B)", 0, 50, min(50, cjl + 5), key="sc_b_cjl")
        sc_b_mat = st.slider("MAT (Scénář B)", 0, 50, min(50, mat + 5), key="sc_b_mat")

    eval_a = service.evaluate_schools_for_user(
        user_cjl=sc_a_cjl,
        user_mat=sc_a_mat,
        prospech_category=prospech,
        kraj_filter=kraj,
        kategorie_filter=kategorie,
        obor_filter=obor,
        mesta_filter=mesta if mesta else None,
    )
    eval_b = service.evaluate_schools_for_user(
        user_cjl=sc_b_cjl,
        user_mat=sc_b_mat,
        prospech_category=prospech,
        kraj_filter=kraj,
        kategorie_filter=kategorie,
        obor_filter=obor,
        mesta_filter=mesta if mesta else None,
    )

    df_a = eval_a["evaluated_schools"]
    df_b = eval_b["evaluated_schools"]
    pr_a = eval_a["pr_info"]
    pr_b = eval_b["pr_info"]

    # Metriky scénářů
    mc1, mc2 = st.columns(2)
    mc1.metric(
        f"Scénář A ({sc_a_cjl + sc_a_mat} b.)",
        f"{pr_a['effective_pr']:.1f} %",
        delta=f"{pr_a['effective_pr'] - pr_info['effective_pr']:+.1f} % vs. aktuální",
    )
    mc2.metric(
        f"Scénář B ({sc_b_cjl + sc_b_mat} b.)",
        f"{pr_b['effective_pr']:.1f} %",
        delta=f"{pr_b['effective_pr'] - pr_info['effective_pr']:+.1f} % vs. aktuální",
    )

    # Srovnávací tabulka
    if not df_a.empty and not df_b.empty:
        merge_cols = ["redizo", "kod_oboru", "nazev_skoly", "obor", "mesto"]
        df_cmp = df_a[merge_cols + ["chance_label"]].merge(
            df_b[merge_cols + ["chance_label"]],
            on=merge_cols,
            suffixes=(" (A)", " (B)"),
        )

        df_cmp["Změna"] = df_cmp.apply(
            lambda r: "✅ Zlepšení"
            if "Jistota" in str(r["chance_label (B)"]) and "Jistota" not in str(r["chance_label (A)"])
            else (
                "⬇️ Zhoršení"
                if "Riziková" in str(r["chance_label (B)"]) and "Riziková" not in str(r["chance_label (A)"])
                else "Beze změny"
            ),
            axis=1,
        )

        st.dataframe(
            df_cmp.rename(columns={
                "nazev_skoly": "Škola",
                "obor": "Obor",
                "mesto": "Město",
                "chance_label (A)": f"Šance A ({sc_a_cjl + sc_a_mat} b.)",
                "chance_label (B)": f"Šance B ({sc_b_cjl + sc_b_mat} b.)",
            })[
                [
                    "Škola", "Obor", "Město",
                    f"Šance A ({sc_a_cjl + sc_a_mat} b.)",
                    f"Šance B ({sc_b_cjl + sc_b_mat} b.)",
                    "Změna",
                ]
            ],
            hide_index=True,
            width="stretch",
        )

        n_improved = (df_cmp["Změna"] == "✅ Zlepšení").sum()
        n_worsened = (df_cmp["Změna"] == "⬇️ Zhoršení").sum()
        if n_improved > 0 or n_worsened > 0:
            st.caption(
                f"📊 Celkem: **{n_improved}** škol se zlepšením, "
                f"**{n_worsened}** se zhoršením šancí."
            )

# ----- 7. Backtest – „Přijali by mě loni?" -----
st.markdown("---")
st.subheader("7. ⏪ Backtest – Přijali by mě v minulých letech?")
st.caption(
    "💡 Porovnejte své aktuální body se skutečnými hranicemi přijetí z minulých ročníků. "
    "Žádná predikce – čistá historická fakta."
)

with st.expander("💡 Jak funguje Backtest?"):
    st.markdown("""
    ### Co je Backtest?
    Backtest bere vaše aktuální body z ČJL a MAT a porovná je se **skutečnými minimálními percentily**, které byly potřeba pro přijetí v daném ročníku.

    **Jak s tím pracovat:**
    1. Vyberte rok (2024, 2025 nebo 2026) v přepínači níže.
    2. V tabulce uvidíte u každé školy, zda byste s vašimi body byli **přijati** (🟢) nebo **nepřijati** (🔴).
    3. U nepřijatých škol se zobrazí, kolik procentních bodů vám chybělo.

    **K čemu je to dobré:**
    - Buduje důvěru v nástroj – vidíte konkrétní výsledek, ne odhad.
    - Ukazuje, jak moc se hranice rok od roku mění.
    - Pomáhá realisticky posoudit vaši úroveň: pokud byste ve 2 ze 3 let byli přijati, šance je solidní.
    """)

bt_years = service.get_available_backtest_years()
if bt_years:
    bt_year = st.radio(
        "Zvolte ročník pro backtest:",
        options=bt_years,
        horizontal=True,
        key="backtest_year",
    )

    df_bt = service.backtest_for_year(
        user_cjl=cjl,
        user_mat=mat,
        prospech_category=prospech,
        backtest_year=bt_year,
        kraj_filter=kraj,
        kategorie_filter=kategorie,
        obor_filter=obor,
        mesta_filter=mesta if mesta else None,
    )

    if not df_bt.empty:
        n_total = len(df_bt)
        n_prijat = df_bt["prijat"].sum()
        n_neprijat = n_total - n_prijat

        mc1, mc2, mc3 = st.columns(3)
        mc1.metric("Celkem škol", n_total)
        mc2.metric("🟢 Přijat/a", n_prijat)
        mc3.metric("🔴 Nepřijat/a", n_neprijat)

        st.dataframe(
            df_bt[["chance_label", "nazev_skoly", "obor", "mesto", "skutecny_pr_min", "user_pr", "pretlak"]].rename(
                columns={
                    "chance_label": f"Výsledek ({bt_year})",
                    "nazev_skoly": "Škola",
                    "obor": "Obor",
                    "mesto": "Město",
                    "skutecny_pr_min": "Skutečný PR min",
                    "user_pr": "Váš percentil",
                    "pretlak": "Přetlak",
                }
            ),
            hide_index=True,
            width="stretch",
        )

        pct_success = (n_prijat / n_total * 100) if n_total > 0 else 0
        st.caption(
            f"📊 S vašimi body byste v roce **{bt_year}** byli přijati na "
            f"**{n_prijat} z {n_total}** škol ({pct_success:.0f} % úspěšnost)."
        )
    else:
        st.info(f"Pro rok {bt_year} a zvolené filtry nejsou dostupná žádná data.")
else:
    st.info("V databázi nejsou dostupná historická data pro backtest.")


# ----- 8. Detailní karta školy -----
if not df_schools.empty:
    st.markdown("---")
    st.subheader("8. 🏫 Detailní karta školy")
    st.caption(
        "💡 Zobrazte si kompletní kartu vybrané střední školy – všechny vyučované obory, "
        "vývoj kapacit, počty přihlášek a historickou náročnost."
    )

    with st.expander("💡 Jak pracovat s kartou školy?"):
        st.markdown("""
        ### Co karta školy zobrazuje?
        Na rozdíl od hlavního přehledu, který zobrazuje konkrétní filtrované obory, karta školy nabízí **kompletní pohled na danou instituci**:

        **Co zde najdete:**
        1. **Všechny vyučované obory:** Zjistíte, zda škola nabízí i jiné příbuzné obory (např. vedle 4letého gymnázia i 8leté, nebo vedle IT oboru i Technické lyceum).
        2. **Vývoj kapacit:** Zda škola v čase navyšuje kapacity (což zvyšuje vaše šance).
        3. **Zájem uchazečů (Přetlak):** Kolik přihlášek na 1. místě připadá na 1 přijatého žáka.
        4. **Historické hranice přijetí:** Vývoj minimálního potřebného percentilu v ročnících 2024, 2025 a 2026.
        """)

    # Unikátní školy z filtrů
    unique_schools = (
        df_schools[["redizo", "nazev_skoly", "mesto"]]
        .drop_duplicates(subset=["redizo"])
        .sort_values("nazev_skoly")
    )

    school_options = {
        f"{row['nazev_skoly']} ({row['mesto']})": row["redizo"]
        for _, row in unique_schools.iterrows()
    }

    selected_sch_label = st.selectbox(
        "Vyberte školu pro zobrazení detailní karty:",
        options=list(school_options.keys()),
        key="detail_school_select",
    )

    if selected_sch_label:
        selected_redizo = school_options[selected_sch_label]
        sch_detail = service.get_full_school_info(selected_redizo)

        if sch_detail and "info" in sch_detail:
            info = sch_detail["info"]
            hist_df = sch_detail["history"]

            st.markdown(f"#### 🏫 {info['nazev_skoly']}")
            st.caption(f"📍 **Město:** {info['mesto']} | 🗺️ **Kraj:** {info['kraj']} | 🆔 **REDIZO:** {info['redizo']}")

            if not hist_df.empty:
                # Metriky školy
                latest_year = hist_df["rok"].max()
                latest_data = hist_df[hist_df["rok"] == latest_year]
                total_cap = latest_data["kapacita"].sum()
                total_apps = latest_data["prihlasky_p1"].sum()
                num_obory = latest_data["kod_oboru"].nunique()

                c_d1, c_d2, c_d3 = st.columns(3)
                c_d1.metric("Počet vyučovaných oborů", num_obory)
                c_d2.metric(f"Celková kapacita ({latest_year})", f"{total_cap} žáků")
                c_d3.metric(f"Přihlášky 1. priority ({latest_year})", f"{total_apps} uchazečů")

                # Tabulka oborů a historie
                st.markdown("##### 📋 Přehled oborů a historických výsledků")
                st.dataframe(
                    hist_df.rename(
                        columns={
                            "nazev_oboru": "Obor",
                            "kod_oboru": "Kód oboru",
                            "kategorie_oboru": "Kategorie",
                            "rok": "Rok",
                            "kapacita": "Kapacita",
                            "prihlasky_p1": "Přihlášky (1. p.)",
                            "index_pretlaku": "Přetlak",
                            "min_percentil": "Min percentil",
                        }
                    )[
                        [
                            "Obor",
                            "Kategorie",
                            "Rok",
                            "Kapacita",
                            "Přihlášky (1. p.)",
                            "Přetlak",
                            "Min percentil",
                        ]
                    ],
                    hide_index=True,
                    width="stretch",
                )

                # Plotly graf vývoje oborů na škole
                fig_sch = go.Figure()
                for obor_name, obor_group in hist_df.groupby("nazev_oboru"):
                    fig_sch.add_trace(
                        go.Scatter(
                            x=obor_group["rok"],
                            y=obor_group["min_percentil"],
                            mode="lines+markers",
                            name=obor_name,
                            marker=dict(size=8),
                        )
                    )
                fig_sch.update_layout(
                    title=f"Vývoj minimálního percentilu podle oborů ({info['nazev_skoly']})",
                    xaxis_title="Rok",
                    yaxis_title="Minimální percentil (PR min)",
                    yaxis=dict(range=[0, 100]),
                    template="plotly_white",
                    height=380,
                )
                st.plotly_chart(fig_sch, width="stretch")

# ----- Footer -----
st.markdown("---")
st.caption(
    "📊 Data: Oficiální Cermat data za roky 2024–2026 (data.cermat.cz) | "
    "⚠️ Predikce slouží pouze jako orientační odhad | "
    "🔧 Cermat Asistent v0.1.0"
)

