"""
Sistema de Registro de Reacciones Adversas a Medicamentos (RAMs)
=================================================================
Funcionalidades:
  - Diccionario de RAMs por grupo terapéutico (sustituible por RAG)
  - Pregunta activa al paciente cada 7 días por DM
  - Registro en base de datos SQLite
  - Generación de sección de RAMs para informe farmacéutico

Arquitectura preparada para RAG:
  obtener_rams_medicamento() es la función puente.
  Cuando implementes RAG, solo cambias esta función.
  El resto del sistema no se toca.
"""

from datetime import datetime, timedelta


# ══════════════════════════════════════════════════════
#  DICCIONARIO DE RAMs POR MEDICAMENTO
#  Fuente: fichas técnicas CIMA (AEMPS)
#  Futuro RAG
# ══════════════════════════════════════════════════════

# RAMs genéricas — se usan si el medicamento no está en el diccionario
RAMS_GENERICAS = [
    "Náuseas o vómitos",
    "Dolor de cabeza",
    "Mareos",
    "Fatiga o cansancio inusual",
    "Problemas digestivos (diarrea, estreñimiento)",
    "Reacciones en la piel (sarpullido, picor)",
]

# Diccionario principal — clave: nombre en minúsculas (o parte del nombre)
# Valor: lista de RAMs frecuentes según ficha técnica
DICCIONARIO_RAMS = {

    # ── ESTATINAS (hipolipemiantes) ──
    "atorvastatina": [
        "Dolor o debilidad muscular (mialgia)",
        "Elevación de enzimas hepáticas (cansancio, ictericia)",
        "Dolor de cabeza",
        "Náuseas o molestias digestivas",
        "Dolor articular",
    ],
    "simvastatina": [
        "Dolor o debilidad muscular (mialgia)",
        "Elevación de enzimas hepáticas",
        "Náuseas o molestias digestivas",
        "Dolor de cabeza",
        "Insomnio",
    ],
    "rosuvastatina": [
        "Dolor o debilidad muscular (mialgia)",
        "Dolor de cabeza",
        "Náuseas",
        "Dolor abdominal",
        "Estreñimiento",
    ],

    # ── IBPs (inhibidores de la bomba de protones) ──
    "omeprazol": [
        "Dolor de cabeza",
        "Náuseas o vómitos",
        "Diarrea o estreñimiento",
        "Dolor abdominal",
        "Flatulencia",
        "Hipomagnesemia (calambres, fatiga) en uso prolongado",
    ],
    "pantoprazol": [
        "Dolor de cabeza",
        "Diarrea",
        "Náuseas",
        "Dolor abdominal",
        "Flatulencia",
    ],
    "esomeprazol": [
        "Dolor de cabeza",
        "Náuseas",
        "Diarrea o estreñimiento",
        "Dolor abdominal",
        "Flatulencia",
    ],

    # ── ANTIHIPERTENSIVOS ──
    "enalapril": [
        "Tos seca persistente",
        "Mareos o hipotensión (bajada de tensión)",
        "Dolor de cabeza",
        "Fatiga",
        "Hiperpotasemia (calambres musculares)",
        "Angioedema (hinchazón cara/labios — consultar urgencias)",
    ],
    "amlodipino": [
        "Edema en tobillos o pies",
        "Sofocos o sensación de calor",
        "Dolor de cabeza",
        "Mareos",
        "Palpitaciones",
        "Fatiga",
    ],
    "losartan": [
        "Mareos o hipotensión",
        "Hiperpotasemia (calambres musculares)",
        "Dolor de cabeza",
        "Fatiga",
        "Angioedema (hinchazón cara/labios — consultar urgencias)",
    ],
    "ramipril": [
        "Tos seca persistente",
        "Mareos o hipotensión",
        "Dolor de cabeza",
        "Fatiga",
        "Hiperpotasemia",
        "Angioedema (hinchazón cara/labios — consultar urgencias)",
    ],

    # ── ANTIDIABÉTICOS ──
    "metformina": [
        "Náuseas o vómitos (especialmente al inicio)",
        "Diarrea o molestias digestivas",
        "Pérdida de apetito",
        "Sabor metálico en la boca",
        "Déficit de vitamina B12 en uso prolongado (hormigueos)",
    ],
    "sitagliptina": [
        "Infecciones respiratorias (resfriados frecuentes)",
        "Dolor de cabeza",
        "Náuseas",
        "Dolor articular",
        "Pancreatitis (dolor abdominal intenso — consultar médico)",
    ],
    "empagliflozina": [
        "Infecciones urinarias (escozor al orinar)",
        "Infecciones genitales por hongos",
        "Aumento de la micción",
        "Mareos o hipotensión",
        "Cetoacidosis diabética (náuseas, vómitos, dolor abdominal — urgencias)",
    ],

    # ── ANTICOAGULANTES ──
    "acenocumarol": [
        "Sangrado inusual (encías, nariz, heridas que no cierran)",
        "Hematomas frecuentes",
        "Sangre en orina (orina rosada o roja)",
        "Sangre en heces (heces negras)",
        "Dolor de cabeza intenso súbito",
    ],
    "apixaban": [
        "Sangrado inusual (encías, nariz, heridas que no cierran)",
        "Hematomas frecuentes",
        "Náuseas",
        "Anemia (fatiga, palidez)",
        "Sangre en orina o heces",
    ],
    "rivaroxaban": [
        "Sangrado inusual",
        "Hematomas frecuentes",
        "Náuseas o molestias digestivas",
        "Sangre en orina o heces",
        "Mareos",
    ],

        # ── ANTIDEPRESIVOS ──
    "sertralina": [
        "Náuseas o vómitos (especialmente al inicio)",
        "Diarrea o molestias digestivas",
        "Insomnio o somnolencia",
        "Dolor de cabeza",
        "Sudoración excesiva",
        "Disfunción sexual (disminución libido, anorgasmia)",
        "Ansiedad o inquietud al inicio del tratamiento",
    ],
    "fluoxetina": [
        "Náuseas o molestias digestivas",
        "Insomnio",
        "Dolor de cabeza",
        "Nerviosismo o ansiedad",
        "Pérdida de apetito",
        "Disfunción sexual",
        "Sudoración excesiva",
    ],
    "escitalopram": [
        "Náuseas",
        "Insomnio o somnolencia",
        "Dolor de cabeza",
        "Sudoración",
        "Boca seca",
        "Disfunción sexual",
        "Fatiga",
    ],

    "citalopram": [
        "Náuseas",
        "Boca seca",
        "Sudoración",
        "Somnolencia",
        "Disfunción sexual",
        "Palpitaciones (consultar si son frecuentes)",
    ],

    "venlafaxina": [
        "Náuseas o vómitos",
        "Dolor de cabeza",
        "Insomnio",
        "Sudoración excesiva",
        "Boca seca",
        "Aumento de la tensión arterial",
        "Disfunción sexual",
        "Síndrome de retirada si se suspende bruscamente",
    ],

    "duloxetina": [
        "Náuseas",
        "Boca seca",
        "Estreñimiento",
        "Somnolencia o insomnio",
        "Sudoración",
        "Mareos",
        "Disfunción sexual",
    ],

    "amitriptilina": [
        "Somnolencia o sedación marcada",
        "Boca seca intensa",
        "Estreñimiento",
        "Retención urinaria",
        "Visión borrosa",
        "Aumento de peso",
        "Hipotensión ortostática (mareo al levantarse)",
        "Palpitaciones",
    ],

    "mirtazapina": [
        "Somnolencia marcada",
        "Aumento del apetito y de peso",
        "Boca seca",
        "Estreñimiento",
        "Mareos",
        "Sueños vívidos",
    ],

    "trazodona": [
        "Somnolencia marcada",
        "Mareos o hipotensión",
        "Boca seca",
        "Dolor de cabeza",
        "Visión borrosa",
        "Priapismo (erección prolongada — consultar urgencias)",
    ],
}


