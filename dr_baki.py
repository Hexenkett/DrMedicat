import discord
from discord.ext import commands, tasks
from dotenv import load_dotenv
import os
import sqlite3
from datetime import datetime, timedelta
from functools import partial
from rams import (
    obtener_rams_medicamento,
    registrar_ram,
    actualizar_ultima_encuesta,
    debe_preguntar_rams,
    obtener_rams_usuario,
    generar_seccion_rams_informe
)
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)


# ══════════════════════════════════════════════════════
#  BASE DE DATOS — INICIALIZACIÓN Y FUNCIONES CORE
# ══════════════════════════════════════════════════════

DB_PATH = "pharmabot.db"

def get_conn():
    """Devuelve una conexión a la base de datos."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def inicializar_db():
    """Crea las tablas si no existen. Se llama una vez al arrancar el bot."""
    with get_conn() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS usuarios (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                discord_id  TEXT UNIQUE NOT NULL,
                creado_en   TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS medicamentos (
                id                INTEGER PRIMARY KEY AUTOINCREMENT,
                usuario_id        TEXT NOT NULL,
                nombre            TEXT NOT NULL,
                dosis             TEXT NOT NULL,
                frecuencia_texto  TEXT NOT NULL,
                frecuencia_horas  REAL NOT NULL,
                fecha_inicio      TEXT NOT NULL,
                activo            INTEGER DEFAULT 1,
                FOREIGN KEY (usuario_id) REFERENCES usuarios(discord_id)
            );

            CREATE TABLE IF NOT EXISTS tomas (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                med_id          INTEGER NOT NULL,
                usuario_id      TEXT NOT NULL,
                hora_programada TEXT NOT NULL,
                hora_real       TEXT,
                estado          TEXT NOT NULL DEFAULT 'pendiente',
                FOREIGN KEY (med_id) REFERENCES medicamentos(id),
                FOREIGN KEY (usuario_id) REFERENCES usuarios(discord_id)
            );

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
    print("✅ Base de datos inicializada correctamente.")


# ══════════════════════════════════════════════════════
#  SQLite
# ══════════════════════════════════════════════════════

def registrar_usuario_si_no_existe(discord_id: str):
    with get_conn() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO usuarios (discord_id) VALUES (?)",
            (discord_id,)
        )

def insertar_medicamento(discord_id: str, nombre: str, dosis: str,
                          frecuencia_texto: str, frecuencia_horas: float,
                          fecha_inicio: str) -> int:
    registrar_usuario_si_no_existe(discord_id)
    with get_conn() as conn:
        cursor = conn.execute(
            """INSERT INTO medicamentos
               (usuario_id, nombre, dosis, frecuencia_texto, frecuencia_horas, fecha_inicio)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (discord_id, nombre, dosis, frecuencia_texto, frecuencia_horas, fecha_inicio)
        )
        return cursor.lastrowid

def obtener_medicamentos(discord_id: str) -> list:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM medicamentos WHERE usuario_id = ? AND activo = 1",
            (discord_id,)
        ).fetchall()
    return [dict(row) for row in rows]

def eliminar_medicamento(med_id: int):
    with get_conn() as conn:
        conn.execute(
            "UPDATE medicamentos SET activo = 0 WHERE id = ?",
            (med_id,)
        )

def registrar_toma(med_id: int, usuario_id: str, hora_programada: datetime,
                   hora_real, estado: str):
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO tomas (med_id, usuario_id, hora_programada, hora_real, estado)
               VALUES (?, ?, ?, ?, ?)""",
            (
                med_id,
                usuario_id,
                hora_programada.isoformat(),
                hora_real.isoformat() if hora_real else None,
                estado
            )
        )

def actualizar_estado_toma(toma_id: int, estado: str, hora_real=None):
    with get_conn() as conn:
        conn.execute(
            "UPDATE tomas SET estado = ?, hora_real = ? WHERE id = ?",
            (estado, hora_real.isoformat() if hora_real else None, toma_id)
        )

def obtener_historial(discord_id: str, dias: int = 30) -> list:
    desde = (datetime.now() - timedelta(days=dias)).isoformat()
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT t.id, t.med_id, t.hora_programada as timestamp,
                      t.hora_real, t.estado, m.nombre, m.dosis
               FROM tomas t
               JOIN medicamentos m ON t.med_id = m.id
               WHERE t.usuario_id = ? AND t.hora_programada >= ?
               ORDER BY t.hora_programada ASC""",
            (discord_id, desde)
        ).fetchall()
    return [dict(row) for row in rows]

