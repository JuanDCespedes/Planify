# Arquitectura técnica

Este documento describe cómo está organizada la aplicación y cómo fluyen las operaciones principales. La guía de instalación, configuración de proveedores externos, uso y despliegue está en [`README.md`](../README.md).

## Alcance y tecnologías

Planify es una aplicación web Flask con plantillas Jinja, JavaScript/CSS del lado del cliente y persistencia SQLAlchemy. SQLite es la base de datos local predeterminada. Las funciones principales no requieren servicios externos; Google OAuth, Web Push y correo SMTP son opcionales.

## Estructura del repositorio

El repositorio contiene la aplicación dentro de `app/`:

```text
app/
├── app.py                         # Entrada para desarrollo local (Flask)
├── serve.py                       # Entrada WSGI con Waitress
├── config.py                      # Configuración de despliegue alternativa
├── pythonanywhere_wsgi.py         # Adaptador WSGI de PythonAnywhere
├── requirements.txt
├── tests/test_app.py              # Pruebas de integración
└── planify/
    ├── __init__.py                # Fábrica de la aplicación y extensiones
    ├── config.py                  # Configuración desde variables de entorno
    ├── extensions.py              # Extensiones compartidas
    ├── domain/
    │   ├── models.py              # Entidades y tablas ORM
    │   └── rules.py               # Validaciones y opciones del dominio
    ├── application/
    │   ├── auth_service.py        # Registro, autenticación y cuentas Google
    │   └── services.py            # Casos de uso de agenda, categorías y avisos
    ├── infrastructure/
    │   ├── database.py            # Motor y sesiones SQLAlchemy
    │   ├── migrations.py          # Migración de propiedad de datos antiguos
    │   ├── repositories.py        # Consultas de persistencia
    │   ├── security.py            # Manejo de errores HTTP y seguridad
    │   ├── notification_delivery.py
    │   └── notification_scheduler.py
    ├── presentation/
    │   └── routes.py              # Rutas Flask y coordinación HTTP
    ├── templates/                 # Vistas Jinja y formularios
    └── static/                    # CSS, JavaScript y service worker
```

## Capas y responsabilidades

### Presentación

`planify/presentation/routes.py` registra el blueprint `main`, recibe solicitudes HTTP, aplica los controles de sesión y enlaza formularios y respuestas con los servicios de aplicación. Las plantillas están en `planify/templates/`. El comportamiento del navegador y los estilos viven en `planify/static/js/` y `planify/static/css/`; `service-worker.js` habilita las notificaciones push del navegador.

Las rutas de acceso, registro y autenticación Google son públicas. Las demás rutas del blueprint requieren una sesión autenticada. Las operaciones que cambian datos usan POST y los formularios están protegidos por CSRF.

### Mapa de rutas

| Ruta | Acceso | Función |
|---|---|---|
| `GET/POST /login`, `GET/POST /register` | Público | Acceso y creación de cuenta. |
| `GET /forgot-password` | Público | Pantalla informativa de recuperación; no envía correo de restablecimiento. |
| `GET /auth/google`, `GET /auth/google/callback` | Público | Inicio de sesión o vinculación con Google cuando OAuth está configurado. |
| `POST /logout` | Sesión | Cierre de sesión. |
| `GET /`, `GET /calendar` | Sesión | Panel y calendario. |
| `GET/POST /events/new`, `GET/POST /events/<id>/edit`, `POST /events/<id>/delete` | Sesión | Crear, editar y borrar eventos propios. |
| `GET/POST /routine` | Sesión | Consultar y añadir bloques de rutina. |
| `GET /notifications`, `GET /api/notifications` | Sesión | Ver avisos y consultar avisos recientes desde el navegador. |
| `GET /api/notifications/push-key`, `POST/DELETE /api/notifications/push-subscription` | Sesión | Consultar la clave pública y gestionar la suscripción Web Push del usuario. |
| `GET /service-worker.js` | Sesión | Servir el service worker de notificaciones. |
| `POST /notifications/<id>/read`, `POST /notifications/read-all`, `POST /notifications/<id>/dismiss` | Sesión | Marcar o descartar avisos propios. |
| `GET /settings` | Sesión | Consultar ajustes. |
| `POST /settings/profile`, `/settings/password`, `/settings/preferences`, `/settings/default-reminder` | Sesión | Actualizar perfil, contraseña y preferencias. |
| `POST /settings/categories`, `/settings/categories/<id>`, `/settings/categories/<id>/delete` | Sesión | Administrar categorías propias. |
| `POST /settings/account/delete` | Sesión | Eliminar la cuenta autenticada. |

### Aplicación

`planify/application/auth_service.py` centraliza normalización de correo, validación de registro, autenticación local y vinculación/creación de cuentas Google.

