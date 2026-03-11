import os
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
from app.database import engine, get_db
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from app import models
from app.auth import (
    hash_password, verify_password, create_access_token, require_admin,
    require_evaluador, get_current_user, create_revision_token, verify_revision_token
)
from xhtml2pdf import pisa
import io
import csv
from fastapi_mail import FastMail, MessageSchema, ConnectionConfig

models.Base.metadata.create_all(bind=engine)



app = FastAPI(title="Congreso")
app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")

import re

def strip_tags(text: str) -> str:
    return re.sub(r'<[^>]+>', '', text or '').strip()

def apply_abstract_edit_from_form(abstract: models.Abstract, form_data, db: Session):
    abstract.titulo = form_data.get("titulo", "").strip()
    abstract.email_autor = form_data.get("email_autor", "").strip()
    abstract.contenido_html = form_data.get("contenido_html", "").strip()
    abstract.referencias_html = form_data.get("referencias_html", "")
    abstract.area_tematica = form_data.get("area_tematica", "").strip()
    abstract.presentacion_oral = int(form_data.get("presentacion_oral", 0))

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


# --- Crea admin por defecto si no existe ---
def create_default_admin():
    db = next(get_db())
    exists = db.query(models.User).filter(models.User.email == "admin@congreso.com").first()
    if not exists:
        admin = models.User(
            email="admin@congreso.com",
            nombre="Administrador",
            password_hash=hash_password("admin1234"),
            role=models.RoleEnum.admin
        )
        db.add(admin)
        db.commit()

create_default_admin()

# --- Login ---
@app.get("/login", response_class=HTMLResponse)
def login_form(request: Request):
    return templates.TemplateResponse("login.html", {"request": request, "error": None})

@app.post("/login")
def login(request: Request, response: Response, email: str = Form(...), password: str = Form(...), db: Session = Depends(get_db)):
    user = db.query(models.User).filter(models.User.email == email).first()
    if not user or not verify_password(password, user.password_hash):
        return templates.TemplateResponse("login.html", {"request": request, "error": "Email o contraseña incorrectos"})
    token = create_access_token({"sub": user.email, "role": user.role})
    resp = RedirectResponse(url="/admin" if user.role == models.RoleEnum.admin else "/eval", status_code=302)
    resp.set_cookie("access_token", token, httponly=True)
    return resp

@app.get("/logout")
def logout():
    resp = RedirectResponse(url="/login", status_code=302)
    resp.delete_cookie("access_token")
    return resp



# --- Envío público de abstracts ---
@app.get("/submit", response_class=HTMLResponse)
def submit_form(request: Request):
    return templates.TemplateResponse("public/submit.html", {"request": request})
@app.post("/submit", response_class=HTMLResponse)
def submit_abstract(
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
    db: Session = Depends(get_db)
):
    if not contenido_html or contenido_html.strip() == "<p></p>":
        return templates.TemplateResponse("public/submit.html", {
            "request": request,
            "error": "El resumen no puede estar vacío."
        })

    abstract = models.Abstract(
    titulo=titulo,
    autor="",
    afiliacion="",
    email_autor=email_autor,
    contenido_html=contenido_html,
    referencias_html=referencias_html,
    tiene_referencias=tiene_referencias,
    presentacion_oral=presentacion_oral,
    area_tematica=area_tematica,
)
    db.add(abstract)
    db.flush()  # para obtener el id

    # Guardar afiliaciones
    for i in range(1, afil_count + 1):
        from fastapi import Request as FastRequest
        nombre_afil = request._form.get(f"afil_nombre_{i}", "").strip()
        if nombre_afil:
            afil = models.Afiliacion(
                abstract_id=abstract.id,
                nombre=nombre_afil,
                orden=i
            )
            db.add(afil)

    # Guardar autores
    presentador_idx = request._form.get("presentador", "1")
    autor_presentador = ""
    for i in range(1, autor_count + 1):
        nombre_autor = request._form.get(f"autor_nombre_{i}", "").strip()
        afils_str = request._form.get(f"autor_afils_{i}", "").strip()
        if nombre_autor:
            es_presentador = 1 if str(i) == str(presentador_idx) else 0
            autor = models.Autor(
                abstract_id=abstract.id,
                nombre=nombre_autor,
                orden=i,
                es_presentador=es_presentador,
                afiliaciones_ids=afils_str
            )
            db.add(autor)
            if es_presentador:
                autor_presentador = nombre_autor

    # Actualizar campo autor con el presentador
    abstract.autor = autor_presentador

    db.commit()

    return templates.TemplateResponse("public/submit.html", {
        "request": request,
        "success": True
    })
