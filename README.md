# NANO2026 — Web del Congreso

Sistema web para el **XXIV Encuentro de Superficies y Materiales Nanoestructurados (NANO2026)**  
Campus UNSAM · San Martín, Buenos Aires · 3, 4 y 5 de junio de 2026

---

## Stack tecnológico

| Capa | Tecnología |
|---|---|
| Backend | FastAPI + Python 3.11 |
| Templates | Jinja2 |
| Base de datos | SQLite + SQLAlchemy |
| Autenticación | JWT (python-jose) + bcrypt |
| Editor de texto | Quill.js (CDN) |
| Generación PDF | xhtml2pdf |
| CSS | Tailwind CSS (CDN) |
| Servidor (producción) | Caddy |
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
│       ├── public/      # Páginas públicas
│       ├── admin/       # Panel administrador
│       └── eval/        # Panel evaluadores
├── requirements.txt
└── README.md
```

---

## Instalación

### 1. Clonar el repositorio
```bash
git clone git@gitlab.com:nano2026/web.git
cd web
```

### 2. Crear entorno virtual e instalar dependencias
```bash
python -m venv venv
source venv/bin/activate        # Linux/Mac
# venv\Scripts\activate         # Windows

pip install -r requirements.txt
```

### 3. Correr el servidor de desarrollo
```bash
uvicorn app.main:app --reload
```

Abrí `http://127.0.0.1:8000` en el navegador.

---

## Credenciales por defecto

Al iniciar por primera vez se crea automáticamente un usuario admin:

| Campo | Valor |
|---|---|
| Email | `admin@congreso.com` |
| Contraseña | `admin1234` |

⚠️ **Cambiar la contraseña antes de poner en producción.**

---

## Roles del sistema

| Rol | Acceso |
|---|---|
| Público | Home, resúmenes aprobados, buscador, formulario de envío |
| Evaluador | Panel `/eval` — ver y evaluar resúmenes asignados |
| Admin | Panel `/admin` — gestionar resúmenes, evaluadores y aprobaciones |

---

## Páginas principales

### Públicas
| URL | Descripción |
|---|---|
| `/` | Home del congreso |
| `/abstracts` | Buscador de resúmenes (por título, autor, afiliación) |
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
Ponente envía resumen en /submit
    → Estado: pendiente
    → Admin asigna evaluadores en /admin/abstracts/{id}
    → Evaluador revisa y deja decisión + comentario
    → Admin aprueba o rechaza
    → Si aprobado: aparece en /abstracts
    → Cualquier visitante puede buscar y descargar PDF
```

---

## Despliegue en producción (Raspberry Pi 5)

### Dependencias del sistema
```bash
sudo apt-get install -y libpango1.0-dev caddy
```

### Variables de entorno

Antes de producción, cambiar en `app/auth.py`:
```python
SECRET_KEY = "clave-secreta-larga-y-aleatoria"
```

### Configuración Caddy
```
nano2026.org {
    reverse_proxy localhost:8000
}
```

### Correr con uvicorn en producción
```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 2
```

---

## Notas

- La base de datos `congreso.db` se crea automáticamente al iniciar
- Los resúmenes se almacenan como HTML limpio (generado por Quill.js)
- El PDF se genera al vuelo con xhtml2pdf, sin almacenamiento en disco
- Para producción se recomienda poner Cloudflare delante del servidor

---
G. Corthey
gcorthey@unsam.edu.ar