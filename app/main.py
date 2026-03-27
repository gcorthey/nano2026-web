import json
import os
import string
import secrets
from dotenv import load_dotenv
load_dotenv()
import httpx
from datetime import datetime
from jose import JWTError
from fastapi import FastAPI, Request, Response, Depends, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from app.database import engine, get_db, SessionLocal
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from app import models
from app.auth import (
    hash_password, verify_password, create_access_token, require_admin,
    require_evaluador, get_current_user, create_revision_token, verify_revision_token,
    create_password_reset_token, verify_password_reset_token, password_reset_fingerprint
)
from xhtml2pdf import pisa
import io
import csv
from fastapi_mail import FastMail, MessageSchema, ConnectionConfig
from sqlalchemy import text
from xml.sax.saxutils import escape

models.Base.metadata.create_all(bind=engine)

def ensure_schema_updates():
    with engine.begin() as conn:
        abstract_columns = {
            row[1]
            for row in conn.execute(text("PRAGMA table_info(abstracts)")).fetchall()
        }
        if "codigo_final" not in abstract_columns:
            conn.execute(text("ALTER TABLE abstracts ADD COLUMN codigo_final VARCHAR"))
        if "tipo_resumen" not in abstract_columns:
            conn.execute(text("ALTER TABLE abstracts ADD COLUMN tipo_resumen VARCHAR NOT NULL DEFAULT 'contribucion'"))
        else:
            conn.execute(text("UPDATE abstracts SET tipo_resumen = 'contribucion' WHERE tipo_resumen IS NULL OR tipo_resumen = ''"))
        if "numero_invitado" not in abstract_columns:
            conn.execute(text("ALTER TABLE abstracts ADD COLUMN numero_invitado INTEGER"))

        user_columns = {
            row[1]
            for row in conn.execute(text("PRAGMA table_info(users)")).fetchall()
        }
        if "require_password_change" not in user_columns:
            conn.execute(text("ALTER TABLE users ADD COLUMN require_password_change INTEGER NOT NULL DEFAULT 0"))

ensure_schema_updates()



app = FastAPI(title="Congreso")
app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")

import re

AREA_CODE_MAP = {
    "1": "A",
    "2": "B",
    "3": "E",
    "4": "D",
    "5": "C",
    "6": "G",
    "7": "F",
}

AREA_NAMES = {
    "A": "Síntesis de nanomateriales",
    "B": "Autoensamblado",
    "C": "Propiedades de nanomateriales",
    "D": "Fenómenos de Superficies",
    "E": "Nanobiointerfases y procesos biológicos",
    "F": "Nanotecnología y salud",
    "G": "Aplicaciones de nanomateriales en ambiente, energía, agro, alimentos y catálisis",
}

ABSTRACT_TYPE_LABELS = {
    "contribucion": "Contribución",
    "plenaria": "Plenaria",
    "semiplenaria": "Semiplenaria",
    "talento_joven": "Talento joven",
}

INVITED_ABSTRACT_TYPES = {"plenaria", "semiplenaria", "talento_joven"}
INVITED_CODE_PREFIXES = {
    "plenaria": "P",
    "semiplenaria": "SP",
    "talento_joven": "TJ",
}

PROGRAM_DAY_ORDER = {"d1": 0, "d2": 1, "d3": 2}
PROGRAM_TYPE_OPTIONS = [
    ("apertura", "Apertura"),
    ("plenaria", "Plenaria"),
    ("semiplenaria", "Semiplenaria"),
    ("talento_joven", "Talento joven"),
    ("oral", "Sesión oral"),
    ("poster", "Póster"),
    ("empresas", "Industria"),
    ("break", "Break"),
    ("social", "Social"),
    ("cierre", "Cierre"),
]
PROGRAM_KIND_OPTIONS = [
    ("shared", "Actividad común"),
    ("parallel", "Sesiones paralelas"),
]
DEFAULT_PROGRAM_SCHEDULE = {
    "d1": {
        "label": "Mié 3/6",
        "items": [
            {"kind": "shared", "start": "08:30", "end": "09:30", "title": "Acreditación y bienvenida", "type": "apertura", "location": "Auditorio principal"},
            {"kind": "shared", "start": "09:30", "end": "10:30", "title": "Conferencia plenaria 1 — Por confirmar", "type": "plenaria", "location": "Auditorio principal"},
            {"kind": "shared", "start": "10:30", "end": "11:00", "title": "☕ Coffee break", "type": "break", "location": "Espacio común"},
            {"kind": "parallel", "start": "11:00", "end": "11:30", "type": "oral", "tracks": [
                {"title": "Conferencia Semiplenaria 1", "type": "semiplenaria", "room": "Sala 1"},
                {"title": "Conferencia Semiplenaria 2", "type": "semiplenaria", "room": "Sala 2"},
            ]},
            {"kind": "parallel", "start": "11:30", "end": "12:30", "type": "oral", "tracks": [
                {"title": "Sesión oral", "type": "oral", "room": "Sala 1"},
                {"title": "Sesión oral", "type": "oral", "room": "Sala 2"},
            ]},
            {"kind": "shared", "start": "12:30", "end": "14:00", "title": "🍽️ Almuerzo", "type": "break", "location": "Espacio común"},
            {"kind": "shared", "start": "14:00", "end": "15:00", "title": "Conferencia plenaria 2 — Por confirmar", "type": "plenaria", "location": "Auditorio principal"},
            {"kind": "parallel", "start": "15:00", "end": "15:30", "type": "oral", "tracks": [
                {"title": "Talento joven 1", "type": "talento_joven", "room": "Sala 1"},
                {"title": "Sesión oral", "type": "talento_joven", "room": "Sala 2"},
            ]},
            {"kind": "shared", "start": "15:30", "end": "16:00", "title": "☕ Coffee break", "type": "break", "location": "Espacio común"},
            {"kind": "shared", "start": "16:00", "end": "17:00", "title": "Mesa redonda: Industria", "type": "plenaria", "location": "Auditorio principal"},
            {"kind": "shared", "start": "17:00", "end": "19:00", "title": "Sesión de posters 1", "type": "poster", "location": "Espacio común"},
            {"kind": "shared", "start": "19:00", "end": "20:00", "title": "Evento de bienvenida", "type": "poster", "location": "Espacio común"},
        ],
    },
    "d2": {
        "label": "Mié 3/6",
        "items": [
            {"kind": "shared", "start": "09:00", "end": "10:00", "title": "Conferencia plenaria 4 — Por confirmar", "type": "plenaria", "location": "Auditorio principal"},
            {"kind": "shared", "start": "10:00", "end": "10:30", "title": "Charla Sponsor", "type": "break", "location": "Espacio común"},
            {"kind": "shared", "start": "10:30", "end": "11:00", "title": "☕ Coffee break", "type": "break", "location": "Espacio común"},
            {"kind": "parallel", "start": "11:00", "end": "11:30", "type": "oral", "tracks": [
                {"title": "Conferencia Semiplenaria 3", "type": "semiplenaria", "room": "Sala 1"},
                {"title": "Conferencia Semiplenaria 4", "type": "semiplenaria", "room": "Sala 2"},
            ]},
            {"kind": "parallel", "start": "11:30", "end": "12:30", "type": "oral", "tracks": [
                {"title": "Sesión oral", "type": "oral", "room": "Sala 1"},
                {"title": "Sesión oral", "type": "oral", "room": "Sala 2"},
            ]},
            {"kind": "shared", "start": "12:30", "end": "14:00", "title": "🍽️ Almuerzo", "type": "break", "location": "Espacio común"},
            {"kind": "shared", "start": "14:00", "end": "15:00", "title": "Conferencia plenaria 4 — Por confirmar", "type": "plenaria", "location": "Auditorio principal"},
            {"kind": "parallel", "start": "15:00", "end": "15:30", "type": "oral", "tracks": [
                {"title": "Talento joven 2", "type": "talento_joven", "room": "Sala 1"},
                {"title": "Sesión oral", "type": "talento_joven", "room": "Sala 2"},
            ]},
            {"kind": "shared", "start": "15:30", "end": "16:00", "title": "☕ Coffee break", "type": "break", "location": "Espacio común"},
            {"kind": "shared", "start": "16:00", "end": "17:00", "title": "Mesa redonda: Educación", "type": "plenaria", "location": "Auditorio principal"},
            {"kind": "shared", "start": "17:00", "end": "19:00", "title": "Sesión de posters 2", "type": "poster", "location": "Espacio común"},
        ],
    },
    "d3": {
        "label": "Mié 3/6",
        "items": [
            {"kind": "shared", "start": "09:00", "end": "10:00", "title": "Conferencia plenaria 5 — Por confirmar", "type": "plenaria", "location": "Auditorio principal"},
            {"kind": "shared", "start": "10:00", "end": "10:30", "title": "Charla Sponsor", "type": "break", "location": "Espacio común"},
            {"kind": "shared", "start": "10:30", "end": "11:00", "title": "☕ Coffee break", "type": "break", "location": "Espacio común"},
            {"kind": "parallel", "start": "11:00", "end": "11:30", "type": "oral", "tracks": [
                {"title": "Conferencia Semiplenaria 5", "type": "semiplenaria", "room": "Sala 1"},
                {"title": "Conferencia Semiplenaria 6", "type": "semiplenaria", "room": "Sala 2"},
            ]},
            {"kind": "parallel", "start": "11:30", "end": "12:00", "type": "oral", "tracks": [
                {"title": "Sesión oral", "type": "oral", "room": "Sala 1"},
                {"title": "Sesión oral", "type": "oral", "room": "Sala 2"},
            ]},
            {"kind": "shared", "start": "12:00", "end": "12:30", "title": "Presentación de la Asociación Argentina de Nanotecnología", "type": "break", "location": "Espacio común"},
            {"kind": "shared", "start": "12:00", "end": "12:30", "title": "Acto de finalización y premiación", "type": "break", "location": "Espacio común"},
        ],
    },
}

def strip_tags(text: str) -> str:
    return re.sub(r'<[^>]+>', '', text or '').strip()

def normalize_area_code(area_code: str | None) -> str | None:
    if area_code is None:
        return None
    return AREA_CODE_MAP.get(area_code, area_code)

def normalize_abstract_type(value: str | None) -> str:
    normalized = (value or "contribucion").strip().lower().replace(" ", "_")
    return normalized if normalized in ABSTRACT_TYPE_LABELS else "contribucion"


def normalize_program_type(value: str | None) -> str:
    normalized = (value or "break").strip().lower().replace(" ", "_")
    allowed = {option[0] for option in PROGRAM_TYPE_OPTIONS}
    return normalized if normalized in allowed else "break"


def normalize_program_kind(value: str | None) -> str:
    normalized = (value or "shared").strip().lower()
    return normalized if normalized in {"shared", "parallel"} else "shared"


def seed_program_entries(db: Session) -> None:
    if db.query(models.ProgramEntry).count() > 0:
        return

    for day_key, day in DEFAULT_PROGRAM_SCHEDULE.items():
        for index, item in enumerate(day["items"]):
            entry = models.ProgramEntry(
                day_key=day_key,
                day_label=day["label"],
                position=index,
                kind=item["kind"],
                start_time=item["start"],
                end_time=item["end"],
                item_type=item["type"],
                title=item.get("title"),
                location=item.get("location"),
            )
            if item["kind"] == "parallel":
                track_1 = item["tracks"][0]
                track_2 = item["tracks"][1]
                entry.track_1_title = track_1.get("title")
                entry.track_1_type = track_1.get("type")
                entry.track_1_room = track_1.get("room")
                entry.track_2_title = track_2.get("title")
                entry.track_2_type = track_2.get("type")
                entry.track_2_room = track_2.get("room")
            db.add(entry)
    db.commit()


