# NANO2026 — Web del Congreso

Sistema web para el **XXIV Encuentro de Superficies y Materiales Nanoestructurados (NANO2026)**  
Campus UNSAM · San Martín, Buenos Aires · 3, 4 y 5 de junio de 2026

---

## Stack tecnológico

| Capa | Tecnología |
|---|---|
| Backend | FastAPI + Python 3.13 |
| Templates | Jinja2 |
| Base de datos | SQLite + SQLAlchemy |
| Autenticación | JWT (python-jose) + bcrypt 4.0.1 |
| Editor de texto | Quill.js 1.3.6 (CDN) + KaTeX 0.16.9 |
| Generación PDF | xhtml2pdf |
| CSS | Tailwind CSS (CDN) |
| Servidor (producción) | Caddy en Raspberry Pi 5 |
| DNS | AWS Route 53 |

---

## Estructura del proyecto
```
congreso_nano/
├── app/
│   ├── __init__.py
│   ├── main.py          # Rutas y lógica principal
│   ├── models.py        # Modelos SQLAlchemy
│   ├── database.py      # Configuración de la base de datos
│   ├── auth.py          # Autenticación JWT y roles
│   ├── static/
│   │   ├── css/
│   │   └── js/
│   └── templates/
│       ├── login.html
│       ├── public/
│       │   ├── base.html
│       │   ├── home.html
│       │   ├── about.html
│       │   ├── abstracts.html
│       │   ├── abstract_detail.html
│       │   ├── abstract_pdf.html
│       │   ├── circulares.html
│       │   ├── contacto.html
│       │   ├── inscripcion.html
│       │   ├── sponsors.html
│       │   ├── submit.html
│       │   ├── char_panel_content.html
│       │   ├── speakers.html
│       │   ├── venue.html
│       │   └── programa.html
│       ├── admin/
│       │   ├── base.html
│       │   ├── abstracts.html
│       │   ├── abstract_detail.html
│       │   └── evaluadores.html
│       └── eval/
│           ├── base.html
│           ├── lista.html
│           └── detalle.html
├── requirements.txt
└── README.md
```

---

## Instalación

### 1. Clonar el repositorio
```bash
git clone https://gitlab.com/nano2026/web.git congreso_nano
cd congreso_nano
```

### 2. Instalar dependencias del sistema (solo RPi / Debian)
```bash
sudo apt install -y libcairo2-dev pkg-config python3-dev cmake libxslt1-dev libxml2-dev libjpeg-dev libopenjp2-7
```

### 3. Crear entorno virtual e instalar dependencias Python
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 4. Configurar variables de entorno

Crear un archivo `.env` en la raíz del proyecto.

Variables actualmente utilizadas por la aplicación:

| Variable | Obligatoria | Uso |
|---|---|---|
| `SECRET_KEY` | Sí | Firma de JWT de login y links de revisión |
| `MAIL_USERNAME` | Sí, si se envían mails | Usuario SMTP |
| `MAIL_PASSWORD` | Sí, si se envían mails | Password / app password SMTP |
| `MAIL_FROM` | Sí, si se envían mails | Remitente visible |
| `PUBLIC_BASE_URL` | Recomendado | Base pública para links en correos, ej. `https://nano2026.org` |
| `RECAPTCHA_SECRET` | Opcional | Validación de reCAPTCHA si el flujo lo usa |

Ejemplo:

```env
SECRET_KEY=clave-secreta-larga-y-aleatoria
MAIL_USERNAME=usuario@example.com
MAIL_PASSWORD=app-password
MAIL_FROM=usuario@example.com
PUBLIC_BASE_URL=https://nano2026.org
RECAPTCHA_SECRET=tu-secret
```

### 5. Inicializar la base de datos
```bash
python -c "from app.database import engine; from app import models; models.Base.metadata.create_all(bind=engine)"
```

La base actualmente usa SQLite local en:

```text
sqlite:///./congreso.db
```

### 6. Correr el servidor de desarrollo
```bash
uvicorn app.main:app --reload
```

Abrí `http://127.0.0.1:8000` en el navegador.

> ⚠️ Siempre correr uvicorn desde `congreso_nano/`, nunca desde `app/`.

---

## Credenciales por defecto

Al iniciar por primera vez se crea automáticamente un usuario admin:

| Campo | Valor |
|---|---|
| Email | `admin@congreso.com` |
| Contraseña | `admin1234` |

⚠️ **Cambiar la contraseña antes de poner en producción.**

---

## Base de datos — modelos principales

