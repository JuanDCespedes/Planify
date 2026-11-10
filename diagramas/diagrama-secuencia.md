# Diagrama de secuencia

El flujo muestra el alta de un evento y la generación posterior del recordatorio. El scheduler no comparte base con planificación: consulta sus APIs periódicamente.

```mermaid
sequenceDiagram
    actor U as Usuario
    participant UI as Navegador
    participant W as Gateway web
    participant I as Identidad
    participant P as Planificación
    participant N as Notificaciones
    participant DBP as planning.db
    participant DBN as notifications.db
    participant Push as Servicio Web Push

    U->>UI: Completa evento y recordatorio
    UI->>W: POST /events/new
    W->>I: GET /api/v1/users/{id}
    I-->>W: Cuenta y preferencias
    W->>P: POST /api/v1/users/{id}/events + token
    P->>P: Validar datos y categoría
    alt Datos inválidos
        P-->>W: 400 + errores
        W-->>UI: Mostrar errores del formulario
    else Datos válidos
        P->>DBP: Guardar evento
        DBP-->>P: Confirmación
        P-->>W: 201 + evento JSON
        W-->>UI: Redirigir al panel
    end

    loop Cada minuto
        N->>I: GET usuarios y preferencias
        I-->>N: DTO de usuarios
        N->>P: GET eventos y rutinas del intervalo
        P-->>N: DTO de agenda
        N->>N: Calcular vencimiento y deduplicación
        N->>DBN: Guardar notificación
        DBN-->>N: Confirmación
        opt Push configurado
            N->>Push: Enviar aviso VAPID
            Push-->>UI: Mostrar notificación
        end
    end

    UI->>W: GET /notifications
    W->>N: GET notificaciones del usuario
    N->>DBN: Consultar avisos
    N-->>W: Lista de notificaciones
    W-->>UI: Renderizar centro de notificaciones
```

La creación del evento y el guardado del aviso son transacciones independientes en sus respectivas bases.
