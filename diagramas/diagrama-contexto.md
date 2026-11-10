# Diagrama de contexto

Muestra al usuario y los sistemas externos que interactúan con Planify. Los servicios internos se comunican mediante REST autenticado y cada dominio conserva su propia base.

```mermaid
flowchart LR
    U[Usuario] <-->|HTTPS| W[Gateway web Planify]
    W <-->|REST + token| I[Servicio de identidad]
    W <-->|REST + token| P[Servicio de planificación]
    W <-->|REST + token| N[Servicio de notificaciones]
    N <-->|REST + token| I
    N <-->|REST + token| P
    I <--> IDB[(identity.db)]
    P <--> PDB[(planning.db)]
    N <--> NDB[(notifications.db)]
    W <-->|OpenID Connect opcional| G[Google]
    N -->|SMTP opcional| M[Proveedor de correo]
    N -->|Web Push opcional| S[Servicio push]
    S -->|Notificación push| U
```

El gateway no consulta las bases directamente. El identificador de usuario se pasa en los DTO y se valida como propietario en cada servicio.
