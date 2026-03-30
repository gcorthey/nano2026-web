# NANO2026 - Web del Congreso

Sistema web para el XXIV Encuentro de Superficies y Materiales Nanoestructurados (NANO2026).

Campus UNSAM · San Martin, Buenos Aires · 3, 4 y 5 de junio de 2026

---

## Stack tecnologico

| Capa | Tecnologia |
|---|---|
| Backend | FastAPI + Python 3.11 |
| Templates | Jinja2 |
| Base de datos | SQLite |
| ORM / acceso a datos | SQLAlchemy |
| Autenticacion | JWT (`python-jose`) + bcrypt |
| Editor de texto | Quill.js 1.3.6 + KaTeX 0.16.9 |
| Generacion de PDF | xhtml2pdf |
| CSS | Tailwind CSS via CDN |
| Produccion principal | Uvicorn + systemd + Caddy en Raspberry Pi 5 |
| Edge / proxy | Operacion externa al repo; hoy se usa Cloudflare |

Nota: el README anterior mencionaba AWS Route 53 para DNS, pero eso ya no refleja el despliegue actual.

---

## Estructura del proyecto

```text
congreso_nano/
├── app/
│   ├── __init__.py
│   ├── auth.py
│   ├── database.py
│   ├── main.py
│   ├── models.py
│   ├── static/
│   │   ├── icons/
│   │   ├── images/
│   │   ├── logos/
│   │   └── og/
│   └── templates/
│       ├── forgot_password.html
│       ├── login.html
│       ├── reset_password.html
│       ├── admin/
│       ├── eval/
│       └── public/
├── scripts/
│   ├── backup_db.sh
│   ├── deploy.sh
│   ├── restore_db.sh
│   ├── rpi-backup.sh
│   └── webhook.py
├── Dockerfile
├── Procfile
├── nixpacks.toml
├── requirements.txt
├── runtime.txt
├── LICENSE
└── README.md
```

Notas sobre despliegue:

- La operacion principal hoy esta documentada para Raspberry Pi con `systemd`.
- `Dockerfile`, `Procfile`, `nixpacks.toml` y `runtime.txt` quedaron como soporte o restos de despliegues alternativos; no son la fuente principal de verdad operativa.

---

## Instalacion local

### 1. Clonar el repositorio

```bash
git clone https://gitlab.com/nano2026/web.git congreso_nano
cd congreso_nano
```

### 2. Instalar dependencias del sistema

En Debian / Ubuntu / Raspberry Pi OS:

```bash
sudo apt install -y libcairo2-dev pkg-config python3-dev cmake libxslt1-dev libxml2-dev libjpeg-dev libopenjp2-7 sqlite3
```

### 3. Crear entorno virtual e instalar dependencias Python

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 4. Crear `.env`

Variables usadas por la aplicacion:

| Variable | Obligatoria | Uso |
|---|---|---|
| `SECRET_KEY` | Si | Firma de JWT, login y links firmados |
| `MAIL_USERNAME` | Si, si se envian mails | Usuario SMTP |
| `MAIL_PASSWORD` | Si, si se envian mails | Password o app password SMTP |
| `MAIL_FROM` | Si, si se envian mails | Remitente visible |
| `PUBLIC_BASE_URL` | Recomendado | Base publica para links absolutos |
| `RECAPTCHA_SITE_KEY` | Opcional | Site key publica |
| `RECAPTCHA_SECRET` | Opcional | Verificacion de reCAPTCHA |

Ejemplo:

```env
SECRET_KEY=clave-secreta-larga-y-aleatoria
MAIL_USERNAME=usuario@example.com
MAIL_PASSWORD=app-password
MAIL_FROM=usuario@example.com
PUBLIC_BASE_URL=https://nano2026.org
RECAPTCHA_SITE_KEY=tu-site-key
RECAPTCHA_SECRET=tu-secret
```

### 5. Base de datos

La aplicacion usa SQLite local en:

```text
sqlite:///./congreso.db
```

Las tablas se crean al iniciar la app y `app.main` tambien aplica algunas actualizaciones de esquema compatibles hacia adelante.

Si queres forzar la creacion inicial sin levantar el servidor:

```bash
python -c "from app.database import engine; from app import models; models.Base.metadata.create_all(bind=engine)"
```

### 6. Correr el servidor de desarrollo

```bash
uvicorn app.main:app --reload
```

Abrir `http://127.0.0.1:8000`.

Importante:

- correr `uvicorn` desde la raiz del repo, no desde `app/`;
- al importar `app.main`, tambien se ejecuta la creacion del admin por defecto si no existe.

---

## Credenciales por defecto

Si la base esta vacia, al iniciar se crea automaticamente un usuario admin:

| Campo | Valor |
|---|---|
| Email | `admin@congreso.com` |
| Contrasena | `admin1234` |

En el primer ingreso se fuerza cambio de contrasena.

No dejar estas credenciales activas en produccion.

---

## Modelo de datos principal

Tablas definidas actualmente en `app/models.py`:

