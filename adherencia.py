"""
Motor de cálculo de adherencia clínica
=======================================
Métricas implementadas:
  - % adherencia con ventana de tolerancia configurable
  - Clasificación de tomas: tomada / tomada_con_retraso / olvido / no_tomada
  - Racha máxima y actual de olvidos
  - Patrón horario y por día de la semana
 
Informes:
  - generar_informe_paciente()      → Discord, emojis, lenguaje simple
  - generar_informe_farmaceutico()  → clínico completo, sin emojis, terminología técnica
  - generar_informes_semanales()    → genera ambos listos para enviar por DM
 
Compatible con SQLite (dr_baki.py).
"""
 
from datetime import datetime, timedelta
from collections import Counter
from typing import Optional
from openai import OpenAI 

# ------------------   CONFIGURACIÓN CLÍNICA ------------------ 

 
VENTANA_TOLERANCIA_HORAS = 2
UMBRAL_OPTIMA            = 0.95
UMBRAL_ACEPTABLE         = 0.80
UMBRAL_CRITICA           = 0.50
 
 

# ------------------   1. CLASIFICACIÓN DE UNA TOMA INDIVIDUAL ------------------ 

 
def clasificar_toma(
    hora_programada: datetime,
    hora_real: Optional[datetime],
    estado_boton: str,
    ventana_horas: float = VENTANA_TOLERANCIA_HORAS
) -> str:
    """
    Devuelve el estado clínico final de una toma.
 
    Estados:
        "tomada"             → tomó dentro de la ventana de tolerancia
        "tomada_con_retraso" → tomó fuera de la ventana
        "no_tomada"          → pulsó ❌ explícitamente
        "olvido"             → no respondió y venció la ventana
        "pendiente"          → aún dentro de ventana, sin respuesta
    """
    if estado_boton == "no_tomado":
        return "no_tomada"
 
    if hora_real is None:
        ahora = datetime.now()
        if (ahora - hora_programada).total_seconds() > ventana_horas * 3600:
            return "olvido"
        return "pendiente"
 
    retraso_horas = (hora_real - hora_programada).total_seconds() / 3600
 
    if retraso_horas < 0:
        return "tomada"
    elif retraso_horas <= ventana_horas:
        return "tomada"
    else:
        return "tomada_con_retraso"
 
 

# ------------------   2. CÁLCULO DEL % DE ADHERENCIA ------------------ 

 
def calcular_adherencia(
    historial: list[dict],
    dias: int = 30,
    incluir_retraso: bool = True
) -> dict:
    """
    Calcula el % de adherencia sobre un período.
 
    El historial viene de obtener_historial() en dr_baki.py.
    Cada entrada tiene al menos: timestamp (ISO), estado.
 
    Devuelve:
        porcentaje       → 0.0 a 100.0
        nivel            → "optima" | "aceptable" | "baja" | "critica" | "sin_datos"
        conteos          → desglose por estado
        tomas_analizadas → total de tomas en el período
        adherentes       → tomas que cuentan como adherentes
    """
    desde = datetime.now() - timedelta(days=dias)
 
    tomas = [
        t for t in historial
        if datetime.fromisoformat(t["timestamp"]) >= desde
        and t["estado"] not in ("pendiente", "pospuesta")
    ]
 
    if not tomas:
        return {
            "porcentaje": None,
            "nivel": "sin_datos",
            "conteos": {},
            "tomas_analizadas": 0,
            "adherentes": 0
        }
 
    conteos = Counter(t["estado"] for t in tomas)
    total   = len(tomas)
 
    estados_adherentes = {"tomada"}
    if incluir_retraso:
        estados_adherentes.add("tomada_con_retraso")
 
    adherentes = sum(conteos.get(e, 0) for e in estados_adherentes)
    porcentaje = round((adherentes / total) * 100, 1)
    ratio      = adherentes / total
 
    if ratio >= UMBRAL_OPTIMA:
        nivel = "optima"
    elif ratio >= UMBRAL_ACEPTABLE:
        nivel = "aceptable"
    elif ratio >= UMBRAL_CRITICA:
        nivel = "baja"
    else:
        nivel = "critica"
 
    return {
        "porcentaje": porcentaje,
        "nivel": nivel,
        "conteos": dict(conteos),
        "tomas_analizadas": total,
        "adherentes": adherentes
    }
 
 

