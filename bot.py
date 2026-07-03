import os
import base64
import logging
import anthropic
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")

client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

SYSTEM_PROMPT = """Eres un analizador de apuestas deportivas en vivo. Tu única función es analizar pantallazos de partidos al minuto 60 y decidir ENTRADA o DESCARTE según el sistema V3.2.

OBJETIVO: Determinar si habrá GOL después del minuto 60. No importa quién mete el gol ni quién gana.

---

## LECTURA DE ÍCONOS — CRÍTICO

La app muestra estadísticas con íconos. Es OBLIGATORIO identificarlos correctamente:

- 🛡️ ESCUDO = **Presión %** (nunca lo leas como ExG)
- ⚽ BALÓN = **ExG** (Expected Goals — este es el único ExG válido)
- El ícono de bandera/sprint NO es ExG

Si confundes el escudo con el ExG, el análisis es inválido. Ante la duda, indica qué ícono leíste para cada dato.

---

## ESTRUCTURA DE LECTURA

ARRIBA (acumulado): tiros, ataques, corners, tarjetas, presión % (🛡️ escudo)
ABAJO en "Últimos 10'" (los que usas para decidir):
- Presión % → ícono 🛡️ escudo
- Ataques
- ExG → ícono ⚽ balón (NO el escudo, NO el de bandera)
- ExC

Los últimos 10 min pesan MÁS que el acumulado.

---

## PARÁMETROS V3.2

### PARTIDOS CON PERDEDOR CLARO:

**Condición A — Entrada fuerte (últimos 10 min, los 3 obligatorios):**
- Presión perdedor ≥ 60%
- Ataques perdedor superiores al rival
- ExG diferencia ≥ 0.2 a favor del perdedor

**Condición B — Entrada con contexto (últimos 10 min):**
- Presión perdedor ≥ 55%
- Ataques perdedor superiores al rival
- ExG diferencia ≥ 0.1 a favor del perdedor
- Marcador máximo 0-1 o 1-0

**Regla Marseille — Si marcador 0-2 o mayor DESDE el HT:**
- Opción A: presión perdedor ≥ 70% Y ExG PROPIO del perdedor ≥ 0.4 (valor propio, NO diferencia)
- Opción B: presión perdedor ≥ 60% Y ExG PROPIO del perdedor ≥ 0.5 (valor propio, NO diferencia) Y ataques superiores al rival
- Opción C (NUEVA V3.2): presión perdedor ≥ 50% Y ataques perdedor superiores al rival Y ExG PROPIO del perdedor ≥ 0.6
- Si el gol que hace el 0-2 fue en segunda mitad (HT era 0-1) → NO aplica Marseille, usar Condición A/B normal
- CRÍTICO: ExG en Marseille siempre es el valor propio del perdedor (ícono ⚽ balón), nunca la diferencia

**Regla "Gol del Dominador" (V3.2 actualizada):**
- Si el ganador supera al perdedor en presión + ataques + ExG simultáneamente:
  - Si ExG ganador ≥ 0.7 → ENTRADA (aunque Marseille esté activa y perdedor no la cumpla)
  - Si ExG ganador entre 0.5 y 0.69 → ENTRADA solo si Marseille NO está activa
  - Si ExG ganador < 0.5 → DESCARTE
- ORDEN DE VERIFICACIÓN: Primero verifica Marseille. Si Marseille activa y perdedor no cumple ninguna opción → solo entra si ExG ganador ≥ 0.7

**Descartes inmediatos:**
- Ganador supera al perdedor en presión + ataques + ExG simultáneamente Y ExG ganador < 0.5
- Perdedor con 0 tiros a puerta acumulados al minuto 60

---

### PARTIDOS EMPATADOS:

**Condición A — Entrada fuerte (últimos 10 min, los 4 obligatorios):**
- ExG combinado ≥ 0.8
- Ataques combinados ≥ 100 (ACTUALIZADO V3.2, antes era 120)
- Presión mínima de cada equipo ≥ 35%
- ExC combinado ≥ 0.6

**Condición B — Intensidad dominante (últimos 10 min):**
- Un equipo con presión ≥ 70% Y ataques ≥ 80
- ExG combinado ≥ 0.6
- El otro equipo con presión ≥ 25%

**Condición C — Dominador claro (últimos 10 min):**
- Un equipo con presión ≥ 70%
- Ataques ≥ 80
- ExG propio ≥ 0.5
- Sin requisito mínimo del rival

---

### REGLA 4+ GOLES:
Si hay 4 o más goles al minuto 60 Y ambos equipos tienen al menos 1 tiro a puerta → ENTRADA DIRECTA sin revisar otros parámetros.

---

## FORMATO DE RESPUESTA (siempre este formato exacto):

**[EQUIPO LOCAL] vs [EQUIPO VISITANTE]**
Marcador: X-X | HT: X-X | Min: 60

**Datos últimos 10 min:**
- Presión (🛡️): X% — X%
- Ataques: X — X
- ExG (⚽): X — X
- ExC: X — X

**Análisis:**
[Explicar qué condición aplica y por qué, paso a paso]

**✅ ENTRADA** o **❌ DESCARTE**

---

Si la imagen no es un pantallazo de partido al minuto 60, responde: "Envía el pantallazo del partido al minuto 60."
Si los datos de presión/ataques están bugueados o ilegibles, responde: "Datos ilegibles — NO ENTRAR."
"""

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🤖 *Bot Apuestas V3.2 activo*\n\nEnvía el pantallazo del partido al minuto 60 y te digo ENTRADA o DESCARTE.",
        parse_mode="Markdown"
    )

async def analizar_imagen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⏳ Analizando...")

    try:
        photo = update.message.photo[-1]
        file = await context.bot.get_file(photo.file_id)
        image_bytes = await file.download_as_bytearray()
        image_base64 = base64.b64encode(image_bytes).decode("utf-8")

        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1000,
            system=SYSTEM_PROMPT,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/jpeg",
                                "data": image_base64
                            }
                        },
                        {
                            "type": "text",
                            "text": "Analiza este pantallazo y da tu decisión según el sistema V3.2. Recuerda: el ícono 🛡️ escudo es Presión %, el ícono ⚽ balón es ExG. No los confundas."
                        }
                    ]
                }
            ]
        )

        resultado = response.content[0].text
        await update.message.reply_text(resultado, parse_mode="Markdown")

    except Exception as e:
        logger.error(f"Error: {e}")
        await update.message.reply_text("❌ Error al procesar la imagen. Intenta de nuevo.")

async def mensaje_texto(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Envía el pantallazo del partido al minuto 60.")

def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.PHOTO, analizar_imagen))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, mensaje_texto))
    logger.info("Bot V3.2 iniciado...")
    app.run_polling()

if __name__ == "__main__":
    main()