def build_program_schedule(db: Session) -> dict[str, dict[str, object]]:
    seed_program_entries(db)
    entries = (
        db.query(models.ProgramEntry)
        .order_by(models.ProgramEntry.day_key, models.ProgramEntry.position, models.ProgramEntry.id)
        .all()
    )
    schedule: dict[str, dict[str, object]] = {}
    for entry in entries:
        day = schedule.setdefault(entry.day_key, {"label": entry.day_label, "items": []})
        day["label"] = entry.day_label
        if entry.kind == "parallel":
            day["items"].append({
                "kind": "parallel",
                "start": entry.start_time,
                "end": entry.end_time,
                "type": entry.item_type,
                "tracks": [
                    {
                        "title": entry.track_1_title or "",
                        "type": normalize_program_type(entry.track_1_type),
                        "room": entry.track_1_room or "",
                    },
                    {
                        "title": entry.track_2_title or "",
                        "type": normalize_program_type(entry.track_2_type),
                        "room": entry.track_2_room or "",
                    },
                ],
            })
        else:
            day["items"].append({
                "kind": "shared",
                "start": entry.start_time,
                "end": entry.end_time,
                "title": entry.title or "",
                "type": normalize_program_type(entry.item_type),
                "location": entry.location or "",
            })

    return dict(sorted(schedule.items(), key=lambda item: PROGRAM_DAY_ORDER.get(item[0], 999)))


def next_program_position(db: Session, day_key: str) -> int:
    count = db.query(models.ProgramEntry).filter(models.ProgramEntry.day_key == day_key).count()
    return count


def compact_program_positions(db: Session, day_key: str) -> None:
    entries = (
        db.query(models.ProgramEntry)
        .filter(models.ProgramEntry.day_key == day_key)
        .order_by(models.ProgramEntry.position, models.ProgramEntry.id)
        .all()
    )
    for index, entry in enumerate(entries):
        entry.position = index
    db.commit()


def render_program_entry_form(
    request: Request,
    program_entry: models.ProgramEntry | None = None,
    *,
    error: str | None = None,
) -> HTMLResponse:
    entry = program_entry or models.ProgramEntry(
        day_key="d1",
        day_label="Mié 3/6",
        kind="shared",
        start_time="09:00",
        end_time="10:00",
        item_type="break",
    )
    is_create = program_entry is None
    action = "/admin/programa/new" if is_create else f"/admin/programa/{entry.id}/edit"
    return templates.TemplateResponse("admin/programa_edit.html", {
        "request": request,
        "entry": entry,
        "is_create": is_create,
        "action": action,
        "error": error,
        "program_type_options": PROGRAM_TYPE_OPTIONS,
        "program_kind_options": PROGRAM_KIND_OPTIONS,
    })

def parse_optional_positive_int(value: str | None) -> int | None:
    raw = (value or "").strip()
    if not raw:
        return None
    try:
        parsed = int(raw)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None

def invited_code_for(abstract: models.Abstract) -> str | None:
    prefix = INVITED_CODE_PREFIXES.get(abstract.tipo_resumen)
    if not prefix or abstract.numero_invitado is None:
        return None
    return f"{prefix}{int(abstract.numero_invitado):02d}"

def calculate_final_code(abstract: models.Abstract) -> str | None:
    if abstract.estado != models.EstadoEnum.aprobado:
        return None
    if abstract.tipo_resumen in INVITED_ABSTRACT_TYPES:
        return invited_code_for(abstract)
    area_code = normalize_area_code(abstract.area_tematica)
    if not area_code:
        return None
    base_code = f"{area_code}{abstract.id:02d}"
    if not abstract.presentacion_oral:
        return base_code
    if abstract.tipo_asignado_admin == "oral":
        return f"{base_code}-O"
    if abstract.tipo_asignado_admin == "poster":
        return base_code
    return None

def sync_final_code(abstract: models.Abstract):
    abstract.codigo_final = calculate_final_code(abstract)

def backfill_final_codes():
    db = SessionLocal()
    try:
        abstracts = db.query(models.Abstract).all()
        changed = False
        for abstract in abstracts:
            normalized_area = normalize_area_code(abstract.area_tematica)
            if abstract.area_tematica != normalized_area:
                abstract.area_tematica = normalized_area
                changed = True
            new_code = calculate_final_code(abstract)
            if abstract.codigo_final != new_code:
                abstract.codigo_final = new_code
                changed = True
        if changed:
            db.commit()
    finally:
        db.close()


SITE_NAME = "NANO2026"
DEFAULT_OG_IMAGE_PATH = "/static/og/LOGO.png"


def get_public_base_url(request: Request) -> str:
    return os.getenv("PUBLIC_BASE_URL", str(request.base_url).rstrip("/"))


def get_recaptcha_site_key() -> str:
    return os.getenv("RECAPTCHA_SITE_KEY", "")


def absolute_url(request: Request, path: str) -> str:
    if path.startswith("http://") or path.startswith("https://"):
        return path
    return f"{get_public_base_url(request)}{path}"


def trim_text(text: str | None, max_length: int = 160) -> str:
    normalized = " ".join((text or "").split())
    if len(normalized) <= max_length:
        return normalized
    return normalized[: max_length - 1].rstrip() + "…"


def build_structured_data(
    request: Request,
    *,
    page_title: str,
    page_description: str,
    canonical_url: str,
    include_event: bool = False,
    language: str = "es-AR"
) -> str:
    base_url = get_public_base_url(request)
    data = {
        "@context": "https://schema.org",
        "@graph": [
            {
                "@type": "Organization",
                "@id": f"{base_url}#organization",
                "name": SITE_NAME,
                "url": base_url,
                "email": "nano2026@unsam.edu.ar",
                "sameAs": [
                    "https://www.instagram.com/encuentronano2026/"
                ]
            },
            {
                "@type": "WebSite",
                "@id": f"{base_url}#website",
                "url": base_url,
                "name": SITE_NAME,
                "inLanguage": language
            },
            {
                "@type": "WebPage",
                "@id": f"{canonical_url}#webpage",
                "url": canonical_url,
                "name": page_title,
                "description": page_description,
                "isPartOf": {
                    "@id": f"{base_url}#website"
                },
                "about": {
                    "@id": f"{base_url}#organization"
                },
                "inLanguage": language
            }
        ]
    }

    if include_event:
        data["@graph"].append({
            "@type": "Event",
            "@id": f"{base_url}#event",
            "name": "NANO2026 - XXIV Encuentro de Superficies y Materiales Nanoestructurados",
            "description": page_description,
            "eventAttendanceMode": "https://schema.org/OfflineEventAttendanceMode",
            "eventStatus": "https://schema.org/EventScheduled",
            "startDate": "2026-06-03",
            "endDate": "2026-06-05",
            "url": canonical_url,
            "image": [
                absolute_url(request, DEFAULT_OG_IMAGE_PATH)
            ],
            "offers": {
                "@type": "AggregateOffer",
                "url": f"{base_url}/inscripcion",
                "priceCurrency": "USD",
                "lowPrice": 35,
                "highPrice": 160,
                "offerCount": 15,
                "availability": "https://schema.org/InStock",
                "validFrom": "2025-12-01T00:00:00-03:00"
            },
            "performer": [
                {
                    "@type": "Person",
                    "name": "Roman Krahne"
                },
                {
                    "@type": "Person",
                    "name": "Fabrizio Messina"
                },
                {
                    "@type": "Person",
                    "name": "Daniel Lanzillotti Kimura"
                },
                {
                    "@type": "Person",
                    "name": "Ana Flávia Nogueira"
                },
                {
                    "@type": "Person",
                    "name": "María Lidia Herrera"
                },
                {
                    "@type": "Person",
                    "name": "Lilo Pozzo"
                }
            ],
            "location": {
                "@type": "Place",
                "name": "Campus UNSAM",
                "address": {
                    "@type": "PostalAddress",
                    "addressLocality": "San Martin",
                    "addressRegion": "Buenos Aires",
                    "addressCountry": "AR"
                }
            },
            "organizer": {
                "@id": f"{base_url}#organization"
            }
        })

    return json.dumps(data, ensure_ascii=False, separators=(",", ":"))


def public_page_context(
    request: Request,
    *,
    title: str,
    description: str,
    canonical_path: str,
    og_image_path: str = DEFAULT_OG_IMAGE_PATH,
    include_event_schema: bool = False,
    language: str = "es-AR",
    html_lang: str | None = None,
    og_locale: str | None = None,
    extra: dict | None = None
) -> dict:
    canonical_url = absolute_url(request, canonical_path)
    resolved_html_lang = html_lang or language.split("-")[0]
    resolved_og_locale = og_locale or language.replace("-", "_")
    context = {
        "request": request,
        "page_title": title,
        "meta_description": trim_text(description, 160),
        "canonical_url": canonical_url,
        "og_image_url": absolute_url(request, og_image_path),
        "html_lang": resolved_html_lang,
        "og_locale": resolved_og_locale,
        "structured_data": build_structured_data(
            request,
            page_title=title,
            page_description=trim_text(description, 220),
            canonical_url=canonical_url,
            include_event=include_event_schema,
            language=language
        )
    }
    if extra:
        context.update(extra)
    return context


def public_urls(request: Request) -> list[str]:
    base_url = get_public_base_url(request)
    return [
        f"{base_url}/",
        f"{base_url}/about",
        f"{base_url}/inscripcion",
        f"{base_url}/programa",
        f"{base_url}/speakers",
        f"{base_url}/venue",
        f"{base_url}/sponsors",
        f"{base_url}/en/sponsors",
        f"{base_url}/submit",
        f"{base_url}/circulares",
        f"{base_url}/contacto",
        f"{base_url}/abstracts",
    ]

def get_accepted_with_revision_ids(db: Session) -> set[int]:
    log_rows = db.query(models.AbstractLog.abstract_id).filter(
        models.AbstractLog.event_type == "revision_email_sent"
    ).distinct().all()
    flag_rows = db.query(models.AbstractAcceptanceFlag.abstract_id).filter(
        models.AbstractAcceptanceFlag.minor_revision == 1
    ).distinct().all()
    return {
        abstract_id
        for (abstract_id,) in log_rows + flag_rows
    }

def build_admin_abstracts_query(
    db: Session,
    estado: str,
    area: str,
    aprobado_tipo: str
):
    query = db.query(models.Abstract)
    area = normalize_area_code(area)

    if estado != "todos":
        query = query.filter(models.Abstract.estado == estado)
    if area != "todas":
        query = query.filter(models.Abstract.area_tematica == area)

    accepted_with_revision_ids = get_accepted_with_revision_ids(db)
    if estado == "aprobado":
        if aprobado_tipo == "aprobado":
            if accepted_with_revision_ids:
                query = query.filter(~models.Abstract.id.in_(accepted_with_revision_ids))
        elif aprobado_tipo == "aprobado_con_rev":
            if accepted_with_revision_ids:
                query = query.filter(models.Abstract.id.in_(accepted_with_revision_ids))
            else:
                query = query.filter(models.Abstract.id == -1)

    return query, accepted_with_revision_ids

def set_minor_revision_flag(db: Session, abstract: models.Abstract, enabled: bool):
    flag = db.query(models.AbstractAcceptanceFlag).filter(
        models.AbstractAcceptanceFlag.abstract_id == abstract.id
    ).first()
    if not flag:
        flag = models.AbstractAcceptanceFlag(
            abstract_id=abstract.id,
            minor_revision=1 if enabled else 0,
        )
        db.add(flag)
    else:
        flag.minor_revision = 1 if enabled else 0

