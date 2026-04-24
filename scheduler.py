"""
scheduler.py - Core scheduling engine for predictive maintenance inspections.

Implements the greedy assignment algorithm respecting:
  - 12-hour shift structure with fixed blocks (startup, lunch/dinner, closeout)
  - 9 effective hours per shift
  - Skill matching between technicians and required techniques
  - Field work requires pairs of technicians from the same group
  - Travel time counted within the 9-hour budget
  - Inspections cannot be interrupted by lunch/dinner breaks
"""
import json
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from models import Tecnico, OrdenTrabajo, Asignacion
from database import get_rotacion_turnos, get_tiempos_traslado_dict

# ═══════════════════════════════════════
# SHIFT STRUCTURE CONSTANTS
# ═══════════════════════════════════════

# Day shift (06:00-18:00)
DAY_BLOCKS = [
    ("07:00", "12:00"),  # Operative block 1
    ("13:00", "17:00"),  # Operative block 2
]

# Night shift (18:00-06:00)
NIGHT_BLOCKS = [
    ("19:00", "23:00"),  # Operative block 1
    ("00:00", "05:00"),  # Operative block 2
]

MAX_EFFECTIVE_HOURS = 9.0


def _parse_time(t: str) -> int:
    """Convert HH:MM to minutes from midnight."""
    h, m = map(int, t.split(":"))
    return h * 60 + m


def _format_time(minutes: int) -> str:
    """Convert minutes from midnight to HH:MM."""
    minutes = minutes % (24 * 60)
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def _get_block_ranges(turno: str) -> list:
    """
    Return list of (start_min, end_min) for operative blocks.
    For night shift, times after midnight are represented as > 1440.
    """
    if turno == "Dia":
        return [(_parse_time(s), _parse_time(e)) for s, e in DAY_BLOCKS]
    else:
        blocks = []
        for s, e in NIGHT_BLOCKS:
            s_min = _parse_time(s)
            e_min = _parse_time(e)
            # Night shift: times before 06:00 next day
            if s_min < 18 * 60:  # after midnight
                s_min += 24 * 60
            if e_min < 18 * 60:
                e_min += 24 * 60
            blocks.append((s_min, e_min))
        return blocks


def _get_turno_for_grupo(grupo: str, fecha: str) -> str | None:
    """
    Look up the shift type for a grupo on a given date.
    Returns 'Dia', 'Noche', or None (Descanso).
    """
    rotacion = get_rotacion_turnos()
    for rot in rotacion:
        if rot["grupo"] == grupo:
            turno = rot["calendario"].get(fecha)
            if turno and turno != "Descanso":
                return turno
            return None
    return None


def _get_travel_time(origen: str, destino: str) -> int:
    """Get travel time in minutes between two locations."""
    if origen == destino:
        return 0

    tiempos = get_tiempos_traslado_dict()

    # From Taller to a Zone
    if origen == "Taller":
        return tiempos["desde_taller"].get(destino, 0)

    # From a Zone to Taller (use the same time as taller->zone)
    if destino == "Taller":
        return tiempos["desde_taller"].get(origen, 0)

    # Between zones
    return tiempos["entre_zonas"].get(origen, {}).get(destino, 0)


class TechnicianState:
    """Tracks a technician's schedule throughout a shift."""

    def __init__(self, tecnico_id: str, habilidades: list, turno: str):
        self.id = tecnico_id
        self.habilidades = habilidades
        self.turno = turno
        self.blocks = _get_block_ranges(turno)
        self.used_hours = 0.0
        self.current_location = "Taller"  # Everyone starts at Taller
        self.schedule = []  # List of (start_min, end_min, ot_id)

    @property
    def remaining_hours(self) -> float:
        return MAX_EFFECTIVE_HOURS - self.used_hours

    def has_skill(self, tecnica: str) -> bool:
        if tecnica == "General":
            return True
        return tecnica in self.habilidades

    def find_slot(self, duration_hours: float, travel_min: int) -> tuple | None:
        """
        Find the earliest available time slot for a task.
        Returns (start_min, end_min) or None if no slot available.
        The task must fit entirely within one operative block (no break interruption).
        """
        total_min_needed = travel_min + int(duration_hours * 60)

        if (self.used_hours + travel_min / 60 + duration_hours) > MAX_EFFECTIVE_HOURS:
            return None

        for block_start, block_end in self.blocks:
            # Find the earliest start within this block
            earliest = block_start
            for sched_start, sched_end, _ in self.schedule:
                if sched_end > earliest and sched_start < block_end:
                    earliest = max(earliest, sched_end)

            actual_task_start = earliest + travel_min
            actual_task_end = actual_task_start + int(duration_hours * 60)

            # Check if the entire task fits within this block
            if actual_task_end <= block_end:
                return (earliest, actual_task_end)

        return None

    def assign(self, start_min: int, end_min: int, ot_id: str,
               travel_min: int, duration_hours: float, destination: str):
        """Record an assignment."""
        self.schedule.append((start_min, end_min, ot_id))
        self.used_hours += travel_min / 60 + duration_hours
        self.current_location = destination


