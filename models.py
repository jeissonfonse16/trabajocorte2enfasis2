"""
models.py - SQLAlchemy ORM models for the inspection scheduling app.
"""
from sqlalchemy import Column, String, Integer, Float, Boolean, Text, create_engine
from sqlalchemy.orm import declarative_base

Base = declarative_base()


class Tecnico(Base):
    __tablename__ = "tecnicos"
    id = Column(String, primary_key=True)
    nombre = Column(String, nullable=False)
    grupo = Column(String, nullable=False)
    habilidades = Column(Text, nullable=False)  # JSON serialized


class TiempoTraslado(Base):
    __tablename__ = "tiempos_traslado"
    id = Column(Integer, primary_key=True, autoincrement=True)
    origen = Column(String, nullable=False)
    destino = Column(String, nullable=False)
    minutos = Column(Integer, nullable=False)


class OrdenTrabajo(Base):
    __tablename__ = "ordenes_trabajo"
    ot_id = Column(String, primary_key=True)
    equipo = Column(String, nullable=False)
    flota = Column(String, nullable=False)
    tarea = Column(Text, nullable=False)
    tecnica_requerida = Column(String, nullable=False)
    duracion_horas = Column(Float, nullable=False)
    ubicacion = Column(String, nullable=False)
    requiere_pareja = Column(Boolean, nullable=False, default=False)
    fecha_solicitud = Column(String, nullable=False)
    estado = Column(String, nullable=False, default="pendiente")


class Asignacion(Base):
    __tablename__ = "asignaciones"
    id = Column(Integer, primary_key=True, autoincrement=True)
    ot_id = Column(String, nullable=False)
    tecnico_id = Column(String, nullable=False)
    tecnico2_id = Column(String, nullable=True)
    fecha = Column(String, nullable=False)
    hora_inicio = Column(String, nullable=False)
    hora_fin = Column(String, nullable=False)
    tiempo_traslado_min = Column(Integer, nullable=False, default=0)
    turno = Column(String, nullable=False)
    grupo = Column(String, nullable=False)
    estado = Column(String, nullable=False, default="programada")
