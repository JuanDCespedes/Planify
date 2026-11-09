# Trazabilidad de requisitos

Este documento contrasta las historias y requisitos del material del proyecto con el código actual. **Implementado** significa que existe un flujo en la interfaz y una operación del servidor; **parcial** indica diferencias o límites que se deben considerar; **pendiente** significa que el flujo no está disponible.

## Historias de usuario

| ID | Historia resumida | Estado | Evidencia o diferencia |
|---|---|---|---|
| HU01 | Crear eventos con título, categoría, fecha, hora y recordatorio | Implementado | Formulario de eventos, servicio de dominio y persistencia SQLite. |
| HU02 | Cambiar correo electrónico | Implementado | Perfil; solicita contraseña actual cuando hay acceso local. |
| HU03 | Cambiar contraseña | Implementado | Configuración; mínimo 12 caracteres y confirmación. |
| HU04 | Activar tema oscuro | Implementado | Alternador en configuración; preferencia local por navegador. |
| HU05 | Configurar notificaciones de rutina | Implementado | Avisos al inicio, 5 minutos antes y sonido. |
| HU06 | Configurar recordatorios de eventos | Implementado | Seis anticipaciones y selección de opciones activas. |
| HU07 | Cancelar alarmas de eventos o rutinas | Parcial | Se puede descartar un aviso ya creado o eliminar un evento; no hay acción para cancelar un aviso programado individual ni para editar/eliminar bloques de rutina. |
| HU08 | Acceder a funciones mediante menú lateral | Implementado | Navegación compartida de las vistas autenticadas. |
| HU09 | Consultar calendario con actividades y tareas pendientes | Parcial | Hay calendario mensual de eventos. No existe una entidad o lista separada de tareas pendientes. |
| HU10 | Seleccionar un día para consultar sus tareas | Parcial | La cuadrícula presenta eventos por día, pero no tiene selección de día ni panel de detalle. |
| HU11 | Crear rutinas con nombre, inicio y finalización | Parcial | Se captura inicio y duración, no hora final; el bloque se asigna al día actual automáticamente. |
| HU12 | Configurar repetición de rutinas | Parcial | Los bloques repiten semanalmente por `day_of_week`; no se puede elegir día ni frecuencia desde la interfaz. |

## Requisitos funcionales

| Requisito | Estado | Observación |
|---|---|---|
| Crear y editar eventos | Implementado | Incluye título, fecha, hora de inicio, categoría y recordatorio. |
| Visualizar eventos en calendario mensual | Implementado | Vista mensual con navegación entre meses. |
| Mostrar agenda del día y próximos eventos | Implementado | El panel muestra los eventos de hoy y los próximos siete días. |
| Crear categorías solicitadas por el usuario | Implementado | Se pueden crear desde el evento o desde Configuración; son privadas por cuenta. |
| Crear bloques con nombre, inicio y finalización | Parcial | Se solicita duración, de 5 a 480 minutos; no hora de finalización. |
| Repetición configurable, incluida diaria | Parcial | La aplicación guarda el día de la semana actual y repite semanalmente; no tiene selector de frecuencia diaria. |
| Configurar anticipación del evento | Implementado | A la hora, 5, 15 o 30 minutos, 1 hora o 1 día. |
| Generar notificaciones de eventos y rutinas | Implementado | Scheduler cada minuto; respeta preferencias y horas silenciosas. |
| Centro que diferencia eventos y rutinas | Parcial | El tipo queda almacenado y se expone en API, pero la interfaz no etiqueta ni filtra el centro por tipo. |
| Descartar avisos y marcarlos leídos | Implementado | Acciones individuales y marcar todo como leído. |
| Avisar al inicio o antes de una rutina | Implementado | Preferencias para inicio y 5 minutos antes. |
| Configurar horas silenciosas | Implementado | Inicio, fin y activación por cuenta. |
| Métodos de entrega | Implementado con configuración | Dentro de la app, navegador/Web Push, correo por aviso y resumen semanal; correo y push dependen del servidor. |
| Agregar bloques desde el planificador diario | Parcial | El formulario está en la vista de rutina, pero solo añade un bloque al día actual y no ofrece edición o borrado. |

## Requisitos no funcionales

| Requisito | Estado actual | Evidencia o trabajo pendiente |
|---|---|---|
| Interfaz intuitiva | Implementado, sujeto a evaluación | Formularios y navegación en español; requiere pruebas con usuarios para medir usabilidad. |
| Carga rápida | No medido | No hay presupuesto de rendimiento ni prueba de carga documentada. |
| Disponibilidad | No garantizada por el código | Depende del proveedor, despliegue, respaldos y monitoreo. |
| Navegadores modernos | Parcialmente verificado | Usa HTML, CSS y APIs web; falta matriz formal de navegadores. |
| Adaptación a tamaños de pantalla | Implementado en estilos | No hay prueba automatizada de todos los tamaños. |
| Protección contra acceso no autorizado | Implementado | Sesiones, hash, CSRF, límites de acceso por propietario y validación de OAuth. |
| Privacidad de eventos y rutinas | Implementado | Repositorios y servicios filtran por usuario; pruebas cubren aislamiento. |
| Conservación de datos | Implementado con una base por servicio | Docker usa tres volúmenes persistentes; faltan respaldos automáticos y restauración probada. |
| Sincronización de vistas | Implementado mediante APIs síncronas | El gateway consulta al servicio propietario; no hay transacciones distribuidas entre bases. |
| Claridad de controles | Implementado, sujeto a evaluación | Etiquetas y mensajes en español; requiere pruebas con usuarios. |
| Mantenibilidad | Implementado parcialmente | Código Python separado por capas; la ruta HTTP aún coordina varias funciones. |
| Escalabilidad | No validada | Las APIs ya se despliegan por separado, pero SQLite, token compartido, scheduler único y ausencia de cola limitan el crecimiento; no hay prueba de carga. |

## Arquitectura y microservicios

La aplicación está separada en cuatro procesos: `web` gateway, `identity_service`, `planning_service` y `notification_service`. Cada servicio de dominio tiene su propia SQLite y API interna; el gateway no consulta directamente esas bases. El scheduler, el estado de avisos y la entrega pertenecen a notificaciones.

Esta separación cumple con una arquitectura de microservicios inicial, pero mantiene límites concretos: APIs síncronas autenticadas con un token compartido, sin cola durable ni transacciones entre servicios. La eliminación de cuenta es una saga best-effort. Para producción de mayor escala se recomiendan tokens distintos por consumidor, TLS/red privada, outbox/eventos, reintentos observables, migración administrada y métricas por servicio.

## Próximos incrementos sugeridos

1. Agregar selección de día, hora final y reglas explícitas de repetición en rutinas.
2. Añadir acciones de editar y eliminar bloques, y cancelar recordatorios programados individualmente.
3. Mostrar tipo de aviso y filtros de evento/rutina en el centro.
4. Definir recuperación de contraseña con correo verificado.
5. Medir rendimiento y probar la interfaz en navegadores y tamaños acordados.
6. Introducir una cola durable, credenciales internas por consumidor y métricas si el volumen requiere escalar notificaciones.