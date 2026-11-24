# Comparación: Docker y microservicios

Planify permite mostrar dos despliegues del mismo producto sin reemplazar su versión actual. La opción de un contenedor ejecuta la aplicación monolítica; la opción existente de Docker Compose ejecuta el gateway y tres microservicios.

## Idea principal

**Docker es una tecnología de empaquetado y ejecución de procesos; microservicios son una decisión de arquitectura.** Es posible ejecutar una aplicación monolítica en un contenedor y ejecutar varios microservicios con Docker Compose. Tener varios contenedores no convierte automáticamente una aplicación en microservicios: cada servicio debe tener una responsabilidad y datos propios.

## Variantes disponibles

| Aspecto | Monolito en Docker | Microservicios en Docker Compose |
|---|---|---|
| Cómo iniciarlo | `docker compose -f docker-compose.monolith.yml up --build -d` | `docker compose up --build -d` |
| Contenedores de la aplicación | Uno | Cuatro: gateway web, identidad, planificación y notificaciones |
| Límites de módulos | Capas y servicios dentro de la misma aplicación Flask | APIs HTTP internas entre procesos independientes |
| Persistencia | Una base SQLite en `planify-monolith-data` | Tres bases SQLite en volúmenes separados |
| Comunicación | Llamadas de funciones dentro del proceso | Solicitudes HTTP autenticadas por un token interno |
| Complejidad operativa | Menos configuración; un despliegue | Más configuración, coordinación de servicios y migración de datos |
| Escalado | Se escala la aplicación completa | Se puede escalar cada servicio por separado, con restricciones del scheduler actual |
| Ideal para | Presentar capas, lógica y despliegue sencillo | Mostrar límites de dominio, contratos y comunicación entre servicios |

Ambas opciones construyen la imagen con el mismo `Dockerfile`. Compose selecciona el modo con la configuración: `docker-compose.monolith.yml` fuerza `PLANIFY_MICROSERVICES_ENABLED=false`; `docker-compose.yml` inicia el gateway con los servicios de identidad, planificación y notificaciones. Se debe ejecutar un modo a la vez para evitar confusiones entre sus bases de datos.

## Qué mostrar en una comparación

1. Presenta Docker como el paquete reproducible que incluye Python, dependencias y comando de inicio.
2. Inicia el monolito y muestra que sus capas de presentación, aplicación, dominio e infraestructura viven en un único proceso.
3. Detén el modo monolítico y ejecuta el Compose distribuido.
4. Muestra los cuatro contenedores, los puertos de las APIs internas y los tres volúmenes de datos independientes.
5. Compara la facilidad del monolito con la separación y el costo operativo adicional de los microservicios.

## Alcance y datos

El monolito Docker usa un volumen nuevo llamado `planify-monolith-data`; no importa automáticamente el `instance/planify.db` del proyecto ni los volúmenes de microservicios. Si vas a comparar datos persistentes, crea una cuenta de demostración en cada modo. El modo distribuido puede migrar la base heredada con el perfil `migration`, según las instrucciones del README.

Los dos comandos `docker compose down` detienen sus servicios pero mantienen los volúmenes. No añadas `-v` a esos comandos salvo que quieras eliminar de forma permanente los datos de demostración.