def obtener_ultima_toma_programada(med_id: int):
    with get_conn() as conn:
        row = conn.execute(
            """SELECT hora_programada FROM tomas
               WHERE med_id = ? ORDER BY hora_programada DESC LIMIT 1""",
            (med_id,)
        ).fetchone()
    if row:
        return datetime.fromisoformat(row["hora_programada"])
    return None


# ══════════════════════════════════════════════════════
#  CONFIGURACIÓN
# ══════════════════════════════════════════════════════

VENTANA_TOLERANCIA_HORAS = 2


# ══════════════════════════════════════════════════════
#  EVENTOS
# ══════════════════════════════════════════════════════

@bot.event
async def on_ready():
    if not hasattr(bot, "ready_once"):
        bot.ready_once = True
        inicializar_db()
        print(f"✅ Bot conectado como {bot.user}")
        revisar_recordatorios.start()
        cerrar_tomas_pendientes.start()
        revisar_encuestas_rams.start()
        enviar_informe_farmaceutico_mensual.start()


# ══════════════════════════════════════════════════════
#  COMANDOS
# ══════════════════════════════════════════════════════

@bot.command()
async def ayuda(ctx):
    mensaje = """
📌 **Lista de comandos disponibles:**
- `!registrar`        → Registrar un medicamento
- `!mismedicamentos`  → Ver tus medicamentos
- `!eliminar`         → Eliminar un medicamento
- `!adherencia`       → Ver tu resumen de adherencia
- `!ayuda`            → Mostrar esta lista
"""
    await ctx.send(mensaje)

@bot.command()
async def info(ctx):
    await ctx.send("Esta herramienta te ayuda a llevar un seguimiento de tu medicación diaria.")


# ══════════════════════════════════════════════════════
#  REGISTRAR MEDICAMENTO
# ══════════════════════════════════════════════════════

@bot.command()
async def registrar(ctx):
    def check(msg): return msg.author == ctx.author and msg.channel == ctx.channel

    await ctx.send("💊 ¿Cuál es el nombre del medicamento?")
    nombre = (await bot.wait_for("message", check=check)).content.strip()

    while True:
        await ctx.send("💉 ¿Cuál es la dosis (por ejemplo 500mg)?")
        dosis = (await bot.wait_for("message", check=check)).content.strip()
        if dosis:
            break
        await ctx.send("❌ La dosis no puede estar vacía.")

    while True:
        await ctx.send("⏱ ¿Con qué frecuencia se toma? (ej: 'cada 8 horas' o 'cada 30 minutos')")
        frecuencia_texto = (await bot.wait_for("message", check=check)).content.strip().lower()
        partes = frecuencia_texto.split()
        if len(partes) != 3 or partes[0] != "cada":
            await ctx.send("❌ Formato incorrecto. Usa 'cada X minutos' o 'cada X horas'.")
            continue
        try:
            numero = float(partes[1].replace(",", "."))
            if numero <= 0:
                await ctx.send("❌ La frecuencia debe ser mayor que 0.")
                continue
            if unidad in ["minuto", "minutos"] and numero < 15:
                await ctx.send("❌ La frecuencia mínima es cada 15 minutos.")
                continue
            if unidad in ["hora", "horas"] and numero > 24:
                await ctx.send("❌ La frecuencia máxima es cada 24 horas.")
                continue
            
            unidad = partes[2]
            if unidad not in ["minuto", "minutos", "hora", "horas"]:
                await ctx.send("❌ Unidad incorrecta. Usa 'minutos' o 'horas'.")
                continue
            break
        except ValueError:
            await ctx.send("❌ Número de frecuencia inválido.")
            continue

    inicio_str = datetime.now().strftime("%d/%m/%Y %H:%M")
    frecuencia_horas = numero / 60 if unidad in ["minuto", "minutos"] else numero
    user_id = str(ctx.author.id)

    med_id = insertar_medicamento(
        discord_id=user_id,
        nombre=nombre,
        dosis=dosis,
        frecuencia_texto=frecuencia_texto,
        frecuencia_horas=frecuencia_horas,
        fecha_inicio=inicio_str
    )

    await ctx.send(
        f"✅ Medicamento registrado:\n"
        f"**{nombre}** — {dosis} — {frecuencia_texto}"
    )