def apply_abstract_edit_from_form(abstract: models.Abstract, form_data, db: Session):
    abstract.titulo = form_data.get("titulo", "").strip()
    abstract.tipo_resumen = normalize_abstract_type(form_data.get("tipo_resumen"))
    abstract.numero_invitado = parse_optional_positive_int(form_data.get("numero_invitado"))
    abstract.email_autor = form_data.get("email_autor", "").strip()
    abstract.contenido_html = form_data.get("contenido_html", "").strip()
    abstract.referencias_html = form_data.get("referencias_html", "")
    if abstract.tipo_resumen in INVITED_ABSTRACT_TYPES:
        abstract.area_tematica = None
        abstract.presentacion_oral = 1
        abstract.tipo_asignado_admin = "oral"
    else:
        abstract.area_tematica = normalize_area_code(form_data.get("area_tematica", "").strip())
        abstract.presentacion_oral = int(form_data.get("presentacion_oral", 0))
        abstract.numero_invitado = None
    abstract.tiene_referencias = 1 if strip_tags(abstract.referencias_html) else 0

    autor_count = int(form_data.get("autor_count", 0))
    afil_count = int(form_data.get("afil_count", 0))

    db.query(models.Autor).filter(models.Autor.abstract_id == abstract.id).delete()
    db.query(models.Afiliacion).filter(models.Afiliacion.abstract_id == abstract.id).delete()
    db.flush()

    for i in range(1, afil_count + 1):
        nombre_afil = form_data.get(f"afil_nombre_{i}", "").strip()
        if nombre_afil:
            db.add(models.Afiliacion(abstract_id=abstract.id, nombre=nombre_afil, orden=i))

    presentador_idx = form_data.get("presentador", "1")
    autor_presentador = ""
    for i in range(1, autor_count + 1):
        nombre_autor = form_data.get(f"autor_nombre_{i}", "").strip()
        afils_str = form_data.get(f"autor_afils_{i}", "").strip()
        if nombre_autor:
            es_presentador = 1 if str(i) == str(presentador_idx) else 0
            db.add(models.Autor(
                abstract_id=abstract.id,
                nombre=nombre_autor,
                orden=i,
                es_presentador=es_presentador,
                afiliaciones_ids=afils_str
            ))
            if es_presentador:
                autor_presentador = nombre_autor

    abstract.autor = autor_presentador
    first_affiliation = db.query(models.Afiliacion).filter(
        models.Afiliacion.abstract_id == abstract.id
    ).order_by(models.Afiliacion.orden.asc()).first()
    abstract.afiliacion = first_affiliation.nombre if first_affiliation else ""
    sync_final_code(abstract)


# --- Crea admin por defecto si no existe ---
def create_default_admin():
    db = next(get_db())
    exists = db.query(models.User).filter(models.User.email == "admin@congreso.com").first()
    if not exists:
        admin = models.User(
            email="admin@congreso.com",
            nombre="Administrador",
            password_hash=hash_password("admin1234"),
            role=models.RoleEnum.admin,
            require_password_change=1
        )
        db.add(admin)
        db.commit()

create_default_admin()
backfill_final_codes()

def get_password_reset_user_or_400(token: str, db: Session) -> models.User:
    try:
        payload = verify_password_reset_token(token)
        user_id = int(payload.get("user_id"))
        email = payload.get("email", "")
        expected_fingerprint = payload.get("pwd", "")
    except (JWTError, TypeError, ValueError):
        raise HTTPException(status_code=400, detail="Link inválido o vencido")

    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user or user.email != email:
        raise HTTPException(status_code=400, detail="Link inválido o vencido")
    if password_reset_fingerprint(user.password_hash) != expected_fingerprint:
        raise HTTPException(status_code=400, detail="Link inválido o vencido")
    return user

# --- Login ---
@app.get("/login", response_class=HTMLResponse)
def login_form(request: Request):
    return templates.TemplateResponse("login.html", {
        "request": request,
        "error": None,
        "success": None
    })

@app.post("/login")
def login(request: Request, response: Response, email: str = Form(...), password: str = Form(...), db: Session = Depends(get_db)):
    user = db.query(models.User).filter(models.User.email == email).first()
    if not user or not verify_password(password, user.password_hash):
        return templates.TemplateResponse("login.html", {
            "request": request,
            "error": "Email o contraseña incorrectos",
            "success": None
        })
    token = create_access_token({"sub": user.email, "role": user.role})
    target_url = "/force-password-change" if user.require_password_change else ("/admin" if user.role == models.RoleEnum.admin else "/eval")
    resp = RedirectResponse(url=target_url, status_code=302)
    resp.set_cookie("access_token", token, httponly=True)
    return resp

@app.get("/force-password-change", response_class=HTMLResponse)
def force_password_change_form(
    request: Request,
    current_user: models.User = Depends(get_current_user)
):
    if not current_user.require_password_change:
        return RedirectResponse(url="/admin" if current_user.role == models.RoleEnum.admin else "/eval", status_code=302)
    return templates.TemplateResponse("reset_password.html", {
        "request": request,
        "token": None,
        "error": None,
        "force_change": True
    })

@app.post("/force-password-change", response_class=HTMLResponse)
def force_password_change_submit(
    request: Request,
    password: str = Form(...),
    password_confirm: str = Form(...),
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    if not current_user.require_password_change:
        return RedirectResponse(url="/admin" if current_user.role == models.RoleEnum.admin else "/eval", status_code=302)

    if password != password_confirm:
        return templates.TemplateResponse("reset_password.html", {
            "request": request,
            "token": None,
            "error": "Las contraseñas no coinciden.",
            "force_change": True
        }, status_code=400)

    if len(password) < 8:
        return templates.TemplateResponse("reset_password.html", {
            "request": request,
            "token": None,
            "error": "La contraseña debe tener al menos 8 caracteres.",
            "force_change": True
        }, status_code=400)

    current_user.password_hash = hash_password(password)
    current_user.require_password_change = 0
    db.commit()

    return RedirectResponse(url="/admin" if current_user.role == models.RoleEnum.admin else "/eval", status_code=302)

@app.get("/forgot-password", response_class=HTMLResponse)
def forgot_password_form(request: Request):
    return templates.TemplateResponse("forgot_password.html", {
        "request": request,
        "error": None,
        "success": None
    })

@app.post("/forgot-password", response_class=HTMLResponse)
async def forgot_password_submit(
    request: Request,
    email: str = Form(...),
    db: Session = Depends(get_db)
):
    user = db.query(models.User).filter(models.User.email == email.strip()).first()
    success_message = "Si existe una cuenta con ese email, enviamos un enlace para restablecer la contraseña."

    if not user:
        return templates.TemplateResponse("forgot_password.html", {
            "request": request,
            "error": None,
            "success": success_message
        })

    token = create_password_reset_token(user.id, user.email, user.password_hash)
    base_url = os.getenv("PUBLIC_BASE_URL", str(request.base_url).rstrip("/"))
    reset_url = f"{base_url}/reset-password/{token}"
    body = (
        f"Hola {user.nombre},\n\n"
        f"Recibimos una solicitud para restablecer la contraseña de tu cuenta en NANO2026.\n\n"
        f"Podés definir una nueva contraseña desde este enlace:\n{reset_url}\n\n"
        f"El enlace vence en 2 horas y deja de servir si la contraseña ya fue cambiada.\n\n"
        f"Si no hiciste esta solicitud, podés ignorar este correo.\n\n"
        f"Saludos,\n"
        f"Comité organizador NANO2026\n"
    )
    mensaje = MessageSchema(
        subject="[NANO2026] Restablecer contraseña",
        recipients=[user.email],
        body=body,
        subtype="plain"
    )
    fm = FastMail(mail_config)
    try:
        await fm.send_message(mensaje)
    except Exception:
        return templates.TemplateResponse("forgot_password.html", {
            "request": request,
            "error": "No se pudo enviar el correo de recuperación. Revisá la configuración SMTP e intentá de nuevo.",
            "success": None
        }, status_code=500)

    return templates.TemplateResponse("forgot_password.html", {
        "request": request,
        "error": None,
        "success": success_message
    })

@app.get("/reset-password/{token}", response_class=HTMLResponse)
def reset_password_form(
    token: str,
    request: Request,
    db: Session = Depends(get_db)
):
    get_password_reset_user_or_400(token, db)
    return templates.TemplateResponse("reset_password.html", {
        "request": request,
        "token": token,
        "error": None
    })

@app.post("/reset-password/{token}", response_class=HTMLResponse)
def reset_password_submit(
    token: str,
    request: Request,
    password: str = Form(...),
    password_confirm: str = Form(...),
    db: Session = Depends(get_db)
):
    if password != password_confirm:
        return templates.TemplateResponse("reset_password.html", {
            "request": request,
            "token": token,
            "error": "Las contraseñas no coinciden."
        }, status_code=400)

    if len(password) < 8:
        return templates.TemplateResponse("reset_password.html", {
            "request": request,
            "token": token,
            "error": "La contraseña debe tener al menos 8 caracteres."
        }, status_code=400)

    user = get_password_reset_user_or_400(token, db)
    user.password_hash = hash_password(password)
    user.require_password_change = 0
    db.commit()

    return templates.TemplateResponse("login.html", {
        "request": request,
        "error": None,
        "success": "Contraseña actualizada. Ya podés iniciar sesión."
    })

@app.get("/logout")
def logout():
    resp = RedirectResponse(url="/login", status_code=302)
    resp.delete_cookie("access_token")
    return resp



# --- Envío público de abstracts ---
@app.get("/submit", response_class=HTMLResponse)
def submit_form(request: Request):
    return templates.TemplateResponse(
        "public/submit.html",
        {
            **public_page_context(
                request,
                title="Envío de resúmenes | NANO2026",
                description=(
                    "Presentá tu resumen para el NANO2026 y participá del encuentro "
                    "de superficies y materiales nanoestructurados."
                ),
                canonical_path="/submit"
            ),
            "recaptcha_site_key": get_recaptcha_site_key(),
            "initial_submit_data": {
                "tipo_resumen": "contribucion",
                "titulo": "",
                "email_autor": "",
                "area_tematica": "",
                "presentacion_oral": "",
                "contenido_html": "",
                "referencias_html": "",
                "tiene_referencias": 0,
                "presentador": "",
                "autores": [],
                "afiliaciones": [],
            }
        }
    )
@app.post("/submit", response_class=HTMLResponse)
async def submit_abstract(
    request: Request,
    titulo: str = Form(...),
    presentacion_oral: int = Form(...),
    email_autor: str = Form(...),
    contenido_html: str = Form(...),
    autor_count: int = Form(...),
    afil_count: int = Form(...),
    area_tematica: str = Form(...),
    referencias_html: str = Form(""),
    tiene_referencias: int = Form(0),
    recaptcha_token: str = Form(""),
    db: Session = Depends(get_db)
):
    form_state = {
        "tipo_resumen": "contribucion",
        "titulo": titulo,
        "email_autor": email_autor,
        "area_tematica": normalize_area_code(area_tematica) or area_tematica,
        "presentacion_oral": str(presentacion_oral),
        "contenido_html": contenido_html,
        "referencias_html": referencias_html,
        "tiene_referencias": 1 if tiene_referencias else 0,
        "presentador": request._form.get("presentador", "").strip(),
        "autores": [],
        "afiliaciones": [],
    }
    for i in range(1, autor_count + 1):
        form_state["autores"].append({
            "index": i,
            "nombre": request._form.get(f"autor_nombre_{i}", ""),
            "afils": request._form.get(f"autor_afils_{i}", ""),
        })
    for i in range(1, afil_count + 1):
        form_state["afiliaciones"].append({
            "index": i,
            "nombre": request._form.get(f"afil_nombre_{i}", ""),
        })

    def submit_error(message: str, status_code: int = 400):
        return templates.TemplateResponse("public/submit.html", {
            **public_page_context(
                request,
                title="Envío de resúmenes | NANO2026",
                description=(
                    "Presentá tu resumen para el NANO2026 y participá del encuentro "
                    "de superficies y materiales nanoestructurados."
                ),
                canonical_path="/submit"
            ),
            "recaptcha_site_key": get_recaptcha_site_key(),
            "initial_submit_data": form_state,
            "error": message
        }, status_code=status_code)

    titulo = titulo.strip()
    email_autor = email_autor.strip()
    resumen_texto = strip_tags(contenido_html)
    referencias_texto = strip_tags(referencias_html)

    if not titulo:
        return submit_error("El título no puede estar vacío.")
    if not email_autor:
        return submit_error("El email del autor presentador es obligatorio.")
    if not resumen_texto:
        return submit_error("El resumen no puede estar vacío.")
    if len(resumen_texto) > 2500:
        return submit_error("El resumen no puede superar los 2500 caracteres.")
    if tiene_referencias and len(referencias_texto) > 750:
        return submit_error("Las referencias bibliográficas no pueden superar los 750 caracteres.")

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "https://www.google.com/recaptcha/api/siteverify",
            data={
                "secret": os.getenv("RECAPTCHA_SECRET"),
                "response": recaptcha_token
            }
        )
        result = resp.json()

    if not result.get("success"):
        print("reCAPTCHA result:", result)
        return submit_error("Verificación fallida. Por favor intentá de nuevo.")

    afiliaciones_data: list[tuple[int, str]] = []
    for i in range(1, afil_count + 1):
        nombre_afil = request._form.get(f"afil_nombre_{i}", "").strip()
        if nombre_afil:
            afiliaciones_data.append((i, nombre_afil))

    if not afiliaciones_data:
        return submit_error("Debe haber al menos una afiliación.")

    autores_data: list[tuple[int, str, str]] = []
    for i in range(1, autor_count + 1):
        nombre_autor = request._form.get(f"autor_nombre_{i}", "").strip()
        afils_str = request._form.get(f"autor_afils_{i}", "").strip()
        if nombre_autor:
            autores_data.append((i, nombre_autor, afils_str))

    if not autores_data:
        return submit_error("Debe haber al menos un autor.")

    presentador_idx = request._form.get("presentador", "").strip()
    presentadores = [autor for autor in autores_data if str(autor[0]) == presentador_idx]
    if len(presentadores) != 1:
        return submit_error("Debe seleccionarse exactamente un autor presentador.")

    abstract = models.Abstract(
        tipo_resumen="contribucion",
        titulo=titulo,
        autor=presentadores[0][1],
        afiliacion=afiliaciones_data[0][1],
        email_autor=email_autor,
        contenido_html=contenido_html,
        referencias_html=referencias_html if tiene_referencias else "",
        tiene_referencias=1 if tiene_referencias else 0,
        presentacion_oral=presentacion_oral,
        area_tematica=normalize_area_code(area_tematica),
    )
    db.add(abstract)
    db.flush()  # para obtener el id

    # Guardar afiliaciones
    for orden, nombre_afil in afiliaciones_data:
        afil = models.Afiliacion(
            abstract_id=abstract.id,
            nombre=nombre_afil,
            orden=orden
        )
        db.add(afil)

    # Guardar autores
    for orden, nombre_autor, afils_str in autores_data:
        autor = models.Autor(
            abstract_id=abstract.id,
            nombre=nombre_autor,
            orden=orden,
            es_presentador=1 if str(orden) == presentador_idx else 0,
            afiliaciones_ids=afils_str
        )
        db.add(autor)

    db.commit()

    return templates.TemplateResponse("public/submit.html", {
        **public_page_context(
            request,
            title="Envío de resúmenes | NANO2026",
            description=(
                "Presentá tu resumen para el NANO2026 y participá del encuentro "
                "de superficies y materiales nanoestructurados."
            ),
            canonical_path="/submit"
        ),
        "recaptcha_site_key": get_recaptcha_site_key(),
        "initial_submit_data": {
            "tipo_resumen": "contribucion",
            "titulo": "",
            "email_autor": "",
            "area_tematica": "",
            "presentacion_oral": "",
            "contenido_html": "",
            "referencias_html": "",
            "tiene_referencias": 0,
            "presentador": "",
            "autores": [],
            "afiliaciones": [],
        },
        "success": True
    })
