# Planify

Planify es una aplicación de planificación personal en español. Cada cuenta tiene sus propios eventos, calendario, bloques de rutina y notificaciones. La interfaz incluye un dashboard adaptable, tema oscuro guardado en el navegador y un acceso diseñado a partir de la referencia de inicio de sesión.

## Ejecutar en Windows

### Requisitos

- Windows 10/11
- Python 3.10 o posterior
- Visual Studio Code y la extensión oficial de Python (recomendados)

### Instalación

1. Abre `planify.code-workspace` en VS Code o abre esta carpeta.
2. En la terminal integrada de PowerShell, crea y activa el entorno virtual:

   ```powershell
   py -m venv .venv
   .\.venv\Scripts\Activate.ps1
   ```

   Si PowerShell bloquea la activación, ejecuta `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass` en esa misma terminal y vuelve a activar el entorno.

3. Instala las dependencias:

   ```powershell
   python -m pip install -r requirements.txt
   ```

4. Inicia Planify:

   ```powershell
   python app.py
   ```

5. Visita [http://127.0.0.1:5000](http://127.0.0.1:5000), crea tu cuenta y entra al planificador.

La base SQLite se crea en `instance/planify.db`. Al registrarse, cada cuenta recibe sus propios datos de ejemplo; los cambios de otras cuentas no aparecen en su espacio.

## Pruebas

Con el entorno virtual activo:

```powershell
python -m unittest discover -s tests -v
```

## Arquitectura

- `planify/presentation/`: rutas Flask, acceso, registro, sesiones y plantillas Jinja.
- `planify/application/`: casos de uso y servicios de autenticación, agenda, rutina y notificaciones.
- `planify/domain/`: entidades, validaciones y almacenamiento de contraseñas con hash scrypt de Werkzeug.
- `planify/infrastructure/`: base SQLite, migración de datos existentes, repositorios y protección CSRF.
- `planify/templates/` y `planify/static/`: interfaz adaptable en español, estilos y tema local.

Las notificaciones siguen siendo locales y de demostración. A futuro, `NotificationService` puede publicar eventos a un adaptador para extraer el envío y la programación a un microservicio. No se implementan correo ni notificaciones push reales.

## Cuentas y seguridad

- Cada cuenta usa una dirección de correo y una contraseña propia.
- Las contraseñas se guardan únicamente como hashes scrypt, nunca como texto recuperable. El mínimo para crear una cuenta es de 12 caracteres.
- Las sesiones usan cookies `HttpOnly` y `SameSite=Lax`; en producción se fuerzan cookies `Secure`.
- Los formularios POST requieren token CSRF. Las rutas de acceso y registro tienen límites de intentos.
- El registro es abierto: los visitantes pueden crear su propia cuenta. Los datos del planificador se filtran por el identificador de la sesión.
- Google/GitHub OAuth y la recuperación por correo no están configurados; no se ofrecen como botones que aparenten funcionar. La pantalla de recuperación explica la limitación.
- En instalaciones existentes, los datos antiguos sin propietario no se muestran ni se asignan a la primera cuenta que se registre.

## Despliegue con Docker

La SQLite de producción debe permanecer en un volumen persistente. La configuración `docker-compose.yml` incluida monta el volumen `planify-data` en `/data`.

1. Copia el archivo de variables y crea una clave secreta aleatoria:

   ```powershell
   py -3 -c "import secrets; from pathlib import Path; Path('.env').write_text('PLANIFY_ENV=production\nPLANIFY_SECRET_KEY='+secrets.token_urlsafe(48)+'\nPLANIFY_DATABASE_URL=sqlite:////data/planify.db\nPLANIFY_RATE_LIMIT_STORAGE_URI=memory://\n', encoding='utf-8')"
   ```

2. Construye e inicia el servicio:

   ```powershell
   docker compose up --build -d
   ```

3. Abre [http://localhost:8000](http://localhost:8000). Para parar la aplicación, ejecuta `docker compose down`; el volumen persiste incluso después de parar el contenedor.

No publiques `.env` ni reutilices la clave de ejemplo. Para alojar Planify en un proveedor externo, configura el equivalente a `PLANIFY_ENV=production`, define una clave secreta larga, y monta almacenamiento persistente en `/data`. Un disco temporal puede borrar SQLite cuando el proveedor reinicia o vuelve a desplegar la aplicación. Los límites de intentos predeterminados se guardan en memoria; para varias instancias, configura `PLANIFY_RATE_LIMIT_STORAGE_URI` con un almacén compartido compatible.