# ══════════════════════════════════════════════════════
#  FUNCIÓN PUENTE — RAG EN EL FUTURO
# ══════════════════════════════════════════════════════

def obtener_rams_medicamento(nombre_medicamento: str) -> list[str]:

    nombre = nombre_medicamento.lower().strip()

    # Búsqueda exacta primero
    if nombre in DICCIONARIO_RAMS:
        rams = DICCIONARIO_RAMS[nombre]
    else:
        rams = None
        for clave, lista in DICCIONARIO_RAMS.items():
            if clave in nombre or nombre in clave:
                rams = lista
                break
        if rams is None:
            rams = RAMS_GENERICAS

    return rams + [
        "Reacciones alergicas (picor, urticaria, cara o garganta hinchada, difícil respirar)",
        "Ninguno de los anteriores"
    ]


# ══════════════════════════════════════════════════════
#  BASE DE DATOS — TABLA RAMs
# ══════════════════════════════════════════════════════

def inicializar_tabla_rams(conn):
    """
    Crea la tabla de RAMs si no existe.
    Llamar desde inicializar_db() en dr_baki.py.

    Añade esto en inicializar_db():
        from rams import inicializar_tabla_rams
        inicializar_tabla_rams(conn)
    """
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS rams (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            usuario_id      TEXT NOT NULL,
            med_id          INTEGER NOT NULL,
            fecha_registro  TEXT NOT NULL,
            tiene_ram       INTEGER NOT NULL,
            descripcion     TEXT,
            intensidad      INTEGER,
            rams_marcadas   TEXT,
            FOREIGN KEY (usuario_id) REFERENCES usuarios(discord_id),
            FOREIGN KEY (med_id) REFERENCES medicamentos(id)
        );

        CREATE TABLE IF NOT EXISTS ultima_encuesta_ram (
            usuario_id  TEXT NOT NULL,
            med_id      INTEGER NOT NULL,
            fecha       TEXT NOT NULL,
            PRIMARY KEY (usuario_id, med_id)
        );
    """)


def registrar_ram(conn, usuario_id: str, med_id: int, tiene_ram: bool,
                  descripcion: str = None, intensidad: int = None,
                  rams_marcadas: list = None):
    """
    Guarda una respuesta de encuesta RAM en la base de datos.

    Parámetros:
        tiene_ram     → True si reportó alguna RAM
        descripcion   → texto libre del paciente (opcional)
        intensidad    → 1-5 (opcional, para uso futuro)
        rams_marcadas → lista de RAMs que marcó el paciente
    """
    conn.execute(
        """INSERT INTO rams
           (usuario_id, med_id, fecha_registro, tiene_ram, descripcion, intensidad, rams_marcadas)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (
            usuario_id,
            med_id,
            datetime.now().isoformat(),
            1 if tiene_ram else 0,
            descripcion,
            intensidad,
            ",".join(rams_marcadas) if rams_marcadas else None
        )
    )


