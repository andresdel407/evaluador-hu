# Arranque en tres pasos

## 1. Clave

```bash
cp .env.example .env
```

Abre `.env` y pon tu clave de Google AI Studio en `GEMINI_API_KEY`.
La generas gratis y sin tarjeta en <https://aistudio.google.com> → "Get API key".

## 2. Levantar

```bash
docker compose up --build
```

Abre <http://localhost:8000>.

## 3. Verificar antes de presentar

En otra terminal:

```bash
docker compose exec evaluador python check.py
```

Comprueba tres cosas en orden: la compuerta 1, la configuración, y una llamada
real al modelo. Si las tres pasan, la demo funciona.

---

## Modo acoplado (solo para el experimento)

Por defecto la compuerta 2 hace **dos llamadas** al modelo: una evalúa contra la
rúbrica y otra complementa (reescritura o preguntas al PO). El veredicto no lo
emite el modelo: lo deriva Python a partir del tipo de cada falla.

El prompt original, que evaluaba y complementaba en una sola llamada, se
conserva para poder comparar ambos diseños. En `.env`:

```
MODO_ACOPLADO=true
```

En ese modo hay una sola llamada y el veredicto vuelve a venir del modelo. La
respuesta de `/api/evaluar` es la misma en ambos modos, y trae `modo`,
`llamadas_modelo` y `latencias_ms` para trazabilidad.

Como con cualquier variable de entorno, hay que recrear el contenedor:

```bash
docker compose up -d --force-recreate
```

---

## Requirement smells (medición, no compuerta)

Cada evaluación devuelve además un bloque `smells`: un detector determinista de
*requirement smells* basado en Zakeri-Nasrabadi y Parsa (2024). No usa modelo,
no sale a la red y **nunca bloquea** — en el paper tiene precisión 0.42, así que
sirve como señal, no como decisión.

Analiza una unidad por oración (la historia, y cada criterio por separado) y
reporta por unidad las palabras marcadas, la claridad C(R) de la ecuación 3 del
paper, y el número de palabras. Cuando el veredicto es `rechazo_redaccion` y hay
reescritura, repite todo sobre la versión reescrita y agrega qué términos de
contenido aparecieron y cuáles desaparecieron.

Dos variables opcionales, ambas en `false` por defecto:

```
SMELLS_EN_PROMPT=false           # si los hallazgos entran al prompt de evaluación
REEVALUAR_COMPLEMENTACION=false  # reevalúa la reescritura; cuesta una llamada extra
```

Requiere el modelo de spaCy `es_core_news_sm`, que el `Dockerfile` descarga en
la construcción. Sin Docker hay que bajarlo a mano:

```bash
python -m spacy download es_core_news_sm
```

---

## Si algo falla

**"Falta la variable GEMINI_API_KEY"** — el `.env` no existe o está vacío.
Recuerda que `.env.example` es la plantilla; el archivo que se lee es `.env`.

**"El proveedor rechazó la credencial"** — la clave no es válida, o no
corresponde al proveedor que declara `LLM_MODEL`.

**"Se agotó el cupo de solicitudes"** — el nivel gratuito de Gemini tiene
límites por minuto y por día. Espera un minuto y reintenta.

**"No se pudo abrir conexión con LLM_API_BASE=..."** — el servidor local no
está corriendo, o el contenedor no lo alcanza. Recorre la comprobación de
alcance en tres pasos del final de este documento.

**"El proveedor 'ollama_chat' es local y no necesita clave, pero sí necesita
saber dónde está el servidor"** — falta `LLM_API_BASE` en el `.env`.

**El puerto 8000 está ocupado** — cambia el mapeo en `docker-compose.yml` a
`"8080:8000"` y entra por <http://localhost:8080>.

**Sin Docker** — funciona igual en local:

```bash
pip install -r requirements.txt
uvicorn app.main:app --reload
```

---

## Cambiar de proveedor

El proveedor es una variable de entorno, nunca una edición de código: correr la
misma rúbrica contra modelos distintos es un requisito metodológico de la tesis,
no una comodidad. En `.env` se cambian dos líneas y se recrea el contenedor.

| Proveedor | `LLM_MODEL` | Clave | `LLM_API_BASE` |
|---|---|---|---|
| Ollama (por defecto) | `ollama_chat/gemma3:4b` | no requiere | sí, obligatorio |
| Google | `gemini/gemini-3.5-flash` | `GEMINI_API_KEY` | no |
| DeepSeek | `deepseek/deepseek-flash` | `DEEPSEEK_API_KEY` | no |
| Anthropic | `anthropic/claude-sonnet-4-5` | `ANTHROPIC_API_KEY` | no |
| OpenAI | `openai/gpt-4o` | `OPENAI_API_KEY` | no |
| Mistral | `mistral/mistral-large-latest` | `MISTRAL_API_KEY` | no |
| Groq | `groq/llama-3.3-70b-versatile` | `GROQ_API_KEY` | no |

