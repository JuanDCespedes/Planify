# Planify

Planify es una aplicación de planificación personal en español. Cada cuenta tiene sus propios eventos, calendario, bloques de rutina y notificaciones. La interfaz adaptable usa los detalles coral/naranja del prototipo de acceso y configuración; el tema oscuro se guarda en el navegador.

Esta guía cubre instalación, configuración, uso y despliegue. Para conocer las capas, los modelos, los flujos internos y las responsabilidades de los módulos, consulta la [documentación técnica](docs/architecture.md). Los comandos de esta guía se ejecutan desde esta carpeta `app/` del repositorio.

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
- Las categorías son privadas de cada cuenta. Al crear o editar un evento, puedes elegir una categoría existente o escribir un tema nuevo; Planify lo guarda en tus categorías personales y lo reutiliza en tus próximos eventos. También puedes cambiar el color y el nombre desde Ajustes. Los eventos existentes conservan su categoría durante la migración.

La configuración de notificaciones guarda por cuenta los recordatorios habilitados, los avisos de rutina, las horas de silencio y las preferencias de entrega. Un planificador revisa los avisos cada minuto y los guarda en SQLite con claves de deduplicación. Las horas silenciosas retrasan los avisos hasta el fin del intervalo.

Los avisos del navegador requieren permiso y Planify abierto; el sonido de rutina solo puede reproducirse mientras la aplicación está abierta y el navegador lo permite. Las notificaciones push en segundo plano son opcionales y requieren claves VAPID y una suscripción concedida por cada navegador. Si se activa en Ajustes, el correo por evento o rutina se envía al vencer cada recordatorio; los resúmenes semanales son un control separado y se envían los lunes desde las 09:00, hora de Bogotá por defecto (`PLANIFY_TIMEZONE`). Ambos requieren SMTP configurado en el servidor. Sin SMTP configurado no se enviarán correos. Los intentos fallidos se reintentan hasta cinco veces, con 15 minutos entre intentos. No se guardan secretos en SQLite.

Para activar push, genera el par VAPID dentro del entorno virtual:

```powershell
python -c "from planify.infrastructure.notification_delivery import generate_vapid_keys; print(*generate_vapid_keys(), sep='\n')"
```

La primera línea es la clave privada y la segunda la pública. Guárdalas solo en variables de entorno locales, junto con `PLANIFY_VAPID_CLAIMS_EMAIL=mailto:tu-correo@example.com`. Reinicia Planify, activa y guarda la opción push en Ajustes y luego pulsa **Activar en este navegador**. La aplicación requiere HTTPS (excepto `localhost`) para service workers y push.

### Correo con Gmail

El botón de inicio de sesión con Google no habilita el envío de correo: son configuraciones independientes. Para que Planify envíe recordatorios desde una cuenta de Gmail:

1. Activa la verificación en dos pasos en la cuenta de Google que enviará los mensajes.
2. En la configuración de seguridad de esa cuenta, genera una **contraseña de aplicación**. No uses la contraseña normal de Google ni la compartas por chat.
3. Abre `.env` en la raíz del proyecto y agrega estas variables sin borrar las de Google OAuth existentes. Reemplaza el correo y el valor de ejemplo localmente:

   ```dotenv
   PLANIFY_SMTP_HOST=smtp.gmail.com
   PLANIFY_SMTP_PORT=587
   PLANIFY_SMTP_USERNAME=tu-cuenta@gmail.com
   PLANIFY_SMTP_PASSWORD=contraseña-de-aplicación
   PLANIFY_SMTP_FROM=tu-cuenta@gmail.com
   PLANIFY_SMTP_USE_SSL=false
   PLANIFY_SMTP_STARTTLS=true
   ```

   Usa la contraseña de aplicación de 16 caracteres (sin espacios). Mantén `.env` privado y no la envíes por chat.
4. Reinicia Planify. En **Configuración → Métodos de entrega**, activa y guarda **Correo por cada recordatorio de evento o rutina**. El resumen semanal es opcional y se controla por separado.
5. Prueba creando un evento futuro con recordatorio habilitado. El correo se envía al vencer ese recordatorio; las horas de **No molestar** pueden retrasarlo. El correo de prueba no es retroactivo para avisos de más de un día.

