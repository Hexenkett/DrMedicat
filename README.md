<p align="center">
  <img src="farmabot_farmiau.png" alt="Dr MediCat" width="180"/>
</p>

<h1 align="center">Dr MediCat — Pharmacotherapeutic Follow-up Chatbot</h1>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.11-blue?logo=python" />
  <img src="https://img.shields.io/badge/discord.py-2.x-5865F2?logo=discord" />
  <img src="https://img.shields.io/badge/OpenAI-GPT--4o%20mini-412991?logo=openai" />
  <img src="https://img.shields.io/badge/SQLite-local-003B57?logo=sqlite" />
  <img src="https://img.shields.io/badge/Deployed%20on-Railway-0B0D0E?logo=railway" />
</p>

<p align="center">
  A Discord-based virtual assistant that helps patients track medication adherence, monitor adverse drug reactions, and automatically generates monthly pharmacotherapeutic reports using AI.
</p>

---

## What is Dr MediCat?

Dr MediCat is a chatbot built for Discord that acts as a pocket pharmacist. Developed as a Bachelor's Thesis project at the **Universitat de Barcelona (Grau de Farmàcia)**, it addresses a real clinical problem: according to the WHO, **50% of patients with chronic conditions do not follow their treatment correctly**.

Current tools remind patients — but don't track, don't monitor, and don't report. Dr MediCat does all three.

---

## Features

### 💊 Medication Adherence Tracking
- Patients log doses via interactive Discord buttons — no typing required
- Two complementary metrics calculated automatically:
  - **Strict MPR (±30 min)** — for narrow therapeutic window drugs where timing is critical
  - **Global adherence (±2h)** — reflects realistic daily compliance
- Detects temporal forgetting patterns (which time slots are most problematic)

### ⚠️ Adverse Drug Reaction (ADR) Monitoring
- Weekly automated surveys based on official drug technical sheets from **CIMA/AEMPS** (Spain's drug regulatory database)
- Patients select symptoms via buttons — no free text needed
- Data structured to feed into pharmacovigilance systems (**FEDRA / EudraVigilance**)

### 📊 AI-Generated Pharmacotherapeutic Reports
- Monthly reports drafted by **GPT-4o mini**
- **Key design decision:** ADR data is pulled directly from the database, bypassing the LLM entirely — no hallucinations in safety-critical information
- Reports include: adherence summary, forgetting patterns, ADR flags, and clinical recommendations

---

## Tech Stack

| Layer | Technology |
|---|---|
| Interface | discord.py, Discord API |
| Adherence logic | Python (adherencia.py) |
| ADR monitoring | Python (rams.py) |
| AI reports | OpenAI GPT-4o mini |
| Database | SQLite (5 tables) |
| Hosting | Railway |
| Secrets | python-dotenv |

---

## Project Structure

```
Pharmabot/
├── dr_baki.py        # Main bot — Discord interface layer
├── adherencia.py     # Adherence logic — dose tracking & metrics
├── rams.py           # ADR monitoring — weekly surveys
├── pharmabot.db      # SQLite database (5 tables)
├── requirements.txt  # Dependencies
└── .gitignore
```

---

## Setup

```bash
# 1. Clone the repo
git clone https://github.com/Hexenkett/Pharmabot.git
cd Pharmabot

# 2. Install dependencies
pip install -r requirements.txt

# 3. Create your .env file
cp .env.example .env
# Fill in your Discord token and OpenAI API key

# 4. Run the bot
python dr_baki.py
```

### Required `.env` variables
```
DISCORD_TOKEN=your_discord_bot_token
OPENAI_API_KEY=your_openai_api_key
```

---

## Academic Context

This project was developed as a **Bachelor's Thesis (TFG)** for the *Grau de Farmàcia* at the **Universitat de Barcelona**, within the field of **Clinical Pharmacy**.

- **Hypothesis:** Technical feasibility of building an integrated prototype combining adherence tracking, ADR monitoring, and AI-generated reports in a messaging platform
- **Scope:** Technical validation — not clinical efficacy (real-world validation is the proposed next step)
- **Regulatory framework:** Designed with EU AI Act and GDPR considerations in mind

---

## ⚠️ Disclaimer

This is an **academic prototype**. It has not been validated with real patients and is not intended for clinical use. All data used during development was simulated.

---

## Author

**Pedro Ignacio Mallada Martinez**
Grau de Farmàcia — Universitat de Barcelona

[![LinkedIn](https://img.shields.io/badge/LinkedIn-Connect-0A66C2?logo=linkedin)](https://www.linkedin.com/in/pedro-mallada-959581333/)