def generar_plan(db: Session, grupo: str, fecha_inicio: str, fecha_fin: str) -> dict:
    """
    Generate a weekly schedule for the given group and date range.

    Algorithm:
    1. For each day, determine if the group works and what shift
    2. Get all pending OTs
    3. Sort: field work first (require pair), then by duration descending
    4. Greedy assignment: for each OT, find best technician(s) with skill + availability
    5. Record assignments in DB

    Returns summary dict.
    """
    start = datetime.strptime(fecha_inicio, "%Y-%m-%d")
    end = datetime.strptime(fecha_fin, "%Y-%m-%d")

    # Get technicians for this group
    tecnicos_db = db.query(Tecnico).filter(Tecnico.grupo == grupo).all()
    if not tecnicos_db:
        return {"error": f"No technicians found for {grupo}"}

    total_asignadas = 0
    total_pendientes = 0
    dias_trabajados = 0
    resumen_dias = []

    current = start
    while current <= end:
        fecha = current.strftime("%Y-%m-%d")
        turno = _get_turno_for_grupo(grupo, fecha)

        if turno is None:
            resumen_dias.append({
                "fecha": fecha,
                "turno": "Descanso",
                "asignadas": 0,
                "pendientes": 0,
            })
            current += timedelta(days=1)
            continue

        dias_trabajados += 1

        # Initialize technician states for this day
        tech_states = {}
        for t in tecnicos_db:
            habs = json.loads(t.habilidades)
            if habs:  # Skip technicians with no skills
                tech_states[t.id] = TechnicianState(t.id, habs, turno)

        # Get pending OTs (sorted: field first, then by duration desc)
        ots_pendientes = db.query(OrdenTrabajo).filter(
            OrdenTrabajo.estado == "pendiente"
        ).all()

        ots_sorted = sorted(
            ots_pendientes,
            key=lambda ot: (0 if ot.requiere_pareja else 1, -ot.duracion_horas)
        )

        dia_asignadas = 0

        for ot in ots_sorted:
            if ot.requiere_pareja:
                # Field work - need 2 technicians
                assigned = _assign_pair(
                    db, ot, tech_states, fecha, turno, grupo
                )
            else:
                # Workshop work - need 1 technician
                assigned = _assign_single(
                    db, ot, tech_states, fecha, turno, grupo
                )

            if assigned:
                dia_asignadas += 1
                total_asignadas += 1

        # Count remaining pending
        remaining = db.query(OrdenTrabajo).filter(
            OrdenTrabajo.estado == "pendiente"
        ).count()

        resumen_dias.append({
            "fecha": fecha,
            "turno": turno,
            "asignadas": dia_asignadas,
            "pendientes": remaining,
        })

        current += timedelta(days=1)

    total_pendientes = db.query(OrdenTrabajo).filter(
        OrdenTrabajo.estado == "pendiente"
    ).count()

    return {
        "grupo": grupo,
        "fecha_inicio": fecha_inicio,
        "fecha_fin": fecha_fin,
        "total_asignadas": total_asignadas,
        "total_pendientes": total_pendientes,
        "dias_trabajados": dias_trabajados,
        "resumen_dias": resumen_dias,
    }


def _assign_single(db: Session, ot: OrdenTrabajo, tech_states: dict,
                    fecha: str, turno: str, grupo: str) -> bool:
    """Try to assign a single technician to a workshop/taller OT."""
    best_tech = None
    best_slot = None
    best_travel = 0

    for tid, state in tech_states.items():
        if not state.has_skill(ot.tecnica_requerida):
            continue

        travel = _get_travel_time(state.current_location, ot.ubicacion)
        slot = state.find_slot(ot.duracion_horas, travel)

        if slot is not None:
            if best_tech is None or state.remaining_hours > tech_states[best_tech].remaining_hours:
                best_tech = tid
                best_slot = slot
                best_travel = travel

    if best_tech and best_slot:
        start_min, end_min = best_slot
        task_start = start_min + best_travel

        db.add(Asignacion(
            ot_id=ot.ot_id,
            tecnico_id=best_tech,
            tecnico2_id=None,
            fecha=fecha,
            hora_inicio=_format_time(task_start),
            hora_fin=_format_time(end_min),
            tiempo_traslado_min=best_travel,
            turno=turno,
            grupo=grupo,
            estado="programada",
        ))
        ot.estado = "programada"
        db.commit()

        tech_states[best_tech].assign(
            start_min, end_min, ot.ot_id,
            best_travel, ot.duracion_horas, ot.ubicacion
        )
        return True

    return False