# ══════════════════════════════════════════════════════
#  VER MEDICAMENTOS
# ══════════════════════════════════════════════════════

@bot.command()
async def mismedicamentos(ctx):
    user_id = str(ctx.author.id)
    meds = obtener_medicamentos(user_id)

    if not meds:
        await ctx.send("📋 No tienes medicamentos registrados.")
        return

    mensaje = "📋 **Tus medicamentos registrados:**\n"
    for i, med in enumerate(meds, start=1):
        mensaje += (
            f"{i}. **{med['nombre']}** — {med['dosis']} — "
            f"cada {med['frecuencia_texto']} — desde {med['fecha_inicio']}\n"
        )
    await ctx.send(mensaje)


# ══════════════════════════════════════════════════════
#  ELIMINAR MEDICAMENTO
# ══════════════════════════════════════════════════════

@bot.command()
async def eliminar(ctx):
    user_id = str(ctx.author.id)
    meds = obtener_medicamentos(user_id)

    if not meds:
        await ctx.send("📭 No tienes medicamentos registrados.")
        return

    opciones = [
        discord.SelectOption(
            label=f"{med['nombre']} — {med['dosis']}",
            description=f"cada {med['frecuencia_texto']}",
            value=str(med["id"])
        )
        for med in meds
    ]

    select = discord.ui.Select(
        placeholder="Selecciona el medicamento a eliminar...",
        min_values=1,
        max_values=1,
        options=opciones
    )

    async def callback_eliminar(interaction: discord.Interaction):
        if str(interaction.user.id) != user_id:
            await interaction.response.send_message("Este menú no es para ti.", ephemeral=True)
            return

        med_id = int(interaction.data["values"][0])
        nombre = next(m["nombre"] for m in meds if m["id"] == med_id)

        eliminar_medicamento(med_id)

        for child in view.children:
            child.disabled = True
        await interaction.response.edit_message(
            content=f"✅ Medicamento **{nombre}** eliminado correctamente.",
            view=view
        )

    select.callback = callback_eliminar

    view = discord.ui.View(timeout=60)
    view.add_item(select)

    await ctx.send("**Selecciona el medicamento que quieres eliminar:**", view=view)


# ══════════════════════════════════════════════════════
#  INFORME DE ADHERENCIA (paciente)
# ══════════════════════════════════════════════════════

@bot.command()
async def adherencia(ctx):
    from adherencia import generar_informe_paciente

    user_id   = str(ctx.author.id)
    historial = obtener_historial(user_id, dias=7)

    if not historial:
        await ctx.send("📊 No hay datos suficientes todavía. Sigue registrando tus tomas.")
        return

    informe = generar_informe_paciente(
        historial,
        nombre_paciente=ctx.author.display_name,
        dias=7
    )
    await ctx.send(informe)


# ══════════════════════════════════════════════════════
#  RECORDATORIOS AUTOMÁTICOS
# ══════════════════════════════════════════════════════