Si Gmail rechaza la conexión, confirma que la verificación en dos pasos está activa, que la contraseña de aplicación es correcta y que el equipo puede conectarse a `smtp.gmail.com` por el puerto 587. Planify reintenta los envíos fallidos hasta cinco veces, con 15 minutos entre intentos.

Para otros proveedores, configura `PLANIFY_SMTP_HOST`, `PLANIFY_SMTP_PORT`, `PLANIFY_SMTP_FROM` y, si se requieren, `PLANIFY_SMTP_USERNAME` y `PLANIFY_SMTP_PASSWORD`. Usa `PLANIFY_SMTP_USE_SSL=true` para SSL directo; de lo contrario se usa STARTTLS cuando `PLANIFY_SMTP_STARTTLS=true`. Las variables deben establecerse antes de iniciar Planify y el servicio debe reiniciarse para tomarlas. Nunca publiques credenciales.

El planificador integrado está pensado para una sola instancia del proceso web. En despliegues con varios workers, desactívalo con `PLANIFY_ENABLE_NOTIFICATION_SCHEDULER=false` y ejecuta un único proceso scheduler dedicado para evitar tareas de correo duplicadas. Para extraerlo más adelante, `process_due_notifications` es el punto de entrada independiente de Flask y `NotificationService` puede publicar eventos a un adaptador o cola de microservicio.

## Cuentas y seguridad

- Cada cuenta usa una dirección de correo y una contraseña propia.
- Las contraseñas se guardan únicamente como hashes scrypt, nunca como texto recuperable. El mínimo para crear una cuenta es de 12 caracteres.
- Las sesiones usan cookies `HttpOnly` y `SameSite=Lax`; en producción se fuerzan cookies `Secure`.
- Los formularios POST requieren token CSRF. Las rutas de acceso y registro tienen límites de intentos.
- El registro es abierto: los visitantes pueden crear su propia cuenta. Los datos del planificador se filtran por el identificador de la sesión.
- Google OAuth se integra con OpenID Connect. El botón explica la configuración pendiente y solo permite iniciar el flujo cuando hay credenciales OAuth locales.
- El inicio de sesión con Google exige correo verificado. Si ese correo coincide con una cuenta existente, Planify conecta automáticamente el Google verificado y permite iniciar sesión por ambos métodos.
- Los recordatorios y notificaciones son privados por cuenta; push y SMTP son canales opcionales configurados por el administrador.
- En instalaciones existentes, los datos antiguos sin propietario no se muestran ni se asignan a la primera cuenta que se registre.

### Configurar el acceso con Google

Google requiere un cliente OAuth de tipo **Aplicación web**. Los secretos son tuyos: no los compartas por chat y no los publiques en GitHub.

Para la ejecución local de desarrollo, crea o edita `.env` en la raíz del proyecto y agrega las credenciales del cliente OAuth:

```dotenv
GOOGLE_CLIENT_ID=tu-id-de-cliente
GOOGLE_CLIENT_SECRET=tu-secreto-de-cliente
```

`.env` está excluido de Git. Reinicia Planify después de guardar los cambios; no uses las credenciales de producción en el repositorio ni en `.env.example`.

