# Inspecciones Predictivas - Dashboard

Aplicacion web para la **Programacion Dinamica de Inspecciones Predictivas** de mantenimiento industrial.

## Stack Tecnologico

- **Backend**: Python + FastAPI
- **Frontend**: HTML + CSS + JavaScript vanilla
- **Base de datos**: SQLite con SQLAlchemy
- **Servidor**: Uvicorn

## Estructura del Proyecto

```
inspecciones_app/
├── main.py              # FastAPI app + endpoints
├── database.py          # Engine, sesiones, carga de datos
├── models.py            # Modelos SQLAlchemy (ORM)
├── scheduler.py         # Motor de programacion (asignacion greedy)
├── indicadores.py       # Calculo de KPIs
├── datos_json/          # Datos fuente (4 archivos JSON)
│   ├── tecnicos.json
│   ├── ordenes_trabajo.json
│   ├── tiempos_traslado.json
│   └── rotacion_turnos.json
├── static/
│   ├── index.html       # Dashboard principal
│   ├── style.css        # Estilos (tema oscuro)
│   └── app.js           # Logica del frontend
├── requirements.txt
└── README.md
```

## Instalacion y Ejecucion

```bash
# 1. Instalar dependencias
pip install -r requirements.txt

# 2. Iniciar el servidor
python -m uvicorn main:app --reload

# 3. Abrir en el navegador
# http://localhost:8000
```

## Uso

1. Abrir `http://localhost:8000`
2. Seleccionar un **grupo** (1-4) y una **fecha de inicio de semana**
3. Hacer clic en **"Generar Plan"**
4. Ver el Gantt semanal, KPIs y tabla de OTs
5. Usar el panel de simulacion (boton flotante) para agregar OTs o registrar ausencias

## Reglas de Negocio

- **Turno de 12 horas**: 9 horas efectivas (bloques operativos)
- **Trabajo de campo**: requiere 2 tecnicos del mismo grupo
- **Habilidades**: solo se asigna si el tecnico domina la tecnica
- **Traslados**: el tiempo cuenta dentro de las 9 horas
- **Sin interrupciones**: las inspecciones no se parten por almuerzo/cena

## API Endpoints

| Metodo | Ruta | Descripcion |
|--------|------|-------------|
| GET | `/` | Dashboard |
| POST | `/api/inicializar` | Carga datos iniciales |
| GET | `/api/grupos` | Lista grupos |
| GET | `/api/tecnicos` | Lista tecnicos |
| GET | `/api/ordenes` | Lista OTs con filtros |
| POST | `/api/generar-plan` | Genera plan semanal |
| GET | `/api/plan-semanal` | Obtiene plan con Gantt |
| PUT | `/api/actualizar-estado` | Actualiza estado de OT |
| POST | `/api/nueva-ot` | Agrega OT nueva |
| POST | `/api/ausencia-tecnico` | Registra ausencia |
| GET | `/api/indicadores` | KPIs en tiempo real |
| DELETE | `/api/reset` | Reset para pruebas |