`planify/application/services.py` implementa los casos de uso de eventos, categorías, rutinas y notificaciones. Los servicios reciben una sesión SQLAlchemy y, cuando los datos pertenecen a una cuenta, su `user_id`. También coordina la creación de categorías personales y los datos de ejemplo para una cuenta nueva.

### Dominio

`planify/domain/models.py` define las entidades ORM y sus tablas. `planify/domain/rules.py` contiene las categorías iniciales, tipos de recordatorio y validaciones reutilizadas por los servicios.

### Infraestructura

- `database.py` crea el motor, inicializa el esquema, abre una sesión por contexto de Flask y la cierra al finalizar la solicitud.
- `migrations.py` adapta las tablas SQLite existentes a la separación por propietario; los registros históricos sin propietario no se adjudican a una cuenta nueva.
- `repositories.py` encapsula las consultas. Las consultas de eventos, categorías y avisos personales incluyen el identificador de propietario.
- `notification_delivery.py` encapsula los transportes SMTP y Web Push.
- `notification_scheduler.py` busca avisos vencidos, los persiste y coordina las entregas.
- `security.py` registra manejadores para errores de seguridad y solicitudes.

## Inicio de la aplicación

`app.py` crea la aplicación y usa el servidor integrado de Flask en `127.0.0.1:5000`, apropiado para desarrollo local. `serve.py` sirve la misma fábrica con Waitress, escucha en `0.0.0.0` y usa el puerto indicado por `PORT` (8000 por defecto); Docker usa esta entrada.

`planify.create_app()` configura Flask, CSRF, Flask-Login, Flask-Limiter y OAuth; registra el blueprint, prepara la base y las migraciones, y registra los manejadores de seguridad. Si `PLANIFY_ENABLE_NOTIFICATION_SCHEDULER` está activado, inicia el planificador en segundo plano, excepto en pruebas y en el padre del recargador de depuración.

La configuración se lee en `planify/config.py`. `python-dotenv` carga `app/.env` si existe y no reemplaza variables ya definidas en el proceso. En ausencia de `PLANIFY_DATABASE_URL`, la base local se crea en `app/instance/planify.db`.

## Modelo de datos

| Entidad | Tabla | Responsabilidad |
|---|---|---|
| `User` | `users` | Cuenta, hash de contraseña, vínculo opcional con Google y preferencias personales. |
| `Event` | `events` | Evento con fecha, hora, categoría, propietario y recordatorio. |
| `Category` | `categories` | Categoría y color personalizados por cuenta; el nombre es único por propietario. |
| `RoutineBlock` | `routine_blocks` | Bloque semanal con día, hora y duración. |
| `Notification` | `notifications` | Aviso persistido, estado de lectura, deduplicación y estado de entrega de correo. |
| `PushSubscription` | `push_subscriptions` | Suscripción Web Push vinculada a una cuenta y a un navegador. |

El límite de privacidad se aplica en los repositorios y servicios: se busca o modifica cada registro personal utilizando también el identificador del usuario autenticado. La interfaz nunca debe tratar un identificador de evento, categoría o notificación como prueba de propiedad.

## Flujos principales

### Registro y acceso

1. La ruta recibe el formulario y delega en `AuthenticationService`.
2. El servicio normaliza el correo y valida su formato, unicidad y la contraseña (12 a 128 caracteres).
3. La contraseña se guarda como hash con las utilidades de seguridad de Werkzeug.
4. Se crean las categorías iniciales y, si aún no hay eventos, datos de ejemplo privados para esa cuenta.
5. Flask-Login mantiene la sesión y el usuario autenticado se usa como propietario en las operaciones siguientes.

Con Google, Authlib realiza el flujo OpenID Connect. Solo se acepta un perfil que incluya correo verificado, correo y subject; la cuenta se busca o vincula por correo normalizado y el identificador estable de Google.

### Eventos, categorías y rutinas

Las rutas validan y convierten los datos del formulario y llaman al servicio correspondiente. Las reglas del dominio validan campos; los repositorios consultan exclusivamente los datos del usuario. Al guardar un evento se comprueba que la categoría también pertenezca a la cuenta. Las categorías en uso no se pueden eliminar y cada cuenta debe conservar al menos una.

### Recordatorios y entregas

El planificador APScheduler se ejecuta cada minuto. Calcula recordatorios de eventos y bloques de rutina, respeta las preferencias y las horas silenciosas de cada usuario, y persiste avisos con una clave de deduplicación para evitar crearlos repetidamente. El intervalo de tolerancia evita perder un aviso si una ejecución ocurre unos segundos después de su hora prevista.