# --- Admin: lista de abstracts ---
@app.get("/admin", response_class=HTMLResponse)
def admin_abstracts(
    request: Request,
    estado: str = "todos",
    area: str = "todas",
    current_user: models.User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    query = db.query(models.Abstract)
    if estado != "todos":
        query = query.filter(models.Abstract.estado == estado)
    if area != "todas":
        query = query.filter(models.Abstract.area_tematica == area)
    abstracts = query.order_by(models.Abstract.fecha_envio.desc()).all()
    evaluadores = db.query(models.User).filter(models.User.role == "evaluador").all()
    return templates.TemplateResponse("admin/abstracts.html", {
        "request": request,
        "abstracts": abstracts,
        "estado_filtro": estado,
        "area_filtro": area,
        "current_user": current_user,
        "evaluadores": evaluadores
    })

# --- Admin: detalle de abstract ---
@app.get("/admin/abstracts/{abstract_id}", response_class=HTMLResponse)
def admin_abstract_detail(
    abstract_id: int,
    request: Request,
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
        "current_user": current_user
    })

# --- Admin: aprobar/rechazar ---
@app.post("/admin/abstracts/{abstract_id}/approve")
def admin_approve(abstract_id: int, current_user: models.User = Depends(require_admin), db: Session = Depends(get_db)):
    abstract = db.query(models.Abstract).filter(models.Abstract.id == abstract_id).first()
    abstract.estado = models.EstadoEnum.aprobado
    db.commit()
    return RedirectResponse(url=f"/admin/abstracts/{abstract_id}", status_code=302)

@app.post("/admin/abstracts/{abstract_id}/reject")
def admin_reject(abstract_id: int, current_user: models.User = Depends(require_admin), db: Session = Depends(get_db)):
    abstract = db.query(models.Abstract).filter(models.Abstract.id == abstract_id).first()
    abstract.estado = models.EstadoEnum.rechazado
    db.commit()
    return RedirectResponse(url=f"/admin/abstracts/{abstract_id}", status_code=302)
    

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
    evaluadores = db.query(models.User).filter(models.User.role == models.RoleEnum.evaluador).all()
    return templates.TemplateResponse("admin/evaluadores.html", {
        "request": request,
        "evaluadores": evaluadores,
        "current_user": current_user
    })

