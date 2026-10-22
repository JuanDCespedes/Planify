# Planify

Planify es una primera versión funcional de un planificador personal en español. Permite organizar eventos, consultar el calendario, crear bloques de rutina, gestionar notificaciones de demostración y cambiar entre tema claro y oscuro.

## Requisitos

- Windows 10/11
- Python 3.10 o posterior
- Visual Studio Code (recomendado) y la extensión oficial de Python

## Preparar y ejecutar en Windows

1. Abre `planify.code-workspace` en VS Code o abre esta carpeta.
2. En la terminal integrada de PowerShell, crea y activa un entorno virtual:

   ```powershell
   py -m venv .venv
   .\.venv\Scripts\Activate.ps1
   ```

   Si PowerShell bloquea la activación, permite scripts solo en la sesión actual con `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass` y vuelve a activar el entorno.

3. Instala las dependencias:

   ```powershell
   python -m pip install -r requirements.txt
   ```

4. Inicia el servidor local:

   ```powershell
   python app.py
   ```

5. Abre la dirección que muestra Flask, normalmente `http://127.0.0.1:5000`.

La base SQLite se crea automáticamente en `instance/planify.db` y se carga con eventos, bloques de rutina y notificaciones de ejemplo la primera vez. Para usar otra ubicación, configura `PLANIFY_DATABASE_URL` antes de iniciar la aplicación.

## Pruebas

Con el entorno virtual activo:

```powershell
python -m unittest discover -s tests -v
```

## Capas de la aplicación

- `planify/presentation/`: rutas Flask y vistas Jinja; valida entrada HTTP y coordina la respuesta.
- `planify/application/`: servicios de casos de uso, consultas, operaciones y carga inicial de datos.
- `planify/domain/`: entidades SQLAlchemy y reglas de validación reutilizables, sin dependencias de Flask.
- `planify/infrastructure/`: conexión y sesiones de base de datos SQLite y repositorios de persistencia.
- `planify/templates/` y `planify/static/`: interfaz adaptable, estilos y comportamiento del tema local.

### Posible extracción de un microservicio de notificaciones

La funcionalidad actual de notificaciones es deliberadamente local y de demostración. Para una evolución futura, se puede extraer un servicio a partir de los casos de uso de `NotificationService` y del modelo `Notification`: definir primero un contrato de eventos (por ejemplo, evento creado o recordatorio vencido), publicar esos eventos desde la capa de aplicación mediante una interfaz y conectar un adaptador de mensajería como infraestructura. El nuevo servicio podría encargarse de programar y registrar avisos, mientras Planify conserva las preferencias y la experiencia de usuario. Las integraciones reales de correo o notificaciones push quedan fuera del alcance de esta versión.

## Alcance y seguridad

Esta entrega no incluye autenticación ni envíos reales de correo o push. `PLANIFY_SECRET_KEY` admite una clave de entorno para futuras sesiones; el valor de desarrollo incluido no debe reutilizarse en producción. No se almacenan contraseñas en esta versión.