### DeepSeek

```
DEEPSEEK_API_KEY=sk-...
LLM_MODEL=deepseek/deepseek-flash
LLM_REASONING_EFFORT=none
```

Exige clave y no necesita `LLM_API_BASE`. Expone dos modelos vigentes:
`deepseek-flash`, el económico, y `deepseek-v4-pro`. **No uses `deepseek-chat`,
`deepseek-reasoner` ni `deepseek-v4-flash`: los tres están retirados.**

**`LLM_REASONING_EFFORT=none` no es opcional acá.** litellm traduce esta
variable al dialecto de cada proveedor y el mismo valor no significa lo mismo
en todos: en Ollama `minimal` se traduce a `think:false`, pero en DeepSeek solo
el literal `none` apaga el razonamiento y cualquier otro valor no vacío lo
enciende. Con el razonamiento encendido, `deepseek-flash` gasta los 1600 tokens
de `LLM_MAX_TOKENS` pensando y la respuesta se trunca antes de cerrar el JSON,
en todas las corridas. Si venís de otro proveedor, revisá este valor: no se
traslada.

`deepseek-flash` es un alias y su contenido puede cambiar sin aviso. Para que
una corrida sea reproducible en la tesis, anotá la fecha junto al resultado.

Después de editar `.env` hay que recrear el contenedor:

```bash
docker compose up -d --force-recreate
```

Si falta la clave, `check.py` y `/api/salud` lo dicen antes de gastar la
llamada: la comprobación previa sabe qué variable espera cada proveedor.

---

## Sin costo ni clave: Ollama local

Con Ollama corriendo en tu máquina, en `.env`:

```
LLM_MODEL=ollama_chat/gemma3:4b
LLM_API_BASE=http://host.docker.internal:11434
```

Eso es todo lo que cambia en el repositorio: el proveedor sigue siendo una
variable de entorno. Usa el prefijo `ollama_chat/` y no `ollama/`; es el que
habla con `/api/chat`, el endpoint que litellm recomienda para conversaciones.

`LLM_SEED` es opcional y solo reduce la varianza entre corridas; Ollama la
respeta y la recibe como `options.seed`.

Después de editar `.env` hay que recrear el contenedor, porque las variables se
leen al arrancar el proceso:

```bash
docker compose up -d --force-recreate
```

Los resultados son peores en ambigüedad, que es justo lo que más importa para
la rúbrica, pero sirve para desarrollar e iterar sin gastar cupo.

### Configuración del host (fuera del repositorio)

Lo anterior asume que el contenedor alcanza al Ollama del host. Esa parte **no
vive en el repositorio** y no la configura `docker compose`: es configuración de
la máquina, y hay que dejarla hecha una vez.

Lo verificado en el entorno de desarrollo de la tesis (Windows + WSL2):

1. **`.wslconfig`** en el perfil del usuario de Windows (`C:\Users\<usuario>\.wslconfig`),
   con red en modo espejo:

   ```ini
   [wsl2]
   networkingMode=mirrored
   ```

   En modo espejo, WSL comparte las interfaces de red del host, así que los
   puertos que el host escucha quedan visibles sin reenvíos manuales. Requiere
   reiniciar WSL: `wsl --shutdown`.

2. **Docker Desktop** como motor de contenedores (con integración de WSL2). Es
   Docker Desktop el que resuelve el nombre `host.docker.internal` dentro del
   contenedor; en un Docker Engine instalado directamente en Linux ese nombre no
   existe por defecto.

3. **`host.docker.internal`** como dirección del host en `LLM_API_BASE`. No se
   usa `localhost`: dentro del contenedor, `localhost` es el contenedor mismo.

Con esos tres elementos no hizo falta nada más: ni `OLLAMA_HOST=0.0.0.0` en el
host, ni reglas de firewall, ni `extra_hosts` en `docker-compose.yml`.

### Comprobación de alcance en tres pasos

Si la llamada al modelo falla, recorre estos tres pasos en orden; el primero que
falle dice dónde está el problema.

**1. Ollama responde en el host.** En Windows o en la shell de WSL:

```bash
ollama list
```

**2. El contenedor alcanza el puerto del host.** La imagen no trae `curl`, así
que se usa python:

```bash
docker compose exec evaluador python -c "import urllib.request; print(urllib.request.urlopen('http://host.docker.internal:11434/api/tags').read()[:200])"
```

Debe imprimir la lista de modelos en JSON. Si falla aquí, el problema es de red
del host (paso 1 o 2 de la sección anterior), no de la aplicación.

**3. La aplicación evalúa de punta a punta.**

```bash
docker compose exec evaluador python check.py
```

El modelo que aparece en el paso 2 de `check.py` debe ser el de `LLM_MODEL`. Si
dice otro, el contenedor se levantó con un `.env` viejo: recrea con
`--force-recreate`.
