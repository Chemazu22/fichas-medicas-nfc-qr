# Guía de operación

## Datos y privacidad

La aplicación guarda SQLite, configuración, respaldos, perfiles locales, QR e indicadores de publicación en `~/Library/Application Support/FichasMedicas/`. Actualizar o reemplazar el `.app` no debería eliminar esa carpeta. SQLite usa permisos locales, pero no cifra los expedientes; usa una cuenta de macOS protegida y FileVault.

GitHub Pages sirve perfiles públicamente. Un UUID difícil de adivinar no es autenticación. Publica solo los campos seleccionados con consentimiento vigente y recuerda que revocar el consentimiento requiere completar una publicación posterior para retirar la página remota.

## Primer uso

1. Abre Fichas Médicas y registra una persona. Elige el nacimiento con el botón Calendario. Puedes guardar hasta tres contactos de emergencia; el teléfono acepta números con prefijo `+`, espacios, paréntesis o guiones. El formulario guarda los datos localmente; no autoriza su publicación. La migración del esquema añade los campos nuevos al abrir la versión actualizada y conserva la ficha existente.
2. En Expedientes, abre Consentimiento y selecciona los campos autorizados. La confirmación es obligatoria.
3. En Configuración, indica la URL HTTPS base de Pages, la carpeta de checkout y el remoto Git. Usa autenticación local de Git mediante Keychain o SSH; la aplicación no almacena tokens.
4. Verifica Git y el remoto. Luego usa Publicar perfiles autorizados para preparar el commit y ejecutar el push.
5. Genera el QR después de publicar y comprobar que Pages sirve la URL. La app no escribe tarjetas NFC; usa un dispositivo compatible para grabar el payload URI.

## Cambios y revocación

Editar un expediente invalida su HTML y QR locales. Revocar, archivar o eliminar también los invalida. La UI muestra si hay publicación, actualización o retiro pendiente. Completa la operación de publicación y revisa el perfil remoto después de un push exitoso.

## Respaldos y restauración

En Respaldos puedes crear una copia SQLite consistente y revisar su integridad. La restauración exige confirmación y guarda primero un respaldo de seguridad de la base actual. Después de restaurar, vuelve a solicitar consentimiento explícito para cada perfil antes de generarlo o publicarlo. Mantén copias en un lugar protegido y verifica que puedas recuperarlas antes de depender de ellas.

## Actualizar la aplicación

Cierra la app y reemplaza `FichasMedicas.app` por la versión nueva. Conserva `~/Library/Application Support/FichasMedicas/`; no forma parte del bundle ni del ZIP de entrega.
