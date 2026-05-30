# ════════════════════════════════════════════════════
#  Proyecto Final Circuitos DC 2026-1
#  Daniel Polanco & Juan Perdomo – USCO
#  main.py  –  MicroPython para ESP32
# ════════════════════════════════════════════════════
#
#  Hardware:
#    - PT100 + Puente de Wheatstone + AD620
#    - Salida del AD620: 0 a 3.1 V  →  0 a 100 °C
#    - Pin ADC: GPIO32 (ADC1, no interfiere con WiFi)
#
#  Flujo:
#    1. Conectar WiFi
#    2. Sincronizar hora real con NTP (internet)
#    3. Leer ADC → convertir a temperatura
#    4. Enviar { "temperatura": xx.x,
#                "fecha": "2026-05-28",
#                "hora": "14:35:22",
#                "timestamp_ms": xxxxxx }
#       a Firebase RTDB via HTTP PATCH
#    5. Esperar INTERVALO_S segundos y repetir
# ════════════════════════════════════════════════════

import network
import urequests
import ujson
import time
import ntptime
import utime
from machine import ADC, Pin

# ── Configuración WiFi ────────────────────────────
WIFI_SSID     = 'Juancamiloperdomo'       # <-- Cambia aquí
WIFI_PASSWORD = 'Juancamilo1208'  # <-- Cambia aquí

# ── Configuración Firebase ────────────────────────
FIREBASE_URL = 'https://project-dc-pt100-default-rtdb.firebaseio.com/sensor.json'

# ── Configuración ADC ─────────────────────────────
ADC_PIN    = 32
ADC_MAX    = 4095   # Resolución 12 bits
VOLT_MAX   = 3.3    # Voltaje máximo de salida del AD620 (RG=270Ω)
TEMP_MIN   = 0.0    # °C a 0 V
TEMP_MAX   = 100.0  # °C a 3.3V

# ── Zona horaria Colombia (UTC-5) ─────────────────
UTC_OFFSET = -5 * 3600   # Colombia = UTC-5

# ── Intervalo de envío ────────────────────────────
INTERVALO_S = 1     # Segundos entre cada envío

# ════════════════════════════════════════════════════
#  INICIALIZAR ADC
# ════════════════════════════════════════════════════
adc = ADC(Pin(ADC_PIN))
adc.atten(ADC.ATTN_11DB)    # Rango: 0 – 3.3 V
adc.width(ADC.WIDTH_12BIT)  # Resolución: 12 bits

# ════════════════════════════════════════════════════
#  CONECTAR WiFi
# ════════════════════════════════════════════════════
def conectar_wifi():
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    if not wlan.isconnected():
        print('[WiFi] Conectando a', WIFI_SSID, '...')
        wlan.connect(WIFI_SSID, WIFI_PASSWORD)
        intentos = 0
        while not wlan.isconnected():
            time.sleep(0.5)
            intentos += 1
            if intentos > 40:  # 20 segundos máximo
                print('[WiFi] No se pudo conectar.')
                return False
    print('[WiFi] Conectado. IP:', wlan.ifconfig()[0])
    return True

# ════════════════════════════════════════════════════
#  SINCRONIZAR HORA NTP
# ════════════════════════════════════════════════════
def sincronizar_ntp():
    try:
        ntptime.host = 'pool.ntp.org'
        ntptime.settime()  # Sincroniza el reloj interno del ESP32
        print('[NTP] Hora sincronizada correctamente.')
        return True
    except Exception as e:
        print('[NTP] Error al sincronizar:', e)
        return False

# ════════════════════════════════════════════════════
#  OBTENER FECHA Y HORA ACTUAL (Colombia UTC-5)
# ════════════════════════════════════════════════════
def obtener_datetime():
    # time.time() devuelve segundos desde epoch (UTC)
    t = time.time() + UTC_OFFSET
    tm = time.localtime(t)
    fecha = '{:04d}-{:02d}-{:02d}'.format(tm[0], tm[1], tm[2])
    hora  = '{:02d}:{:02d}:{:02d}'.format(tm[3], tm[4], tm[5])
    return fecha, hora, t * 1000  # timestamp en ms

# ════════════════════════════════════════════════════
#  LEER TEMPERATURA
# ════════════════════════════════════════════════════
def leer_temperatura():
    # Promedio de 5 lecturas para reducir ruido
    suma = 0
    for _ in range(5):
        suma += adc.read()
        time.sleep_ms(2)  # 5 × 2ms = 10ms total (antes 10 × 5ms = 50ms)
    raw = suma / 5

    # Convertir ADC → Voltaje → Temperatura
    voltaje     = (raw / ADC_MAX) * VOLT_MAX
    temperatura = (voltaje / VOLT_MAX) * (TEMP_MAX - TEMP_MIN) + TEMP_MIN
    return round(temperatura, 2)

# ════════════════════════════════════════════════════
#  ENVIAR A FIREBASE
# ════════════════════════════════════════════════════
def enviar_firebase(temperatura, fecha, hora, timestamp_ms):
    payload = ujson.dumps({
        'temperatura' : temperatura,
        'fecha'       : fecha,       # "2026-05-28"
        'hora'        : hora,        # "14:35:22"  (Colombia UTC-5, via NTP)
        'timestamp_ms': int(timestamp_ms)
    })
    headers = {'Content-Type': 'application/json'}
    try:
        resp = urequests.patch(FIREBASE_URL, data=payload, headers=headers)
        print('[Firebase] {} {} -> {:.2f}C | Status: {}'.format(
            fecha, hora, temperatura, resp.status_code))
        resp.close()
        return True
    except Exception as e:
        print('[Firebase] Error al enviar:', e)
        return False

# ════════════════════════════════════════════════════
#  PROGRAMA PRINCIPAL
# ════════════════════════════════════════════════════
def main():
    if not conectar_wifi():
        print('[ERROR] Sin WiFi. Reinicia la ESP32.')
        return

    # Sincronizar hora — reintentar hasta 3 veces
    for intento in range(3):
        if sincronizar_ntp():
            break
        print('[NTP] Reintentando... ({}/3)'.format(intento + 1))
        time.sleep(2)

    while True:
        inicio = utime.ticks_ms()

        temp               = leer_temperatura()
        fecha, hora, ts_ms = obtener_datetime()

        print('[ADC] Temperatura: {:.2f} °C'.format(temp))

        enviar_firebase(temp, fecha, hora, ts_ms)

        # Descontar el tiempo que tardó el ciclo para mantener 1s exacto
        transcurrido = utime.ticks_diff(utime.ticks_ms(), inicio)
        pausa = max(0, INTERVALO_S * 1000 - transcurrido)
        time.sleep_ms(pausa)

# ── Arranque ──────────────────────────────────────
main()