# ------------------   3. RACHA DE OLVIDOS ------------------ 

 
def calcular_rachas_olvido(historial: list[dict]) -> dict:
    """
    Detecta rachas de olvidos consecutivos.
 
    Devuelve:
        racha_actual  → tomas consecutivas de olvido hasta la más reciente
        racha_maxima  → mayor racha registrada en todo el historial
        inicio_racha  → timestamp de inicio de la racha actual (si existe)
    """
    tomas_ordenadas = sorted(
        [t for t in historial if t["estado"] not in ("pendiente", "pospuesta")],
        key=lambda t: t["timestamp"]
    )
 
    if not tomas_ordenadas:
        return {"racha_actual": 0, "racha_maxima": 0, "inicio_racha": None}
 
    estados_olvido = {"olvido", "no_tomada"}
    racha_maxima = 0
    racha_tmp    = 0
    inicio_tmp   = None
 
    for toma in tomas_ordenadas:
        if toma["estado"] in estados_olvido:
            racha_tmp += 1
            if inicio_tmp is None:
                inicio_tmp = toma["timestamp"]
            if racha_tmp > racha_maxima:
                racha_maxima = racha_tmp
        else:
            racha_tmp  = 0
            inicio_tmp = None
 
    return {
        "racha_actual": racha_tmp,
        "racha_maxima": racha_maxima,
        "inicio_racha": inicio_tmp
    }
 
 

# ------------------   4. PATRONES DE OLVIDO ------------------ 

 
DIAS_ES = {
    "Monday": "lunes", "Tuesday": "martes", "Wednesday": "miércoles",
    "Thursday": "jueves", "Friday": "viernes",
    "Saturday": "sábado", "Sunday": "domingo"
}
 
def analizar_patrones(historial: list[dict]) -> dict:
    """
    Detecta en qué horas y días se concentran los olvidos.
 
    Devuelve:
        por_hora          → {hora (0-23): nº olvidos}
        por_dia           → {nombre_dia: nº olvidos}
        hora_problematica → (hora, nº) con más olvidos
        dia_problematico  → (dia, nº) con más olvidos
        total_olvidos     → total de olvidos en el historial
    """
    olvidos = [
        t for t in historial
        if t["estado"] in ("olvido", "no_tomada")
    ]
 
    if not olvidos:
        return {
            "por_hora": {}, "por_dia": {},
            "hora_problematica": None,
            "dia_problematico": None,
            "total_olvidos": 0
        }
 
    por_hora = Counter()
    por_dia  = Counter()
 
    for t in olvidos:
        dt = datetime.fromisoformat(t["timestamp"])
        por_hora[dt.hour] += 1
        por_dia[DIAS_ES[dt.strftime("%A")]] += 1
 
    total = len(olvidos)
 
    return {
        "por_hora": dict(por_hora),
        "por_dia": dict(por_dia),
        "hora_problematica": por_hora.most_common(1)[0] if por_hora else None,
        "dia_problematico":  por_dia.most_common(1)[0]  if por_dia  else None,
        "total_olvidos": total
    }
 
 