@tasks.loop(minutes=1)
async def revisar_recordatorios():
    ahora = datetime.now()

    with get_conn() as conn:
        meds = conn.execute(
            "SELECT * FROM medicamentos WHERE activo = 1"
        ).fetchall()

    for med in meds:
        med = dict(med)
        try:
            inicio = datetime.strptime(med["fecha_inicio"], "%d/%m/%Y %H:%M")
        except ValueError:
            continue

        frecuencia_horas = med.get("frecuencia_horas")
        if not frecuencia_horas or frecuencia_horas <= 0:
            continue

        ultima_programada = obtener_ultima_toma_programada(med["id"])
        if ultima_programada:
            proxima = ultima_programada + timedelta(hours=frecuencia_horas)
        else:
            proxima = inicio

        if proxima <= ahora and (ahora - proxima).total_seconds() < 300:
            try:
                usuario = await bot.fetch_user(int(med["usuario_id"]))

                registrar_toma(
                    med_id=med["id"],
                    usuario_id=med["usuario_id"],
                    hora_programada=proxima,
                    hora_real=None,
                    estado="pendiente"
                )

                with get_conn() as conn:
                    toma_id = conn.execute(
                        "SELECT id FROM tomas WHERE med_id = ? ORDER BY id DESC LIMIT 1",
                        (med["id"],)
                    ).fetchone()["id"]

                view = RecordatorioView(
                    user_id=med["usuario_id"],
                    med=med,
                    toma_id=toma_id,
                    hora_programada=proxima
                )
                await usuario.send(
                    f"⏰ Es hora de tomar **{med['nombre']} ({med['dosis']})**",
                    view=view
                )

            except Exception as e:
                print(f"❌ Error enviando recordatorio a {med['usuario_id']}: {e}")


# ══════════════════════════════════════════════════════
#  CERRAR TOMAS PENDIENTES 
# ══════════════════════════════════════════════════════

@tasks.loop(hours=1)
async def cerrar_tomas_pendientes():
    ahora  = datetime.now()
    limite = ahora - timedelta(hours=VENTANA_TOLERANCIA_HORAS)

    with get_conn() as conn:
        tomas_vencidas = conn.execute(
            """SELECT id FROM tomas
               WHERE estado = 'pendiente'
               AND hora_programada <= ?""",
            (limite.isoformat(),)
        ).fetchall()

        if tomas_vencidas:
            ids = [str(t["id"]) for t in tomas_vencidas]
            conn.execute(
                f"""UPDATE tomas SET estado = 'olvido'
                    WHERE id IN ({','.join(ids)})"""
            )
            print(f"⏰ Cerradas {len(ids)} tomas pendientes como olvido.")
        else:
            print("✅ Sin tomas pendientes vencidas.")


# ══════════════════════════════════════════════════════
#  ENCUESTAS DE RAMs 
# ══════════════════════════════════════════════════════

@tasks.loop(hours=24)
async def revisar_encuestas_rams():
    """Revisa cada 24h si algún usuario lleva 7 días sin encuesta RAM."""
    with get_conn() as conn:
        meds = conn.execute(
            "SELECT * FROM medicamentos WHERE activo = 1"
        ).fetchall()

    for med in meds:
        med = dict(med)
        with get_conn() as conn:
            if not debe_preguntar_rams(conn, med["usuario_id"], med["id"]):
                continue

        try:
            usuario    = await bot.fetch_user(int(med["usuario_id"]))
            rams_lista = obtener_rams_medicamento(med["nombre"])

            view = EncuestaRamView(
                user_id=med["usuario_id"],
                med=med,
                rams_lista=rams_lista
            )

            await usuario.send(
                f"💊 **Seguimiento semanal — {med['nombre']}**\n\n"
                f"Han pasado 7 días. ¿Has notado alguno de estos síntomas "
                f"desde que tomas **{med['nombre']}**?",
                view=view
            )

        except Exception as e:
            print(f"❌ Error enviando encuesta RAM a {med['usuario_id']}: {e}")


# ══════════════════════════════════════════════════════
#  TEST DE ENCUESTA DE RAMs - COMANDO PARA PROBAR RAMs
# ══════════════════════════════════════════════════════

@bot.command()
async def testram(ctx):
    """Comando temporal para probar la encuesta RAM sin esperar 7 días."""
    user_id = str(ctx.author.id)
    meds = obtener_medicamentos(user_id)
    if not meds:
        await ctx.send("No tienes medicamentos registrados.")
        return
    med = meds[0]
    rams_lista = obtener_rams_medicamento(med["nombre"])
    view = EncuestaRamView(
        user_id=user_id,
        med=med,
        rams_lista=rams_lista
    )
    await ctx.author.send(
        f"💊 **Seguimiento semanal — {med['nombre']}**\n\n"
        f"¿Has notado alguno de estos síntomas desde que tomas **{med['nombre']}**?",
        view=view
    )
    await ctx.send("✅ Encuesta enviada por DM.")



