from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, Enum
from sqlalchemy.orm import relationship
from datetime import datetime
from app.database import Base
import enum

class RoleEnum(str, enum.Enum):
    admin = "admin"
    evaluador = "evaluador"

class EstadoEnum(str, enum.Enum):
    pendiente = "pendiente"
    aprobado = "aprobado"
    rechazado = "rechazado"

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True, nullable=False)
    nombre = Column(String, nullable=False)
    password_hash = Column(String, nullable=False)
    role = Column(Enum(RoleEnum), nullable=False)
    reviews = relationship("Review", back_populates="evaluador")
    asignaciones = relationship("Asignacion", back_populates="evaluador")

class Abstract(Base):
    __tablename__ = "abstracts"
    id = Column(Integer, primary_key=True, index=True)
    titulo = Column(String, nullable=False)
    autor = Column(String, nullable=False)
    afiliacion = Column(String, nullable=False)
    email_autor = Column(String, nullable=False)
    contenido_html = Column(Text, nullable=False)
    estado = Column(Enum(EstadoEnum), default=EstadoEnum.pendiente)
    fecha_envio = Column(DateTime, default=datetime.utcnow)
    reviews = relationship("Review", back_populates="abstract")
    asignaciones = relationship("Asignacion", back_populates="abstract")

class Review(Base):
    __tablename__ = "reviews"
    id = Column(Integer, primary_key=True, index=True)
    abstract_id = Column(Integer, ForeignKey("abstracts.id"), nullable=False)
    evaluador_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    decision = Column(Enum(EstadoEnum), nullable=True)
    comentario = Column(Text, nullable=True)
    fecha = Column(DateTime, default=datetime.utcnow)
    abstract = relationship("Abstract", back_populates="reviews")
    evaluador = relationship("User", back_populates="reviews")

class Asignacion(Base):
    __tablename__ = "asignaciones"
    id = Column(Integer, primary_key=True, index=True)
    abstract_id = Column(Integer, ForeignKey("abstracts.id"), nullable=False)
    evaluador_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    abstract = relationship("Abstract", back_populates="asignaciones")
    evaluador = relationship("User", back_populates="asignaciones")

class Registration(Base):
    __tablename__ = "registrations"
    id = Column(Integer, primary_key=True, index=True)
    nombre = Column(String, nullable=False)
    email = Column(String, nullable=False)
    afiliacion = Column(String)
    tipo_asistente = Column(String)
    fecha = Column(DateTime, default=datetime.utcnow)

class Session(Base):
    __tablename__ = "sessions"
    id = Column(Integer, primary_key=True, index=True)
    titulo = Column(String, nullable=False)
    hora_inicio = Column(DateTime)
    hora_fin = Column(DateTime)
    sala = Column(String)
    tipo = Column(String)  # charla, poster, keynote, etc.

class Speaker(Base):
    __tablename__ = "speakers"
    id = Column(Integer, primary_key=True, index=True)
    nombre = Column(String, nullable=False)
    afiliacion = Column(String)
    bio = Column(Text)