# ------------------   5. INFORME PACIENTE ------------------  

 
def generar_informe_paciente(
    historial: list[dict],
    nombre_paciente: str = "Paciente",
    dias: int = 7
) -> str:

    adherencia = calcular_adherencia(historial, dias=dias)
    rachas     = calcular_rachas_olvido(historial)
    patrones   = analizar_patrones(historial)
 
    if adherencia["nivel"] == "sin_datos":
        return (
            f"👋 Hola **{nombre_paciente}**!\n"
            "📊 Todavía no hay suficientes datos esta semana. "
            "¡Sigue registrando tus tomas!"
        )
 
    emoji_nivel = {
        "optima":    "🟢",
        "aceptable": "🟡",
        "baja":      "🟠",
        "critica":   "🔴"
    }.get(adherencia["nivel"], "⚪")
 
    lineas = [
        f"👋 Hola **{nombre_paciente}**, aquí tienes tu resumen de la semana:",
        "",
        f"{emoji_nivel} **{adherencia['porcentaje']}% de tomas realizadas**",
        f"✅ Tomadas: {adherencia['conteos'].get('tomada', 0)}",
        f"⏱ Con algo de retraso: {adherencia['conteos'].get('tomada_con_retraso', 0)}",
        f"❌ Olvidadas: {adherencia['conteos'].get('olvido', 0) + adherencia['conteos'].get('no_tomada', 0)}",
    ]
 
    if rachas["racha_actual"] >= 3:
        lineas.append(
            f"\n⚠️ Llevas **{rachas['racha_actual']} tomas seguidas** sin tomar. "
            "¡Intenta retomar la rutina!"
        )
    elif rachas["racha_actual"] > 0:
        lineas.append(f"\n⚠️ Llevas {rachas['racha_actual']} toma(s) sin registrar.")
 
    if patrones["total_olvidos"] >= 2 and patrones["dia_problematico"]:
        d, _ = patrones["dia_problematico"]
        lineas.append(f"\n💡 Sueles olvidarlo más los **{d}**. ¡Pon una alarma ese día!")
 
    lineas.append("")
    if adherencia["nivel"] == "critica":
        lineas.append("🚨 Tu adherencia está muy baja. Habla con tu farmacéutico.")
    elif adherencia["nivel"] == "baja":
        lineas.append("⚠️ Estás por debajo del 80%. Intenta no saltarte más tomas.")
    elif adherencia["nivel"] == "aceptable":
        lineas.append("👍 ¡Buen trabajo esta semana! Sigue así.")
    else:
        lineas.append("🌟 ¡Semana perfecta! Muy bien.")
 
    return "\n".join(lineas)
 
 

