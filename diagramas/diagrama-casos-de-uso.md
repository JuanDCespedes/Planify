# Diagrama de casos de uso

El límite del sistema representa Planify como producto. El usuario interactúa con el gateway; los servicios internos colaboran para completar las operaciones.

```mermaid
flowchart LR
    visitor[Visitante]
    user[Usuario autenticado]
    google[Google OAuth]
    services[Servicios internos]

    subgraph planify[Planify]
        register((Crear cuenta))
        login((Iniciar sesión))
        dashboard((Consultar panel))
        calendar((Consultar calendario))
        events((Crear, editar y eliminar eventos))
        categories((Gestionar categorías))
        routines((Consultar y crear rutinas))
        reminders((Configurar recordatorios))
        notifications((Consultar notificaciones))
        read((Marcar como leída))
        dismiss((Descartar notificación))
        profile((Gestionar perfil y contraseña))
        preferences((Configurar preferencias y horas silenciosas))
        theme((Cambiar tema))
    end

    visitor --> register
    visitor --> login
    login -. acceso opcional .-> google
    user --> dashboard
    user --> calendar
    user --> events
    user --> categories
    user --> routines
    user --> reminders
    user --> notifications
    user --> profile
    user --> preferences
    user --> theme
    notifications --> read
    notifications --> dismiss
    services --> reminders
    services --> notifications
```

La cobertura implementada de cada caso se detalla en [`../app/docs/trazabilidad.md`](../app/docs/trazabilidad.md); algunos requisitos de rutina y cancelación de alarmas todavía son parciales.
