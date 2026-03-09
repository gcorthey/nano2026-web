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
│       │   ├── abstracts.html
│       │   ├── abstract_detail.html
│       │   ├── abstract_pdf.html
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

### 4. Crear carpetas estáticas
```bash
mkdir -p app/static/css app/static/js
```

### 5. Inicializar la base de datos
```bash
python -c "from app.database import engine; from app import models; models.Base.metadata.create_all(bind=engine)"
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
| `registrations` | Inscripciones al congreso |
| `sessions` | Sesiones del programa |
| `speakers` | Oradores invitados |

### Campos destacados en `abstracts`
- `titulo` — HTML (soporta cursiva, sub/superíndice, símbolos)
- `contenido_html` — HTML generado por Quill.js
- `referencias_html` — HTML de referencias bibliográficas (formato APA)
- `area_tematica` — número del 1 al 7
- `presentacion_oral` — 0 o 1

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
| `/speakers` | Speakers y mesas temáticas |
| `/venue` | Lugar, cómo llegar, alojamiento |
| `/programa` | Programa del congreso |

### Protegidas

| URL | Rol requerido |
|---|---|
| `/admin` | Admin |
| `/admin/abstracts/{id}` | Admin |
| `/admin/evaluadores` | Admin |
| `/eval` | Evaluador |
| `/eval/{id}` | Evaluador |

---

## Flujo de resúmenes
```
Ponente envía resumen en /submit (sin login)
    → Estado: pendiente
    → Admin asigna evaluadores en /admin/abstracts/{id}
    → Evaluador revisa y deja decisión + comentario en /eval/{id}
    → Si el abstract solicita oral, el evaluador recomienda o no oral
    → Admin aprueba o rechaza (decisión final)
    → Si aprobado: aparece en /abstracts público
    → Cualquier visitante puede buscar y descargar PDF
```

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

### 3. Cambiar SECRET_KEY antes de producción

En `app/auth.py`:
```python
SECRET_KEY = "clave-secreta-larga-y-aleatoria"
```

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

## Notas

- La base de datos `congreso.db` se crea automáticamente al iniciar
- Los resúmenes se almacenan como HTML limpio generado por Quill.js
- El PDF se genera al vuelo con xhtml2pdf, sin almacenamiento en disco
- El título del abstract soporta cursiva, sub/superíndice y símbolos especiales
- Las referencias van en campo separado con formato APA
- Para producción se recomienda poner Cloudflare delante del servidor

---

G. Corthey  
gcorthey@unsam.edu.ar