# ------------------   6. INFORME FARMACÉUTICO ------------------  

 
def generar_informe_farmaceutico(
    historial: list[dict],
    nombre_paciente: str = "Paciente",
    discord_id: str = "",
    nombre_medicamento: str = "No especificado",
    dias: int = 30,
    ventana_horas: float = VENTANA_TOLERANCIA_HORAS
) -> str:
    """
    Informe clínico completo para el farmacéutico.
    Sin emojis, terminología clínica, señales de alerta y recomendaciones.
    Período por defecto: 30 días.
    """
    adherencia          = calcular_adherencia(historial, dias=dias, incluir_retraso=True)
    adherencia_estricta = calcular_adherencia(historial, dias=dias, incluir_retraso=False)
    rachas              = calcular_rachas_olvido(historial)
    patrones            = analizar_patrones(historial)
 
    fecha_informe = datetime.now().strftime("%d/%m/%Y %H:%M")
    desde_fecha   = (datetime.now() - timedelta(days=dias)).strftime("%d/%m/%Y")
    hasta_fecha   = datetime.now().strftime("%d/%m/%Y")
 
    lineas = [
        "=" * 58,
        "  INFORME DE SEGUIMIENTO FARMACOTERAPEUTICO",
        "  Generado automaticamente por PharmaBot",
        "=" * 58,
        "",
        "DATOS DEL PACIENTE",
        "-" * 40,
        f"  Identificador discord : {discord_id if discord_id else 'No disponible'}",
        f"  Nombre                : {nombre_paciente}",
        f"  Medicamento           : {nombre_medicamento}",
        f"  Periodo analizado     : {desde_fecha} — {hasta_fecha} ({dias} dias)",
        f"  Fecha del informe     : {fecha_informe}",
        f"  Ventana tolerancia    : {ventana_horas}h",
        "",
    ]
 
    # ── 1. Adherencia ──
    lineas += [
        "1. INDICADORES DE ADHERENCIA",
        "-" * 40,
    ]
 
    if adherencia["nivel"] == "sin_datos":
        lineas.append("  Sin datos suficientes en el periodo analizado.")
    else:
        mpr = adherencia_estricta["porcentaje"]
        mpr_texto = f"{mpr}%" if mpr is not None else "No calculable"
 
        lineas += [
            f"  Adherencia global (incl. retraso) : {adherencia['porcentaje']}%",
            f"  MPR estricto (solo en hora)       : {mpr_texto}",
            f"  Clasificacion OMS                 : {adherencia['nivel'].upper()}",
            f"    Optima   (>=95%) : {'SI' if adherencia['nivel'] == 'optima' else 'NO'}",
            f"    Aceptable(>=80%) : {'SI' if adherencia['nivel'] in ('optima','aceptable') else 'NO'}",
            "",
            "  Desglose de tomas:",
            f"    Total analizadas       : {adherencia['tomas_analizadas']}",
            f"    Tomadas en hora        : {adherencia['conteos'].get('tomada', 0)}",
            f"    Tomadas con retraso    : {adherencia['conteos'].get('tomada_con_retraso', 0)}",
            f"    No tomadas (rechazo)   : {adherencia['conteos'].get('no_tomada', 0)}",
            f"    Olvidos (sin respuesta): {adherencia['conteos'].get('olvido', 0)}",
        ]
 
    # ── 2. Rachas ──
    lineas += [
        "",
        "2. ANALISIS DE RACHAS DE INCUMPLIMIENTO",
        "-" * 40,
        f"  Racha actual de olvidos : {rachas['racha_actual']} tomas consecutivas",
        f"  Racha maxima registrada : {rachas['racha_maxima']} tomas consecutivas",
    ]
 
    if rachas["inicio_racha"]:
        try:
            dt = datetime.fromisoformat(rachas["inicio_racha"])
            lineas.append(f"  Inicio racha actual     : {dt.strftime('%d/%m/%Y %H:%M')}")
        except Exception:
            pass
 
    # ── 3. Patrones ──
    lineas += [
        "",
        "3. PATRONES TEMPORALES DE INCUMPLIMIENTO",
        "-" * 40,
    ]
 
    if patrones["total_olvidos"] == 0:
        lineas.append("  Sin olvidos registrados en el periodo.")
    else:
        lineas.append(f"  Total olvidos analizados : {patrones['total_olvidos']}")
 
        if patrones["hora_problematica"]:
            h, n = patrones["hora_problematica"]
            pct = round((n / patrones["total_olvidos"]) * 100, 1)
            lineas.append(f"  Franja horaria critica   : {h:02d}:00h ({n} olvidos, {pct}%)")
 
        if patrones["dia_problematico"]:
            d, n = patrones["dia_problematico"]
            pct = round((n / patrones["total_olvidos"]) * 100, 1)
            lineas.append(f"  Dia mayor incumplimiento : {d.capitalize()} ({n} olvidos, {pct}%)")
 
        if patrones["por_dia"]:
            lineas.append("\n  Distribucion por dia:")
            for dia, n in sorted(patrones["por_dia"].items(), key=lambda x: -x[1]):
                barra = "█" * n
                lineas.append(f"    {dia.capitalize():<12} {barra} ({n})")
 
    # ── 4. Señales de alerta ──
    lineas += [
        "",
        "4. SEÑALES DE ALERTA CLINICA",
        "-" * 40,
    ]
 
    alertas = []
 
    if adherencia.get("nivel") == "critica":
        alertas.append("  [CRITICA]  Adherencia <50%. Riesgo de fallo terapeutico.")
    elif adherencia.get("nivel") == "baja":
        alertas.append("  [ALERTA]   Adherencia <80%. Intervencion recomendada.")
 
    if rachas["racha_actual"] >= 5:
        alertas.append(f"  [CRITICA]  Racha activa de {rachas['racha_actual']} olvidos consecutivos.")
    elif rachas["racha_actual"] >= 3:
        alertas.append(f"  [ALERTA]   Racha activa de {rachas['racha_actual']} olvidos consecutivos.")
 
    if rachas["racha_maxima"] >= 7:
        alertas.append(f"  [ATENCION] Racha maxima historica de {rachas['racha_maxima']} olvidos.")
 
    no_tomadas = adherencia.get("conteos", {}).get("no_tomada", 0)
    if no_tomadas >= 3:
        alertas.append(
            f"  [ATENCION] {no_tomadas} rechazos activos de toma. "
            "Posible efecto adverso o rechazo voluntario."
        )
 
    if not alertas:
        alertas.append("  Sin señales de alerta en el periodo analizado.")
 
    lineas += alertas
 
    # ── 5. Recomendaciones ──
    lineas += [
        "",
        "5. RECOMENDACIONES DE INTERVENCION",
        "-" * 40,
    ]
 
    nivel = adherencia.get("nivel", "sin_datos")
 
    recomendaciones = {
        "sin_datos": [
            "  Datos insuficientes. Continuar monitorizacion."
        ],
        "optima": [
            "  Adherencia optima. Mantener seguimiento rutinario mensual."
        ],
        "aceptable": [
            "  Adherencia aceptable. Recomendaciones:",
            "    - Reforzar positivamente al paciente.",
            "    - Revisar franjas horarias problematicas si existen.",
            "    - Seguimiento en 30 dias.",
        ],
        "baja": [
            "  Adherencia baja. Intervencion recomendada:",
            "    - Entrevista motivacional con el paciente.",
            "    - Valorar simplificacion de pauta si es posible.",
            "    - Identificar causas: efectos adversos, olvidos, rechazo.",
            "    - Seguimiento intensificado en 15 dias.",
        ],
        "critica": [
            "  Adherencia critica. Intervencion urgente:",
            "    - Contacto directo con el paciente prioritario.",
            "    - Notificar al medico prescriptor si procede.",
            "    - Valorar posibles RNM (Resultados Negativos de Medicacion).",
            "    - Revision completa del tratamiento.",
            "    - Seguimiento semanal hasta estabilizacion.",
        ],
    }
 
    lineas += recomendaciones.get(nivel, ["  Sin recomendaciones disponibles."])
 
    lineas += [
        "",
        "=" * 58,
        "  PharmaBot — Informe de uso interno farmaceutico",
        "  No substituye el criterio clinico del profesional.",
        "=" * 58,
    ]
 
    return "\n".join(lineas)
 
 