El aviso se puede entregar en la aplicación, por push o por correo según las preferencias y configuración disponibles. El correo de avisos de evento/rutina se reintenta como máximo cinco veces, con al menos 15 minutos entre intentos. El resumen semanal, si está habilitado y SMTP está configurado, se prepara los lunes a partir de las 09:00 en `PLANIFY_TIMEZONE` y se envía una sola vez por semana. Los proveedores externos pueden fallar; esos fallos se registran en el log y no se guardan credenciales en SQLite.

El planificador integrado está pensado para un solo proceso web. En una instalación con varios workers, hay que deshabilitarlo en los workers y ejecutar un único scheduler, para evitar que varios procesos intenten entregar lo mismo.

## Configuración

Las variables opcionales se definen en el entorno del proceso o en `app/.env`. No se deben guardar credenciales reales en Git.

| Variable | Propósito | Valor predeterminado |
|---|---|---|
| `PLANIFY_ENV` | Entorno; `production` activa requisitos y cookies seguras. | `development` |
| `PLANIFY_SECRET_KEY` | Firma de sesiones Flask. En producción debe ser aleatoria y tener al menos 32 caracteres. | Clave de desarrollo insegura; no usar en producción. |
| `PLANIFY_DATABASE_URL` | URL de SQLAlchemy. | SQLite en `instance/planify.db`. |
| `PLANIFY_TIMEZONE` | Zona horaria de recordatorios y resúmenes. | `America/Bogota` |
| `PLANIFY_DEBUG` | Depuración de Flask. | Desactivada |
| `PLANIFY_RATE_LIMIT_STORAGE_URI` | Almacén para límites de solicitudes de Flask-Limiter. | `memory://` |
| `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` | Credenciales opcionales para inicio de sesión Google. | Vacías |
| `GOOGLE_REDIRECT_URI` | URI de retorno OAuth explícita, útil detrás de un proxy. | Derivada de la solicitud |
| `PLANIFY_VAPID_PUBLIC_KEY`, `PLANIFY_VAPID_PRIVATE_KEY`, `PLANIFY_VAPID_CLAIMS_EMAIL` | Firma y contacto para Web Push. Las tres son necesarias para habilitarlo. | Vacías |
| `PLANIFY_SMTP_HOST`, `PLANIFY_SMTP_PORT`, `PLANIFY_SMTP_FROM` | Servidor y remitente para correo. | Host/remitente vacíos; puerto `587` |
| `PLANIFY_SMTP_USERNAME`, `PLANIFY_SMTP_PASSWORD` | Autenticación SMTP, cuando el proveedor la requiere. | Vacías |
| `PLANIFY_SMTP_USE_SSL`, `PLANIFY_SMTP_STARTTLS` | Modo de seguridad SMTP. | `false` y `true` |
| `PLANIFY_ENABLE_NOTIFICATION_SCHEDULER` | Activa el scheduler integrado. | `true` |
| `PORT` | Puerto de `serve.py`. | `8000` |

Para obtener ejemplos de configuración completos, sigue las secciones de Google OAuth, correo, Docker y PythonAnywhere de la [guía principal](../README.md).

## Seguridad y privacidad

- Las contraseñas se almacenan como hashes; la aplicación no puede recuperarlas en texto claro.
- CSRF está habilitado para formularios y Flask-Limiter protege, entre otras, las rutas de acceso.
- Las cookies de sesión usan `HttpOnly` y `SameSite=Lax`; en producción también `Secure`.
- En producción, el inicio falla si `PLANIFY_SECRET_KEY` falta, es la clave de desarrollo o tiene menos de 32 caracteres. La aplicación habilita `ProxyFix` para despliegues detrás de proxy.
- Google OAuth exige correo verificado. El destino del parámetro `next` se limita a rutas locales.
- La base puede contener información personal: usa almacenamiento persistente y restringe su acceso en despliegues.
- Las funciones opcionales externas requieren HTTPS para los service workers y Web Push, salvo en `localhost`.

## Pruebas y mantenimiento

Ejecuta la suite desde `app/` con:

```powershell
python -m unittest discover -s tests -v
```

Las pruebas usan configuraciones y bases de datos de prueba; no uses una base de producción para ejecutarlas. Para añadir funcionalidad, conserva la separación entre rutas, servicios, reglas de dominio y persistencia; añade pruebas para validación, autorización por propietario y los casos de uso afectados.

## Documentación dentro del código

Los módulos Python incluyen docstrings en español para explicar su responsabilidad. Las clases y funciones documentan su propósito y, cuando es relevante, sus límites de propiedad, efectos de persistencia o resultados de validación. La suite `tests/test_app.py` describe en cada prueba el comportamiento que verifica. Se evitan comentarios redundantes dentro de instrucciones evidentes; los comentarios deben reservarse para decisiones o restricciones que no se entiendan directamente del código.
