"""
indicadores.py - KPI calculations for the inspection scheduling dashboard.

Computes:
  - Total OTs by status
  - Compliance percentage
  - Average utilization per technician
  - Travel time totals
  - Non-productive time
  - Per-technician detail breakdown
"""
import json
from sqlalchemy.orm import Session
from models import Tecnico, OrdenTrabajo, Asignacion


def calcular_indicadores(db: Session, grupo: str = None,
                         fecha_inicio: str = None, fecha_fin: str = None) -> dict:
    """
    Calculate KPIs for the given group and date range.

    Formulas:
      cumplimiento_pct     = finalizadas / (programadas + en_ejecucion + finalizadas) * 100
      utilizacion_pct      = (horas_inspeccion + horas_traslado) / 9 * 100
      tiempo_no_productivo = 9 - horas_inspeccion - horas_traslado (per active tech)
    """

    # ── Count OTs by status ──
    ots_query = db.query(OrdenTrabajo)
    total_ots = ots_query.count()

    estados = {}
    for estado in ["pendiente", "programada", "en_ejecucion", "finalizada", "no_ejecutada"]:
        estados[estado] = ots_query.filter(OrdenTrabajo.estado == estado).count()

    # ── Compliance ──
    denom = estados["programada"] + estados["en_ejecucion"] + estados["finalizada"]
    cumplimiento = (estados["finalizada"] / denom * 100) if denom > 0 else 0.0

    # ── Get assignments filtered by grupo and dates ──
    asig_query = db.query(Asignacion)
    if grupo:
        asig_query = asig_query.filter(Asignacion.grupo == grupo)
    if fecha_inicio:
        asig_query = asig_query.filter(Asignacion.fecha >= fecha_inicio)
    if fecha_fin:
        asig_query = asig_query.filter(Asignacion.fecha <= fecha_fin)

    asignaciones = asig_query.all()

    # ── Per-technician calculations ──
    tech_data = {}  # tecnico_id -> {horas_inspeccion, horas_traslado, ots_count, dias}

    for asig in asignaciones:
        # Calculate inspection duration from hora_inicio / hora_fin
        h_inicio = _time_to_hours(asig.hora_inicio)
        h_fin = _time_to_hours(asig.hora_fin)

        # Handle night shift crossing midnight
        if h_fin < h_inicio:
            duracion = (24 - h_inicio) + h_fin
        else:
            duracion = h_fin - h_inicio

        traslado_horas = asig.tiempo_traslado_min / 60.0

        for tid in [asig.tecnico_id, asig.tecnico2_id]:
            if tid is None:
                continue
            if tid not in tech_data:
                tech_data[tid] = {
                    "horas_inspeccion": 0.0,
                    "horas_traslado": 0.0,
                    "ots_count": 0,
                    "dias": set(),
                }
            tech_data[tid]["horas_inspeccion"] += duracion
            tech_data[tid]["horas_traslado"] += traslado_horas
            tech_data[tid]["ots_count"] += 1
            tech_data[tid]["dias"].add(asig.fecha)

    # Build per-technician detail
    tecnicos_detalle = []
    total_traslado_horas = 0.0
    total_no_productivo = 0.0
    sum_utilizacion = 0.0
    active_count = 0

    # Get technician names
    all_tecnicos = {t.id: t.nombre for t in db.query(Tecnico).all()}

    for tid, data in tech_data.items():
        num_dias = len(data["dias"])
        max_horas = 9.0 * num_dias  # 9 effective hours per shift day

        total_horas = data["horas_inspeccion"] + data["horas_traslado"]
        utilizacion = (total_horas / max_horas * 100) if max_horas > 0 else 0.0
        no_productivo = max(0, max_horas - total_horas)

        tecnicos_detalle.append({
            "tecnico": all_tecnicos.get(tid, tid),
            "tecnico_id": tid,
            "horas_inspeccion": round(data["horas_inspeccion"], 1),
            "horas_traslado": round(data["horas_traslado"], 1),
            "utilizacion_pct": round(min(utilizacion, 100), 1),
            "ots_asignadas": data["ots_count"],
        })

        total_traslado_horas += data["horas_traslado"]
        total_no_productivo += no_productivo
        sum_utilizacion += utilizacion
        active_count += 1

    avg_utilizacion = (sum_utilizacion / active_count) if active_count > 0 else 0.0

    return {
        "total_ots": total_ots,
        "programadas": estados["programada"],
        "en_ejecucion": estados["en_ejecucion"],
        "finalizadas": estados["finalizada"],
        "no_ejecutadas": estados["no_ejecutada"],
        "pendientes_backlog": estados["pendiente"],
        "cumplimiento_pct": round(cumplimiento, 1),
        "utilizacion_promedio_pct": round(avg_utilizacion, 1),
        "tiempo_traslados_horas": round(total_traslado_horas, 1),
        "tiempo_no_productivo_horas": round(total_no_productivo, 1),
        "tecnicos_detalle": sorted(tecnicos_detalle, key=lambda x: x["tecnico"]),
    }


def _time_to_hours(time_str: str) -> float:
    """Convert HH:MM string to decimal hours."""
    if not time_str:
        return 0.0
    parts = time_str.split(":")
    return int(parts[0]) + int(parts[1]) / 60.0