# ------------------   7. FUNCIÓN PARA EL TASK SEMANAL DEL BOT ------------------ 

 
def generar_informes_semanales(
    historial_paciente: list[dict],
    historial_farmaceutico: list[dict],
    nombre_paciente: str,
    discord_id: str,
    nombre_medicamento: str,
    ventana_horas: float = VENTANA_TOLERANCIA_HORAS
) -> dict:
    """
    Genera ambos informes listos para enviar por DM semanal.
 
    Uso en dr_baki.py dentro del @tasks.loop(hours=168):
 
        from adherencia import generar_informes_semanales
 
        historial_7d  = obtener_historial(user_id, dias=7)
        historial_30d = obtener_historial(user_id, dias=30)
 
        informes = generar_informes_semanales(
            historial_paciente=historial_7d,
            historial_farmaceutico=historial_30d,
            nombre_paciente="Carlos",
            discord_id=user_id,
            nombre_medicamento="Atorvastatina 20mg"
        )
 
        await paciente_user.send(informes["paciente"])
        await farmaceutico_user.send(informes["farmaceutico"])
 
    Devuelve:
        {
            "paciente":     str  → mensaje corto con emojis para Discord
            "farmaceutico": str  → informe clínico completo
        }
    """
    return {
        "paciente": generar_informe_paciente(
            historial_paciente,
            nombre_paciente=nombre_paciente,
            dias=7
        ),
        "farmaceutico": generar_informe_farmaceutico(
            historial_farmaceutico,
            nombre_paciente=nombre_paciente,
            discord_id=discord_id,
            nombre_medicamento=nombre_medicamento,
            dias=30,
            ventana_horas=ventana_horas
        )
    }

# ══════════════════════════════════════════════════════
#  INFORME FARMACÉUTICO CON LLM (OpenAI)
# ══════════════════════════════════════════════════════

OPENAI_API_KEY = "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"

