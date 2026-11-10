# Diagrama de flujo principal

```mermaid
flowchart TD
    start([Inicio]) --> auth{¿Hay sesión válida?}
    auth -- No --> login[Iniciar sesión o crear cuenta]
    login --> identity[Validar credenciales con identidad]
    identity --> valid{¿Credenciales válidas?}
    valid -- No --> login
    valid -- Sí --> dashboard
    auth -- Sí --> dashboard[Mostrar panel y eventos próximos]

    dashboard --> action{Seleccionar acción}
    action -->|Eventos| event[Crear o editar evento]
    event --> validate{¿Datos válidos?}
    validate -- No --> event
    validate -- Sí --> planning[Guardar en servicio de planificación]
    planning --> refresh[Actualizar vista del gateway]

    action -->|Rutina| routine[Consultar o crear bloque]
    routine --> saveRoutine[Guardar en servicio de planificación]
    saveRoutine --> refresh

    action -->|Notificaciones| center[Consultar centro de notificaciones]
    center --> notificationAction{Seleccionar aviso}
    notificationAction -->|Marcar leído| markRead[Actualizar servicio de notificaciones]
    notificationAction -->|Descartar| dismiss[Eliminar aviso propio]
    markRead --> refresh
    dismiss --> refresh

    action -->|Ajustes| settings[Actualizar perfil o preferencias]
    settings --> identityUpdate[Guardar preferencias en identidad]
    settings --> planningUpdate[Guardar categorías en planificación]
    identityUpdate --> refresh
    planningUpdate --> refresh

    planning --> scheduler[Scheduler de notificaciones consulta APIs]
    scheduler --> due{¿Aviso vencido y habilitado?}
    due -- No --> scheduler
    due -- Sí --> persist[Deduplicar y guardar en notifications.db]
    persist --> deliver[Enviar por canales habilitados]
    deliver --> refresh

    refresh --> continue{¿Seguir usando Planify?}
    continue -- Sí --> dashboard
    continue -- No --> end([Cerrar sesión o salir])
```

Los avisos respetan las preferencias y horas silenciosas. La entrega por correo y Web Push depende de la configuración del servicio de notificaciones.
