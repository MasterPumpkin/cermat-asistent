# 🎓 Cermat Asistent

> **Odhad šancí na přijetí a doporučení strategie přihlášek na střední školy na základě oficiálních dat Cermat (DiPSy éra 2024–2026).**

[![Python Version](https://img.shields.io/badge/python-3.13-blue.svg)](https://www.python.org/)
[![Package Manager](https://img.shields.io/badge/uv-fast-purple.svg)](https://github.com/astral-sh/uv)
[![Framework](https://img.shields.io/badge/Streamlit-1.42+-red.svg)](https://streamlit.io/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Tests](https://img.shields.io/badge/tests-43%20passed-brightgreen.svg)](tests/)

---

## 🌟 O projektu

**Cermat Asistent** je webová aplikace v Pythonu navržená pro rodiče a uchazeče o střední školy v ČR. Pomáhá objektivně zhodnotit šance na přijetí na základě **kompletních výsledků Jednotné přijímací zkoušky (JPZ) Cermat za ročníky 2024, 2025 a 2026**.

Aplikace pracuje s efektivními percentily, koriguje meziroční změny obtížnosti testů z ČJL a MAT, zohledňuje školní prospěch i spádové oblasti a navrhuje optimální poskládání škol pro elektronický systém **DiPSy**.

---

## 🚀 Hlavní funkcionality

### 1. 📊 Přehled vyhodnocených škol
- Přepočet cvičných bodů z ČJL a MAT na **aktuální percentil**.
- Zohlednění školního prospěchu z 8. a 9. třídy ZŠ.
- Přehledná tabulka s barevným vyhodnocením šancí:
  - 🟢 **Vysoká (Jistota)** – Váš percentil je nad horní hranicí odhadovaného pásma.
  - 🟡 **Střední (Reálná)** – Váš percentil leží v pásmu nejistoty (rozhodne den zkoušky).
  - 🔴 **Nízká (Riziková)** – Váš percentil je pod odhadovanou hranicí přijetí.

### 2. 🎯 DiPSy strategie (1.–3. priorita)
- Automatické sestavení optimální trojice přihlášek s respektováním algoritmu elektronického rozřazování v DiPSy:
  - **1. místo:** Vysněná / náročnější škola bez rizika penalizace.
  - **2. místo:** Reálná škola odpovídající vašemu výkonu.
  - **3. místo:** Bezpečná záchranná škola (Jistota).

### 3. 📈 Interaktivní Plotly graf
- Zobrazení historického vývoje minimálních percentilů pro vybraný obor (2024, 2025, 2026).
- **Predikce pro nadcházející ročník** s vyznačeným svislým **pásmem nejistoty (Interval spolehlivosti)**.
- Srovnávací čára aktuálního výkonu uchazeče.

### 4. 🎯 Reverzní kalkulačka bodů
- Výpočet, kolik bodů z ČJL a MAT musíte získat pro přijetí na vybranou školu.
- Dva režimy přípravy:
  - **Vyvážený:** Stejný cílový percentil v obou předmětech.
  - **Kompenzační:** Zadáte vaši silnější ČJL a kalkulačka dopočítá minimální nutné body z matematiky.

### 5. 💡 Plán B (Spádové alternativy)
- Při rizikové šanci na vysněné škole systém automaticky vyhledá příbuzné obory podle **KKOV** *(např. IT → Technická lycea, Elektrotechnika; Gymnázium → Obchodní/Přírodovědná lycea)*.
- **Prioritizace spádové oblasti:** Přednostně nabízí obory ve vašich zvolených preferovaných městech *(např. Kutná Hora, Kolín, Čáslav)*.

### 6. ℹ️ Metodický průvodce & Nápovědy
- Vysvětlení pravidla min. 60 % JPZ testy / max. 40 % školní část (jazykové certifikáty Cambridge FCE/PET, olympiády, soutěže a prospěch).

---

## ☁️ Nasazení na Streamlit Community Cloud (Deployment Guide)

Aplikace je plně uzpůsobena pro nasazení zdarma na **Streamlit Community Cloud** (zahrnuje pre-built SQLite databázi `cermat.db` o velikosti pouze 2.2 MB a soubor `requirements.txt`).

### Postup nasazení:
1. Nahrajte repozitář na **GitHub**.
2. Přihlaste se na [share.streamlit.io](https://share.streamlit.io).
3. Klikněte na **"New app"**.
4. Vyberte váš GitHub repozitář, větev `main` a nastavte:
   - **Main file path:** `src/cermat_asistent/app.py`
5. Klikněte na **"Deploy!"** a vaše aplikace bude za pár sekund veřejně dostupná online.

---

## 💻 Rychlý start (Local Setup)

### Požadavky
- Python `>= 3.11` (doporučeno Python `3.13`)
- Správce balíčků [`uv`](https://github.com/astral-sh/uv)

### 1. Klonování repozitáře
```bash
git clone https://github.com/USER/cermat-asistent.git
cd cermat-asistent
```

### 2. Instalace závislostí
```bash
uv sync
```

### 3. Načtení databáze z oficiálních Cermat souborů
```bash
uv run python -m cermat_asistent.db
```

### 4. Spuštění webové aplikace
```bash
uv run streamlit run src/cermat_asistent/app.py
```
Aplikace se automaticky otevře v prohlížeči na adrese `http://localhost:8501`.

---

## 🧪 Spuštění testů

Projekt obsahuje komplexní testovací sadu (43 testů) pokrývající matematický engine, backendové služby, spádové lokace i bezpečnost (SQL Injection & Edge Cases):

```bash
uv run pytest tests/ -v
```

---

## 📂 Struktura projektu

```text
cermat-asistent/
├── data/                       # Zdrojová Cermat data za roky 2024, 2025 a 2026
│   ├── 2024/
│   ├── 2025/
│   └── 2026/
├── src/
│   └── cermat_asistent/
│       ├── __init__.py
│       ├── app.py              # Streamlit dashboard
│       ├── config.py           # Konfigurace a parametry predikce
│       ├── db.py               # SQLite schéma a ETL importy
│       ├── predictor.py        # Statistický predikční engine
│       └── service.py          # Backendové služby a logika
├── tests/                      # Pytest testovací sada (43 testů)
│   ├── test_predictor.py
│   ├── test_service.py
│   └── test_security_edge_cases.py
├── .github/
│   └── workflows/
│       └── ci.yml              # GitHub Actions CI pipeline
├── .gitignore
├── cermat.db                   # Pre-built SQLite databáze (2.2 MB)
├── LICENSE
├── pyproject.toml              # UV / Pip konfigurace
├── requirements.txt            # Streamlit Cloud závislosti
└── README.md
```

---

## 📊 Datový zdroj

- **Oficiální data:** Cermat – výsledky 1. kola Jednotné přijímací zkoušky 2024, 2025 a 2026 ([data.cermat.cz](https://data.cermat.cz)).

---

## 📜 Licence

Tento projekt je licencován pod [MIT Licencí](LICENSE).