def generar_informe_farmaceutico_llm(
    historial: list[dict],
    rams: list[dict],
    nombre_paciente: str,
    discord_id: str,
    nombre_medicamento: str,
    dias: int = 30,
    ventana_horas: float = VENTANA_TOLERANCIA_HORAS
) -> str:
    """
    Genera el informe farmacéutico usando OpenAI en vez de plantillas fijas.
    Si falla la API, cae back a la versión de plantillas.
    """
    # Calcular métricas para pasarlas al LLM
    adherencia          = calcular_adherencia(historial, dias=dias, incluir_retraso=True)
    adherencia_estricta = calcular_adherencia(historial, dias=dias, incluir_retraso=False)
    rachas              = calcular_rachas_olvido(historial)
    patrones            = analizar_patrones(historial)

    # Construir resumen de RAMs
    rams_texto = "Sin RAMs reportadas en el periodo."
    if rams:
        con_ram = [r for r in rams if r["tiene_ram"]]
        if con_ram:
            items = []
            for r in con_ram:
                sintomas = r.get("rams_marcadas") or ""
                descripcion = r.get("descripcion") or ""
                fecha = r.get("fecha_registro", "")[:10]
                items.append(f"- {fecha}: {sintomas} {descripcion}".strip())
            rams_texto = "\n".join(items)

    # Construir el contexto para el LLM
    contexto = f"""
Paciente: {nombre_paciente}
Medicamento(s): {nombre_medicamento}
Periodo analizado: últimos {dias} días
Ventana de tolerancia: {ventana_horas}h

DATOS DE ADHERENCIA:
- Adherencia global (incluye retrasos): {adherencia.get('porcentaje', 'N/A')}%
- MPR estricto (solo en hora): {adherencia_estricta.get('porcentaje', 'N/A')}%
- Clasificación OMS: {adherencia.get('nivel', 'sin_datos').upper()}
- Tomas analizadas: {adherencia.get('tomas_analizadas', 0)}
- Tomadas en hora: {adherencia.get('conteos', {}).get('tomada', 0)}
- Tomadas con retraso: {adherencia.get('conteos', {}).get('tomada_con_retraso', 0)}
- No tomadas (rechazo): {adherencia.get('conteos', {}).get('no_tomada', 0)}
- Olvidos: {adherencia.get('conteos', {}).get('olvido', 0)}

RACHAS DE INCUMPLIMIENTO:
- Racha actual: {rachas['racha_actual']} tomas consecutivas sin tomar
- Racha máxima registrada: {rachas['racha_maxima']} tomas consecutivas

PATRONES TEMPORALES:
- Total olvidos: {patrones['total_olvidos']}
- Hora problemática: {patrones['hora_problematica']}
- Día problemático: {patrones['dia_problematico']}

REACCIONES ADVERSAS REPORTADAS (RAMs):
{rams_texto}
"""

    prompt = f"""Eres un farmacéutico clínico experto generando un informe de seguimiento farmacoterapéutico.

Con los siguientes datos del paciente, redacta un informe clínico profesional en español.
El informe debe incluir:
1. Resumen ejecutivo del estado de adherencia
2. Análisis clínico de los datos (relaciona adherencia, patrones y RAMs si las hay)
3. Señales de alerta si las hay
4. Recomendaciones de intervención concretas y personalizadas

El tono debe ser profesional, clínico y conciso. Sin emojis. Máximo 400 palabras.
No incluyas los datos en bruto — redacta un informe narrativo fluido.

DATOS DEL PACIENTE:
{contexto}
"""

    try:
        client = OpenAI(api_key=OPENAI_API_KEY)
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "Eres un farmacéutico clínico experto en seguimiento farmacoterapéutico."},
                {"role": "user", "content": prompt}
            ],
            max_tokens=600,
            temperature=0.3   # baja temperatura = más consistente y clínico
        )
        return response.choices[0].message.content.strip()

    except Exception as e:
        print(f"⚠️ Error API OpenAI: {e}. Usando informe de plantillas.")
        return generar_informe_farmaceutico(
            historial,
            nombre_paciente=nombre_paciente,
            discord_id=discord_id,
            nombre_medicamento=nombre_medicamento,
            dias=dias,
            ventana_horas=ventana_horas
        ) 