# ══════════════════════════════════════════════════════
#  BOTONES — RECORDATORIO DE TOMA
# ══════════════════════════════════════════════════════

class RecordatorioView(discord.ui.View):
    def __init__(self, user_id: str, med: dict, toma_id: int, hora_programada: datetime):
        super().__init__(timeout=3600)
        self.user_id         = user_id
        self.med             = med
        self.toma_id         = toma_id
        self.hora_programada = hora_programada
        self.respondido      = False

        tomado_btn = discord.ui.Button(label="✅ Tomado", style=discord.ButtonStyle.success)
        tomado_btn.callback = self.callback_tomado
        self.add_item(tomado_btn)

        posponer_btn = discord.ui.Button(label="⏰ Posponer", style=discord.ButtonStyle.secondary)
        posponer_btn.callback = self.callback_posponer
        self.add_item(posponer_btn)

        no_tomado_btn = discord.ui.Button(label="❌ No tomado", style=discord.ButtonStyle.danger)
        no_tomado_btn.callback = self.callback_no_tomado
        self.add_item(no_tomado_btn)

    async def _deshabilitar_botones(self, interaction: discord.Interaction):
        for child in self.children:
            child.disabled = True
        await interaction.message.edit(view=self)

    def _verificar_usuario(self, interaction: discord.Interaction) -> bool:
        return str(interaction.user.id) == str(self.user_id)

    async def callback_tomado(self, interaction: discord.Interaction):
        if not self._verificar_usuario(interaction):
            await interaction.response.send_message("Este recordatorio no es para ti.", ephemeral=True)
            return
        if self.respondido:
            await interaction.response.send_message("Ya has respondido a este recordatorio.", ephemeral=True)
            return
        self.respondido = True

        ahora         = datetime.now()
        retraso_horas = (ahora - self.hora_programada).total_seconds() / 3600
        estado        = "tomada" if retraso_horas <= VENTANA_TOLERANCIA_HORAS else "tomada_con_retraso"

        actualizar_estado_toma(self.toma_id, estado, hora_real=ahora)
        await interaction.response.send_message(
            f"✅ Toma de **{self.med['nombre']}** registrada a las {ahora.strftime('%H:%M')}",
            ephemeral=True
        )
        await self._deshabilitar_botones(interaction)

    async def callback_posponer(self, interaction: discord.Interaction):
        if not self._verificar_usuario(interaction):
            await interaction.response.send_message("Este recordatorio no es para ti.", ephemeral=True)
            return
        if self.respondido:
            await interaction.response.send_message("Ya has respondido a este recordatorio.", ephemeral=True)
            return
        self.respondido = True

        actualizar_estado_toma(self.toma_id, "pospuesta")

        nueva_hora = datetime.now() + timedelta(minutes=10)
        bot.loop.call_later(
            600,
            lambda: bot.loop.create_task(
                self._enviar_recordatorio_pospuesto(interaction.user, nueva_hora)
            )
        )

        await interaction.response.send_message(
            f"⏰ Te recordaré **{self.med['nombre']}** en 10 minutos.",
            ephemeral=True
        )
        await self._deshabilitar_botones(interaction)

    async def _enviar_recordatorio_pospuesto(self, usuario, hora_programada: datetime):
        registrar_toma(
            med_id=self.med["id"],
            usuario_id=self.user_id,
            hora_programada=hora_programada,
            hora_real=None,
            estado="pendiente"
        )
        with get_conn() as conn:
            toma_id = conn.execute(
                "SELECT id FROM tomas WHERE med_id = ? ORDER BY id DESC LIMIT 1",
                (self.med["id"],)
            ).fetchone()["id"]

        nueva_view = RecordatorioView(
            user_id=self.user_id,
            med=self.med,
            toma_id=toma_id,
            hora_programada=hora_programada
        )
        await usuario.send(
            f"⏰ Recordatorio pospuesto: **{self.med['nombre']} ({self.med['dosis']})**",
            view=nueva_view
        )

    async def callback_no_tomado(self, interaction: discord.Interaction):
        if not self._verificar_usuario(interaction):
            await interaction.response.send_message("Este recordatorio no es para ti.", ephemeral=True)
            return
        if self.respondido:
            await interaction.response.send_message("Ya has respondido a este recordatorio.", ephemeral=True)
            return
        self.respondido = True

        actualizar_estado_toma(self.toma_id, "no_tomada")
        await interaction.response.send_message(
            f"❌ Toma de **{self.med['nombre']}** marcada como no tomada.",
            ephemeral=True
        )
        await self._deshabilitar_botones(interaction)


