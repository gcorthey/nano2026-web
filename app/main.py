import os
from dotenv import load_dotenv
load_dotenv()
import httpx
from datetime import datetime
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
    require_evaluador, get_current_user
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
    return templates.TemplateResponse("admin/abstract_detail.html", {
        "request": request,
        "abstract": abstract,
        "evaluadores_disponibles": evaluadores_disponibles,
        "reviews": reviews,
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
    recomienda_oral: int = Form(None),
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
    return templates.TemplateResponse("eval/detalle.html", {
        "request": request,
        "abstract": abstract,
        "review": review,
        "current_user": current_user
    })
@app.post("/eval/{abstract_id}", response_class=HTMLResponse)
def eval_submit(
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
    elif decision == "rechazado":
        abstract.estado = models.EstadoEnum.rechazado

    db.commit()
    return templates.TemplateResponse("eval/detalle.html", {
        "request": request,
        "abstract": abstract,
        "review": review,
        "success": True,
        "current_user": current_user
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
    abstract.titulo = titulo
    abstract.email_autor = email_autor
    abstract.contenido_html = contenido_html
    abstract.referencias_html = referencias_html
    abstract.area_tematica = area_tematica
    abstract.presentacion_oral = presentacion_oral
    # Borrar autores y afiliaciones anteriores
    db.query(models.Autor).filter(models.Autor.abstract_id == abstract_id).delete()
    db.query(models.Afiliacion).filter(models.Afiliacion.abstract_id == abstract_id).delete()
    db.flush()
    # Guardar afiliaciones nuevas
    for i in range(1, afil_count + 1):
        nombre_afil = request._form.get(f"afil_nombre_{i}", "").strip()
        if nombre_afil:
            db.add(models.Afiliacion(abstract_id=abstract_id, nombre=nombre_afil, orden=i))
    # Guardar autores nuevos
    presentador_idx = request._form.get("presentador", "1")
    autor_presentador = ""
    for i in range(1, autor_count + 1):
        nombre_autor = request._form.get(f"autor_nombre_{i}", "").strip()
        afils_str = request._form.get(f"autor_afils_{i}", "").strip()
        if nombre_autor:
            es_presentador = 1 if str(i) == str(presentador_idx) else 0
            db.add(models.Autor(abstract_id=abstract_id, nombre=nombre_autor, orden=i, es_presentador=es_presentador, afiliaciones_ids=afils_str))
            if es_presentador:
                autor_presentador = nombre_autor
    abstract.autor = autor_presentador
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
    
    if not result.get("success") or result.get("score", 0) < 0.5:
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