| Tabla | Descripción |
|---|---|
| `users` | Usuarios del sistema (admin / evaluador) |
| `abstracts` | Resúmenes enviados |
| `autores` | Autores por resumen (con superíndices de afiliación) |
| `afiliaciones` | Afiliaciones por resumen |
| `reviews` | Evaluaciones de los revisores |
| `asignaciones` | Asignación evaluador ↔ abstract |
| `abstract_logs` | Historial de eventos y envíos de correo |
| `registrations` | Inscripciones al congreso |
| `sessions` | Sesiones del programa |
| `speakers` | Oradores invitados |

### Campos destacados en `abstracts`
- `titulo` — HTML (soporta cursiva, sub/superíndice, símbolos)
- `contenido_html` — HTML generado por Quill.js
- `referencias_html` — HTML de referencias bibliográficas (formato APA)
- `area_tematica` — número del 1 al 7
- `presentacion_oral` — 0 o 1
- `tipo_asignado_admin` — decisión final del admin sobre `oral` o `poster`

---

## Roles del sistema

| Rol | Acceso |
|---|---|
| Público | Home, resúmenes aprobados, buscador, formulario de envío |
| Evaluador | Panel `/eval` — ver y evaluar resúmenes asignados |
| Admin | Panel `/admin` — gestionar resúmenes, evaluadores |

---

## Páginas principales

### Públicas

| URL | Descripción |
|---|---|
| `/` | Home del congreso |
| `/abstracts` | Buscador de resúmenes aprobados |
| `/abstracts/{id}` | Resumen individual |
| `/abstracts/{id}/pdf` | Descargar resumen en PDF |
| `/submit` | Formulario de envío de resúmenes |
| `/revision/{token}` | Reenvío de correcciones por link firmado |
| `/inscripcion` | Información de inscripción y datos bancarios |
| `/sponsors` | Página institucional para auspiciantes |
| `/about` | Sobre el encuentro |
| `/circulares` | Información institucional complementaria |
| `/contacto` | Contacto |
| `/speakers` | Speakers y mesas temáticas |
| `/venue` | Lugar, cómo llegar, alojamiento |
| `/programa` | Programa del congreso |

### Protegidas

| URL | Rol requerido |
|---|---|
| `/admin` | Admin |
| `/admin/abstracts/{id}` | Admin |
| `/admin/abstracts/export/csv` | Admin |
| `/admin/evaluadores` | Admin |
| `/eval` | Evaluador |
| `/eval/{id}` | Evaluador |
| `/forgot-password` | Público |
| `/reset-password/{token}` | Público por link firmado |

---

## Flujo de resúmenes
```
Ponente envía resumen en /submit (sin login)
    → Estado: pendiente
    → Admin asigna evaluadores en /admin/abstracts/{id}
    → Evaluador revisa y deja decisión + comentario en /eval/{id}
    → Si el abstract solicita oral, el evaluador recomienda o no oral
    → Si requiere cambios, el evaluador puede enviar correo con link firmado a /revision/{token}
    → El presentador reenvía correcciones y el resumen vuelve a pendiente
    → Si aprobado, se envía correo de aceptación
    → Admin define modalidad final (oral / póster)
    → Admin puede enviar al presentador la decisión de modalidad
    → Si aprobado: aparece en /abstracts público
    → Cualquier visitante puede buscar y descargar PDF
```

### Notas del flujo actual

- La aprobación del evaluador cambia el estado del abstract a `aprobado` y dispara correo de aceptación.
- El listado admin `/admin` permite filtrar aprobados simples vs. aprobados con revisión previa.
- La categoría `aprobado con revisión` se determina a partir del historial (`abstract_logs`) cuando existió un `revision_email_sent`.
- El admin puede exportar CSV respetando los filtros activos.
- La modalidad final `oral` / `poster` la decide el admin, independientemente de la recomendación del evaluador.

---

## Áreas temáticas

| # | Área |
|---|---|
| 1 | Síntesis de nanomateriales |
| 2 | Autoensamblado |
| 3 | Nanobiointerfaces y procesos biológicos |
| 4 | Superficies |
| 5 | Propiedades de nanomateriales |
| 6 | Aplicaciones de nanomateriales en ambiente, energía, agro, alimentos y catálisis |
| 7 | Nanotecnología y Salud |

---

## Despliegue en producción (Raspberry Pi 5)

### 1. Instalar Caddy
```bash
sudo apt install -y caddy
```

### 2. Configurar Caddy
```bash
sudo nano /etc/caddy/Caddyfile
```

Contenido:
```
nano2026.org {
    reverse_proxy localhost:8000
}
```

### 3. Definir variables de entorno de producción