# ══════════════════════════════════════════════════════
#  BOTONES — ENCUESTA RAM
# ══════════════════════════════════════════════════════

class EncuestaRamView(discord.ui.View):
    """Primera pantalla: ¿Has notado alguna RAM? Sí / No"""
    def __init__(self, user_id: str, med: dict, rams_lista: list):
        super().__init__(timeout=86400)
        self.user_id    = user_id
        self.med        = med
        self.rams_lista = rams_lista
        self.respondido = False

        si_btn = discord.ui.Button(label="⚠️ Sí, he notado algo", style=discord.ButtonStyle.danger)
        si_btn.callback = self.callback_si
        self.add_item(si_btn)

        no_btn = discord.ui.Button(label="✅ No, todo bien", style=discord.ButtonStyle.success)
        no_btn.callback = self.callback_no
        self.add_item(no_btn)

    def _verificar_usuario(self, interaction: discord.Interaction) -> bool:
        return str(interaction.user.id) == str(self.user_id)

    async def callback_no(self, interaction: discord.Interaction):
        if not self._verificar_usuario(interaction):
            await interaction.response.send_message("Esta encuesta no es para ti.", ephemeral=True)
            return
        if self.respondido:
            return
        self.respondido = True

        with get_conn() as conn:
            registrar_ram(conn, self.user_id, self.med["id"], tiene_ram=False)
            actualizar_ultima_encuesta(conn, self.user_id, self.med["id"])

        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(
            content="✅ Perfecto, ¡gracias por responder! Seguimos de cerca tu tratamiento.",
            view=self
        )

    async def callback_si(self, interaction: discord.Interaction):
        if not self._verificar_usuario(interaction):
            await interaction.response.send_message("Esta encuesta no es para ti.", ephemeral=True)
            return
        if self.respondido:
            return
        self.respondido = True
        view = SeleccionRamView(
            user_id=self.user_id,
            med=self.med,
            rams_lista=self.rams_lista
        )

        sintomas_texto = "\n".join([f"{i+1}. {r}" for i, r in enumerate(self.rams_lista)])

        await interaction.response.edit_message(
            content=f"Selecciona los síntomas que has notado:\n\n{sintomas_texto}",
            view=view
        )


class SeleccionRamView(discord.ui.View):
    """Segunda pantalla: selección de síntomas del medicamento."""
    def __init__(self, user_id: str, med: dict, rams_lista: list):
        super().__init__(timeout=86400)
        self.user_id    = user_id
        self.med        = med
        self.rams_lista = rams_lista
        self.seleccion  = []

        opciones = [
            discord.SelectOption(label=ram[:100], value=str(i))
            for i, ram in enumerate(rams_lista[:25])
        ]

        select = discord.ui.Select(
            placeholder="Selecciona los síntomas que has notado...",
            min_values=1,
            max_values=len(opciones),
            options=opciones
        )
        select.callback = self.callback_seleccion
        self.add_item(select)

    async def callback_seleccion(self, interaction: discord.Interaction):
        if str(interaction.user.id) != str(self.user_id):
            await interaction.response.send_message("Esta encuesta no es para ti.", ephemeral=True)
            return

        seleccion = [self.rams_lista[int(v)] for v in interaction.data["values"]]

        if "Ninguno de los anteriores" in seleccion:
            view = DescripcionRamView(
                user_id=self.user_id,
                med=self.med,
                rams_marcadas=[]
            )
            await interaction.response.edit_message(
                content="Entendido. ¿Quieres describir con tus propias palabras "
                        "El sintoma que has notado?",
                view=view
            )
            return
        
        self.seleccion = seleccion
        view = DescripcionRamView(
            user_id=self.user_id,
            med=self.med,
            rams_marcadas=self.seleccion
        )

        await interaction.response.edit_message(
            content=f"✅ Anotado: **{', '.join(self.seleccion)}**\n\n"
                    f"¿Quieres añadir algo más con tus propias palabras?",
            view=view
        )


