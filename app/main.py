from datetime import datetime
from fastapi import FastAPI, Request, Response, Depends, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
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

models.Base.metadata.create_all(bind=engine)

app = FastAPI(title="Congreso")
app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")

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
    db: Session = Depends(get_db)
):
    if not contenido_html or contenido_html.strip() == "<p></p>":
        return templates.TemplateResponse("public/submit.html", {
            "request": request,
            "error": "El resumen no puede estar vacío."
        })

    abstract = models.Abstract(
        titulo=titulo,
        autor="",  # se llena abajo con el presentador
        afiliacion="",
        email_autor=email_autor,
        contenido_html=contenido_html,
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
    return templates.TemplateResponse("admin/abstracts.html", {
        "request": request,
        "abstracts": abstracts,
        "estado_filtro": estado,
        "area_filtro": area,
        "current_user": current_user
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
    evaluadores = db.query(models.User).filter(models.User.role == models.RoleEnum.evaluador).all()
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
    asig = models.Asignacion(abstract_id=abstract_id, evaluador_id=evaluador_id)
    db.add(asig)
    db.commit()
    return RedirectResponse(url=f"/admin/abstracts/{abstract_id}", status_code=302)

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
    else:
        review = models.Review(
            abstract_id=abstract_id,
            evaluador_id=current_user.id,
            decision=decision,
            comentario=comentario
        )
        db.add(review)
    db.commit()
    abstract = asig.abstract
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
    print("DEBUG abstracts:", len(abstracts), [a.titulo for a in abstracts])
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


@app.get("/debug/aprobados")
def debug_aprobados(db: Session = Depends(get_db)):
    abstracts = db.query(models.Abstract).filter(
        models.Abstract.estado == models.EstadoEnum.aprobado
    ).all()
    return [{"id": a.id, "titulo": a.titulo, "estado": a.estado} for a in abstracts]



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