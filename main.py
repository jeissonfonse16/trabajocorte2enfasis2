"""
main.py - FastAPI application for Predictive Maintenance Inspection Scheduling.

Serves the dashboard frontend and provides REST API endpoints
for plan generation, status updates, simulations, and KPIs.
"""
import json
import os
from datetime import datetime
from fastapi import FastAPI, Depends, Query, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import init_db, get_db, cargar_datos_iniciales, get_rotacion_turnos
from models import Tecnico, OrdenTrabajo, Asignacion
from scheduler import generar_plan, reprogramar, liberar_tecnico
from indicadores import calcular_indicadores

# ═══════════════════════════════════════
# APP SETUP
# ═══════════════════════════════════════

app = FastAPI(title="Inspecciones Predictivas", version="1.0.0")

STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

# Initialize database immediately for Serverless
init_db()
db_init = SessionLocal()
try:
    cargar_datos_iniciales(db_init)
finally:
    db_init.close()

# No need for @app.on_event("startup") in Vercel


# ═══════════════════════════════════════
# PYDANTIC MODELS
# ═══════════════════════════════════════

class GenerarPlanRequest(BaseModel):
    grupo: str
    fecha_inicio: str
    fecha_fin: str

class ActualizarEstadoRequest(BaseModel):
    ot_id: str
    estado: str

class NuevaOTRequest(BaseModel):
    equipo: str
    tarea: str
    tecnica_requerida: str
    duracion_horas: float
    ubicacion: str
    flota: str = "General"

class AusenciaRequest(BaseModel):
    tecnico_id: str
    fecha: str
    grupo: str
    fecha_inicio: str = ""
    fecha_fin: str = ""


# ═══════════════════════════════════════
# ENDPOINTS
# ═══════════════════════════════════════

@app.get("/")
async def root():
    """Serve the main dashboard."""
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))


@app.post("/api/inicializar")
def inicializar(db: Session = Depends(get_db)):
    """Load JSON data into the database if tables are empty."""
    resumen = cargar_datos_iniciales(db)
    return resumen


@app.get("/api/grupos")
def listar_grupos(db: Session = Depends(get_db)):
    """List all available groups."""
    grupos = db.query(Tecnico.grupo).distinct().all()
    return sorted([g[0] for g in grupos])


@app.get("/api/tecnicos")
def listar_tecnicos(grupo: str = Query(None), db: Session = Depends(get_db)):
    """List technicians, optionally filtered by group."""
    query = db.query(Tecnico)
    if grupo:
        query = query.filter(Tecnico.grupo == grupo)
    tecnicos = query.all()
    return [
        {
            "id": t.id,
            "nombre": t.nombre,
            "grupo": t.grupo,
            "habilidades": json.loads(t.habilidades),
        }
        for t in tecnicos
    ]


