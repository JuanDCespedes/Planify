# Planify

- 20232020148 - Juan Diego Cespedes

Planify es una aplicación web en español para organizar eventos, rutinas y recordatorios personales. La solución usa un gateway web y tres microservicios con bases de datos independientes: identidad, planificación y notificaciones.

## Inicio rápido en Windows

Desde la carpeta del repositorio:

```powershell
cd app
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
```

El lanzador genera un token interno aleatorio por ejecución. Mantén `.env` fuera de Git; agrega ahí tus credenciales OAuth si habilitas Google. Si ya existe `app/instance/planify.db`, respáldala y ejecuta la migración antes de iniciar los servicios:

```powershell
.\.venv\Scripts\python.exe migrate_to_microservices.py
```

Inicia los cuatro procesos:

```powershell
powershell -ExecutionPolicy Bypass -File start-planify.ps1
```

Abre [http://127.0.0.1:5000](http://127.0.0.1:5000). Para detener los procesos iniciados por el lanzador:

```powershell
powershell -ExecutionPolicy Bypass -File stop-planify.ps1
```

Los registros locales se guardan bajo `%TEMP%\Planify\logs`. El lanzador desactiva SMTP y Web Push por defecto para evitar envíos reales durante el desarrollo.

## Google OAuth local

En Google Cloud Console, registra el origen autorizado `http://127.0.0.1:5000` y el URI de redirección `http://127.0.0.1:5000/auth/google/callback`. Ambos deben coincidir exactamente con el callback que usa el lanzador. Guarda `GOOGLE_CLIENT_ID` y `GOOGLE_CLIENT_SECRET` únicamente en `.env`; nunca los publiques.

## Servicios y migración

- `identity_service` posee cuentas, contraseñas y preferencias.
- `planning_service` posee eventos, categorías y rutinas.
- `notification_service` posee avisos y suscripciones, ejecuta el scheduler y entrega correo/Web Push.
- El gateway web sirve las páginas y llama a los servicios mediante APIs REST internas autenticadas.

Cada microservicio tiene su propia SQLite y un volumen Docker independiente. Para conservar datos anteriores, `migrate_to_microservices.py` copia filas con propietario, mantiene los identificadores y no modifica la base original. La migración puede repetirse sin duplicar registros. En Docker Compose se ejecuta mediante el perfil de migración:

```powershell
docker compose --profile migration run --rm migrate
docker compose up --build -d
```

La aplicación queda en [http://localhost:8000](http://localhost:8000). SMTP y VAPID son opcionales; sus credenciales se entregan solo al contenedor de notificaciones.

## Documentación

- [Guía de instalación, configuración, uso y despliegue](app/README.md)
- [Manual de usuario](app/docs/manual-usuario.md)
- [Arquitectura de microservicios y flujos](app/docs/arquitectura.md)
- [Trazabilidad de requisitos](app/docs/trazabilidad.md)

## Pruebas

Ejecuta la suite desde `app/`:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```