def _assign_pair(db: Session, ot: OrdenTrabajo, tech_states: dict,
                 fecha: str, turno: str, grupo: str) -> bool:
    """Try to assign a pair of technicians to a field OT."""
    # Find all technicians with the required skill
    eligible = []
    for tid, state in tech_states.items():
        if not state.has_skill(ot.tecnica_requerida):
            continue
        travel = _get_travel_time(state.current_location, ot.ubicacion)
        slot = state.find_slot(ot.duracion_horas, travel)
        if slot is not None:
            eligible.append((tid, slot, travel))

    if len(eligible) < 2:
        return False

    # Sort by most available time remaining (spread workload)
    eligible.sort(key=lambda x: -tech_states[x[0]].remaining_hours)

    # Find a pair that can work at the same time
    for i in range(len(eligible)):
        for j in range(i + 1, len(eligible)):
            tid1, slot1, travel1 = eligible[i]
            tid2, slot2, travel2 = eligible[j]

            # Find common start time (latest of the two)
            task_start1 = slot1[0] + travel1
            task_start2 = slot2[0] + travel2
            common_start = max(task_start1, task_start2)
            common_end = common_start + int(ot.duracion_horas * 60)

            # Verify both can accommodate this common slot
            can1 = _verify_common_slot(tech_states[tid1], common_start - travel1, common_end)
            can2 = _verify_common_slot(tech_states[tid2], common_start - travel2, common_end)

            if can1 and can2:
                db.add(Asignacion(
                    ot_id=ot.ot_id,
                    tecnico_id=tid1,
                    tecnico2_id=tid2,
                    fecha=fecha,
                    hora_inicio=_format_time(common_start),
                    hora_fin=_format_time(common_end),
                    tiempo_traslado_min=max(travel1, travel2),
                    turno=turno,
                    grupo=grupo,
                    estado="programada",
                ))
                ot.estado = "programada"
                db.commit()

                tech_states[tid1].assign(
                    common_start - travel1, common_end, ot.ot_id,
                    travel1, ot.duracion_horas, ot.ubicacion
                )
                tech_states[tid2].assign(
                    common_start - travel2, common_end, ot.ot_id,
                    travel2, ot.duracion_horas, ot.ubicacion
                )
                return True

    return False


def _verify_common_slot(state: TechnicianState, slot_start: int, slot_end: int) -> bool:
    """Verify that a specific time range fits within the technician's available blocks."""
    for block_start, block_end in state.blocks:
        if slot_start >= block_start and slot_end <= block_end:
            # Check no overlap with existing schedule
            for s, e, _ in state.schedule:
                if slot_start < e and slot_end > s:
                    return False
            return True
    return False


def reprogramar(db: Session, ot_ids: list, grupo: str,
                fecha_inicio: str, fecha_fin: str) -> dict:
    """
    Reschedule specific OTs:
    1. Set them back to 'pendiente'
    2. Remove their assignments
    3. Re-run the planner for remaining days
    """
    for ot_id in ot_ids:
        # Delete assignment
        db.query(Asignacion).filter(Asignacion.ot_id == ot_id).delete()
        # Reset OT status
        ot = db.query(OrdenTrabajo).filter(OrdenTrabajo.ot_id == ot_id).first()
        if ot:
            ot.estado = "pendiente"

    db.commit()

    # Re-generate plan
    return generar_plan(db, grupo, fecha_inicio, fecha_fin)


def liberar_tecnico(db: Session, tecnico_id: str, fecha: str,
                    grupo: str, fecha_inicio: str, fecha_fin: str) -> dict:
    """
    Handle technician absence:
    1. Find all assignments for this tech on this date
    2. Free those OTs
    3. Re-run scheduler
    """
    asignaciones = db.query(Asignacion).filter(
        Asignacion.fecha == fecha,
        (Asignacion.tecnico_id == tecnico_id) | (Asignacion.tecnico2_id == tecnico_id)
    ).all()

    ot_ids = [a.ot_id for a in asignaciones]

    for asig in asignaciones:
        ot = db.query(OrdenTrabajo).filter(OrdenTrabajo.ot_id == asig.ot_id).first()
        if ot:
            ot.estado = "pendiente"
        db.delete(asig)

    db.commit()

    return {
        "tecnico": tecnico_id,
        "fecha": fecha,
        "ots_liberadas": ot_ids,
        "reprogramacion": generar_plan(db, grupo, fecha_inicio, fecha_fin),
    }