@app.get("/api/ordenes")
def listar_ordenes(
    estado: str = Query(None),
    grupo: str = Query(None),
    tecnica: str = Query(None),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db)
):
    """List work orders with optional filters and pagination."""
    query = db.query(OrdenTrabajo)

    if estado:
        query = query.filter(OrdenTrabajo.estado == estado)
    if tecnica:
        query = query.filter(OrdenTrabajo.tecnica_requerida == tecnica)

    total = query.count()
    ots = query.offset((page - 1) * per_page).limit(per_page).all()

    # Get assignments for these OTs
    ot_ids = [ot.ot_id for ot in ots]
    asignaciones = db.query(Asignacion).filter(Asignacion.ot_id.in_(ot_ids)).all()
    asig_map = {}
    for a in asignaciones:
        asig_map[a.ot_id] = {
            "tecnico_id": a.tecnico_id,
            "tecnico2_id": a.tecnico2_id,
            "fecha": a.fecha,
            "hora_inicio": a.hora_inicio,
            "hora_fin": a.hora_fin,
            "turno": a.turno,
        }

    # Get technician names
    all_tecnicos = {t.id: t.nombre for t in db.query(Tecnico).all()}

    result = []
    for ot in ots:
        item = {
            "ot_id": ot.ot_id,
            "equipo": ot.equipo,
            "flota": ot.flota,
            "tarea": ot.tarea,
            "tecnica_requerida": ot.tecnica_requerida,
            "duracion_horas": ot.duracion_horas,
            "ubicacion": ot.ubicacion,
            "requiere_pareja": ot.requiere_pareja,
            "fecha_solicitud": ot.fecha_solicitud,
            "estado": ot.estado,
            "asignacion": None,
        }
        if ot.ot_id in asig_map:
            asig = asig_map[ot.ot_id]
            t1_name = all_tecnicos.get(asig["tecnico_id"], asig["tecnico_id"])
            t2_name = all_tecnicos.get(asig["tecnico2_id"], "") if asig["tecnico2_id"] else ""
            item["asignacion"] = {
                **asig,
                "tecnico_nombre": t1_name,
                "tecnico2_nombre": t2_name,
            }
        result.append(item)

    return {"total": total, "page": page, "per_page": per_page, "ordenes": result}


@app.post("/api/generar-plan")
def api_generar_plan(req: GenerarPlanRequest, db: Session = Depends(get_db)):
    """Generate a weekly schedule plan."""
    resultado = generar_plan(db, req.grupo, req.fecha_inicio, req.fecha_fin)
    return resultado


@app.get("/api/plan-semanal")
def plan_semanal(
    grupo: str = Query(...),
    fecha_inicio: str = Query(...),
    fecha_fin: str = Query(...),
    db: Session = Depends(get_db)
):
    """Get the weekly plan with assignments, schedules, and technicians."""
    # Get assignments for this group and date range
    asignaciones = db.query(Asignacion).filter(
        Asignacion.grupo == grupo,
        Asignacion.fecha >= fecha_inicio,
        Asignacion.fecha <= fecha_fin,
    ).all()

    # Get technicians
    tecnicos = db.query(Tecnico).filter(Tecnico.grupo == grupo).all()
    tech_names = {t.id: t.nombre for t in tecnicos}

    # Get rotation for this group
    rotacion = get_rotacion_turnos()
    calendario = {}
    for rot in rotacion:
        if rot["grupo"] == grupo:
            calendario = rot["calendario"]
            break

    # Build plan structure: per technician, per day
    plan = {}
    for t in tecnicos:
        habs = json.loads(t.habilidades)
        if not habs:
            continue
        plan[t.id] = {
            "nombre": t.nombre,
            "habilidades": habs,
            "dias": {},
        }

    # Fill in assignments
    ot_cache = {}
    for asig in asignaciones:
        if asig.ot_id not in ot_cache:
            ot = db.query(OrdenTrabajo).filter(OrdenTrabajo.ot_id == asig.ot_id).first()
            ot_cache[asig.ot_id] = ot

        ot = ot_cache[asig.ot_id]
        entry = {
            "ot_id": asig.ot_id,
            "equipo": ot.equipo if ot else "",
            "tarea": ot.tarea if ot else "",
            "tecnica": ot.tecnica_requerida if ot else "",
            "ubicacion": ot.ubicacion if ot else "",
            "hora_inicio": asig.hora_inicio,
            "hora_fin": asig.hora_fin,
            "duracion": ot.duracion_horas if ot else 0,
            "traslado_min": asig.tiempo_traslado_min,
            "estado": asig.estado,
            "pareja": tech_names.get(asig.tecnico2_id, "") if asig.tecnico2_id else "",
        }

        for tid in [asig.tecnico_id, asig.tecnico2_id]:
            if tid and tid in plan:
                if asig.fecha not in plan[tid]["dias"]:
                    plan[tid]["dias"][asig.fecha] = []
                plan[tid]["dias"][asig.fecha].append(entry)

    return {
        "grupo": grupo,
        "fecha_inicio": fecha_inicio,
        "fecha_fin": fecha_fin,
        "calendario": calendario,
        "tecnicos": plan,
    }