def actualizar_ultima_encuesta(conn, usuario_id: str, med_id: int):
    """Registra cuándo se hizo la última encuesta RAM para evitar repeticiones."""
    conn.execute(
        """INSERT OR REPLACE INTO ultima_encuesta_ram (usuario_id, med_id, fecha)
           VALUES (?, ?, ?)""",
        (usuario_id, med_id, datetime.now().isoformat())
    )


def debe_preguntar_rams(conn, usuario_id: str, med_id: int,
                         dias_intervalo: int = 7) -> bool:
    """
    Devuelve True si han pasado más de N días desde la última encuesta.
    """
    row = conn.execute(
        "SELECT fecha FROM ultima_encuesta_ram WHERE usuario_id = ? AND med_id = ?",
        (usuario_id, med_id)
    ).fetchone()

    if not row:
        return True  # Nunca se ha preguntado

    ultima = datetime.fromisoformat(row["fecha"])
    return (datetime.now() - ultima).days >= dias_intervalo


def obtener_rams_usuario(conn, usuario_id: str, dias: int = 30) -> list:
    """
    Devuelve todas las RAMs registradas de un usuario en los últimos N días.
    Usado para generar la sección de RAMs en el informe farmacéutico.
    """
    desde = (datetime.now() - timedelta(days=dias)).isoformat()
    rows = conn.execute(
        """SELECT r.*, m.nombre as med_nombre
           FROM rams r
           JOIN medicamentos m ON r.med_id = m.id
           WHERE r.usuario_id = ? AND r.fecha_registro >= ?
           ORDER BY r.fecha_registro DESC""",
        (usuario_id, desde)
    ).fetchall()
    return [dict(row) for row in rows]


# ══════════════════════════════════════════════════════
#  GENERADOR DE SECCIÓN RAMs PARA INFORME FARMACÉUTICO
# ══════════════════════════════════════════════════════

def generar_seccion_rams_informe(rams: list[dict]) -> str:
    """
    Genera la sección de RAMs para añadir al informe farmacéutico.
    Se llama desde generar_informe_farmaceutico() en adherencia.py.

    Parámetros:
        rams → lista devuelta por obtener_rams_usuario()
    """
    lineas = [
        "",
        "6. REACCIONES ADVERSAS REPORTADAS (RAMs)",
        "-" * 40,
    ]

    if not rams:
        lineas.append("  Sin encuestas de RAMs registradas en el periodo.")
        return "\n".join(lineas)

    total_encuestas  = len(rams)
    con_ram          = sum(1 for r in rams if r["tiene_ram"])
    sin_ram          = total_encuestas - con_ram

    lineas += [
        f"  Total encuestas realizadas : {total_encuestas}",
        f"  Con RAMs reportadas        : {con_ram}",
        f"  Sin RAMs                   : {sin_ram}",
    ]

    if con_ram > 0:
        lineas.append("\n  Detalle de RAMs reportadas:")
        for ram in rams:
            if not ram["tiene_ram"]:
                continue
            fecha = datetime.fromisoformat(ram["fecha_registro"]).strftime("%d/%m/%Y")
            lineas.append(f"\n    Fecha      : {fecha}")
            lineas.append(f"    Medicamento: {ram['med_nombre']}")

            if ram["rams_marcadas"]:
                sintomas = ram["rams_marcadas"].split(",")
                lineas.append(f"    Sintomas   :")
                for s in sintomas:
                    lineas.append(f"      - {s.strip()}")

            if ram["descripcion"]:
                lineas.append(f"    Descripcion: {ram['descripcion']}")

        # Alerta si hay RAMs graves mencionadas
        palabras_alerta = ["angioedema", "urgencias", "médico", "cetoacidosis",
                           "pancreatitis", "sangre", "intenso"]
        descripciones = " ".join([
            (r.get("descripcion") or "") + (r.get("rams_marcadas") or "")
            for r in rams if r["tiene_ram"]
        ]).lower()

        if any(p in descripciones for p in palabras_alerta):
            lineas += [
                "",
                "  [ALERTA] Se han reportado sintomas que requieren evaluacion clinica urgente.",
                "           Contactar con el paciente prioritariamente.",
            ]

    return "\n".join(lineas)
