#!/usr/bin/env python3
"""
Monitor de precios -> alertas por Telegram.

Uso:
    python monitor.py                 # revisa precios y avisa por Telegram si algo bajó
    python monitor.py --check         # solo muestra los precios en pantalla, no avisa ni guarda
    python monitor.py --test-telegram # manda un mensaje de prueba
    python monitor.py --solo lavaplatos,microondas   # revisa solo esos productos

Config por variables de entorno:
    TELEGRAM_TOKEN    token del bot (de @BotFather)
    TELEGRAM_CHAT_ID  tu chat id
"""

import argparse
import json
import os
import random
import re
import sys
import time
from datetime import datetime, timezone, timedelta
from urllib.parse import urlsplit

import requests

RAIZ = os.path.dirname(os.path.abspath(__file__))
ARCHIVO_PRODUCTOS = os.path.join(RAIZ, "productos.json")
ARCHIVO_ESTADO = os.path.join(RAIZ, "precios.json")

TZ_CL = timezone(timedelta(hours=-4))

# --- Reglas de alerta -------------------------------------------------------
# Avisar con cualquier baja respecto al último precio visto.
# Súbelo a 5 si quieres filtrar bajas chicas (ej. 5 = solo bajas de 5% o más).
BAJA_MINIMA_PCT = 0.0
# Precios fuera de este rango se consideran error de lectura y se descartan.
PRECIO_MIN_VALIDO = 1_000
PRECIO_MAX_VALIDO = 20_000_000
# Una caída mayor a esto se marca como "verificar" (suele ser el precio de una cuota).
CAIDA_SOSPECHOSA_PCT = 55.0

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "es-CL,es;q=0.9,en;q=0.8",
    "Cache-Control": "no-cache",
}


# --- Utilidades -------------------------------------------------------------
def clp(n):
    if n is None:
        return "—"
    return "$" + f"{int(round(n)):,}".replace(",", ".")


def ahora():
    return datetime.now(TZ_CL)


def a_numero(txt):
    """Convierte '1.299.990', '1299990', '1.299.990,50' o '1299990.50' a float CLP."""
    if txt is None:
        return None
    s = str(txt).strip().replace("$", "").replace("\xa0", " ").replace(" ", "")
    s = re.sub(r"[^\d.,]", "", s)
    if not s:
        return None
    if "," in s and "." in s:
        # el separador decimal es el que aparece más a la derecha
        s = s.replace(".", "") if s.rfind(",") > s.rfind(".") else s.replace(",", "")
        s = s.replace(",", ".")
    elif "," in s:
        ent, _, dec = s.rpartition(",")
        s = f"{ent.replace(',', '')}.{dec}" if len(dec) == 2 and ent else s.replace(",", "")
    elif "." in s:
        ent, _, dec = s.rpartition(".")
        if not (len(dec) == 2 and ent and len(ent.replace(".", "")) <= 3):
            s = s.replace(".", "")
    try:
        v = float(s)
    except ValueError:
        return None
    return v if v > 0 else None


def valido(v):
    return v is not None and PRECIO_MIN_VALIDO <= v <= PRECIO_MAX_VALIDO


def dominio(url):
    return urlsplit(url).netloc.lower().replace("www.", "")


# --- Extracción de precio ---------------------------------------------------
def _de_json_ld(html):
    """Precios declarados en schema.org (lo usan casi todas las tiendas serias)."""
    encontrados = []

    def hurgar(nodo):
        if isinstance(nodo, dict):
            for clave in ("price", "lowPrice", "highPrice"):
                if clave in nodo:
                    v = a_numero(nodo[clave])
                    if valido(v):
                        encontrados.append(v)
            for v in nodo.values():
                hurgar(v)
        elif isinstance(nodo, list):
            for v in nodo:
                hurgar(v)

    for bloque in re.findall(
        r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        html, re.S | re.I,
    ):
        texto = bloque.strip()
        for intento in (texto, re.sub(r",\s*([}\]])", r"\1", texto)):
            try:
                hurgar(json.loads(intento))
                break
            except Exception:
                continue
    return min(encontrados) if encontrados else None


