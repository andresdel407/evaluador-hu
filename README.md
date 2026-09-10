# Evaluador de historias de usuario y criterios de aceptación

Compuerta de calidad previa a la generación automatizada de escenarios Gherkin.
Objetivo específico 2 — trabajo de grado, Maestría en Ingeniería, Universidad del Valle.

---

## Levantar

```bash
cp .env.example .env      # y pon tu clave dentro
docker compose up --build
```

Abre <http://localhost:8000>.

La carpeta `app/` está montada en caliente: editas `rubric.py` o `gate1.py`, guardas,
y el servidor recarga solo. No hay que reconstruir la imagen para iterar sobre la rúbrica.

---

## Cambiar de proveedor de LLM

Toda la interacción con el modelo pasa por [litellm](https://github.com/BerriAI/litellm),
que normaliza la interfaz de más de cien proveedores a la firma de OpenAI. El código
de la aplicación nunca sabe con quién está hablando.

Para cambiar de proveedor se editan dos líneas del `.env`:

```bash
# Anthropic
ANTHROPIC_API_KEY=sk-ant-...
LLM_MODEL=anthropic/claude-sonnet-4-5

# OpenAI
OPENAI_API_KEY=sk-...
LLM_MODEL=openai/gpt-4o

# Google
GEMINI_API_KEY=...
LLM_MODEL=gemini/gemini-2.0-flash

# Local, sin clave ni costo
LLM_MODEL=ollama/llama3.1
OLLAMA_API_BASE=http://host.docker.internal:11434
```

Esto no es una comodidad de ingeniería: es una condición metodológica. Si la tesis
sostiene que la calidad del insumo pesa más que la capacidad del modelo, hay que poder
correr la misma rúbrica sobre varios modelos y mostrarlo. Con esta capa, comparar
proveedores es cambiar una variable de entorno, no reescribir el evaluador.

---

## Arquitectura

```
entrada ─▶ Compuerta 1 ─▶ Compuerta 2 ─▶ veredicto ─▶ uno de tres carriles
           determinista    LLM sobre
           (Python puro)   la rúbrica
```

| Archivo | Responsabilidad |
|---|---|
| `app/rubric.py` | Única fuente de verdad de la rúbrica. El prompt se construye desde aquí. |
| `app/gate1.py` | Chequeos estructurales con expresiones regulares. Sin modelo. |
| `app/gate2.py` | Evaluación semántica vía litellm. `temperature=0`. |
| `app/main.py` | Orquestación y API. |
| `app/static/index.html` | Interfaz, sin paso de compilación. |
| `tests/test_gate1.py` | Pruebas de la parte determinista. |

**La compuerta 1 corre siempre y no cuesta nada.** Si el insumo no supera los chequeos
duros —falta el rol, o no hay criterios de aceptación— el flujo se detiene ahí y el
modelo nunca se invoca. Lo demás pasa como señal dentro del prompt de la compuerta 2,
para no repetir trabajo ni contradecirla.

**La rúbrica está codificada como estructura, no como sugerencia.** El esquema JSON
obliga a que cada falla se clasifique como `redaccion` o `informacion`, y a que la
complementación venga vacía cuando hay una falla de información. El modelo no puede
devolver una respuesta bien formada y a la vez inventar un criterio de aceptación.

---

## Los tres carriles

| Veredicto | Qué significa | Qué hace el sistema |
|---|---|---|
| `rechazo_redaccion` | La información está, mal expresada | Reescribe usando solo lo que ya estaba |
| `rechazo_informacion` | Falta conocimiento de negocio | **Se detiene** y devuelve preguntas al PO |
| `aprobado` | Insumo derivable | Continúa hacia la generación de Gherkin |

El segundo carril es el punto del diseño. Un modelo sin esa restricción produciría un
criterio de aceptación plausible pero inventado, que se convertiría en escenario, luego
en prueba, y la prueba pasaría — dejando una prueba verde que valida un comportamiento
que nadie pidió.

---

## Pruebas

```bash
docker compose run --rm evaluador python -m pytest tests/ -q
```

o en local, con el entorno ya creado:

```bash
python -m pytest tests/ -q
```

---

## Endpoints

| Método | Ruta | Uso |
|---|---|---|
| `GET` | `/api/salud` | Modelo y temperatura en uso |
| `GET` | `/api/rubrica` | Rúbrica vigente, con fuente de cada criterio |
| `POST` | `/api/evaluar` | `{"historia": "...", "criterios": "..."}` |

Documentación interactiva en `/docs`.

---

## Limitaciones conocidas

- La compuerta 1 usa patrones para español e inglés. Historias en otros idiomas
  fallarán los chequeos estructurales aunque estén bien escritas.
- El criterio `conflict_free` se evalúa dentro de una sola historia. QUS lo define
  sobre el conjunto del backlog; esa versión requeriría comparación entre historias.
- No hay persistencia. Cada evaluación es independiente. Para los experimentos de
  validación habrá que agregar almacenamiento de resultados.
- La cobertura de caminos depende de que el modelo reconozca qué caminos son
  relevantes en el dominio, lo cual es precisamente lo que la rúbrica asume que
  puede fallar. Es el criterio que más necesita validación contra juicio humano.

---

## Referencias de la rúbrica

- Lucassen, Dalpiaz, van der Werf & Brinkkemper (2016). *Improving agile requirements:
  the Quality User Story framework and tool.* Requirements Engineering 21(3), 383–403.
- Ferreira, Rodrigues da Silva & Paiva (2022). *Towards the Art of Writing Agile
  Requirements with User Stories, Acceptance Criteria, and Related Constructs.* ENASE.
- Zhang, Rayhan, Herda, Goericke & Nass (2024). *LLM-based agents for automating the
  enhancement of user story quality.* arXiv:2403.09442.
- Ronanki et al. (2024). Evaluación de calidad de historias de usuario con ChatGPT.
- ISO/IEC/IEEE 29148 — características de calidad de requisitos.
# evaluador-hu