@app.post("/admin/evaluadores", response_class=HTMLResponse)
def admin_crear_evaluador(
    request: Request,
    nombre: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    current_user: models.User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    evaluadores = db.query(models.User).filter(models.User.role == models.RoleEnum.evaluador).all()
    existe = db.query(models.User).filter(models.User.email == email).first()
    if existe:
        return templates.TemplateResponse("admin/evaluadores.html", {
            "request": request,
            "evaluadores": evaluadores,
            "error": f"Ya existe un usuario con el email {email}",
            "current_user": current_user
        })
    nuevo = models.User(
        nombre=nombre,
        email=email,
        password_hash=hash_password(password),
        role=models.RoleEnum.evaluador
    )
    db.add(nuevo)
    db.commit()
    evaluadores = db.query(models.User).filter(models.User.role == models.RoleEnum.evaluador).all()
    return templates.TemplateResponse("admin/evaluadores.html", {
        "request": request,
        "evaluadores": evaluadores,
        "success": f"Evaluador {nombre} creado correctamente.",
        "current_user": current_user
    })

@app.post("/admin/evaluadores/{evaluador_id}/delete")
def admin_eliminar_evaluador(
    evaluador_id: int,
    current_user: models.User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    db.query(models.Asignacion).filter(models.Asignacion.evaluador_id == evaluador_id).delete()
    db.query(models.Review).filter(models.Review.evaluador_id == evaluador_id).delete()
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
    elif decision == "revisar":
        abstract.estado = models.EstadoEnum.revisar
    elif decision == "rechazado":
        abstract.estado = models.EstadoEnum.rechazado

    db.commit()

    decision_mail_sent = False
    decision_mail_error = False
    decision_mail_skipped = False

    if decision == "aprobado":
        subject = f"[NANO2026] Abstract #{abstract.id} aceptado"
        body = (
            f"Hola,\n\n"
            f"Nos alegra mucho contarte que tu abstract \"{strip_tags(abstract.titulo)}\" fue aceptado para NANO2026.\n\n"
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
        "revision_token": token
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
        "success_revision_submit": True
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
    return templates.TemplateResponse("public/home.html", {
        "request": request,
        "total_abstracts": total_abstracts,
        "total_aprobados": total_aprobados,
        "total_speakers": total_speakers
    })

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
    return templates.TemplateResponse("public/abstracts.html", {
        "request": request,
        "abstracts": abstracts,
        "q": q,
        "autor": autor,
        "afiliacion": afiliacion
    })
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
    return templates.TemplateResponse("public/abstract_detail.html", {
        "request": request,
        "abstract": abstract
    })


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





@app.get("/speakers", response_class=HTMLResponse)
def speakers(request: Request):
    return templates.TemplateResponse("public/speakers.html", {"request": request})

@app.get("/venue", response_class=HTMLResponse)
def venue(request: Request):
    return templates.TemplateResponse("public/venue.html", {"request": request})

@app.get("/programa", response_class=HTMLResponse)
def programa(request: Request):
    return templates.TemplateResponse("public/programa.html", {"request": request})


@app.get("/about", response_class=HTMLResponse)
def about(request: Request):
    return templates.TemplateResponse("public/about.html", {"request": request})


@app.post("/admin/abstracts/{abstract_id}/delete")
def admin_delete_abstract(abstract_id: int, current_user: models.User = Depends(require_admin), db: Session = Depends(get_db)):
    abstract = db.query(models.Abstract).filter(models.Abstract.id == abstract_id).first()
    if not abstract:
        raise HTTPException(status_code=404, detail="No encontrado")
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
    })

@app.post("/admin/abstracts/{abstract_id}/edit")
def admin_edit_abstract(
    abstract_id: int,
    request: Request,
    titulo: str = Form(...),
    email_autor: str = Form(...),
    contenido_html: str = Form(...),
    referencias_html: str = Form(""),
    area_tematica: str = Form(...),
    presentacion_oral: int = Form(...),
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
    return templates.TemplateResponse("public/circulares.html", {"request": request})
@app.get("/contacto", response_class=HTMLResponse)
def contacto(request: Request):
    return templates.TemplateResponse("public/contacto.html", {"request": request})
@app.get("/inscripcion")
def inscripcion(request: Request):
    return templates.TemplateResponse("public/inscripcion.html", {"request": request})

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
    db.commit()
    return RedirectResponse(url="/admin", status_code=303)

@app.get("/admin/abstracts/export/csv")
def export_abstracts_csv(
    estado: str = "todos",
    area: str = "todas",
    current_user: models.User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    query = db.query(models.Abstract)
    if estado != "todos":
        query = query.filter(models.Abstract.estado == estado)
    if area != "todas":
        query = query.filter(models.Abstract.area_tematica == area)
    abstracts = query.order_by(models.Abstract.fecha_envio.desc()).all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "ID", "Título", "Autores", "Email presentador", "Área",
        "Tipo solicitado", "Tipo evaluador", "Tipo admin",
        "Evaluador asignado", "Estado", "Fecha envío"
    ])
    area_nombres = {
    '1': 'Síntesis de nanomateriales',
    '2': 'Autoensamblado',
    '3': 'Nanobiointerfaces y procesos biológicos',
    '4': 'Superficies',
    '5': 'Propiedades de nanomateriales',
    '6': 'Aplicaciones de nanomateriales en ambiente, energía, agro, alimentos y catálisis',
    '7': 'Nanotecnología y Salud',
}
    
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
            strip_tags(a.titulo),
            autores,
            a.email_autor,
            area_nombres.get(a.area_tematica, "—"),
            "Oral" if a.presentacion_oral else "Póster",
            tipo_eval,
            a.tipo_asignado_admin or "Sin asignar",
            evaluador,
            a.estado.value,
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
            "request": request,
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
            "request": request,
            "success": True
        })
    except Exception as e:
        return templates.TemplateResponse("public/contacto.html", {
            "request": request,
            "error": f"Error: {str(e)}"
        })