@app.put("/api/actualizar-estado")
def actualizar_estado(req: ActualizarEstadoRequest, db: Session = Depends(get_db)):
    """Update OT status. If 'no_ejecutada', also update the assignment."""
    ot = db.query(OrdenTrabajo).filter(OrdenTrabajo.ot_id == req.ot_id).first()
    if not ot:
        raise HTTPException(status_code=404, detail=f"OT {req.ot_id} not found")

    valid_estados = ["pendiente", "programada", "en_ejecucion", "finalizada", "no_ejecutada"]
    if req.estado not in valid_estados:
        raise HTTPException(status_code=400, detail=f"Invalid estado: {req.estado}")

    ot.estado = req.estado

    # Update assignment status too
    asig = db.query(Asignacion).filter(Asignacion.ot_id == req.ot_id).first()
    if asig:
        asig.estado = req.estado

    db.commit()

    return {"ot_id": req.ot_id, "estado": req.estado, "updated": True}


@app.post("/api/nueva-ot")
def nueva_ot(req: NuevaOTRequest, db: Session = Depends(get_db)):
    """Add a new work order to the pending queue."""
    # Generate a unique OT ID
    max_num = 0
    all_ots = db.query(OrdenTrabajo.ot_id).all()
    for (oid,) in all_ots:
        try:
            num = int(oid.replace("OT", ""))
            max_num = max(max_num, num)
        except ValueError:
            pass

    new_id = f"OT{max_num + 1:03d}"

    requiere_pareja = "Zona" in req.ubicacion

    nueva = OrdenTrabajo(
        ot_id=new_id,
        equipo=req.equipo,
        flota=req.flota,
        tarea=req.tarea,
        tecnica_requerida=req.tecnica_requerida,
        duracion_horas=req.duracion_horas,
        ubicacion=req.ubicacion,
        requiere_pareja=requiere_pareja,
        fecha_solicitud=datetime.now().strftime("%Y-%m-%d"),
        estado="pendiente",
    )
    db.add(nueva)
    db.commit()

    return {"ot_id": new_id, "estado": "pendiente", "created": True}


@app.post("/api/ausencia-tecnico")
def ausencia_tecnico(req: AusenciaRequest, db: Session = Depends(get_db)):
    """Handle technician absence: free their OTs and reschedule."""
    # Determine date range for rescheduling
    fecha_inicio = req.fecha_inicio or req.fecha
    fecha_fin = req.fecha_fin or req.fecha

    resultado = liberar_tecnico(
        db, req.tecnico_id, req.fecha,
        req.grupo, fecha_inicio, fecha_fin
    )
    return resultado


@app.get("/api/indicadores")
def api_indicadores(
    grupo: str = Query(None),
    fecha_inicio: str = Query(None),
    fecha_fin: str = Query(None),
    db: Session = Depends(get_db)
):
    """Get KPIs for the dashboard."""
    return calcular_indicadores(db, grupo, fecha_inicio, fecha_fin)


@app.delete("/api/reset")
def reset_data(db: Session = Depends(get_db)):
    """Reset all assignments and set all OTs back to 'pendiente' (for testing)."""
    db.query(Asignacion).delete()
    db.query(OrdenTrabajo).update({OrdenTrabajo.estado: "pendiente"})
    db.commit()
    return {"reset": True, "message": "All assignments deleted, OTs set to pendiente"}


@app.get("/api/rotacion")
def get_rotacion(grupo: str = Query(None)):
    """Get rotation calendar, optionally filtered by group."""
    rotacion = get_rotacion_turnos()
    if grupo:
        for rot in rotacion:
            if rot["grupo"] == grupo:
                return rot
        return {"grupo": grupo, "calendario": {}}
    return rotacion
