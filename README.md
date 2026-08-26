# Monitor de precios 🏠

Revisa 2 veces al día los 26 productos de tu Excel de la casa y te manda un mensaje
de Telegram apenas alguno baje de precio. Corre solo en GitHub Actions (gratis),
así que funciona aunque tengas el computador apagado.

---

## Paso 1 — Crear el bot de Telegram (3 minutos)

1. Abre Telegram y busca **@BotFather** (el verificado, con el tick azul).
2. Escríbele `/newbot`.
3. Te pide un nombre → escribe algo como `Precios Casa`.
4. Te pide un username → tiene que terminar en `bot`, por ejemplo `precios_casa_seba_bot`.
5. Te responde con un **token** así:
   `7712345678:AAH8xY-abcdefGHIJKLmnopQRSTuvwx1234`
   👉 **Guárdalo, es la llave del bot.** No lo publiques en ningún lado.

## Paso 2 — Sacar tu chat_id

1. Busca en Telegram el bot que acabas de crear (por su username) y mándale un `hola`.
   *(Este paso es obligatorio: un bot no puede escribirte primero.)*
2. Abre esta dirección en el navegador, reemplazando `TU_TOKEN`:

   ```
   https://api.telegram.org/botTU_TOKEN/getUpdates
   ```

3. Busca en el texto que aparece algo como `"chat":{"id":987654321,`
   👉 Ese número es tu **chat_id**.

   *Si sale `{"ok":true,"result":[]}` es que no le escribiste al bot todavía — manda
   el mensaje y recarga.*

> **Tip:** si prefieres que los avisos lleguen a un grupo (por ejemplo con tu pareja),
> crea el grupo, agrega el bot, manda un mensaje ahí y repite el paso 2. El id del
> grupo es negativo, tipo `-1001234567890`. Cópialo con el signo menos incluido.

## Paso 3 — Subir esto a GitHub

1. Entra a <https://github.com/new>, ponle nombre (ej. `precios-casa`) y créalo
   **privado**.
2. En la página del repo vacío: **uploading an existing file** → arrastra **todos**
   los archivos de esta carpeta (incluida la carpeta oculta `.github`).

   *Si `.github` no se sube arrastrando, es más fácil desde la terminal:*

   ```bash
   cd precio-alertas
   git init && git add . && git commit -m "monitor de precios"
   git branch -M main
   git remote add origin https://github.com/TU_USUARIO/precios-casa.git
   git push -u origin main
   ```

3. En el repo → **Settings** → **Secrets and variables** → **Actions** →
   **New repository secret**. Crea estos dos:

   | Name               | Secret                      |
   |--------------------|-----------------------------|
   | `TELEGRAM_TOKEN`   | el token del paso 1         |
   | `TELEGRAM_CHAT_ID` | el número del paso 2        |

4. En **Settings** → **Actions** → **General** → abajo en *Workflow permissions*,
   marca **Read and write permissions** y guarda.
   *(Es para que el bot pueda ir guardando el historial de precios en el repo.)*

## Paso 4 — Probarlo

Anda a la pestaña **Actions** → **Revisar precios** → botón **Run workflow**.

En 2–3 minutos te debería llegar el primer mensaje con el precio actual de todo.
Ese mensaje es la línea de base: de ahí en adelante solo te escribe cuando algo baja.

Listo. Corre solo a las **09:00 y 21:00** de Chile.

---

## Cómo funciona

- `productos.json` — la lista sacada de tu Excel: nombre, link, tienda y el precio
  que anotaste como referencia.
- `monitor.py` — entra a cada link, lee el precio y lo compara con el de la última
  revisión.
- `precios.json` — se crea solo. Guarda el precio actual, el mínimo histórico y
  todo el historial de cada producto.
- `.github/workflows/monitor.yml` — el reloj: cuándo corre y con qué secretos.

Para leer el precio prueba, en orden: los datos estructurados de la página
(schema.org), las etiquetas `meta`, reglas específicas por tienda, y por último el
texto visible. Si la tienda bloquea el pedido simple, reintenta abriendo la página
con un navegador real (Chromium) — eso resuelve la mayoría de los bloqueos y las
páginas que cargan el precio con JavaScript.

## Cambiar cosas

**Agregar un producto:** copia un bloque en `productos.json` y edítalo.

```json
{
  "id": "tostador",
  "nombre": "Tostador",
  "tienda": "MercadoLibre",
  "url": "https://www.mercadolibre.cl/...",
  "precio_referencia": 30000,
  "seguir": true,
  "nota": ""
}
```

**Dejar de seguir algo:** ponle `"seguir": false`.

**Cambiar el horario:** edita las líneas `cron` en `.github/workflows/monitor.yml`.
Están en UTC, que es Chile + 4 horas en invierno (+3 en verano, así que en verano
los avisos llegan una hora antes; si te molesta, corre las horas ahí).

**Avisar solo con bajas grandes:** en `monitor.py`, cambia
`BAJA_MINIMA_PCT = 0.0` por `5.0` (avisa solo si baja 5% o más).

## Probarlo en tu computador

```bash
pip install -r requirements.txt
playwright install chromium

export TELEGRAM_TOKEN="..."
export TELEGRAM_CHAT_ID="..."

python monitor.py --test-telegram          # ¿llega el mensaje?
python monitor.py --check                  # muestra precios, no avisa ni guarda
python monitor.py --solo hervidor,alfombra # revisa solo esos
python monitor.py                          # corrida real
```

Pruebas incluidas (no necesitan internet):

```bash
python test_parseo.py       # que lea bien los precios
python test_simulacion.py   # cómo se ven los mensajes
```

## Si algo falla

**"No pude leer" un producto.** Casi siempre el link cambió o la tienda cambió su
página. Abre el link a mano; si ya no existe, actualízalo en `productos.json`.
Si un producto falla 4 revisiones seguidas te llega un aviso silencioso.

**MercadoLibre a veces bloquea.** Es la más quisquillosa con los servidores de
GitHub. El respaldo con navegador lo resuelve casi siempre; si un producto
específico falla seguido, prueba con el link corto del producto (sin nada después
del `?`).

**Aviso con "⚠️ baja muy grande".** Significa que leyó un precio menos de la mitad
del anterior. A veces es real (liquidación), pero a veces leyó el valor de una
cuota. Confirma en la página antes de correr a comprar.

**Precios con descuento por medio de pago.** El monitor lee el precio de lista;
los descuentos de tarjeta o los cupones que se aplican en el carro no los ve.

## Notas sobre tu lista

- **Mesa de comedor** y **Sillas de comedor** (Mamá Compra) y **Cortinas/Rollers**
  (aún por ver) quedaron en la lista pero sin seguimiento, porque no tenían link.
  Cuando tengas el link, pégalo y cambia `"seguir": true`.
- **Veladores** y **Sofá** tenían dos tiendas anotadas; quedó solo el link que
  estaba en la celda. Si quieres seguir los dos, duplica el bloque con otro `id`.
- A los links les saqué los códigos de publicidad (`gclid`, `utm_...`) porque
  vencen. En los de MercadoLibre dejé el `pdp_filters`, que es el que apunta a la
  oferta concreta que elegiste y no a otro vendedor.
