# Akumaja Bot

Bot de Telegram para la Plataforma Virtual Akumaja Fiug (Uniguajira).

## Funcionalidades

- **`/cursos`** — Lista tus 19 cursos inscritos con enlaces directos a Moodle
- **`/tareas`** — Próximas entregas/actividades (próximos 30 días)
- **`/notificaciones`** — Resumen completo: vencimientos próximos + actividad reciente
- **Monitoreo automático** — Cada 30 min (5:00–23:59) detecta:
  - Entregas próximas (próximas 24h)
  - Tareas vencidas (últimas 24h)
  - Contenido nuevo en cursos (últimas 6h)
- **Deduplicación** — No envía la misma notificación dos veces (guarda estado en `.sent_notifications.json`)

## Requisitos

- Python 3.10+
- Cuenta en la plataforma Akumaja Fiug
- Bot de Telegram (crear con @BotFather)

## Instalación

```bash
# Clonar el repositorio
git clone <tu-repo>
cd akumaja-bot

# Crear entorno virtual
python -m venv .venv
source .venv/bin/activate

# Instalar dependencias
pip install -r requirements.txt
```

## Configuración

Crea un archivo `.env` basado en `.env.example`:

```env
# Token del bot de Telegram (obtén en @BotFather)
TELEGRAM_BOT_TOKEN=123456789:ABC-DEF...

# Tu Chat ID (obtén enviando /start a @userinfobot)
TELEGRAM_CHAT_ID=706081601

# Credenciales de Moodle
MOODLE_URL=https://akumajafiug.uniguajira.edu.co
MOODLE_USERNAME=tu_usuario
MOODLE_PASSWORD=tu_contraseña
```

## Uso

```bash
# Desarrollo
python bot.py

# Producción (con systemd, Docker, etc.)
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
├── bot.py              # Bot principal con handlers y JobQueue
├── get_courses.py      # Lógica de login y consulta a Moodle (AJAX API)
├── requirements.txt    # Dependencias Python
├── .env                # Variables de entorno (NO commitear)
├── .gitignore
└── README.md
```

## Cómo funciona

El bot usa los **endpoints AJAX internos de Moodle** (los mismos que usa el bloque "Course overview" en el navegador):

1. `core_course_get_enrolled_courses_by_timeline_classification` — Cursos inscritos
2. `core_calendar_get_action_events_by_timesort` — Eventos/entregas del calendario
3. `core_course_get_course_contents` — Contenido reciente de cursos (para detectar cambios)

## Licencia

MIT