class DescripcionRamView(discord.ui.View):
    """Tercera pantalla: descripción libre opcional."""
    def __init__(self, user_id: str, med: dict, rams_marcadas: list):
        super().__init__(timeout=86400)
        self.user_id       = user_id
        self.med           = med
        self.rams_marcadas = rams_marcadas

        finalizar_btn = discord.ui.Button(label="✅ Finalizar", style=discord.ButtonStyle.success)
        finalizar_btn.callback = self.callback_finalizar
        self.add_item(finalizar_btn)

        descripcion_btn = discord.ui.Button(label="📝 Añadir descripción", style=discord.ButtonStyle.secondary)
        descripcion_btn.callback = self.callback_descripcion
        self.add_item(descripcion_btn)

    async def callback_finalizar(self, interaction: discord.Interaction):
        if str(interaction.user.id) != str(self.user_id):
            return

        with get_conn() as conn:
            registrar_ram(
                conn,
                self.user_id,
                self.med["id"],
                tiene_ram=True,
                rams_marcadas=self.rams_marcadas
            )
            actualizar_ultima_encuesta(conn, self.user_id, self.med["id"])

        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(
            content="✅ Gracias por tu respuesta. Tu farmacéutico revisará esta información "
                    "en el próximo informe semanal.",
            view=self
        )

    async def callback_descripcion(self, interaction: discord.Interaction):
        if str(interaction.user.id) != str(self.user_id):
            return

        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(
            content="📝 Escribe a continuación cómo te has sentido (en un solo mensaje):",
            view=self
        )

        def check(msg):
            return (
                msg.author.id == int(self.user_id)
                and isinstance(msg.channel, discord.DMChannel)
            )

        try:
            mensaje     = await bot.wait_for("message", check=check, timeout=300)
            descripcion = mensaje.content.strip()

            with get_conn() as conn:
                registrar_ram(
                    conn,
                    self.user_id,
                    self.med["id"],
                    tiene_ram=True,
                    descripcion=descripcion,
                    rams_marcadas=self.rams_marcadas
                )
                actualizar_ultima_encuesta(conn, self.user_id, self.med["id"])

            await interaction.followup.send(
                "✅ Registrado. Tu farmacéutico lo revisará en el próximo informe.",
                ephemeral=True
            )

        except Exception as e:
            print(f"Error en descripcion RAM: {e}")
            await interaction.followup.send(
                "⏰ Tiempo agotado. Si quieres añadir más detalles, "
                "habla directamente con tu farmacéutico.",
                ephemeral=True
            )


# ══════════════════════════════════════════════════════
#  INFORME FARMACÉUTICO MENSUAL
# ══════════════════════════════════════════════════════