1. En [Google Cloud Console](https://console.cloud.google.com/), crea o selecciona un proyecto y configura la pantalla de consentimiento OAuth. Para una prueba personal, selecciona el tipo externo y añade tu cuenta como usuario de prueba.
2. En **Clientes**, crea un cliente OAuth de tipo **Aplicación web**. No hacen falta claves API ni otros permisos; Planify solo pide `openid`, `email` y `profile`.
3. Añade estos orígenes autorizados:

   ```text
   http://127.0.0.1:5000
   ```

4. Añade estos URI de redirección autorizados (deben coincidir exactamente):

   ```text
   http://127.0.0.1:5000/auth/google/callback
   ```

   Si accedes mediante un dominio HTTPS, añade también ese origen y el URI de retorno correspondiente, por ejemplo `https://planify.example.com` y `https://planify.example.com/auth/google/callback`. Sustituye el ejemplo por tu dominio real; los valores registrados en Google deben coincidir exactamente con los que usa la aplicación.

5. Copia el **ID de cliente** y el **secreto de cliente** en PowerShell, dentro de la misma terminal desde la que iniciarás Planify:

   ```powershell
   $env:GOOGLE_CLIENT_ID = "tu-id-de-cliente"
   $env:GOOGLE_CLIENT_SECRET = "tu-secreto-de-cliente"
   python app.py
   ```

   Para acceso local directo, deja `GOOGLE_REDIRECT_URI` sin definir. Si Planify está detrás de un proxy HTTPS o túnel, define `GOOGLE_REDIRECT_URI` con la dirección pública exacta registrada en Google Cloud; algunos proxies no comunican el esquema HTTPS al servidor y la detección automática produciría una URL incorrecta.

   Cierra y vuelve a iniciar Planify después de añadir o cambiar variables. Al usar Docker, pon las variables en tu archivo local `.env`, que está excluido de Git; nunca las pegues en `.env.example` ni en el repositorio.

6. Abre el inicio de sesión y elige **Continuar con Google**. Si la pantalla de consentimiento está en modo de prueba, solo podrán ingresar las cuentas añadidas como usuarios de prueba.

Authlib valida el estado OAuth y la firma, audiencia, emisor y nonce del ID token; la aplicación solo crea una cuenta o conecta Google a una cuenta existente si Google confirma el correo. Si el mismo correo ya tiene cuenta, el inicio con Google abre esa cuenta y mantiene disponible el acceso por contraseña. Las cuentas creadas solo con Google pueden crear una contraseña desde Ajustes para habilitar el inicio por correo y contraseña.

## Hosting gratuito en PythonAnywhere

PythonAnywhere tiene un plan gratuito para una app pequeña como esta. Consulta sus [planes actuales](https://www.pythonanywhere.com/pricing/) antes de registrarte: el plan gratuito es limitado (incluye un máximo de 512 MB de espacio y 100 segundos de CPU al día) y restringe las conexiones salientes. Planify no necesita conexiones salientes para sus funciones actuales. El proyecto y SQLite quedan dentro de tu directorio personal; no uses este plan para datos sensibles ni para una app de alto tráfico.

1. Crea una cuenta **Beginner gratuita** en [PythonAnywhere](https://www.pythonanywhere.com/registration/register/beginner/); no compartas tu contraseña.
2. En **Web → Add a new web app**, elige **Manual configuration** y **Python 3.13**.
3. Abre una consola **Bash** e instala la app desde el repositorio público:

   ```bash
   git clone https://github.com/JuanDCespedes/Planify.git
   cd ~/Planify/app
   python3.13 -m venv ~/.virtualenvs/planify
   ~/.virtualenvs/planify/bin/pip install -r requirements.txt
   python3.13 -c "import secrets; from pathlib import Path; Path.home().joinpath('.planify_secret').write_text(secrets.token_urlsafe(48), encoding='utf-8')"
   chmod 600 ~/.planify_secret
   ```

   El archivo con la clave secreta se crea fuera del repositorio y solo debe ser accesible para tu cuenta.

4. En la pestaña **Web**, configura la virtualenv como `~/.virtualenvs/planify`. Abre el enlace **WSGI configuration file**, reemplaza su contenido por el de [`pythonanywhere_wsgi.py`](./pythonanywhere_wsgi.py) y guarda.
5. Pulsa **Reload** y abre la URL de tu cuenta (`tu-usuario.pythonanywhere.com`). Regístrate para crear tu espacio personal.

El WSGI configura las cookies seguras y crea SQLite en `~/Planify/app/instance/planify.db`, dentro del almacenamiento de tu cuenta. Las cuentas de esta aplicación son independientes; cualquiera puede registrarse y solo verá sus propios datos. La recuperación por correo sigue desactivada.

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