Como mínimo:

```bash
export SECRET_KEY="clave-secreta-larga-y-aleatoria"
export MAIL_USERNAME="usuario@example.com"
export MAIL_PASSWORD="app-password"
export MAIL_FROM="usuario@example.com"
export PUBLIC_BASE_URL="https://nano2026.org"
```

Alternativamente, definirlas en el archivo de entorno que use el servicio systemd.

### 4. Crear servicio systemd para uvicorn
```bash
sudo nano /etc/systemd/system/nano2026.service
```

Contenido:
```ini
[Unit]
Description=NANO2026 Web
After=network.target

[Service]
User=gcorthey
WorkingDirectory=/home/gcorthey/congreso_nano
ExecStart=/home/gcorthey/congreso_nano/venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 2
EnvironmentFile=/home/gcorthey/congreso_nano/.env
Restart=always

[Install]
WantedBy=multi-user.target
```

Activar:
```bash
sudo systemctl daemon-reload
sudo systemctl enable nano2026
sudo systemctl start nano2026
```

### 5. Verificar que corre
```bash
sudo systemctl status nano2026
```

---

## Backups de base de datos

El proyecto incluye scripts para backup y restore de `congreso.db` en `scripts/`.

### Backup

Script:

```bash
./scripts/backup_db.sh
```

Qué hace:

- crea un snapshot consistente de SQLite usando `sqlite3 .backup`,
- comprime el archivo con `gzip`,
- sube una copia diaria y otra horaria al bucket S3 `nano2026-backups`,
- escribe un log en `backup.log`.

Supuestos actuales del script:

- base local en `/home/gcorthey/congreso_nano/congreso.db`,
- perfil AWS `nano2026`,
- bucket S3 `nano2026-backups`.

### Restore

#### 1. Ver backups disponibles

El script sin argumentos lista las fechas disponibles en `s3://nano2026-backups/daily/`:

```bash
./scripts/restore_db.sh
```

#### 2. Elegir una fecha y ejecutar la restauración

Para restaurar una fecha puntual:

```bash
./scripts/restore_db.sh YYYY-MM-DD
```

Ejemplo:

```bash
./scripts/restore_db.sh 2026-03-10
```

#### 3. Confirmar la operación

El script muestra:

- la fecha del backup que va a restaurar,
- la ruta de destino de la base local,
- una confirmación interactiva `¿Confirmar? [s/N]`.

Solo continúa si se responde `s` o `S`.

#### 4. Qué hace internamente el restore

Una vez confirmada la operación, el script:

- muestra confirmación antes de sobrescribir la base local,
- guarda una copia del estado actual en un archivo como `congreso.db.pre-restore.<timestamp>`,
- descarga el backup diario desde S3,
- valida integridad con `PRAGMA integrity_check`,
- reemplaza la base local solo si el backup es válido.

Importante:

- si la verificación de integridad falla, el restore se aborta,
- el archivo `congreso.db.pre-restore.<timestamp>` queda disponible para volver atrás manualmente.

#### 5. Qué validar después del restore

Después de restaurar, conviene verificar:

- que la aplicación levanta correctamente,
- que podés iniciar sesión en `/login`,
- que el panel `/admin` muestra datos esperados,
- que la fecha/contenido restaurado coincide con el backup elegido.

Si algo sale mal, el archivo de resguardo previo queda en la raíz del proyecto con nombre:

```text
congreso.db.pre-restore.<timestamp>
```

y puede usarse para recuperar el estado anterior.

### Recomendaciones operativas

- No restaurar con la app escribiendo sobre la base al mismo tiempo.
- Verificar credenciales AWS y acceso al bucket antes de correr backup o restore.
- Conservar los archivos `congreso.db.pre-restore.*` hasta confirmar que la restauración fue correcta.

---

## Notas

- La base de datos `congreso.db` se crea automáticamente al iniciar
- Los resúmenes se almacenan como HTML limpio generado por Quill.js
- El PDF se genera al vuelo con xhtml2pdf, sin almacenamiento en disco
- El título del abstract soporta cursiva, sub/superíndice y símbolos especiales
- Las referencias van en campo separado con formato APA
- Los eventos relevantes del flujo se registran en `abstract_logs`
- El proyecto usa envío de mails para aceptación, revisión, rechazo y comunicación de modalidad
- Los links de revisión usan tokens firmados con vencimiento de 72 horas
- La autenticación web se resuelve con cookie `access_token`
- Para producción se recomienda poner Cloudflare delante del servidor

---

G. Corthey  
gcorthey@unsam.edu.ar
