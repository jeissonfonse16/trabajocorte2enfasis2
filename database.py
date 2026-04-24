"""
database.py - Database engine, session management, and initial data loading.
Loads data from the 4 JSON files in datos_json/ when tables are empty.
"""
import json
import os
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker, Session
from models import Base, Tecnico, TiempoTraslado, OrdenTrabajo, Asignacion

# Path to database - use /tmp on Vercel as it's the only writable directory
if os.environ.get('VERCEL'):
    DB_PATH = "/tmp/inspecciones.db"
else:
    DB_PATH = os.path.join(os.path.dirname(__file__), "inspecciones.db")
ENGINE = create_engine(f"sqlite:///{DB_PATH}", echo=False)
SessionLocal = sessionmaker(bind=ENGINE)

# Path to JSON data - Ensure absolute path
JSON_DIR = os.path.join(os.path.abspath(os.path.dirname(__file__)), "datos_json")


def init_db():
    """Create all tables if they don't exist."""
    print(f"DEBUG: Inicializando BD en {DB_PATH}")
    Base.metadata.create_all(ENGINE)


def get_db():
    """FastAPI dependency for database sessions."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _load_json(filename: str):
    """Load a JSON file from the datos_json directory."""
    filepath = os.path.join(JSON_DIR, filename)
    with open(filepath, "r", encoding="utf-8") as f:
        return json.load(f)


def cargar_datos_iniciales(db: Session) -> dict:
    """
    Load initial data from JSON files into the database.
    Only loads if the respective table is empty.
    Returns a summary of records loaded.
    """
    resumen = {"tecnicos": 0, "ots": 0, "traslados": 0, "rotacion": "ya_cargada"}

    # ── Load Tecnicos ──
    if db.query(Tecnico).count() == 0:
        tecnicos_data = _load_json("tecnicos.json")
        for t in tecnicos_data:
            db.add(Tecnico(
                id=t["id"],
                nombre=t["nombre"],
                grupo=t["grupo"],
                habilidades=json.dumps(t["habilidades"], ensure_ascii=False),
            ))
        db.commit()
        resumen["tecnicos"] = len(tecnicos_data)

    # ── Load Tiempos de Traslado ──
    if db.query(TiempoTraslado).count() == 0:
        tiempos_data = _load_json("tiempos_traslado.json")

        # desde_taller entries (origin = "Taller")
        for zona, minutos in tiempos_data["desde_taller"].items():
            db.add(TiempoTraslado(origen="Taller", destino=zona, minutos=minutos))

        # entre_zonas entries
        for origen, destinos in tiempos_data["entre_zonas"].items():
            for destino, minutos in destinos.items():
                db.add(TiempoTraslado(origen=origen, destino=destino, minutos=minutos))

        # mismo_lugar (self-referencing entries with 0 minutes)
        db.add(TiempoTraslado(origen="Taller", destino="Taller", minutos=0))
        for zona in tiempos_data["desde_taller"]:
            db.add(TiempoTraslado(origen=zona, destino=zona, minutos=0))

        db.commit()
        resumen["traslados"] = db.query(TiempoTraslado).count()

    # ── Load Ordenes de Trabajo ──
    if db.query(OrdenTrabajo).count() == 0:
        ots_data = _load_json("ordenes_trabajo.json")
        for ot in ots_data:
            db.add(OrdenTrabajo(
                ot_id=ot["ot_id"],
                equipo=ot["equipo"],
                flota=ot["flota"],
                tarea=ot["tarea"],
                tecnica_requerida=ot["tecnica_requerida"],
                duracion_horas=ot["duracion_horas"],
                ubicacion=ot["ubicacion"],
                requiere_pareja=ot["requiere_pareja"],
                fecha_solicitud=ot["fecha_solicitud"],
                estado=ot["estado"],
            ))
        db.commit()
        resumen["ots"] = len(ots_data)

    return resumen


def get_rotacion_turnos() -> list:
    """Load rotation schedule directly from JSON (not stored in DB)."""
    return _load_json("rotacion_turnos.json")


def get_tiempos_traslado_dict() -> dict:
    """Load travel times as the original dict structure from JSON."""
    return _load_json("tiempos_traslado.json")