@tasks.loop(hours=720)   # 720h = 30 días
async def enviar_informe_farmaceutico_mensual():
    """
    Cada 30 días envía al paciente el informe farmacéutico clínico completo
    para que pueda entregarlo en su farmacia comunitaria.
    Incluye adherencia de 30 días + RAMs reportadas.
    """
    from adherencia import generar_informe_farmaceutico_llm
    
    print("📋 Iniciando envío de informes farmacéuticos mensuales...")
    
    with get_conn() as conn:
        # Obtener todos los usuarios con al menos un medicamento activo
        usuarios = conn.execute("""
            SELECT DISTINCT usuario_id FROM medicamentos WHERE activo = 1
        """).fetchall()
    
    for row in usuarios:
        user_id = row["usuario_id"]
        
        try:
            # Obtener datos del usuario
            meds = obtener_medicamentos(user_id)
            if not meds:
                continue
            
            historial = obtener_historial(user_id, dias=30)
            if not historial:
                print(f"⏭️ Usuario {user_id} sin historial, se omite.")
                continue
            
            # Obtener RAMs del último mes
            with get_conn() as conn:
                rams_registradas = obtener_rams_usuario(conn, user_id, dias=30)
            
            # Obtener nombre del paciente
            usuario = await bot.fetch_user(int(user_id))
            nombre_paciente = usuario.display_name
            
            # Nombres de medicamentos activos
            nombres_meds = ", ".join([m["nombre"] for m in meds])
            
            # Generar informe principal
            informe = generar_informe_farmaceutico_llm(
                historial,
                rams=rams_registradas,
                nombre_paciente=nombre_paciente,
                discord_id=user_id,
                nombre_medicamento=nombres_meds,
                dias=30
            )
            
            # Añadir la sección de RAMs al final
            seccion_rams = generar_seccion_rams_informe(rams_registradas)
            informe_completo = informe + "\n" + seccion_rams
            
            # Enviar al paciente dentro de bloque de código para formato monoespaciado
            await usuario.send(
                "📋 **Tu informe farmacéutico mensual**\n"
                "Puedes entregar este informe a tu farmacéutico para que pueda "
                "hacer un seguimiento personalizado de tu tratamiento.\n"
            )
            
            # Discord limita mensajes a 2000 caracteres — si es muy largo, dividir
            if len(informe_completo) <= 1900:
                await usuario.send(f"```\n{informe_completo}\n```")
            else:
                # Dividir en dos partes
                mitad = len(informe_completo) // 2
                corte = informe_completo.rfind("\n", 0, mitad)
                parte1 = informe_completo[:corte]
                parte2 = informe_completo[corte:]
                await usuario.send(f"```\n{parte1}\n```")
                await usuario.send(f"```\n{parte2}\n```")
            
            print(f"✅ Informe enviado a {user_id}")
            
        except Exception as e:
            print(f"❌ Error enviando informe a {user_id}: {e}")
    
    print("📋 Envío de informes mensuales completado.")

@enviar_informe_farmaceutico_mensual.before_loop
async def before_informe_mensual():
    await bot.wait_until_ready()
    import asyncio
    await asyncio.sleep(720 * 3600)

@bot.command()
async def testinforme(ctx):
    """Comando temporal para probar el informe mensual al instante."""
    from adherencia import generar_informe_farmaceutico_llm
    
    user_id = str(ctx.author.id)
    meds = obtener_medicamentos(user_id)
    
    if not meds:
        await ctx.send("No tienes medicamentos registrados.")
        return
    
    historial = obtener_historial(user_id, dias=30)
    
    with get_conn() as conn:
        rams_registradas = obtener_rams_usuario(conn, user_id, dias=30)
    
    nombres_meds = ", ".join([m["nombre"] for m in meds])
    
    informe = generar_informe_farmaceutico_llm(
        historial,
        rams=rams_registradas,
        nombre_paciente=ctx.author.display_name,
        discord_id=user_id,
        nombre_medicamento=nombres_meds,
        dias=30
    )
    
    seccion_rams = generar_seccion_rams_informe(rams_registradas)
    informe_completo = informe + "\n" + seccion_rams
    
    await ctx.author.send("📋 **Tu informe farmacéutico mensual (prueba)**")
    
    if len(informe_completo) <= 1900:
        await ctx.author.send(f"```\n{informe_completo}\n```")
    else:
        mitad = len(informe_completo) // 2
        corte = informe_completo.rfind("\n", 0, mitad)
        parte1 = informe_completo[:corte]
        parte2 = informe_completo[corte:]
        await ctx.author.send(f"```\n{parte1}\n```")
        await ctx.author.send(f"```\n{parte2}\n```")
    
    await ctx.send("✅ Informe enviado por DM.")



bot.run(TOKEN)