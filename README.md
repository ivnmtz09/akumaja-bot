<div align="center">

# 🌊 Akumaja Bot

**Tu asistente académico para la Plataforma Virtual Akumaja de la Universidad de La Guajira**

Consulta tus materias, entregas pendientes y recibe alertas automáticas directo en Telegram.

[![Bot de Telegram](https://img.shields.io/badge/Telegram-@akumaja__ivan__bot-2CA5E0?style=for-the-badge&logo=telegram&logoColor=white)](https://t.me/akumaja_ivan_bot)
[![Python](https://img.shields.io/badge/Python-3.10+-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://python.org)

<img src="data/images/qr.png" alt="QR Code - Akumaja Bot" width="220"/>

**Escanea el QR o haz clic en el botón para abrir el bot → [@akumaja_ivan_bot](https://t.me/akumaja_ivan_bot)**

</div>

---

## 📋 Tabla de Contenidos

- [¿Qué es Akumaja Bot?](#-qué-es-akumaja-bot)
- [Funcionalidades](#-funcionalidades)
- [Arquitectura](#-arquitectura)
- [Facultades Soportadas](#-facultades-soportadas)
- [Instalación](#-instalación)
- [Configuración](#-configuración)
- [Uso](#-uso)
- [Despliegue en Producción (Oracle Cloud + systemd)](#-despliegue-en-producción-oracle-cloud--systemd)
- [Problemas Resueltos](#-problemas-resueltos)
- [Estructura del Proyecto](#-estructura-del-proyecto)
- [Pruebas](#-pruebas)
- [Backup y Seguridad](#-backup-y-seguridad)


---

## 🤔 ¿Qué es Akumaja Bot?

Akumaja Bot es un bot de Telegram **multiusuario** que se conecta a las plataformas Moodle de la Universidad de La Guajira (Uniguajira). Usa **web scraping avanzado** sobre los endpoints AJAX internos de Moodle para extraer información académica en tiempo real.

Cada usuario conecta su propia cuenta institucional de forma segura (las contraseñas se cifran con **AES-256 / Fernet**) y recibe:

- 📚 Listado de materias inscritas con enlaces directos al aula virtual
- 📅 Calendario de entregas y actividades pendientes con urgencia visual
- 🔔 Alertas automáticas de entregas próximas, tareas vencidas y material nuevo
- 📄 Búsqueda profunda de recursos dentro de cada curso (PDFs, foros, tareas)

---

## ⚡ Funcionalidades

| Comando | Descripción |
|---|---|
| `/start` | Bienvenida y menú principal adaptado a tu estado de sesión |
| `/login` | Conecta tu cuenta Moodle: elige facultad → usuario → contraseña |
| `/cursos` | Lista tus materias inscritas con enlaces directos a Moodle |
| `/tareas` | Entregas y actividades pendientes (próximos 30 días) con badge de urgencia |
| `/notificaciones` | Centro de novedades: vencimientos + material nuevo en cursos |
| `/cuenta` | Tu perfil: usuario, facultad, servidor, materias, estado del bot |
| `/cambiar_facultad` | Migra tu cuenta a otra facultad sin perder sesión |
| `/logout` | Cierra sesión y elimina tus datos del bot de forma segura |
| `/estado` | Estado del servicio y usuarios conectados |
| `/ayuda` | Guía de comandos detallada |

### 🔔 Monitoreo Automático

El bot revisa periódicamente (configurable, por defecto cada 3 horas entre 6:00 AM y 11:59 PM) las cuentas de todos los usuarios conectados y envía alertas de:

- ⏰ **Entregas próximas** — actividades que vencen en las próximas 24 horas
- 🚨 **Tareas vencidas** — entregas que pasaron su fecha límite (últimas 24h)
- 📄 **Material nuevo** — recursos subidos recientemente a los cursos (últimas 6h)

Cada notificación tiene **deduplicación por usuario**: nunca recibirás el mismo aviso dos veces.

### 🔍 Búsqueda Profunda en Cursos

A diferencia de solo consultar el calendario, el bot **entra curso por curso** usando el endpoint `core_course_get_course_contents` y analiza los módulos internos buscando:
- Nuevos PDFs y archivos subidos
- Foros con actividad reciente
- Tareas y actividades que los profesores agregan sin fecha en el calendario

---

## 🏗 Arquitectura

```
┌─────────────────────────────────────────────────────────┐
│                    Telegram Bot API                      │
│              (python-telegram-bot v22.8)                 │
└─────────────────┬───────────────────────────────────────┘
                  │
┌─────────────────▼───────────────────────────────────────┐
│  bot.py — Orquestador Principal                         │
│  • Registro de handlers y comandos                      │
│  • Job queue para monitoreo automático                  │
│  • Timeouts de red configurados (30s)                   │
└─────────────────┬───────────────────────────────────────┘
                  │
     ┌────────────┼────────────────┐
     ▼            ▼                ▼
┌─────────┐ ┌──────────┐ ┌────────────────┐
│ Handlers│ │ Services │ │   Moodle API   │
│─────────│ │──────────│ │────────────────│
│general  │ │accounts  │ │api.py          │
│courses  │ │monitor   │ │ • cloudscraper │
│login    │ │notifs    │ │ • Anti-WAF     │
│faculty  │ │          │ │ • Rate limit   │
│ui.py    │ │          │ │client.py       │
│keyboards│ │          │ │instances.py    │
└─────────┘ └──────────┘ └────────────────┘
                  │
     ┌────────────┼────────────┐
     ▼            ▼            ▼
┌─────────┐ ┌──────────┐ ┌─────────┐
│ SQLite  │ │  Fernet  │ │  .env   │
│akumaja  │ │  AES-256 │ │ config  │
│  .db    │ │ encrypt  │ │         │
└─────────┘ └──────────┘ └─────────┘
```

### ¿Cómo se conecta a Moodle?

El bot **no usa la API REST oficial de Moodle** (que requiere tokens de administrador). En su lugar, simula una sesión de navegador real usando `cloudscraper` y consume los **endpoints AJAX internos** que Moodle usa en su interfaz web:

| Endpoint AJAX | Uso |
|---|---|
| `core_course_get_enrolled_courses_by_timeline_classification` | Listar materias inscritas |
| `core_calendar_get_action_events_by_timesort` | Entregas y eventos del calendario |
| `core_course_get_course_contents` | Contenido interno de cada curso (búsqueda profunda) |

### Caché de Sesiones

Para evitar hacer login en cada consulta (lo que dispararía las alarmas del firewall), el bot implementa un **caché de sesiones en memoria** por usuario. Si la cookie HTTP sigue viva, se reutiliza sin golpear el endpoint de autenticación nuevamente.

---

## 🏛 Facultades Soportadas

| Facultad | Servidor |
|---|---|
| 📐 Ciencias Básicas | `akumajafcbasicas.uniguajira.edu.co` |
| 🏥 Ciencias de la Salud | `akumajafcsalud.uniguajira.edu.co` |
| 📖 Educación | `akumajafaced.uniguajira.edu.co` |
| 🏛 Ciencias Sociales | `akumajafcsociales.uniguajira.edu.co` |
| 💻 Ingenierías (FIUG) | `akumajafiug.uniguajira.edu.co` |
| 📊 FACEYA | `akumajafaceya.uniguajira.edu.co` |
| 🌐 Centro de Lenguas y Postgrados | `virtual.uniguajira.edu.co` |

> **¿Tu facultad no está?** Agrégala en `src/moodle/instances.py`:
> ```python
> registry.add("mi_facultad", "Mi Facultad", "https://akumaja...")
> ```

---

## 🚀 Instalación

### Requisitos previos

- Python 3.10 o superior
- Cuenta en alguna plataforma Akumaja (Uniguajira)
- Bot de Telegram (créalo con [@BotFather](https://t.me/BotFather))

### Pasos

```bash
# 1. Clonar el repositorio
git clone https://github.com/tu-usuario/akumaja-bot.git
cd akumaja-bot

# 2. Crear entorno virtual
python -m venv .venv
source .venv/bin/activate

# 3. Instalar dependencias
pip install -r requirements.txt
```

---

## ⚙️ Configuración

Crea un archivo `.env` basado en `.env.example`:

```env
# === Obligatorio ===
TELEGRAM_BOT_TOKEN=123456789:ABC-DEF...

# === Migración legacy (opcional, solo primer arranque) ===
TELEGRAM_CHAT_ID=706081601
MOODLE_URL=https://akumajafiug.uniguajira.edu.co
MOODLE_USERNAME=tu_usuario
MOODLE_PASSWORD=tu_contraseña

# === Seguridad (recomendado para producción) ===
AKUMAJA_ENCRYPTION_KEY=
```

### 🔐 Clave de cifrado

Las contraseñas de los usuarios se cifran con **Fernet (AES-256-CBC)**. Para producción, genera una clave dedicada:

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Coloca el resultado en `AKUMAJA_ENCRYPTION_KEY`. Si no la defines, el bot genera un archivo `data/akumaja.key` local automáticamente (modo desarrollo).

> ⚠️ **Importante:** Sin la clave de cifrado no se pueden descifrar las credenciales de los usuarios. Respalda siempre `AKUMAJA_ENCRYPTION_KEY` o el archivo `data/akumaja.key`.

---

## 💬 Uso

```bash
python bot.py
```

En Telegram:

1. Envía `/start` al bot
2. Usa `/login` para conectar tu cuenta de Moodle
3. Elige tu facultad → escribe tu usuario → escribe tu contraseña
4. ¡Listo! Usa `/cursos`, `/tareas` o `/notificaciones`

Cada usuario está completamente aislado: sus cursos, tareas, notificaciones y sesiones son independientes.

### Migración desde versión single-user

Si actualizas desde una versión anterior del bot, al primer arranque se migra automáticamente la cuenta de `.env` al chat configurado en `TELEGRAM_CHAT_ID`. Para migrar manualmente:

```bash
python -m src.services.accounts
```

---

## 🖥 Despliegue en Producción (Oracle Cloud + systemd)

El bot está diseñado para correr como servicio en una máquina virtual de Oracle Cloud (o cualquier servidor Linux).

### 1. Crear el servicio systemd

```ini
# /etc/systemd/system/akumaja-bot.service
[Unit]
Description=Akumaja Telegram Bot
After=network.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/home/ubuntu/akumaja-bot
Environment=PATH=/home/ubuntu/akumaja-bot/.venv/bin
ExecStart=/home/ubuntu/akumaja-bot/.venv/bin/python bot.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

### 2. Activar y arrancar

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now akumaja-bot
```

### 3. Ver logs en tiempo real

```bash
sudo journalctl -u akumaja-bot -f
```

### 4. Reiniciar después de un `git pull`

```bash
cd ~/akumaja-bot
git pull
sudo systemctl restart akumaja-bot
```

---

## 🔧 Problemas Resueltos

A lo largo del desarrollo, se encontraron y resolvieron varios problemas técnicos importantes:

### 🚫 Error 403 Forbidden — Bloqueo de Cloudflare

**Problema:** El firewall WAF de Uniguajira (Cloudflare) detectaba las peticiones del bot como tráfico automatizado y bloqueaba la IP con un error `403 Forbidden`.

**Causa:** El bot hacía login simultáneo para múltiples usuarios en ráfaga (8 usuarios en 15 segundos), lo que parecía un ataque DDoS.

**Solución aplicada:**
- Se implementó `cloudscraper` con perfil de navegador **Firefox en Windows** para pasar la verificación de Cloudflare (el perfil de Chrome era bloqueado)
- Se agregaron **demoras aleatorias de 5 a 12 segundos** entre cada usuario en el monitor
- Se implementó **caché de sesiones** para reutilizar cookies HTTP y evitar logins repetidos
- Se capturan los errores 403/503 y se devuelven mensajes controlados al usuario en lugar de tracebacks

### ⏱ Timeout de Telegram (`telegram.error.TimedOut`)

**Problema:** Al ejecutar comandos después de un período de inactividad, la API de Telegram no respondía a tiempo y lanzaba `ConnectTimeout`.

**Solución:** Se aumentaron los timeouts de conexión, lectura y escritura a 30 segundos en la construcción de la aplicación del bot.

### 🕐 Zona Horaria Incorrecta en Fechas

**Problema:** Las fechas de entrega se mostraban en UTC en lugar de la hora local de Colombia.

**Solución:** Se forzó la zona horaria `America/Bogota` usando `ZoneInfo` en todas las conversiones de timestamp a formato legible.

### 📊 Badge de Urgencia Estático

**Problema:** La etiqueta de urgencia mostraba siempre "EN 3 DÍAS" aunque faltara solo 1 día.

**Solución:** Se hizo dinámico el cálculo del badge, ahora muestra "EN 1 DÍA", "EN 2 DÍAS", etc., según el tiempo real restante.

### 🔑 Token del Bot Expuesto en Logs

**Problema:** La librería `httpx` (usada internamente por `python-telegram-bot`) imprimía cada petición HTTP con la URL completa, exponiendo el token del bot en la terminal.

**Solución:** Se subió el nivel de log de `httpx` a `WARNING` para que solo reporte errores reales.

---

## 📁 Estructura del Proyecto

```
akumaja-bot/
├── bot.py                     # Punto de entrada: registro de handlers y job queue
├── requirements.txt           # Dependencias Python
├── .env.example               # Plantilla de configuración
├── .env                       # Variables de entorno (NO commitear)
├── pytest.ini                 # Config de pytest
│
├── data/                      # Datos en ejecución (gitignored)
│   ├── akumaja.db             # Base de datos SQLite (contraseñas cifradas)
│   ├── akumaja.key            # Clave Fernet local (si no hay ENCRYPTION_KEY)
│   ├── images/
│   │   └── qr.png             # QR del bot para compartir
│   └── notifications/         # Dedup de notificaciones por usuario
│
├── src/                       # Código fuente modularizado
│   ├── core/                  # Núcleo del sistema
│   │   ├── config.py          # Variables de entorno y rutas centralizadas
│   │   ├── database.py        # SQLite thread-safe: usuarios y sync
│   │   └── security.py        # Cifrado Fernet (AES-256) de credenciales
│   │
│   ├── moodle/                # Integración con Moodle
│   │   ├── instances.py       # Registro de facultades/instancias
│   │   ├── client.py          # Cliente Moodle por usuario con caché de sesión
│   │   └── api.py             # Scraping AJAX + anti-WAF + rate limiting
│   │
│   ├── services/              # Lógica de negocio
│   │   ├── accounts.py        # Login, logout, caché de clientes, migración
│   │   ├── monitor.py         # Monitoreo automático multiusuario
│   │   └── notifications.py   # Deduplicación y persistencia de alertas
│   │
│   └── bot/                   # Presentación (Telegram)
│       ├── ui.py              # Separadores, badges, formateadores de mensajes
│       ├── keyboards.py       # Teclados persistentes e inline
│       └── handlers/          # Handlers por responsabilidad
│           ├── general.py     # /start, /ayuda, /estado
│           ├── courses.py     # /cursos, /tareas, /notificaciones, /cuenta
│           ├── login.py       # Flujo conversacional de /login
│           └── faculty.py     # Flujo conversacional de /cambiar_facultad
│
└── tests/                     # Pruebas unitarias (pytest)
    ├── test_multiuser.py
    └── test_ui.py
```

---

## 🧪 Pruebas

```bash
pytest tests/ -v
```

44+ pruebas unitarias con mocks (sin credenciales reales): instancias, base de datos, cifrado, login, cambio de facultad, normalización de usuario, menú y monitor.

---

## 🛡 Backup y Seguridad

| Qué respaldar | Dónde está | Por qué |
|---|---|---|
| Base de datos | `data/akumaja.db` | Contiene las cuentas con contraseñas cifradas |
| Clave de cifrado | `data/akumaja.key` o `AKUMAJA_ENCRYPTION_KEY` | Sin ella no se descifran las credenciales |
| Variables de entorno | `.env` | Token del bot y config de Telegram |

> 💡 **Tip:** En producción, usa `AKUMAJA_ENCRYPTION_KEY` como variable de entorno del sistema y respalda `data/` periódicamente.

---

## 👨‍💻 Autor

Desarrollado por **Iván Martínez** — Ingeniería de Sistemas, Universidad de La Guajira.

<div align="center">

[![Telegram Bot](https://img.shields.io/badge/Probar_el_Bot-@akumaja__ivan__bot-2CA5E0?style=for-the-badge&logo=telegram&logoColor=white)](https://t.me/akumaja_ivan_bot)

</div>
