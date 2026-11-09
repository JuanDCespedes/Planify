# Manual de usuario

Planify es una aplicación web para organizar eventos, rutinas semanales y recordatorios personales. Cada cuenta tiene sus propios datos. Esta guía describe las funciones disponibles en la versión actual.

## Acceder y crear una cuenta

1. Abre Planify en el navegador.
2. Selecciona **Crear cuenta** y registra un correo válido y una contraseña de 12 a 128 caracteres.
3. La aplicación inicia sesión al completar el registro y crea categorías iniciales para tu cuenta.
4. En visitas posteriores, inicia sesión con el mismo correo y contraseña. El acceso con Google aparece cuando el administrador configuró OAuth.
5. Usa **Cerrar sesión** para terminar la sesión en ese navegador.

La pantalla de recuperación de contraseña es informativa: el envío de enlaces de restablecimiento todavía no está implementado.

## Navegación

- **Panel** muestra los eventos de hoy y los eventos de los próximos siete días. Desde aquí se puede crear, editar o eliminar un evento.
- **Calendario** muestra eventos en una vista mensual. Los controles permiten cambiar de mes; cada evento visible enlaza a su edición.
- **Mi rutina** muestra los bloques correspondientes al día actual y permite añadir un bloque para ese día de la semana.
- **Notificaciones** permite consultar avisos, marcarlos como leídos y descartarlos.
- **Configuración** contiene las preferencias de recordatorios, entrega, perfil, contraseña y categorías.

El menú lateral permite cambiar entre estas secciones. El diseño se adapta a pantallas pequeñas y grandes.

## Crear o editar un evento

1. Pulsa **Nuevo evento** en el panel o en el calendario.
2. Escribe un título de hasta 120 caracteres.
3. Selecciona la fecha y la hora de inicio.
4. Selecciona una categoría existente o escribe un nombre nuevo. Las categorías creadas desde el formulario se guardan en la cuenta y se pueden reutilizar.
5. Elige cuándo quieres recibir el recordatorio: a la hora del evento, 5, 15 o 30 minutos antes, 1 hora antes o 1 día antes. Las opciones desactivadas en Configuración no se ofrecen para eventos nuevos.
6. Pulsa **Crear evento**. Para un evento existente, pulsa **Guardar cambios**.

Para editar, abre el evento desde el panel o desde el calendario. Para eliminarlo, usa el control de eliminación en el panel y confirma la acción.

## Consultar el calendario

El calendario agrupa los eventos propios por día y permite avanzar o retroceder un mes. Si un día contiene más eventos de los que caben en la celda, se indica cuántos quedan ocultos. En esta versión el calendario presenta eventos; no existe una entidad separada de tareas pendientes ni una vista lateral de detalle al seleccionar un día.

## Crear una rutina

1. Abre **Mi rutina**.
2. Escribe el nombre del bloque, su hora de inicio y su duración entre 5 y 480 minutos.
3. Pulsa **Añadir a mi rutina**.

El bloque se guarda para el día de la semana actual y vuelve a aparecer en ese día cada semana. La versión actual no permite elegir otro día desde el formulario, definir una hora final directamente, editar o eliminar bloques, ni configurar reglas de repetición distintas.

## Notificaciones y recordatorios

El centro de notificaciones lista los avisos recientes de la cuenta. Cada aviso se puede marcar como leído o descartar; descartar lo elimina del centro. **Marcar todo como leído** actualiza todos los avisos pendientes.

Los canales disponibles dependen de la configuración del servidor:

- Las notificaciones dentro de la aplicación se guardan en la base de datos.
- Los avisos del navegador necesitan permiso del usuario y Planify abierto para la consulta periódica.
- Web Push puede mostrarse con el navegador cerrado, pero requiere claves VAPID, HTTPS (salvo `localhost`) y una suscripción por navegador.
- El correo requiere configuración SMTP. Los correos por evento o rutina y el resumen semanal son opciones independientes.
- Las horas silenciosas retrasan los avisos hasta que termina el intervalo configurado.

Las preferencias de rutina permiten avisar al inicio o 5 minutos antes y activar un sonido. El sonido solo puede reproducirse cuando Planify está abierta y el navegador lo permite. Si un canal externo no está configurado, activarlo en la interfaz no basta para que se envíen avisos por ese canal.

## Perfil y configuración

En **Configuración** puedes:

- Activar o desactivar anticipaciones de recordatorios y elegir la anticipación predeterminada.
- Cambiar las preferencias de avisos de rutina, las horas silenciosas y los canales de entrega.
- Activar el tema oscuro. La selección se guarda en el almacenamiento local del navegador, no como preferencia sincronizada entre dispositivos.
- Cambiar el nombre y el correo. Para cambiar el correo, se solicita la contraseña actual; las cuentas creadas solo con Google deben crear primero una contraseña.
- Crear, renombrar, recolorear y eliminar categorías. No se puede eliminar una categoría que tenga eventos ni la última categoría de la cuenta.
- Cambiar o crear una contraseña. Se requiere la contraseña actual si el acceso local ya estaba habilitado.
- Eliminar la cuenta y sus datos. La acción requiere confirmaciones adicionales y no se puede deshacer.

La guía principal del proyecto contiene instrucciones para configurar Google OAuth, SMTP, VAPID y despliegues con Docker o PythonAnywhere.