#!/usr/bin/env python
"""
Pre-demo smoke check.

Run this before presenting. Verifies, in order, that gate 1 works, that the
provider configuration is complete, and that a real model call returns valid
JSON. Console output stays in Spanish, like the rest of the UI.

    docker compose run --rm evaluador python check.py
"""

import sys

from app import gate1, gate2

STORY = "Como cliente registrado quiero aplicar un cupón en el carrito para pagar menos."
CRITERIA = (
    "- Dado un carrito con un producto y un cupón vigente, cuando el cliente "
    "ingresa el código, entonces el total se reduce.\n"
    "- Dado un cupón expirado, cuando lo ingresa, entonces se muestra "
    '"Cupón expirado" y el total no cambia.'
)

GREEN, RED, GREY, RESET = "\033[92m", "\033[91m", "\033[90m", "\033[0m"


def ok(msg):
    print(f"{GREEN}  OK{RESET}  {msg}")


def fail(msg, detail=""):
    print(f"{RED}  X {RESET}  {msg}")
    if detail:
        print(f"{GREY}       {detail}{RESET}")


def main() -> int:
    print("\nVerificación del evaluador\n" + "-" * 46)

    # 1. Gate 1
    print("\n1. Compuerta 1 (determinista, sin modelo)")
    checks = gate1.run_gate1(STORY, CRITERIA)
    failed = [c.id for c in checks if not c.passed]
    if failed:
        fail("La historia de referencia no debería fallar", f"Fallaron: {failed}")
        return 1
    ok(f"{len(checks)} chequeos ejecutados sobre la historia de referencia")

    # 2. Configuration
    print("\n2. Configuración del proveedor")
    mode = "acoplado" if gate2.COUPLED_MODE else "desacoplado"
    print(f"{GREY}       modelo: {gate2.MODEL} · temperatura: {gate2.TEMPERATURE} · modo: {mode}{RESET}")
    problem = gate2.check_configuration()
    if problem:
        fail("Configuración incompleta", problem)
        return 1
    ok("Modelo y credencial configurados")

    # 3. Real call
    print("\n3. Llamada real al modelo")
    try:
        result = gate2.run_gate2(STORY, CRITERIA, gate1.summarize_for_prompt(checks))
    except gate2.EvaluationError as exc:
        fail("La llamada falló", str(exc))
        return 1

    verdict = result.get("veredicto")
    if not verdict:
        fail("El modelo respondió sin veredicto", str(result)[:200])
        return 1
    ok(f"Respuesta válida · veredicto: {verdict}")
    if result.get("resumen"):
        print(f"{GREY}       {result['resumen']}{RESET}")
    timings = " · ".join(
        f"{l['fase']} {l['ms']:.0f} ms" for l in result.get("latencias_ms", [])
    )
    print(f"{GREY}       {result.get('llamadas_modelo', 0)} llamada(s): {timings}{RESET}")
    if result.get("modelo_desobedecio"):
        print(f"{GREY}       el modelo devolvió salida que el veredicto no autorizaba{RESET}")

    print(f"\n{GREEN}Todo listo para la demo.{RESET}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
