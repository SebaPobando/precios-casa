"""Pruebas del lector de precios con HTML de ejemplo (no necesita internet).
   Ejecuta:  python test_parseo.py
"""
import monitor as m

casos = [
    # (nombre, html, url, precio esperado)
    ("json-ld mercadolibre",
     '<script type="application/ld+json">{"@type":"Product","name":"Hervidor",'
     '"offers":{"@type":"Offer","price":24990,"priceCurrency":"CLP"}}</script>',
     "https://www.mercadolibre.cl/x/up/MLCU1", 24990),
    ("meta itemprop",
     '<div><meta itemprop="price" content="1299990"></div>',
     "https://www.lg.com/cl/x", 1299990),
    ("og price ikea",
     '<meta property="product:price:amount" content="12.990">',
     "https://www.ikea.com/cl/es/p/x", 12990),
    ("andes fraction ML",
     '<span class="andes-money-amount__fraction">459.990</span>',
     "https://www.mercadolibre.cl/x", 459990),
    ("magento cannon",
     '<span data-price-amount="45990" data-price-type="finalPrice">$45.990</span>',
     "https://cannonhome.cl/x", 45990),
    ("oferta menor que precio normal",
     '<script type="application/ld+json">{"@type":"Product","offers":[{"price":"399990"},'
     '{"price":"449990"}]}</script>',
     "https://www.mi.com/cl/product/x", 399990),
    ("decimales con coma",
     '<meta itemprop="price" content="1299990,00">',
     "https://www.lg.com/cl/x", 1299990),
    ("solo texto visible",
     '<html><body><h1>Alfombra</h1><p>$89.990</p><span>$89.990</span>'
     '<small>o 12 cuotas de $7.499</small></body></html>',
     "https://tienda-rara.cl/x", 89990),
    ("ignora precios absurdos (envío gratis $0)",
     '<script type="application/ld+json">{"offers":{"price":0}}</script>'
     '<meta itemprop="price" content="34990">',
     "https://cannonhome.cl/x", 34990),
]

fallos = 0
for nombre, html, url, esperado in casos:
    obtenido, metodo = m.extraer_precio(html, url)
    ok = obtenido == esperado
    fallos += not ok
    print(f"{'OK ' if ok else 'FALLA'}  {nombre:<38} esperado={esperado:<10} obtenido={obtenido} ({metodo})")

print("\n-- conversión de números --")
for txt, esperado in [("1.299.990", 1299990), ("$ 459.990", 459990), ("24990", 24990),
                      ("1.299.990,50", 1299990.5), ("12,990.00", 12990), ("", None), ("$0", None)]:
    obtenido = m.a_numero(txt)
    ok = obtenido == esperado
    fallos += not ok
    print(f"{'OK ' if ok else 'FALLA'}  {txt!r:<18} -> {obtenido} (esperado {esperado})")

print("\nTODO OK" if not fallos else f"\n{fallos} PRUEBAS FALLARON")
raise SystemExit(1 if fallos else 0)
