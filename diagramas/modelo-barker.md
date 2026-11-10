# Modelo de datos (notación Barker)

El diagrama es una vista lógica de las entidades del sistema. Las relaciones de `user_id` entre identidad y otros servicios se aplican mediante APIs; no son claves foráneas entre bases distintas.

```mermaid
erDiagram
    IDENTITY_USER ||--o{ PLANNING_CATEGORY : "user_id por API"
    IDENTITY_USER ||--o{ PLANNING_EVENT : "user_id por API"
    IDENTITY_USER ||--o{ PLANNING_ROUTINE : "user_id por API"
    IDENTITY_USER ||--o{ NOTIFICATION : "user_id por API"
    IDENTITY_USER ||--o{ PUSH_SUBSCRIPTION : "user_id por API"
    PLANNING_CATEGORY ||--o{ PLANNING_EVENT : clasifica

    IDENTITY_USER {
        int id PK
        string email UK
        string password_hash
        string google_subject UK
        string display_name
        string preferencias_recordatorio
        string horas_silenciosas
    }
    PLANNING_CATEGORY {
        int id PK
        int user_id
        string name
        string color
    }
    PLANNING_EVENT {
        int id PK
        int user_id
        int category_id FK
        string title
        date event_date
        time start_time
        string reminder
    }
    PLANNING_ROUTINE {
        int id PK
        int user_id
        string title
        time start_time
        int duration_minutes
        int day_of_week
    }
    NOTIFICATION {
        int id PK
        int user_id
        string title
        string message
        string notification_type
        string dedupe_key UK
        datetime created_at
        boolean is_read
        datetime email_sent_at
    }
    PUSH_SUBSCRIPTION {
        int id PK
        int user_id
        string endpoint UK
        string p256dh
        string auth
    }
```

## Propiedad por servicio

| Base | Entidades |
|---|---|
| `identity.db` | `IDENTITY_USER` y preferencias de cuenta. |
| `planning.db` | `PLANNING_CATEGORY`, `PLANNING_EVENT` y `PLANNING_ROUTINE`. |
| `notifications.db` | `NOTIFICATION` y `PUSH_SUBSCRIPTION`. |

`PLANNING_EVENT.category_id` es una relación real dentro de `planning.db`. El resto de las relaciones con `user_id` son referencias lógicas al identificador emitido por identidad. Las claves y atributos de este modelo se resumen para presentación; los modelos ORM de cada microservicio son la definición ejecutable.