def _de_meta(html):
    patrones = [
        r'<meta[^>]+itemprop=["\']price["\'][^>]+content=["\']([^"\']+)["\']',
        r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+itemprop=["\']price["\']',
        r'<meta[^>]+property=["\']product:price:amount["\'][^>]+content=["\']([^"\']+)["\']',
        r'<meta[^>]+property=["\']og:price:amount["\'][^>]+content=["\']([^"\']+)["\']',
        r'<meta[^>]+name=["\']twitter:data1["\'][^>]+content=["\']([^"\']+)["\']',
    ]
    for p in patrones:
        for m in re.finditer(p, html, re.I):
            v = a_numero(m.group(1))
            if valido(v):
                return v
    return None


def _de_reglas_tienda(html, url):
    d = dominio(url)
    reglas = {
        "mercadolibre.cl": [
            r'"price"\s*:\s*([0-9]+(?:\.[0-9]+)?)\s*,',
            r'andes-money-amount__fraction[^>]*>([\d.,]+)<',
        ],
        "ikea.com": [
            r'data-price=["\']([\d.,]+)["\']',
            r'pip-temp-price__integer["\'][^>]*>\s*([\d.,]+)',
            r'"price"\s*:\s*"?([\d.,]+)"?',
        ],
        "cannonhome.cl": [
            r'data-price-amount=["\']([\d.,]+)["\']',
            r'"finalPrice"[^}]*?"amount"\s*:\s*([\d.,]+)',
        ],
        "mi.com": [
            r'"salePrice"\s*:\s*"?([\d.,]+)"?',
            r'"price"\s*:\s*"?([\d.,]+)"?',
        ],
        "lg.com": [
            r'"finalPrice"\s*:\s*"?([\d.,]+)"?',
            r'"price"\s*:\s*"?([\d.,]+)"?',
        ],
    }
    candidatos = []
    for p in reglas.get(d, []) + [r'itemprop=["\']price["\'][^>]*content=["\']([\d.,]+)["\']']:
        for m in re.finditer(p, html, re.I):
            v = a_numero(m.group(1))
            if valido(v):
                candidatos.append(v)
        if candidatos:
            # dentro de una misma regla, el precio de venta es el menor (vs. precio normal tachado)
            return min(candidatos)
    return None


def _de_texto(html):
    """Último recurso: el signo peso en el HTML visible."""
    limpio = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html, flags=re.S | re.I)
    limpio = re.sub(r"<[^>]+>", " ", limpio)
    valores = []
    for m in re.finditer(r"\$\s?([\d][\d.\s]{3,12})(?!\s*(?:x|cuotas))", limpio, re.I):
        v = a_numero(m.group(1))
        if valido(v):
            valores.append(v)
    if not valores:
        return None
    # el precio del producto suele ser el que más se repite en la página
    return max(set(valores), key=valores.count)


def extraer_precio(html, url):
    for extractor in (_de_json_ld, _de_meta, _de_reglas_tienda, _de_texto):
        try:
            v = extractor(html, url) if extractor in (_de_reglas_tienda,) else extractor(html)
        except Exception:
            v = None
        if valido(v):
            return v, extractor.__name__.lstrip("_")
    return None, None


# --- Descarga ---------------------------------------------------------------
def bajar_html(url, sesion, intentos=3):
    ultimo = ""
    for i in range(intentos):
        try:
            r = sesion.get(url, headers=HEADERS, timeout=30)
            if r.status_code == 200 and len(r.text) > 500:
                return r.text, None
            ultimo = f"HTTP {r.status_code}"
        except Exception as e:
            ultimo = f"{type(e).__name__}"
        time.sleep(2 + i * 3 + random.random())
    return None, ultimo