| Tabla | Descripcion |
|---|---|
| `users` | Usuarios admin y evaluadores |
| `abstracts` | Resumenes enviados, invitados y contribuciones |
| `autores` | Autores por resumen |
| `afiliaciones` | Afiliaciones por resumen |
| `reviews` | Evaluaciones |
| `asignaciones` | Asignacion evaluador ↔ abstract |
| `abstract_logs` | Historial de eventos del abstract |
| `abstract_acceptance_flags` | Flags auxiliares de aceptacion / revision menor |
| `registrations` | Inscripciones |
| `sessions` | Tabla legacy de sesiones |
| `speakers` | Tabla legacy de speakers |
| `program_entries` | Programa actual editable |
| `program_days` | Metadata de dias del programa |

Campos destacados en `abstracts`:

- `tipo_resumen`: `contribucion`, `plenaria`, `semiplenaria`, `talento_joven`
- `numero_invitado`: orden de invitado cuando aplica
- `contenido_html`: contenido enriquecido generado por Quill
- `referencias_html`: referencias en HTML
- `area_tematica`: codigo de area
- `presentacion_oral`: preferencia del autor
- `tipo_asignado_admin`: decision final del admin (`oral` o `poster`)
- `codigo_final`: codigo visible / final del resumen

---

## Roles del sistema

| Rol | Acceso |
|---|---|
| Publico | Sitio institucional, abstracts aprobados, envio de resumen |
| Evaluador | `/eval` y revision de asignados |
| Admin | `/admin`, gestion de abstracts, evaluadores y programa |

---

## Rutas principales

### Publicas

| URL | Descripcion |
|---|---|
| `/` | Home |
| `/about` | Sobre el encuentro |
| `/circulares` | Circulares |
| `/contacto` | Contacto |
| `/inscripcion` | Informacion de inscripcion |
| `/programa` | Programa del congreso |
| `/speakers` | Conferencias invitadas |
| `/venue` | Sede y alojamiento |
| `/sponsors` | Sponsors |
| `/en/sponsors` | Version en ingles de sponsors |
| `/submit` | Envio de resumen |
| `/abstracts` | Buscador de resumenes aprobados |
| `/abstracts/{id}` | Resumen individual |
| `/abstracts/{id}/pdf` | PDF del resumen |
| `/revision/{token}` | Reenvio por link firmado |
| `/login` | Login |
| `/forgot-password` | Solicitud de reset |
| `/reset-password/{token}` | Cambio de contrasena por token |
| `/robots.txt` | Reglas para crawlers |
| `/sitemap.xml` | Sitemap |

### Protegidas

| URL | Rol requerido |
|---|---|
| `/admin` | Admin |
| `/admin/abstracts/new` | Admin |
| `/admin/abstracts/{id}` | Admin |
| `/admin/abstracts/{id}/edit` | Admin |
| `/admin/abstracts/export/csv` | Admin |
| `/admin/evaluadores` | Admin |
| `/admin/programa` | Admin |
| `/admin/programa/new` | Admin |
| `/admin/programa/{id}/edit` | Admin |
| `/eval` | Evaluador o admin |
| `/eval/{id}` | Evaluador o admin |
| `/force-password-change` | Usuario autenticado con cambio obligatorio |

---

## Flujo de resumenes

```text
Ponente envia resumen en /submit
    -> estado inicial pendiente
    -> admin asigna evaluadores
    -> evaluador deja decision y comentario
    -> si hace falta, se envia link firmado de revision
    -> el autor reenvia correcciones
    -> si se aprueba, se envia mail de aceptacion
    -> admin define modalidad final oral / poster
    -> si corresponde, el resumen queda visible en /abstracts
```

Notas del flujo actual:

- la recomendacion de oral del evaluador no fija la decision final;
- el admin puede filtrar abstracts aprobados simples vs. aprobados con revision previa;
- el historial de eventos se guarda en `abstract_logs`;
- los links de revision usan tokens firmados con vencimiento;
- el admin puede exportar CSV respetando filtros activos.

---

## Areas tematicas

| # | Area |
|---|---|
| 1 | Sintesis de nanomateriales |
| 2 | Autoensamblado |
| 3 | Nanobiointerfaces y procesos biologicos |
| 4 | Superficies |
| 5 | Propiedades de nanomateriales |
| 6 | Aplicaciones de nanomateriales en ambiente, energia, agro, alimentos y catalisis |
| 7 | Nanotecnologia y salud |

---

## Despliegue en produccion

El esquema principal documentado hoy es:

- FastAPI + Uvicorn
- servicio `systemd`
- Caddy como reverse proxy
- GitLab como remoto del repo
- webhook local opcional para redeploy

### 1. Instalar Caddy

```bash
sudo apt install -y caddy
```

### 2. Configurar Caddy

Ejemplo minimo:

```caddyfile
nano2026.org {
    reverse_proxy 127.0.0.1:8000
}
```

### 3. Crear servicio systemd para la app

Ejemplo:

```ini
[Unit]
Description=NANO2026 Web
After=network.target

[Service]
User=appuser
WorkingDirectory=/srv/congreso_nano
ExecStart=/srv/congreso_nano/venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 2
EnvironmentFile=/srv/congreso_nano/.env
Restart=always

[Install]
WantedBy=multi-user.target
```

