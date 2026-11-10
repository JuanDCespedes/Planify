# Requisitos de Planify

## Historias de usuario

| ID | Historia |
|---|---|
| HU01 | Como usuario, quiero crear eventos con título, categoría, fecha, hora y recordatorio para organizar mis actividades. |
| HU02 | Como usuario, quiero cambiar mi correo electrónico para mantener actualizadas mis credenciales. |
| HU03 | Como usuario, quiero cambiar mi contraseña para mantener seguras mis credenciales. |
| HU04 | Como usuario, quiero activar el tema oscuro para usar una apariencia más cómoda. |
| HU05 | Como usuario, quiero configurar las notificaciones de mi rutina según mis preferencias. |
| HU06 | Como usuario, quiero configurar la anticipación de las notificaciones de mis eventos. |
| HU07 | Como usuario, quiero cancelar alarmas de eventos o rutinas para evitar notificaciones no deseadas. |
| HU08 | Como usuario, quiero usar un menú lateral para acceder rápidamente a las funciones principales. |
| HU09 | Como usuario, quiero consultar un calendario con mis actividades para planificarme. |
| HU10 | Como usuario, quiero seleccionar un día del calendario para consultar sus tareas y actividades. |
| HU11 | Como usuario, quiero crear rutinas indicando actividad, hora de inicio y hora de finalización. |
| HU12 | Como usuario, quiero configurar la repetición de una actividad de rutina. |

## Requisitos funcionales

1. Crear eventos con título, fecha, hora de inicio, categoría y recordatorio.
2. Editar eventos existentes.
3. Mostrar los eventos en un calendario mensual.
4. Mostrar en el panel las actividades programadas para el día actual.
5. Mostrar los próximos eventos.
6. Permitir categorías definidas por el usuario.
7. Crear bloques de rutina indicando actividad, hora de inicio y hora de finalización.
8. Configurar la repetición de los bloques de rutina, incluida la repetición diaria.
9. Configurar recordatorios de eventos.
10. Ofrecer estas anticipaciones: al momento, 5, 15 o 30 minutos, 1 hora o 1 día antes.
11. Generar notificaciones relacionadas con eventos y rutinas.
12. Ofrecer un centro de notificaciones que permita diferenciar eventos de rutinas.
13. Descartar notificaciones.
14. Marcar notificaciones como leídas.
15. Configurar avisos al inicio o antes de un bloque de rutina.
16. Configurar horas silenciosas mediante hora de inicio y de finalización.
17. Permitir métodos de entrega: push, correo de resumen semanal y notificaciones dentro de la aplicación.
18. Agregar bloques de rutina desde el planificador diario.

## Requisitos no funcionales

1. La interfaz debe permitir crear eventos y rutinas sin conocimientos técnicos.
2. Las secciones deben cargar con rapidez y sin esperas innecesarias.
3. El sistema debe estar disponible cuando el usuario necesite consultar su agenda.
4. La aplicación debe funcionar en navegadores web modernos.
5. La interfaz debe adaptarse a diferentes tamaños de pantalla.
6. La información debe protegerse contra el acceso de usuarios no autorizados.
7. Los eventos, las rutinas y los datos de cuenta deben ser privados para su propietario.
8. Los datos deben conservarse durante el uso normal del sistema.
9. La información del panel, calendario, rutinas y notificaciones debe mantenerse sincronizada.
10. Los textos y controles deben permitir una interacción clara y comprensible.
11. La estructura debe permitir cambios y funcionalidades nuevas sin afectar innecesariamente lo existente.
12. El sistema debe soportar el crecimiento de usuarios y datos sin una degradación significativa.

## Diagramas requeridos

- Diagrama de contexto.
- Diagramas de secuencia.
- Diagrama de casos de uso.
- Diagrama de flujo.
- Diagrama de base de datos en notación Barker.

La arquitectura vigente y los diagramas técnicos del despliegue distribuido están en [`app/docs/arquitectura.md`](../app/docs/arquitectura.md). El estado de implementación y las brechas frente a estos requisitos están en [`app/docs/trazabilidad.md`](../app/docs/trazabilidad.md).