def bajar_con_navegador(url):
    """Fallback para tiendas que bloquean o cargan el precio con JavaScript."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return None, "playwright no instalado"
    try:
        with sync_playwright() as p:
            navegador = p.chromium.launch(args=["--no-sandbox", "--disable-blink-features=AutomationControlled"])
            ctx = navegador.new_context(
                user_agent=HEADERS["User-Agent"],
                locale="es-CL",
                viewport={"width": 1366, "height": 900},
            )
            pagina = ctx.new_page()
            pagina.goto(url, wait_until="domcontentloaded", timeout=45000)
            try:
                pagina.wait_for_timeout(3500)
            except Exception:
                pass
            html = pagina.content()
            navegador.close()
            return html, None
    except Exception as e:
        return None, f"navegador: {type(e).__name__}"


def consultar(producto, sesion, usar_navegador=True):
    url = producto["url"]
    html, err = bajar_html(url, sesion)
    precio, metodo = extraer_precio(html, url) if html else (None, None)
    if precio is None and usar_navegador:
        html2, err2 = bajar_con_navegador(url)
        if html2:
            precio, metodo = extraer_precio(html2, url)
            if precio is not None:
                metodo = (metodo or "?") + "+navegador"
            else:
                err = "precio no encontrado en la página"
        else:
            err = err or err2
    elif precio is None and html:
        err = "precio no encontrado en la página"
    return precio, metodo, (None if precio else (err or "sin respuesta"))


# --- Estado -----------------------------------------------------------------
def cargar(ruta, defecto):
    if os.path.exists(ruta):
        with open(ruta, encoding="utf-8") as f:
            return json.load(f)
    return defecto


def guardar(ruta, datos):
    with open(ruta, "w", encoding="utf-8") as f:
        json.dump(datos, f, ensure_ascii=False, indent=2)


# --- Telegram ---------------------------------------------------------------
def telegram(texto, silencioso=False):
    token = os.environ.get("TELEGRAM_TOKEN", "").strip()
    chat = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat:
        print("!! Falta TELEGRAM_TOKEN o TELEGRAM_CHAT_ID; el mensaje no se envió.\n")
        print(texto)
        return False
    for trozo in [texto[i:i + 3900] for i in range(0, len(texto), 3900)] or [texto]:
        r = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={
                "chat_id": chat,
                "text": trozo,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
                "disable_notification": silencioso,
            },
            timeout=30,
        )
        if not r.ok:
            print("!! Telegram respondió:", r.status_code, r.text[:300])
            return False
    return True


def escapar(s):
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


# --- Programa ---------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="solo mostrar precios, no avisar ni guardar")
    ap.add_argument("--test-telegram", action="store_true", help="mandar un mensaje de prueba")
    ap.add_argument("--solo", default="", help="ids de productos separados por coma")
    ap.add_argument("--sin-navegador", action="store_true", help="no usar Playwright como respaldo")
    args = ap.parse_args()

    if args.test_telegram:
        ok = telegram("✅ Listo, el bot de precios quedó conectado.")
        print("Enviado." if ok else "No se pudo enviar.")
        return 0 if ok else 1

    cfg = cargar(ARCHIVO_PRODUCTOS, {"productos": []})
    productos = [p for p in cfg["productos"] if p.get("seguir") and p.get("url")]
    if args.solo:
        pedidos = {s.strip() for s in args.solo.split(",") if s.strip()}
        productos = [p for p in productos if p["id"] in pedidos]

    estado = cargar(ARCHIVO_ESTADO, {"productos": {}})
    guardados = estado.setdefault("productos", {})
    primera_vez = not guardados

    bajadas, subidas, fallos, leidos = [], [], [], []
    sesion = requests.Session()

    for i, p in enumerate(productos, 1):
        precio, metodo, err = consultar(p, sesion, usar_navegador=not args.sin_navegador)
        prev = guardados.get(p["id"], {})
        anterior = prev.get("precio")
        print(f"[{i:2}/{len(productos)}] {p['nombre'][:32]:<32} {clp(precio):>12}"
              f"  (antes {clp(anterior)})  {metodo or err}")

        if precio is None:
            fallos.append((p, err))
            if not args.check:
                prev["fallos_seguidos"] = prev.get("fallos_seguidos", 0) + 1
                prev["ultimo_error"] = err
                guardados[p["id"]] = prev
            continue

        leidos.append((p, precio, anterior))

        if anterior and precio < anterior:
            pct = (anterior - precio) / anterior * 100
            if pct >= BAJA_MINIMA_PCT:
                bajadas.append((p, precio, anterior, pct, pct >= CAIDA_SOSPECHOSA_PCT))
        elif anterior and precio > anterior:
            subidas.append((p, precio, anterior))

        if not args.check:
            historial = prev.get("historial", [])
            if not historial or historial[-1][1] != precio:
                historial.append([ahora().strftime("%Y-%m-%d %H:%M"), precio])
            minimo = prev.get("minimo")
            guardados[p["id"]] = {
                "nombre": p["nombre"],
                "precio": precio,
                "visto": ahora().strftime("%Y-%m-%d %H:%M"),
                "minimo": precio if not minimo else min(minimo, precio),
                "minimo_fecha": ahora().strftime("%Y-%m-%d") if (not minimo or precio < minimo)
                                else prev.get("minimo_fecha"),
                "metodo": metodo,
                "fallos_seguidos": 0,
                "historial": historial[-200:],
            }
        time.sleep(1.5 + random.random())

    if args.check:
        print(f"\n{len(leidos)} leídos, {len(fallos)} con problemas. (--check no guarda ni avisa)")
        return 0

    estado["actualizado"] = ahora().strftime("%Y-%m-%d %H:%M")
    guardar(ARCHIVO_ESTADO, estado)

    # --- armar el mensaje ---
    if primera_vez:
        lineas = [f"🏠 <b>Monitor de precios activado</b>",
                  f"Guardé el precio de partida de {len(leidos)} productos. "
                  f"Desde ahora te aviso apenas alguno baje.\n"]
        for p, precio, _ in sorted(leidos, key=lambda x: -x[1]):
            ref = p.get("precio_referencia")
            marca = ""
            if ref:
                dif = precio - ref
                marca = f"  ({'+' if dif > 0 else ''}{clp(dif)} vs Excel)" if abs(dif) > ref * 0.02 else "  (≈ Excel)"
            lineas.append(f"• {escapar(p['nombre'])}: <b>{clp(precio)}</b>{marca}")
        total = sum(x[1] for x in leidos)
        lineas.append(f"\n<b>Total de lo leído hoy: {clp(total)}</b>")
        if fallos:
            lineas.append(f"\n⚠️ No pude leer {len(fallos)}: " +
                          ", ".join(escapar(p['nombre']) for p, _ in fallos))
        telegram("\n".join(lineas))
        return 0

    if not bajadas:
        # sin novedades: no molestamos con un mensaje
        print("\nSin bajas de precio en esta corrida.")
        problemas = [(p, e) for p, e in fallos
                     if guardados.get(p["id"], {}).get("fallos_seguidos", 0) == 4]
        if problemas:
            telegram("⚠️ Llevo 4 revisiones sin poder leer el precio de:\n" +
                     "\n".join(f'• <a href="{escapar(p["url"])}">{escapar(p["nombre"])}</a> — {escapar(e)}'
                               for p, e in problemas) +
                     "\n\nQuizás cambió el link en productos.json.", silencioso=True)
        return 0

    total_ahorro = sum(a - n for _, n, a, _, _ in bajadas)
    titulo = "🔻 <b>¡Bajó de precio!</b>" if len(bajadas) == 1 else \
             f"🔻 <b>{len(bajadas)} productos bajaron de precio</b>"
    lineas = [titulo, ""]
    for p, precio, anterior, pct, raro in sorted(bajadas, key=lambda x: -x[3]):
        est = guardados.get(p["id"], {})
        lineas.append(f'<b><a href="{escapar(p["url"])}">{escapar(p["nombre"])}</a></b> · {escapar(p["tienda"])}')
        lineas.append(f"{clp(anterior)} → <b>{clp(precio)}</b>  (−{pct:.0f}%, {clp(anterior - precio)} menos)")
        detalles = []
        if est.get("minimo") == precio:
            detalles.append("🏅 es el precio más bajo que le he visto")
        ref = p.get("precio_referencia")
        if ref and precio <= ref:
            detalles.append(f"✅ bajo tu presupuesto de {clp(ref)}")
        if raro:
            detalles.append("⚠️ baja muy grande, confirma en la página (puede ser el valor de una cuota)")
        if detalles:
            lineas.append("   " + "\n   ".join(detalles))
        lineas.append("")
    if len(bajadas) > 1:
        lineas.append(f"<b>Ahorro total si compras todo hoy: {clp(total_ahorro)}</b>")
    if subidas:
        lineas.append(f"\n<i>Subieron: " +
                      ", ".join(f"{escapar(p['nombre'])} {clp(a)}→{clp(n)}" for p, n, a in subidas[:6]) + "</i>")
    telegram("\n".join(lineas))
    return 0


if __name__ == "__main__":
    sys.exit(main())
