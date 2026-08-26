"""Simula dos corridas completas sin tocar internet ni Telegram.
   Sirve para ver cómo se verán los mensajes.  Ejecuta: python test_simulacion.py
"""
import json, os, sys, shutil, tempfile
import monitor as m

tmp = tempfile.mkdtemp()
m.ARCHIVO_ESTADO = os.path.join(tmp, "precios.json")

precios = {}   # id -> precio que "devuelve la tienda"
enviados = []

def consultar_falso(p, sesion, usar_navegador=True):
    v = precios.get(p["id"])
    return (v, "simulado", None) if v else (None, None, "HTTP 403")

def telegram_falso(texto, silencioso=False):
    enviados.append(texto)
    print("\n" + "=" * 62 + "\nMENSAJE DE TELEGRAM\n" + "=" * 62)
    print(texto.replace("<b>", "").replace("</b>", "").replace("<i>", "").replace("</i>", ""))
    return True

m.consultar = consultar_falso
m.telegram = telegram_falso
m.time.sleep = lambda *a: None

cfg = json.load(open(m.ARCHIVO_PRODUCTOS, encoding="utf-8"))
activos = [p for p in cfg["productos"] if p["seguir"]]
precios = {p["id"]: p["precio_referencia"] or 50000 for p in activos}
del precios[activos[3]["id"]]          # uno que la tienda bloquea

sys.argv = ["monitor.py"]
print(">>> PRIMERA CORRIDA (guarda precios de partida)")
m.main()

print("\n\n>>> SEGUNDA CORRIDA (bajaron 3 productos, subió 1)")
precios[activos[0]["id"]] = int(precios[activos[0]["id"]] * 0.85)
precios[activos[5]["id"]] = int(precios[activos[5]["id"]] * 0.93)
precios[activos[13]["id"]] = int(precios[activos[13]["id"]] * 0.40)   # baja sospechosa
precios[activos[1]["id"]] = int(precios[activos[1]["id"]] * 1.06)
m.main()

print("\n\n>>> TERCERA CORRIDA (nada cambió: no debe mandar nada)")
antes = len(enviados)
m.main()
print("Mensajes enviados en la tercera corrida:", len(enviados) - antes)

shutil.rmtree(tmp)
assert len(enviados) == 2, "se esperaban exactamente 2 mensajes"
print("\nSimulación OK")
