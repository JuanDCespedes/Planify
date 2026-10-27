# Planify

- 20232020148 - Juan Diego Céspedes

Planify es una aplicación web en español para organizar eventos, rutinas y recordatorios personales. Cada cuenta tiene su propio espacio de trabajo.

## Inicio rápido en Windows

Desde la carpeta del repositorio:

```powershell
cd app
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe app.py
```

Abre [http://127.0.0.1:5000](http://127.0.0.1:5000) y crea una cuenta. La base SQLite local se guarda en `app/instance/planify.db`.

## Documentación

- [Guía de instalación, configuración, uso y despliegue](app/README.md)
- [Arquitectura técnica y flujos principales](app/docs/architecture.md)

## Desarrollo

Ejecuta las pruebas desde `app/`:

```powershell
python -m unittest discover -s tests -v
```