Activacion:

```bash
sudo systemctl daemon-reload
sudo systemctl enable nano2026
sudo systemctl start nano2026
sudo systemctl status nano2026
```

### 4. Redeploy automatico con webhook de GitLab

Flujo esperado:

1. Se hace `git push` a la rama desplegada.
2. GitLab envia un `POST` al servicio `scripts/webhook.py`.
3. El webhook valida `X-Gitlab-Token`.
4. Si el token coincide, dispara `scripts/deploy.sh`.
5. `deploy.sh` actualiza el checkout y reinicia el servicio.

Importante:

- `scripts/deploy.sh` usa `git reset --hard origin/<branch>`;
- el checkout de produccion no debe tener cambios manuales sin commitear;
- el webhook es un servicio aparte, no una ruta FastAPI.

---

## Scripts operativos

| Script | Proposito |
|---|---|
| `scripts/deploy.sh` | Actualiza el repo desplegado y reinicia el servicio |
| `scripts/webhook.py` | Receptor minimo de webhook de GitLab |
| `scripts/backup_db.sh` | Backup de `congreso.db` a S3 |
| `scripts/restore_db.sh` | Restore de backup diario desde S3 |
| `scripts/rpi-backup.sh` | Snapshot completo de la Raspberry Pi |

### `scripts/deploy.sh`

Uso:

```bash
./scripts/deploy.sh
```

Variables soportadas:

| Variable | Default | Uso |
|---|---|---|
| `REPO_DIR` | raiz del repo detectada automaticamente | Checkout desplegado |
| `BRANCH` | `main` | Rama a desplegar |
| `SERVICE_NAME` | `nano2026` | Servicio systemd a reiniciar |

### `scripts/webhook.py`

Uso:

```bash
python3 scripts/webhook.py
```

Variables soportadas:

| Variable | Default | Uso |
|---|---|---|
| `WEBHOOK_SECRET` | `nano2026webhook` | Token esperado |
| `DEPLOY_SCRIPT` | `scripts/deploy.sh` | Script disparado |
| `WEBHOOK_HOST` | `127.0.0.1` | Host de escucha |
| `WEBHOOK_PORT` | `9000` | Puerto de escucha |

### `scripts/backup_db.sh`

Uso:

```bash
./scripts/backup_db.sh
```

Variables soportadas:

| Variable | Default | Uso |
|---|---|---|
| `REPO_DIR` | raiz del repo detectada automaticamente | Base para paths |
| `DB_PATH` | `${REPO_DIR}/congreso.db` | SQLite a respaldar |
| `LOG_FILE` | `${REPO_DIR}/backup.log` | Log local |
| `S3_BUCKET` | `nano2026-backups` | Bucket destino |
| `AWS_PROFILE` | `nano2026` | Perfil AWS CLI |
| `RETENTION_DAYS` | `30` | Reservado para futura retencion |

### `scripts/restore_db.sh`

Uso para listar backups:

```bash
./scripts/restore_db.sh
```

Uso para restaurar una fecha:

```bash
./scripts/restore_db.sh YYYY-MM-DD
```

Variables soportadas:

| Variable | Default | Uso |
|---|---|---|
| `REPO_DIR` | raiz del repo detectada automaticamente | Base para paths |
| `DB_PATH` | `${REPO_DIR}/congreso.db` | Base a reemplazar |
| `S3_BUCKET` | `nano2026-backups` | Bucket origen |
| `AWS_PROFILE` | `nano2026` | Perfil AWS CLI |

### `scripts/rpi-backup.sh`

Uso:

```bash
./scripts/rpi-backup.sh
```

Variables soportadas:

| Variable | Default | Uso |
|---|---|---|
| `AWS_PROFILE` | `nano2026` | Perfil AWS CLI |
| `S3_DEST` | `s3://nano2026-backups/snapshots/` | Destino del snapshot |
| `WORK_DIR` | `$HOME` | Directorio de trabajo |

Supuestos actuales del script:

- guarda imagenes y logs en `$HOME/backups`;
- usa `sudo /usr/local/bin/image-backup`;
- sube el snapshot a S3;
- borra imagenes locales antiguas despues de subir.

---

## Notas operativas

- `congreso.db` se crea automaticamente si no existe.
- El PDF de abstract se genera al vuelo.
- La autenticacion web se resuelve con cookie `access_token`.
- Los mails cubren aceptacion, rechazo, revision y comunicacion de modalidad.
- `program_entries` y `program_days` son la fuente actual del programa editable.
- Las tablas `sessions` y `speakers` siguen definidas en modelos, pero hoy las paginas publicas se apoyan principalmente en contenido de templates y logica de `app/main.py`.

---

## Herramientas de desarrollo

Durante el desarrollo del sitio se utilizaron herramientas de asistencia para programacion, incluyendo Claude Sonnet 4.6 (Anthropic) y Codex sobre GPT-5.4 (OpenAI).

---

## Licencia

Este repositorio se distribuye bajo la licencia `GNU AGPL-3.0`. Ver [LICENSE](LICENSE).

---

G. Corthey  
gcorthey@unsam.edu.ar
