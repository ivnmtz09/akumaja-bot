# Akumaja Bot

Bot de Telegram para la Plataforma Virtual Akumaja (Uniguajira), **multiusuario y multi-instancia**.

## Funcionalidades

- **`/login`** — Conecta tu cuenta Moodle: elige tu facultad, escribe usuario y contraseña
  - El usuario se normaliza automáticamente: quita espacios, acepta el correo completo (`usuario@uniguajira.edu.co`) y pasa a minúsculas
  - Si te equivocas de facultad, hay un botón **"🔄 ¿Te equivocaste? Cambiar facultad"** en el paso del usuario
- **Menú de botones persistente** — Barra fija debajo del campo de escritura que se adapta al estado: sin cuenta muestra `/start` `/login` `/ayuda`; con cuenta muestra `/cursos` `/tareas` `/notificaciones` `/cuenta` `/cambiar_facultad` `/logout` (nunca `/login` y `/logout` a la vez)
- **`/cursos`** — Lista tus cursos inscritos con enlaces directos a Moodle
- **`/tareas`** — Próximas entregas/actividades (próximos 30 días)
- **`/notificaciones`** — Resumen completo: vencimientos próximos + actividad reciente
- **`/cuenta`** — Muestra tu cuenta conectada (usuario, facultad, servidor, cursos, estado) con botones para cambiar facultad o desconectar
- **`/cambiar_facultad`** — Cambia de facultad/instancia Moodle sin desconectarte (valida el login contra la nueva instancia antes de aplicar el cambio; si falla, tu cuenta actual queda intacta)
- **`/logout`** — Desconecta tu cuenta y elimina tus datos del bot
- **`/estado`** — Usuarios conectados e información del bot
- **`/ayuda`** — Ayuda detallada
- **Monitoreo automático** — Cada 30 min (5:00–23:59) detecta y avisa a cada usuario:
  - Entregas próximas (próximas 24h)
  - Tareas vencidas (últimas 24h)
  - Contenido nuevo en cursos (últimas 6h)
- **Deduplicación por usuario** — No envía la misma notificación dos veces (`.sent_notifications_{user_id}.json`)

## Instancias soportadas

| Facultad | Instancia |
|---|---|
| Ciencias Básicas | `akumajafcbasicas.uniguajira.edu.co` |
| Ciencias de la Salud | `akumajafcsalud.uniguajira.edu.co` |
| Educación | `akumajafaced.uniguajira.edu.co` |
| Ciencias Sociales | `akumajafcsociales.uniguajira.edu.co` |
| Ingenierías (FIUG) | `akumajafiug.uniguajira.edu.co` |
| FACEYA | `akumajafaceya.uniguajira.edu.co` |
| Centro de Lenguas y Postgrados | `virtual.uniguajira.edu.co` |

Para agregar una instancia: `registry.add("mi_facultad", "Mi Facultad", "https://akumaja...")` en `moodle_instances.py`.

## Requisitos

- Python 3.10+
- Cuenta en alguna plataforma Akumaja
- Bot de Telegram (crear con @BotFather)

## Instalación

```bash
git clone <tu-repo>
cd akumaja-bot

python -m venv .venv
source .venv/bin/activate

pip install -r requirements.txt
```

## Configuración

Crea un archivo `.env` basado en `.env.example`:

```env
TELEGRAM_BOT_TOKEN=123456789:ABC-DEF...
TELEGRAM_CHAT_ID=706081601            # solo migración inicial
MOODLE_URL=https://akumajafiug.uniguajira.edu.co
MOODLE_USERNAME=tu_usuario
MOODLE_PASSWORD=tu_contraseña
AKUMAJA_ENCRYPTION_KEY=               # opcional, ver abajo
```

**Seguridad:** las contraseñas de los usuarios se cifran con Fernet. Define `AKUMAJA_ENCRYPTION_KEY`
en el entorno para producción (genera una con `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`).
Si no la defines, se genera un `akumaja.key` local automáticamente (modo desarrollo).

## Uso

```bash
python bot.py
```

En Telegram: envía `/login` y sigue los pasos. Cada usuario queda aislado:
sus cursos, tareas, notificaciones y deduplicación son independientes.

Si ya tienes cuenta y quieres cambiar de facultad, usa `/cambiar_facultad`
(o el botón "🔄 Cambiar facultad" de `/cuenta`): el bot te pide las
credenciales, valida el login contra la nueva instancia y solo entonces
actualiza tu cuenta. Si el login falla o cancelas, tu cuenta anterior
permanece intacta.

## Migración desde la versión single-user

En el primer arranque, si la base de datos está vacía, el bot migra automáticamente
la cuenta de `.env` (`MOODLE_URL`, `MOODLE_USERNAME`, `MOODLE_PASSWORD`) al
`TELEGRAM_CHAT_ID` configurado. Para migrar manualmente:

```bash
python -m accounts
```

## Despliegue en servidor (systemd)

```ini
# /etc/systemd/system/akumaja-bot.service
[Unit]
Description=Akumaja Telegram Bot
After=network.target

[Service]
Type=simple
User=tu_usuario
WorkingDirectory=/home/tu_usuario/akumaja-bot
Environment=PATH=/home/tu_usuario/akumaja-bot/.venv/bin
ExecStart=/home/tu_usuario/akumaja-bot/.venv/bin/python bot.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now akumaja-bot
sudo journalctl -u akumaja-bot -f
```

## Estructura del proyecto

```
akumaja-bot/
├── bot.py               # Bot principal: handlers, flujos /login y /cambiar_facultad, menú, JobQueue
├── get_courses.py       # Lógica de login y consulta a Moodle (AJAX API)
├── moodle_instances.py  # Registro central de instancias Moodle
├── moodle_client.py     # Cliente Moodle por usuario (sesión propia)
├── accounts.py          # Login/logout/cambio de facultad, normalización, migración legacy
├── monitor.py           # Recolección y envío de notificaciones por usuario
├── db.py                # SQLite: usuarios (una cuenta por chat)
├── security.py          # Cifrado Fernet de credenciales
├── requirements.txt     # Dependencias Python
├── .env.example         # Plantilla de configuración
├── .env                 # Variables de entorno (NO commitear)
├── .gitignore
├── tests/               # Pruebas unitarias (pytest)
└── README.md

# Archivos generados en ejecución (gitignored)
├── akumaja.db           # Base de datos con las cuentas (contraseñas cifradas)
├── akumaja.key          # Clave Fernet local (si no se define AKUMAJA_ENCRYPTION_KEY)
└── .sent_notifications_{user_id}.json  # Deduplicación de notificaciones por usuario
```

## Cómo funciona

El bot usa los **endpoints AJAX internos de Moodle** (los mismos que usa el bloque "Course overview" en el navegador):

1. `core_course_get_enrolled_courses_by_timeline_classification` — Cursos inscritos
2. `core_calendar_get_action_events_by_timesort` — Eventos/entregas del calendario
3. `core_course_get_course_contents` — Contenido reciente de cursos (para detectar cambios)

## Pruebas

```bash
python -m pytest tests/ -v
```

44 pruebas unitarias con mocks (sin credenciales reales): instancias, base de
datos, cifrado, login, cambio de facultad, normalización de usuario, menú y monitor.

## Backup

La base de datos `akumaja.db` contiene las cuentas (contraseñas cifradas).
Respáldala periódicamente junto con `akumaja.key` (o conserva `AKUMAJA_ENCRYPTION_KEY`),
porque sin la clave no se pueden descifrar las credenciales.

## Licencia

MIT