# --- Admin: lista de abstracts ---
@app.get("/admin", response_class=HTMLResponse)
def admin_abstracts(
    request: Request,
    estado: str = "todos",
    area: str = "todas",
    aprobado_tipo: str = "todos",
    current_user: models.User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    area = normalize_area_code(area)
    query, accepted_with_revision_ids = build_admin_abstracts_query(db, estado, area, aprobado_tipo)
    abstracts = query.order_by(models.Abstract.fecha_envio.desc()).all()
    evaluadores = db.query(models.User).filter(models.User.role == "evaluador").all()
    return templates.TemplateResponse("admin/abstracts.html", {
        "request": request,
        "abstracts": abstracts,
        "accepted_with_revision_ids": accepted_with_revision_ids,
        "estado_filtro": estado,
        "area_filtro": area,
        "aprobado_tipo_filtro": aprobado_tipo,
        "current_user": current_user,
        "evaluadores": evaluadores,
        "abstract_type_labels": ABSTRACT_TYPE_LABELS,
    })

@app.get("/admin/abstracts/new", response_class=HTMLResponse)
def admin_new_abstract_form(
    request: Request,
    current_user: models.User = Depends(require_admin),
):
    abstract = models.Abstract(
        tipo_resumen="plenaria",
        numero_invitado=1,
        titulo="",
        autor="",
        afiliacion="",
        email_autor="",
        contenido_html="",
        referencias_html="",
        tiene_referencias=0,
        presentacion_oral=1,
        area_tematica=None,
    )
    return templates.TemplateResponse("admin/abstract_edit.html", {
        "request": request,
        "abstract": abstract,
        "create_mode": True,
        "form_action": "/admin/abstracts/new",
        "submit_label": "Crear abstract",
        "cancel_url": "/admin",
        "abstract_type_labels": ABSTRACT_TYPE_LABELS,
        "current_user": current_user,
    })

@app.post("/admin/abstracts/new", response_class=HTMLResponse)
async def admin_create_abstract(
    request: Request,
    titulo: str = Form(...),
    email_autor: str = Form(...),
    contenido_html: str = Form(...),
    autor_count: int = Form(...),
    afil_count: int = Form(...),
    area_tematica: str = Form(""),
    referencias_html: str = Form(""),
    tipo_resumen: str = Form("contribucion"),
    numero_invitado: str = Form(""),
    current_user: models.User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    form_data = await request.form()
    tipo_resumen = normalize_abstract_type(tipo_resumen)
    titulo = titulo.strip()
    email_autor = email_autor.strip()
    resumen_texto = strip_tags(contenido_html)
    referencias_texto = strip_tags(referencias_html)
    presentacion_oral = 1 if tipo_resumen in INVITED_ABSTRACT_TYPES else 0
    invited_number = parse_optional_positive_int(numero_invitado)

    abstract = models.Abstract(
        tipo_resumen=tipo_resumen,
        numero_invitado=invited_number,
        titulo=titulo,
        autor="",
        afiliacion="",
        email_autor=email_autor,
        contenido_html=contenido_html,
        referencias_html=referencias_html,
        tiene_referencias=1 if referencias_texto else 0,
        presentacion_oral=presentacion_oral,
        area_tematica=None if tipo_resumen in INVITED_ABSTRACT_TYPES else normalize_area_code(area_tematica),
        estado=models.EstadoEnum.aprobado if tipo_resumen in INVITED_ABSTRACT_TYPES else models.EstadoEnum.pendiente,
    )

    def render_create_error(message: str, status_code: int = 400):
        abstract.autores = []
        abstract.afiliaciones = []
        for i in range(1, autor_count + 1):
            nombre_autor = form_data.get(f"autor_nombre_{i}", "").strip()
            afils_str = form_data.get(f"autor_afils_{i}", "").strip()
            if nombre_autor:
                abstract.autores.append(models.Autor(
                    nombre=nombre_autor,
                    afiliaciones_ids=afils_str,
                    es_presentador=1 if form_data.get("presentador", "").strip() == str(i) else 0,
                    orden=i,
                ))
        for i in range(1, afil_count + 1):
            nombre_afil = form_data.get(f"afil_nombre_{i}", "").strip()
            if nombre_afil:
                abstract.afiliaciones.append(models.Afiliacion(nombre=nombre_afil, orden=i))
        return templates.TemplateResponse("admin/abstract_edit.html", {
            "request": request,
            "abstract": abstract,
            "create_mode": True,
            "form_action": "/admin/abstracts/new",
            "submit_label": "Crear abstract",
            "cancel_url": "/admin",
            "abstract_type_labels": ABSTRACT_TYPE_LABELS,
            "error_message": message,
            "current_user": current_user,
        }, status_code=status_code)

    if not titulo:
        return render_create_error("El título no puede estar vacío.")
    if not email_autor:
        return render_create_error("El email del autor presentador es obligatorio.")
    if not resumen_texto:
        return render_create_error("El resumen no puede estar vacío.")
    if len(resumen_texto) > 2500:
        return render_create_error("El resumen no puede superar los 2500 caracteres.")
    if referencias_texto and len(referencias_texto) > 750:
        return render_create_error("Las referencias bibliográficas no pueden superar los 750 caracteres.")
    if tipo_resumen in INVITED_ABSTRACT_TYPES and invited_number is None:
        return render_create_error("Debés ingresar el número de la charla invitada.")
    if tipo_resumen not in INVITED_ABSTRACT_TYPES and not normalize_area_code(area_tematica):
        return render_create_error("Debés seleccionar un área temática para la contribución.")

    afiliaciones_data: list[tuple[int, str]] = []
    for i in range(1, afil_count + 1):
        nombre_afil = form_data.get(f"afil_nombre_{i}", "").strip()
        if nombre_afil:
            afiliaciones_data.append((i, nombre_afil))
    if not afiliaciones_data:
        return render_create_error("Debe haber al menos una afiliación.")

    autores_data: list[tuple[int, str, str]] = []
    for i in range(1, autor_count + 1):
        nombre_autor = form_data.get(f"autor_nombre_{i}", "").strip()
        afils_str = form_data.get(f"autor_afils_{i}", "").strip()
        if nombre_autor:
            autores_data.append((i, nombre_autor, afils_str))
    if not autores_data:
        return render_create_error("Debe haber al menos un autor.")

    presentador_idx = form_data.get("presentador", "").strip()
    presentadores = [autor for autor in autores_data if str(autor[0]) == presentador_idx]
    if len(presentadores) != 1:
        return render_create_error("Debe seleccionarse exactamente un autor presentador.")

    abstract.autor = presentadores[0][1]
    abstract.afiliacion = afiliaciones_data[0][1]
    db.add(abstract)
    db.flush()

    for orden, nombre_afil in afiliaciones_data:
        db.add(models.Afiliacion(
            abstract_id=abstract.id,
            nombre=nombre_afil,
            orden=orden
        ))

    for orden, nombre_autor, afils_str in autores_data:
        db.add(models.Autor(
            abstract_id=abstract.id,
            nombre=nombre_autor,
            orden=orden,
            es_presentador=1 if str(orden) == presentador_idx else 0,
            afiliaciones_ids=afils_str
        ))

    if tipo_resumen in INVITED_ABSTRACT_TYPES:
        abstract.tipo_asignado_admin = "oral"
        sync_final_code(abstract)

    db.commit()
    return RedirectResponse(url=f"/admin/abstracts/{abstract.id}", status_code=303)

# --- Admin: detalle de abstract ---
@app.get("/admin/abstracts/{abstract_id}", response_class=HTMLResponse)
def admin_abstract_detail(
    abstract_id: int,
    request: Request,
    mail_sent: int = 0,
    mail_error: str = "",
    current_user: models.User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    abstract = db.query(models.Abstract).filter(models.Abstract.id == abstract_id).first()
    if not abstract:
        raise HTTPException(status_code=404, detail="No encontrado")
    evaluadores = db.query(models.User).filter(models.User.role == "evaluador").all()
    asignados_ids = [a.evaluador_id for a in abstract.asignaciones]
    evaluadores_disponibles = [e for e in evaluadores if e.id not in asignados_ids]
    reviews = db.query(models.Review).filter(models.Review.abstract_id == abstract_id).all()
    logs = db.query(models.AbstractLog).filter(
        models.AbstractLog.abstract_id == abstract_id
    ).order_by(models.AbstractLog.created_at.desc()).all()
    return templates.TemplateResponse("admin/abstract_detail.html", {
        "request": request,
        "abstract": abstract,
        "evaluadores_disponibles": evaluadores_disponibles,
        "reviews": reviews,
        "logs": logs,
        "mail_sent": mail_sent,
        "mail_error": mail_error,
        "current_user": current_user
    })

# --- Admin: aprobar/rechazar ---
@app.post("/admin/abstracts/{abstract_id}/approve")
def admin_approve(abstract_id: int, current_user: models.User = Depends(require_admin), db: Session = Depends(get_db)):
    abstract = db.query(models.Abstract).filter(models.Abstract.id == abstract_id).first()
    abstract.estado = models.EstadoEnum.aprobado
    sync_final_code(abstract)
    set_minor_revision_flag(db, abstract, False)
    db.commit()
    return RedirectResponse(url=f"/admin/abstracts/{abstract_id}", status_code=302)

@app.post("/admin/abstracts/{abstract_id}/reject")
def admin_reject(abstract_id: int, current_user: models.User = Depends(require_admin), db: Session = Depends(get_db)):
    abstract = db.query(models.Abstract).filter(models.Abstract.id == abstract_id).first()
    abstract.estado = models.EstadoEnum.rechazado
    abstract.tipo_asignado_admin = None
    abstract.codigo_final = None
    set_minor_revision_flag(db, abstract, False)
    db.commit()
    return RedirectResponse(url=f"/admin/abstracts/{abstract_id}", status_code=302)

@app.post("/admin/abstracts/{abstract_id}/finalize-approval")
def admin_finalize_approval(
    abstract_id: int,
    request: Request,
    current_user: models.User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    abstract = db.query(models.Abstract).filter(models.Abstract.id == abstract_id).first()
    if not abstract:
        raise HTTPException(status_code=404, detail="No encontrado")
    abstract.estado = models.EstadoEnum.aprobado
    set_minor_revision_flag(db, abstract, False)
    db.commit()
    redirect_to = request.headers.get("referer") or "/admin"
    return RedirectResponse(url=redirect_to, status_code=303)
    

# --- Admin: asignar/desasignar evaluador ---
@app.post("/admin/abstracts/{abstract_id}/asignar")
def admin_asignar(abstract_id: int, evaluador_id: int = Form(...), current_user: models.User = Depends(require_admin), db: Session = Depends(get_db)):
    db.query(models.Asignacion).filter(
        models.Asignacion.abstract_id == abstract_id
    ).delete()
    db.add(models.Asignacion(abstract_id=abstract_id, evaluador_id=evaluador_id))
    db.commit()
    return RedirectResponse(url=f"/admin/abstracts/{abstract_id}", status_code=302)


@app.post("/admin/abstracts/asignar-masivo")
def admin_asignar_masivo(
    request: Request,
    evaluador_id: int = Form(...),
    abstract_ids: str = Form(...),
    current_user: models.User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    ids = [int(i) for i in abstract_ids.split(",") if i.strip().isdigit()]
    for abstract_id in ids:
        # Borrar cualquier asignación previa
        db.query(models.Asignacion).filter(
            models.Asignacion.abstract_id == abstract_id
        ).delete()
        db.add(models.Asignacion(abstract_id=abstract_id, evaluador_id=evaluador_id))
    db.commit()
    return RedirectResponse(url="/admin", status_code=303)


@app.post("/admin/abstracts/{abstract_id}/desasignar/{evaluador_id}")
def admin_desasignar(abstract_id: int, evaluador_id: int, current_user: models.User = Depends(require_admin), db: Session = Depends(get_db)):
    db.query(models.Asignacion).filter(
        models.Asignacion.abstract_id == abstract_id,
        models.Asignacion.evaluador_id == evaluador_id
    ).delete()
    db.commit()
    return RedirectResponse(url=f"/admin/abstracts/{abstract_id}", status_code=302) 


# --- Admin: evaluadores ---
@app.get("/admin/evaluadores", response_class=HTMLResponse)
def admin_evaluadores(
    request: Request,
    current_user: models.User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    usuarios = db.query(models.User).order_by(models.User.role, models.User.nombre).all()
    return templates.TemplateResponse("admin/evaluadores.html", {
        "request": request,
        "usuarios": usuarios,
        "current_user": current_user
    })

@app.post("/admin/evaluadores", response_class=HTMLResponse)
async def admin_crear_evaluador(
    request: Request,
    nombre: str = Form(...),
    email: str = Form(...),
    role: str = Form("evaluador"),
    current_user: models.User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    usuarios = db.query(models.User).order_by(models.User.role, models.User.nombre).all()
    try:
        selected_role = models.RoleEnum(role)
    except ValueError:
        return templates.TemplateResponse("admin/evaluadores.html", {
            "request": request,
            "usuarios": usuarios,
            "error": "Rol inválido.",
            "current_user": current_user
        })
    existe = db.query(models.User).filter(models.User.email == email).first()
    if existe:
        return templates.TemplateResponse("admin/evaluadores.html", {
            "request": request,
            "usuarios": usuarios,
            "error": f"Ya existe un usuario con el email {email}",
            "current_user": current_user
        })
    alphabet = string.ascii_letters + string.digits
    generated_password = "".join(secrets.choice(alphabet) for _ in range(8))
    nuevo = models.User(
        nombre=nombre,
        email=email,
        password_hash=hash_password(generated_password),
        role=selected_role,
        require_password_change=1
    )
    db.add(nuevo)
    db.commit()
    usuarios = db.query(models.User).order_by(models.User.role, models.User.nombre).all()
    role_label = "Administrador" if selected_role == models.RoleEnum.admin else "Evaluador"
    base_url = os.getenv("PUBLIC_BASE_URL", str(request.base_url).rstrip("/"))
    login_url = f"{base_url}/login"
    panel_url = f"{base_url}/admin" if selected_role == models.RoleEnum.admin else f"{base_url}/eval"
    mensaje = MessageSchema(
        subject="[NANO2026] Bienvenida y acceso a la plataforma",
        recipients=[email],
        body=(
            f"Hola {nombre},\n\n"
            f"Se creó una cuenta para vos en la plataforma NANO2026 del XXIV Encuentro de Superficies y Materiales Nanoestructurados.\n\n"
            f"Rol asignado: {role_label}\n"
            f"Email de acceso: {email}\n"
            f"Contraseña inicial: {generated_password}\n\n"
            f"Para ingresar:\n"
            f"1. Abrí {login_url}\n"
            f"2. Ingresá con tu email y la contraseña inicial\n"
            f"3. Una vez dentro, vas a acceder a tu panel: {panel_url}\n\n"
            f"Si no recordás la contraseña más adelante, podés usar la opción \"¿Olvidaste tu contraseña?\" en la pantalla de login.\n\n"
            f"Saludos,\n"
            f"Comité organizador NANO2026\n"
        ),
        subtype="plain"
    )
    fm = FastMail(mail_config)
    warning = None
    try:
        await fm.send_message(mensaje)
    except Exception:
        warning = f"{role_label} {nombre} creado correctamente, pero no se pudo enviar el correo de bienvenida."

    return templates.TemplateResponse("admin/evaluadores.html", {
        "request": request,
        "usuarios": usuarios,
        "success": f"{role_label} {nombre} creado correctamente." if not warning else None,
        "warning": warning,
        "current_user": current_user
    })

@app.post("/admin/evaluadores/{evaluador_id}/delete", response_class=HTMLResponse)
def admin_eliminar_evaluador(
    request: Request,
    evaluador_id: int,
    current_user: models.User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    user = db.query(models.User).filter(models.User.id == evaluador_id).first()
    if not user:
        return RedirectResponse(url="/admin/evaluadores", status_code=302)

    usuarios = db.query(models.User).order_by(models.User.role, models.User.nombre).all()
    if user.id == current_user.id:
        return templates.TemplateResponse("admin/evaluadores.html", {
            "request": request,
            "usuarios": usuarios,
            "error": "No podés eliminar tu propio usuario.",
            "current_user": current_user
        }, status_code=400)

    if user.role == models.RoleEnum.admin:
        admin_count = db.query(models.User).filter(models.User.role == models.RoleEnum.admin).count()
        if admin_count <= 1:
            return templates.TemplateResponse("admin/evaluadores.html", {
                "request": request,
                "usuarios": usuarios,
                "error": "Debe existir al menos un administrador.",
                "current_user": current_user
            }, status_code=400)

    review_count = db.query(models.Review).filter(models.Review.evaluador_id == evaluador_id).count()
    if review_count > 0:
        return templates.TemplateResponse("admin/evaluadores.html", {
            "request": request,
            "usuarios": usuarios,
            "error": "No podés eliminar un evaluador que ya revisó resúmenes.",
            "current_user": current_user
        }, status_code=400)

    db.query(models.Asignacion).filter(models.Asignacion.evaluador_id == evaluador_id).delete()
    db.query(models.User).filter(models.User.id == evaluador_id).delete()
    db.commit()
    return RedirectResponse(url="/admin/evaluadores", status_code=302)


# --- Panel evaluador ---
@app.get("/eval", response_class=HTMLResponse)
def eval_lista(
    request: Request,
    current_user: models.User = Depends(require_evaluador),
    db: Session = Depends(get_db)
):
    asignaciones = db.query(models.Asignacion).filter(
    models.Asignacion.evaluador_id == current_user.id
    ).all()
    reviews = db.query(models.Review).filter(
        models.Review.evaluador_id == current_user.id
    ).all()
    reviews_map = {r.abstract_id: r for r in reviews}
    return templates.TemplateResponse("eval/lista.html", {
        "request": request,
        "asignaciones": asignaciones,
        "reviews_map": reviews_map,
        "current_user": current_user
    })

@app.get("/eval/{abstract_id}", response_class=HTMLResponse)
def eval_detalle(
    abstract_id: int,
    request: Request,
    current_user: models.User = Depends(require_evaluador),
    mail_sent: int = 0,
    mail_error: str = "",
    db: Session = Depends(get_db)
):
    asig = db.query(models.Asignacion).filter(
        models.Asignacion.abstract_id == abstract_id,
        models.Asignacion.evaluador_id == current_user.id
    ).first()
    if not asig:
        raise HTTPException(status_code=403, detail="No tenés acceso a este resumen")
    abstract = asig.abstract
    review = db.query(models.Review).filter(
        models.Review.abstract_id == abstract_id,
        models.Review.evaluador_id == current_user.id
    ).first()
    logs = db.query(models.AbstractLog).filter(
        models.AbstractLog.abstract_id == abstract_id
    ).order_by(models.AbstractLog.created_at.desc()).all()
    return templates.TemplateResponse("eval/detalle.html", {
        "request": request,
        "abstract": abstract,
        "review": review,
        "minor_revision_checked": bool(abstract.acceptance_flag and abstract.acceptance_flag.minor_revision == 1),
        "current_user": current_user,
        "mail_sent": mail_sent,
        "mail_error": mail_error,
        "logs": logs
    })
@app.post("/eval/{abstract_id}", response_class=HTMLResponse)
async def eval_submit(
    abstract_id: int,
    request: Request,
    decision: str = Form(...),
    comentario: str = Form(""),
    current_user: models.User = Depends(require_evaluador),
    recomienda_oral: int = Form(None),
    revisiones_menores: int = Form(0),
    db: Session = Depends(get_db)
):
    asig = db.query(models.Asignacion).filter(
        models.Asignacion.abstract_id == abstract_id,
        models.Asignacion.evaluador_id == current_user.id
    ).first()
    if not asig:
        raise HTTPException(status_code=403, detail="No tenés acceso a este resumen")
    review = db.query(models.Review).filter(
        models.Review.abstract_id == abstract_id,
        models.Review.evaluador_id == current_user.id
    ).first()
    previous_decision = review.decision.value if (review and review.decision) else None

    if review:
        review.decision = decision
        review.comentario = comentario
        review.fecha = datetime.utcnow()
        review.recomienda_oral = recomienda_oral
    else:
        review = models.Review(
            abstract_id=abstract_id,
            evaluador_id=current_user.id,
            decision=decision,
            comentario=comentario,
            recomienda_oral=recomienda_oral
        )
        db.add(review)

    # Actualizar estado del abstract según la decisión del evaluador
    abstract = asig.abstract
    if decision == "aprobado":
        abstract.estado = models.EstadoEnum.aprobado
        set_minor_revision_flag(db, abstract, revisiones_menores == 1)
    elif decision == "revisar":
        abstract.estado = models.EstadoEnum.revisar
        abstract.tipo_asignado_admin = None
        set_minor_revision_flag(db, abstract, False)
    elif decision == "rechazado":
        abstract.estado = models.EstadoEnum.rechazado
        abstract.tipo_asignado_admin = None
        set_minor_revision_flag(db, abstract, False)

    sync_final_code(abstract)

    db.commit()

    decision_mail_sent = False
    decision_mail_error = False
    decision_mail_skipped = False

    if decision == "aprobado":
        subject = f"[NANO2026] Abstract #{abstract.id} aceptado"
        oral_note = ""
        if abstract.presentacion_oral:
            oral_note = (
                "Próximamente nos contactaremos "
                "para comunicarte la decisión del comité organizador respecto a la modalidad (oral o poster).\n\n"
            )
        else:
            oral_note = ("La modalidad de tu presentación es póster.\n\n"

            )
        body = (
            f"Hola,\n\n"
            f"Nos alegra mucho contarte que tu abstract \"{strip_tags(abstract.titulo)}\" fue aceptado para NANO2026.\n\n"
            f"{oral_note}"
            f"¡Felicitaciones! Gracias por tu aporte y por ser parte de esta edición.\n\n"
            f"¡Nos vemos en el encuentro!\n\n"
            f"Saludos cordiales,\n"
            f"Comité organizador NANO2026\n"
        )
        event_type = "acceptance_email_sent"
        details = (
            f"Correo de aceptación enviado a {abstract.email_autor} "
            f"por {current_user.nombre} ({current_user.email})."
        )
        existing_mail_log = db.query(models.AbstractLog).filter(
            models.AbstractLog.abstract_id == abstract.id,
            models.AbstractLog.event_type == event_type
        ).first()
        should_send_mail = not (previous_decision == decision and existing_mail_log)

        if should_send_mail:
            mensaje = MessageSchema(
                subject=subject,
                recipients=[abstract.email_autor],
                body=body,
                subtype="plain"
            )

            fm = FastMail(mail_config)
            try:
                await fm.send_message(mensaje)
                db.add(models.AbstractLog(
                    abstract_id=abstract.id,
                    event_type=event_type,
                    details=details,
                    actor_email=current_user.email
                ))
                db.commit()
                decision_mail_sent = True
            except Exception:
                decision_mail_error = True
        else:
            decision_mail_skipped = True

    return templates.TemplateResponse("eval/detalle.html", {
        "request": request,
        "abstract": abstract,
        "review": review,
        "minor_revision_checked": bool(abstract.acceptance_flag and abstract.acceptance_flag.minor_revision == 1),
        "logs": db.query(models.AbstractLog).filter(
            models.AbstractLog.abstract_id == abstract.id
        ).order_by(models.AbstractLog.created_at.desc()).all(),
        "success": True,
        "current_user": current_user,
        "decision_mail_sent": decision_mail_sent,
        "decision_mail_error": decision_mail_error,
        "decision_mail_skipped": decision_mail_skipped
    })

@app.post("/eval/{abstract_id}/send-revision")
async def eval_send_revision_email(
    abstract_id: int,
    request: Request,
    current_user: models.User = Depends(require_evaluador),
    db: Session = Depends(get_db)
):
    asig = db.query(models.Asignacion).filter(
        models.Asignacion.abstract_id == abstract_id,
        models.Asignacion.evaluador_id == current_user.id
    ).first()
    if not asig:
        raise HTTPException(status_code=403, detail="No tenés acceso a este resumen")

    review = db.query(models.Review).filter(
        models.Review.abstract_id == abstract_id,
        models.Review.evaluador_id == current_user.id
    ).first()

    if not review or review.decision not in (models.EstadoEnum.revisar, models.EstadoEnum.rechazado):
        return RedirectResponse(url=f"/eval/{abstract_id}?mail_error=no_review", status_code=303)

    if not (review.comentario or "").strip():
        return RedirectResponse(url=f"/eval/{abstract_id}?mail_error=no_comment", status_code=303)

    abstract = asig.abstract
    if review.decision == models.EstadoEnum.revisar:
        token = create_revision_token(abstract.id, abstract.email_autor)
        base_url = os.getenv("PUBLIC_BASE_URL", str(request.base_url).rstrip("/"))
        edit_url = f"{base_url}/revision/{token}"
        subject = f"[NANO2026] Revisión solicitada para abstract #{abstract.id}"
        body = (
            f"Hola,\n\n"
            f"Tu abstract \"{strip_tags(abstract.titulo)}\" requiere correcciones.\n\n"
            f"Comentarios del evaluador:\n{review.comentario.strip()}\n\n"
            f"Editalo y reenviá la versión corregida desde este link:\n{edit_url}\n\n"
            f"El enlace vence en 72 horas.\n\n"
            f"Saludos cordiales,\n"
            f"Comité organizador NANO2026\n"
        )
        event_type = "revision_email_sent"
        details = (
            f"Correo de revisión enviado a {abstract.email_autor} "
            f"por {current_user.nombre} ({current_user.email})."
        )
    else:
        existing_rejection_log = db.query(models.AbstractLog).filter(
            models.AbstractLog.abstract_id == abstract.id,
            models.AbstractLog.event_type == "rejection_email_sent"
        ).first()
        if existing_rejection_log:
            return RedirectResponse(url=f"/eval/{abstract_id}?mail_error=duplicate_rejection", status_code=303)

        subject = f"[NANO2026] Abstract #{abstract.id} rechazado"
        body = (
            f"Hola,\n\n"
            f"Gracias por enviar tu abstract \"{strip_tags(abstract.titulo)}\".\n\n"
            f"Tras la evaluación del comité, en esta oportunidad no pudo ser aceptado para esta edición.\n\n"
            f"Valoramos mucho tu participación y esperamos poder contar con futuras postulaciones.\n\n"
            f"Comentarios del evaluador:\n{review.comentario.strip()}\n\n"
            f"Saludos cordiales,\n"
            f"Comité organizador NANO2026\n"
        )
        event_type = "rejection_email_sent"
        details = (
            f"Correo de rechazo (con comentarios) enviado a {abstract.email_autor} "
            f"por {current_user.nombre} ({current_user.email})."
        )

    mensaje = MessageSchema(
        subject=subject,
        recipients=[abstract.email_autor],
        body=body,
        subtype="plain"
    )
    fm = FastMail(mail_config)
    try:
        await fm.send_message(mensaje)
    except Exception:
        return RedirectResponse(url=f"/eval/{abstract_id}?mail_error=send_fail", status_code=303)

    db.add(models.AbstractLog(
        abstract_id=abstract.id,
        event_type=event_type,
        details=details,
        actor_email=current_user.email
    ))
    db.commit()
    return RedirectResponse(url=f"/eval/{abstract_id}?mail_sent=1", status_code=303)

@app.get("/revision/{token}", response_class=HTMLResponse)
def revision_edit_form(
    token: str,
    request: Request,
    db: Session = Depends(get_db)
):
    try:
        payload = verify_revision_token(token)
        abstract_id = int(payload.get("abstract_id"))
        email_autor = payload.get("email_autor", "")
    except (JWTError, ValueError):
        raise HTTPException(status_code=400, detail="Link inválido o vencido")

    abstract = db.query(models.Abstract).filter(models.Abstract.id == abstract_id).first()
    if not abstract or abstract.email_autor != email_autor:
        raise HTTPException(status_code=404, detail="Resumen no encontrado")

    return templates.TemplateResponse("admin/abstract_edit.html", {
        "request": request,
        "abstract": abstract,
        "presenter_mode": True,
        "base_template": "public/base.html",
        "revision_token": token,
        "abstract_type_labels": ABSTRACT_TYPE_LABELS,
    })

@app.post("/revision/{token}", response_class=HTMLResponse)
async def revision_edit_submit(
    token: str,
    request: Request,
    db: Session = Depends(get_db)
):
    try:
        payload = verify_revision_token(token)
        abstract_id = int(payload.get("abstract_id"))
        email_autor = payload.get("email_autor", "")
    except (JWTError, ValueError):
        raise HTTPException(status_code=400, detail="Link inválido o vencido")

    abstract = db.query(models.Abstract).filter(models.Abstract.id == abstract_id).first()
    if not abstract or abstract.email_autor != email_autor:
        raise HTTPException(status_code=404, detail="Resumen no encontrado")

    form_data = await request.form()
    apply_abstract_edit_from_form(abstract, form_data, db)
    abstract.estado = models.EstadoEnum.pendiente
    abstract.tipo_asignado_admin = None
    abstract.codigo_final = None
    set_minor_revision_flag(db, abstract, False)
    # Al reenviar correcciones, reiniciar evaluaciones previas para que vuelva a "Pendiente"
    for review in abstract.reviews:
        review.decision = None
        review.comentario = None
        review.recomienda_oral = None
        review.fecha = datetime.utcnow()
    db.commit()

    return templates.TemplateResponse("admin/abstract_edit.html", {
        "request": request,
        "abstract": abstract,
        "presenter_mode": True,
        "base_template": "public/base.html",
        "revision_token": token,
        "success_revision_submit": True,
        "abstract_type_labels": ABSTRACT_TYPE_LABELS,
    })
from sqlalchemy import or_

# --- Páginas públicas ---
@app.get("/", response_class=HTMLResponse)
def home(request: Request, db: Session = Depends(get_db)):
    total_abstracts = db.query(models.Abstract).count()
    total_aprobados = db.query(models.Abstract).filter(
        models.Abstract.estado == models.EstadoEnum.aprobado
    ).count()
    total_speakers = db.query(models.Speaker).count()
    return templates.TemplateResponse(
        "public/home.html",
        public_page_context(
            request,
            title="Congreso de Nanotecnología en Argentina 2026 | NANO2026",
            description=(
                "NANO2026 es el XXIV Encuentro de Superficies y Materiales "
                "Nanoestructurados. Se realiza del 3 al 5 de junio de 2026 en "
                "Campus UNSAM, San Martin, Buenos Aires."
            ),
            canonical_path="/",
            include_event_schema=True,
            extra={
                "total_abstracts": total_abstracts,
                "total_aprobados": total_aprobados,
                "total_speakers": total_speakers,
            }
        )
    )

@app.get("/abstracts", response_class=HTMLResponse)
def abstracts_publicos(
    request: Request,
    q: str = "",
    autor: str = "",
    afiliacion: str = "",
    db: Session = Depends(get_db)
):
    query = db.query(models.Abstract).filter(
        models.Abstract.estado == models.EstadoEnum.aprobado
    )
    if q:
        query = query.filter(models.Abstract.titulo.ilike(f"%{q}%"))
    if autor:
        query = query.filter(models.Abstract.autor.ilike(f"%{autor}%"))
    if afiliacion:
        query = query.filter(models.Abstract.afiliacion.ilike(f"%{afiliacion}%"))
    abstracts = query.order_by(models.Abstract.fecha_envio.desc()).all()
    return templates.TemplateResponse(
        "public/abstracts.html",
        public_page_context(
            request,
            title="Resúmenes aprobados | NANO2026",
            description=(
                "Consultá los resúmenes aprobados del NANO2026 por título, autor "
                "o afiliación."
            ),
            canonical_path="/abstracts",
            extra={
                "abstracts": abstracts,
                "q": q,
                "autor": autor,
                "afiliacion": afiliacion,
            }
        )
    )
@app.get("/abstracts/{abstract_id}", response_class=HTMLResponse)
def abstract_publico_detalle(
    abstract_id: int,
    request: Request,
    db: Session = Depends(get_db)
):
    abstract = db.query(models.Abstract).filter(
        models.Abstract.id == abstract_id,
        models.Abstract.estado == models.EstadoEnum.aprobado
    ).first()
    if not abstract:
        raise HTTPException(status_code=404, detail="Resumen no encontrado")
    abstract_description = trim_text(strip_tags(abstract.contenido_html), 160)
    return templates.TemplateResponse(
        "public/abstract_detail.html",
        public_page_context(
            request,
            title=f"{abstract.titulo} | Resumen NANO2026",
            description=abstract_description or "Resumen aprobado del NANO2026.",
            canonical_path=f"/abstracts/{abstract_id}",
            extra={"abstract": abstract}
        )
    )


@app.get("/abstracts/{abstract_id}/pdf")
def abstract_pdf(abstract_id: int, db: Session = Depends(get_db)):
    abstract = db.query(models.Abstract).filter(
    models.Abstract.id == abstract_id
).first()

    if not abstract:
        raise HTTPException(status_code=404, detail="Resumen no encontrado")

    html_content = templates.get_template("public/abstract_pdf.html").render(
        abstract=abstract
    )
    pdf_buffer = io.BytesIO()
    pisa.CreatePDF(html_content, dest=pdf_buffer)
    pdf_buffer.seek(0)
    return StreamingResponse(
        pdf_buffer,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f"attachment; filename=abstract_{abstract_id}.pdf"
        }
    )




@app.get("/admin/programa", response_class=HTMLResponse)
def admin_programa(
    request: Request,
    current_user: models.User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    schedule = build_program_schedule(db)
    entries = (
        db.query(models.ProgramEntry)
        .order_by(models.ProgramEntry.day_key, models.ProgramEntry.position, models.ProgramEntry.id)
        .all()
    )
    return templates.TemplateResponse("admin/programa.html", {
        "request": request,
        "schedule": schedule,
        "entries": entries,
    })


@app.get("/admin/programa/new", response_class=HTMLResponse)
def admin_programa_new_form(
    request: Request,
    current_user: models.User = Depends(require_admin),
):
    return render_program_entry_form(request)


@app.post("/admin/programa/new", response_class=HTMLResponse)
def admin_programa_create(
    request: Request,
    day_key: str = Form(...),
    day_label: str = Form(...),
    kind: str = Form(...),
    start_time: str = Form(...),
    end_time: str = Form(...),
    item_type: str = Form(...),
    title: str = Form(""),
    location: str = Form(""),
    track_1_title: str = Form(""),
    track_1_type: str = Form(""),
    track_1_room: str = Form(""),
    track_2_title: str = Form(""),
    track_2_type: str = Form(""),
    track_2_room: str = Form(""),
    current_user: models.User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    kind = normalize_program_kind(kind)
    entry = models.ProgramEntry(
        day_key=day_key.strip(),
        day_label=day_label.strip(),
        position=next_program_position(db, day_key.strip()),
        kind=kind,
        start_time=start_time.strip(),
        end_time=end_time.strip(),
        item_type=normalize_program_type(item_type),
        title=title.strip() or None,
        location=location.strip() or None,
        track_1_title=track_1_title.strip() or None,
        track_1_type=normalize_program_type(track_1_type),
        track_1_room=track_1_room.strip() or None,
        track_2_title=track_2_title.strip() or None,
        track_2_type=normalize_program_type(track_2_type),
        track_2_room=track_2_room.strip() or None,
    )
    if kind == "shared" and not entry.title:
        return render_program_entry_form(request, entry, error="Las actividades comunes necesitan un título.")
    if kind == "parallel" and (not entry.track_1_title or not entry.track_2_title):
        return render_program_entry_form(request, entry, error="Las sesiones paralelas necesitan título para ambas tarjetas.")
    db.add(entry)
    db.commit()
    return RedirectResponse(url="/admin/programa", status_code=303)


@app.get("/admin/programa/{entry_id}/edit", response_class=HTMLResponse)
def admin_programa_edit_form(
    entry_id: int,
    request: Request,
    current_user: models.User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    entry = db.query(models.ProgramEntry).filter(models.ProgramEntry.id == entry_id).first()
    if not entry:
        raise HTTPException(status_code=404, detail="Entrada no encontrada")
    return render_program_entry_form(request, entry)


@app.post("/admin/programa/{entry_id}/edit", response_class=HTMLResponse)
def admin_programa_edit(
    entry_id: int,
    request: Request,
    day_key: str = Form(...),
    day_label: str = Form(...),
    kind: str = Form(...),
    start_time: str = Form(...),
    end_time: str = Form(...),
    item_type: str = Form(...),
    title: str = Form(""),
    location: str = Form(""),
    track_1_title: str = Form(""),
    track_1_type: str = Form(""),
    track_1_room: str = Form(""),
    track_2_title: str = Form(""),
    track_2_type: str = Form(""),
    track_2_room: str = Form(""),
    current_user: models.User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    entry = db.query(models.ProgramEntry).filter(models.ProgramEntry.id == entry_id).first()
    if not entry:
        raise HTTPException(status_code=404, detail="Entrada no encontrada")

    old_day_key = entry.day_key
    entry.day_key = day_key.strip()
    entry.day_label = day_label.strip()
    entry.kind = normalize_program_kind(kind)
    entry.start_time = start_time.strip()
    entry.end_time = end_time.strip()
    entry.item_type = normalize_program_type(item_type)
    entry.title = title.strip() or None
    entry.location = location.strip() or None
    entry.track_1_title = track_1_title.strip() or None
    entry.track_1_type = normalize_program_type(track_1_type)
    entry.track_1_room = track_1_room.strip() or None
    entry.track_2_title = track_2_title.strip() or None
    entry.track_2_type = normalize_program_type(track_2_type)
    entry.track_2_room = track_2_room.strip() or None

    if entry.kind == "shared" and not entry.title:
        return render_program_entry_form(request, entry, error="Las actividades comunes necesitan un título.")
    if entry.kind == "parallel" and (not entry.track_1_title or not entry.track_2_title):
        return render_program_entry_form(request, entry, error="Las sesiones paralelas necesitan título para ambas tarjetas.")

    if old_day_key != entry.day_key:
        entry.position = next_program_position(db, entry.day_key)
    db.commit()
    compact_program_positions(db, old_day_key)
    if old_day_key != entry.day_key:
        compact_program_positions(db, entry.day_key)
    return RedirectResponse(url="/admin/programa", status_code=303)


@app.post("/admin/programa/{entry_id}/delete")
def admin_programa_delete(
    entry_id: int,
    current_user: models.User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    entry = db.query(models.ProgramEntry).filter(models.ProgramEntry.id == entry_id).first()
    if not entry:
        raise HTTPException(status_code=404, detail="Entrada no encontrada")
    day_key = entry.day_key
    db.delete(entry)
    db.commit()
    compact_program_positions(db, day_key)
    return RedirectResponse(url="/admin/programa", status_code=303)


@app.post("/admin/programa/{entry_id}/move")
def admin_programa_move(
    entry_id: int,
    direction: str = Form(...),
    current_user: models.User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    entry = db.query(models.ProgramEntry).filter(models.ProgramEntry.id == entry_id).first()
    if not entry:
        raise HTTPException(status_code=404, detail="Entrada no encontrada")
    siblings = (
        db.query(models.ProgramEntry)
        .filter(models.ProgramEntry.day_key == entry.day_key)
        .order_by(models.ProgramEntry.position, models.ProgramEntry.id)
        .all()
    )
    index = next((idx for idx, sibling in enumerate(siblings) if sibling.id == entry.id), None)
    if index is None:
        raise HTTPException(status_code=404, detail="Entrada no encontrada")
    swap_index = index - 1 if direction == "up" else index + 1
    if 0 <= swap_index < len(siblings):
        siblings[index].position, siblings[swap_index].position = siblings[swap_index].position, siblings[index].position
        db.commit()
    compact_program_positions(db, entry.day_key)
    return RedirectResponse(url="/admin/programa", status_code=303)


@app.post("/admin/programa/reorder")
def admin_programa_reorder(
    day_key: str = Form(...),
    ordered_ids: str = Form(...),
    current_user: models.User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    ids = []
    for raw_id in ordered_ids.split(","):
        raw_id = raw_id.strip()
        if not raw_id:
            continue
        try:
            ids.append(int(raw_id))
        except ValueError:
            raise HTTPException(status_code=400, detail="IDs inválidos")

    entries = (
        db.query(models.ProgramEntry)
        .filter(models.ProgramEntry.day_key == day_key)
        .order_by(models.ProgramEntry.position, models.ProgramEntry.id)
        .all()
    )
    existing_ids = {entry.id for entry in entries}
    if existing_ids != set(ids):
        raise HTTPException(status_code=400, detail="El orden enviado no coincide con los bloques del día.")

    entry_by_id = {entry.id: entry for entry in entries}
    for position, entry_id in enumerate(ids):
        entry_by_id[entry_id].position = position
    db.commit()
    return {"ok": True}


@app.get("/speakers", response_class=HTMLResponse)
def speakers(request: Request):
    return templates.TemplateResponse(
        "public/speakers.html",
        public_page_context(
            request,
            title="Conferencias y speakers | NANO2026",
            description=(
                "Conocé las conferencias plenarias y los speakers invitados del "
                "NANO2026."
            ),
            canonical_path="/speakers"
        )
    )

@app.get("/venue", response_class=HTMLResponse)
def venue(request: Request):
    return templates.TemplateResponse(
        "public/venue.html",
        public_page_context(
            request,
            title="Sede del congreso | NANO2026",
            description=(
                "Información sobre la sede del NANO2026 en Campus UNSAM, San Martin, "
                "Buenos Aires."
            ),
            canonical_path="/venue"
        )
    )

@app.get("/programa", response_class=HTMLResponse)
def programa(request: Request, db: Session = Depends(get_db)):
    return templates.TemplateResponse(
        "public/programa.html",
        public_page_context(
            request,
            title="Programa del congreso | NANO2026",
            description=(
                "Revisá el programa del NANO2026 con sesiones, conferencias y "
                "actividades del encuentro."
            ),
            canonical_path="/programa",
            extra={"schedule": build_program_schedule(db)},
        )
    )


@app.get("/about", response_class=HTMLResponse)
def about(request: Request):
    return templates.TemplateResponse(
        "public/about.html",
        public_page_context(
            request,
            title="Sobre el encuentro | NANO2026",
            description=(
                "Conocé el enfoque, la historia y los objetivos del XXIV Encuentro "
                "de Superficies y Materiales Nanoestructurados."
            ),
            canonical_path="/about"
        )
    )

@app.get("/sponsors", response_class=HTMLResponse)
def sponsors(request: Request):
    return templates.TemplateResponse(
        "public/sponsors.html",
        public_page_context(
            request,
            title="Sponsors y empresas | NANO2026",
            description=(
                "Espacio para sponsors, empresas e instituciones vinculadas al "
                "NANO2026."
            ),
            canonical_path="/sponsors"
        )
    )


@app.get("/en/sponsors", response_class=HTMLResponse)
def sponsors_en(request: Request):
    return templates.TemplateResponse(
        "public/sponsors_en.html",
        public_page_context(
            request,
            title="Sponsors and industry partners | NANO2026",
            description=(
                "Sponsorship opportunities for companies, organizations and "
                "institutions connected to NANO2026."
            ),
            canonical_path="/en/sponsors",
            language="en",
            og_locale="en_US"
        )
    )


@app.post("/admin/abstracts/{abstract_id}/delete")
def admin_delete_abstract(abstract_id: int, current_user: models.User = Depends(require_admin), db: Session = Depends(get_db)):
    abstract = db.query(models.Abstract).filter(models.Abstract.id == abstract_id).first()
    if not abstract:
        raise HTTPException(status_code=404, detail="No encontrado")
    db.query(models.AbstractAcceptanceFlag).filter(models.AbstractAcceptanceFlag.abstract_id == abstract_id).delete()
    db.query(models.AbstractLog).filter(models.AbstractLog.abstract_id == abstract_id).delete()
    db.query(models.Review).filter(models.Review.abstract_id == abstract_id).delete()
    db.query(models.Asignacion).filter(models.Asignacion.abstract_id == abstract_id).delete()
    db.query(models.Autor).filter(models.Autor.abstract_id == abstract_id).delete()
    db.query(models.Afiliacion).filter(models.Afiliacion.abstract_id == abstract_id).delete()
    db.delete(abstract)
    db.commit()
    return RedirectResponse(url="/admin", status_code=303)

@app.get("/admin/abstracts/{abstract_id}/edit", response_class=HTMLResponse)
def admin_edit_abstract_form(abstract_id: int, request: Request, current_user: models.User = Depends(require_admin), db: Session = Depends(get_db)):
    abstract = db.query(models.Abstract).filter(models.Abstract.id == abstract_id).first()
    if not abstract:
        raise HTTPException(status_code=404, detail="No encontrado")
    return templates.TemplateResponse("admin/abstract_edit.html", {
        "request": request,
        "abstract": abstract,
        "abstract_type_labels": ABSTRACT_TYPE_LABELS,
    })

@app.post("/admin/abstracts/{abstract_id}/edit")
def admin_edit_abstract(
    abstract_id: int,
    request: Request,
    titulo: str = Form(...),
    email_autor: str = Form(...),
    contenido_html: str = Form(...),
    referencias_html: str = Form(""),
    area_tematica: str = Form(""),
    presentacion_oral: int = Form(0),
    autor_count: int = Form(...),
    afil_count: int = Form(...),
    current_user: models.User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    abstract = db.query(models.Abstract).filter(models.Abstract.id == abstract_id).first()
    if not abstract:
        raise HTTPException(status_code=404, detail="No encontrado")
    apply_abstract_edit_from_form(abstract, request._form, db)
    db.commit()
    return RedirectResponse(url=f"/admin/abstracts/{abstract_id}", status_code=303)
@app.get("/circulares", response_class=HTMLResponse)
def circulares(request: Request):
    return templates.TemplateResponse(
        "public/circulares.html",
        public_page_context(
            request,
            title="Circulares del congreso | NANO2026",
            description="Accedé a las circulares y novedades oficiales del NANO2026.",
            canonical_path="/circulares"
        )
    )
@app.get("/contacto", response_class=HTMLResponse)
def contacto(request: Request):
    return templates.TemplateResponse(
        "public/contacto.html",
        {
            **public_page_context(
                request,
                title="Contacto | NANO2026",
                description=(
                    "Canales de contacto del NANO2026 para consultas sobre inscripción, "
                    "programa, resúmenes y organización."
                ),
                canonical_path="/contacto"
            ),
            "recaptcha_site_key": get_recaptcha_site_key(),
        }
    )
@app.get("/inscripcion")
def inscripcion(request: Request):
    return templates.TemplateResponse(
        "public/inscripcion.html",
        public_page_context(
            request,
            title="Inscripción al congreso | NANO2026",
            description=(
                "Información de inscripción, categorías y costos para participar "
                "del NANO2026."
            ),
            canonical_path="/inscripcion",
            include_event_schema=True
        )
    )

@app.post("/admin/abstracts/{abstract_id}/tipo")
def admin_asignar_tipo(
    abstract_id: int,
    tipo_asignado_admin: str = Form(""),
    current_user: models.User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    abstract = db.query(models.Abstract).filter(models.Abstract.id == abstract_id).first()
    if not abstract:
        raise HTTPException(status_code=404, detail="No encontrado")
    abstract.tipo_asignado_admin = tipo_asignado_admin if tipo_asignado_admin else None
    sync_final_code(abstract)
    db.commit()
    return RedirectResponse(url=f"/admin/abstracts/{abstract_id}", status_code=303)

@app.post("/admin/abstracts/{abstract_id}/send-decision")
async def admin_send_presentation_decision(
    abstract_id: int,
    current_user: models.User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    abstract = db.query(models.Abstract).filter(models.Abstract.id == abstract_id).first()
    if not abstract:
        raise HTTPException(status_code=404, detail="No encontrado")

    if abstract.estado != models.EstadoEnum.aprobado:
        return RedirectResponse(url=f"/admin/abstracts/{abstract_id}?mail_error=not_approved", status_code=303)

    if abstract.tipo_asignado_admin not in ("oral", "poster"):
        return RedirectResponse(url=f"/admin/abstracts/{abstract_id}?mail_error=no_type", status_code=303)

    event_type = "presentation_decision_email_sent"
    existing_mail_log = db.query(models.AbstractLog).filter(
        models.AbstractLog.abstract_id == abstract.id,
        models.AbstractLog.event_type == event_type,
        models.AbstractLog.details.ilike(f"%tipo={abstract.tipo_asignado_admin}%")
    ).first()
    if existing_mail_log:
        return RedirectResponse(url=f"/admin/abstracts/{abstract_id}?mail_error=duplicate_type_mail", status_code=303)

    presentation_label = "presentación oral" if abstract.tipo_asignado_admin == "oral" else "sesión de póster"
    subject = f"[NANO2026] Modalidad asignada para abstract #{abstract.id}"
    body = (
        f"Hola,\n\n"
        f"Te escribimos para confirmarte que tu abstract \"{strip_tags(abstract.titulo)}\" "
        f"fue asignado a la modalidad de {presentation_label} en NANO2026.\n\n"
        f"En breve compartiremos más información sobre el programa y la organización del evento.\n\n"
        f"Saludos cordiales,\n"
        f"Comité organizador NANO2026\n"
    )
    details = (
        f"Correo de modalidad enviado a {abstract.email_autor} "
        f"por {current_user.nombre} ({current_user.email}); tipo={abstract.tipo_asignado_admin}."
    )

    mensaje = MessageSchema(
        subject=subject,
        recipients=[abstract.email_autor],
        body=body,
        subtype="plain"
    )

    fm = FastMail(mail_config)
    try:
        await fm.send_message(mensaje)
    except Exception:
        return RedirectResponse(url=f"/admin/abstracts/{abstract_id}?mail_error=send_fail", status_code=303)

    db.add(models.AbstractLog(
        abstract_id=abstract.id,
        event_type=event_type,
        details=details,
        actor_email=current_user.email
    ))
    db.commit()
    return RedirectResponse(url=f"/admin/abstracts/{abstract_id}?mail_sent=1", status_code=303)

@app.get("/admin/abstracts/export/csv")
def export_abstracts_csv(
    estado: str = "todos",
    area: str = "todas",
    aprobado_tipo: str = "todos",
    current_user: models.User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    query, accepted_with_revision_ids = build_admin_abstracts_query(db, estado, area, aprobado_tipo)
    abstracts = query.order_by(models.Abstract.fecha_envio.desc()).all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "ID", "ID final", "Tipo resumen", "Título", "Autores", "Email presentador", "Área",
        "Tipo solicitado", "Tipo evaluador", "Tipo admin",
        "Evaluador asignado", "Estado", "Fecha envío"
    ])
    for a in abstracts:
        autores = ", ".join(
            f"{au.nombre}{'*' if au.es_presentador else ''}"
            for au in a.autores
        )
        tipo_eval = "—"
        if not a.presentacion_oral:
            tipo_eval = "Póster"
        elif a.reviews:
            r = a.reviews[0]
            if r.recomienda_oral == 1:
                tipo_eval = "Oral"
            elif r.recomienda_oral == 0:
                tipo_eval = "Póster"

        evaluador = a.asignaciones[0].evaluador.nombre if a.asignaciones else "—"

        writer.writerow([
            a.id,
            a.codigo_final or "—",
            ABSTRACT_TYPE_LABELS.get(a.tipo_resumen or "contribucion", "Contribución"),
            strip_tags(a.titulo),
            autores,
            a.email_autor,
            AREA_NAMES.get(a.area_tematica, "—") if (a.tipo_resumen or "contribucion") == "contribucion" else "—",
            "Oral" if a.presentacion_oral else "Póster",
            tipo_eval,
            a.tipo_asignado_admin or "Sin asignar",
            evaluador,
            "aprobado_con_rev" if a.estado == models.EstadoEnum.aprobado and a.id in accepted_with_revision_ids else a.estado.value,
            a.fecha_envio.strftime("%d/%m/%Y %H:%M")
        ])

    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=abstracts.csv"}
    )



mail_config = ConnectionConfig(
    MAIL_USERNAME=os.getenv("MAIL_USERNAME"),
    MAIL_PASSWORD=os.getenv("MAIL_PASSWORD"),
    MAIL_FROM=os.getenv("MAIL_FROM"),
    MAIL_PORT=587,
    MAIL_SERVER="smtp.gmail.com",
    MAIL_STARTTLS=True,
    MAIL_SSL_TLS=False,
    USE_CREDENTIALS=True
)

@app.post("/contacto", response_class=HTMLResponse)
async def contacto_post(
    request: Request,
    nombre: str = Form(...),
    email: str = Form(...),
    subject: str = Form(...),
    body: str = Form(...),
    recaptcha_token: str = Form("")
):
    # Verificar reCAPTCHA
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "https://www.google.com/recaptcha/api/siteverify",
            data={
                "secret": os.getenv("RECAPTCHA_SECRET"),
                "response": recaptcha_token
            }
        )
        result = resp.json()
    
    if not result.get("success"):
        print("reCAPTCHA result:", result)
        return templates.TemplateResponse("public/contacto.html", {
            **public_page_context(
                request,
                title="Contacto | NANO2026",
                description=(
                    "Canales de contacto del NANO2026 para consultas sobre inscripción, "
                    "programa, resúmenes y organización."
                ),
                canonical_path="/contacto"
            ),
            "recaptcha_site_key": get_recaptcha_site_key(),
            "error": "Verificación fallida. Por favor intentá de nuevo."
        })

    # ... resto del código de envío de mail
    mensaje = MessageSchema(
    subject=f"[NANO2026 Contacto] {subject}",
    recipients=["nano2026@unsam.edu.ar"],
    reply_to=[email],
    body=f"Nombre: {nombre}\nEmail: {email}\n\n{body}",
    subtype="plain"
)
    fm = FastMail(mail_config)
    try:
        await fm.send_message(mensaje)
        return templates.TemplateResponse("public/contacto.html", {
            **public_page_context(
                request,
                title="Contacto | NANO2026",
                description=(
                    "Canales de contacto del NANO2026 para consultas sobre inscripción, "
                    "programa, resúmenes y organización."
                ),
                canonical_path="/contacto"
            ),
            "recaptcha_site_key": get_recaptcha_site_key(),
            "success": True
        })
    except Exception as e:
        return templates.TemplateResponse("public/contacto.html", {
            **public_page_context(
                request,
                title="Contacto | NANO2026",
                description=(
                    "Canales de contacto del NANO2026 para consultas sobre inscripción, "
                    "programa, resúmenes y organización."
                ),
                canonical_path="/contacto"
            ),
            "recaptcha_site_key": get_recaptcha_site_key(),
            "error": f"Error: {str(e)}"
        })


@app.get("/robots.txt")
def robots_txt(request: Request):
    content = (
        "User-agent: *\n"
        "Allow: /\n"
        "Disallow: /admin\n"
        "Disallow: /eval\n"
        "Disallow: /login\n"
        "Disallow: /logout\n"
        "Disallow: /forgot-password\n"
        "Disallow: /force-password-change\n"
        "Disallow: /reset-password/\n"
        f"Sitemap: {get_public_base_url(request)}/sitemap.xml\n"
    )
    return Response(content=content, media_type="text/plain")


@app.get("/sitemap.xml")
def sitemap_xml(request: Request, db: Session = Depends(get_db)):
    base_url = get_public_base_url(request)
    urls = public_urls(request)
    approved_abstracts = db.query(models.Abstract.id).filter(
        models.Abstract.estado == models.EstadoEnum.aprobado
    ).all()
    urls.extend(
        f"{base_url}/abstracts/{abstract_id}"
        for (abstract_id,) in approved_abstracts
    )

    xml_items = "\n".join(
        f"  <url><loc>{escape(url)}</loc></url>"
        for url in urls
    )
    xml = (
        "<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n"
        "<urlset xmlns=\"http://www.sitemaps.org/schemas/sitemap/0.9\">\n"
        f"{xml_items}\n"
        "</urlset>\n"
    )
    return Response(content=xml, media_type="application/xml")
