# Fichas Médicas NFC/QR

Aplicación local para administrar expedientes médicos. El desarrollo se organiza por fases. Esta entrega cubre las **Fases 1 a 10: persistencia, privacidad, perfiles, QR/NFC, publicación Git, interfaz, respaldos y entrega local de macOS**. La firma Developer ID y la notarización para distribución pública siguen pendientes.

## Arquitectura objetivo

```text
fichas-medicas/
├── fichas_medicas/
│   ├── main.py                     # Arranque de la aplicación (fase UI)
│   ├── config/
│   │   └── paths.py                # Rutas persistentes de macOS
│   ├── database/
│   │   ├── connection.py           # Conexión, transacción e inicialización
│   │   ├── migrations.py           # Versiones del esquema SQLite
│   │   ├── models.py               # Tipos de datos
│   │   └── repository.py           # CRUD parametrizado de personas
│   ├── security/
│   │   ├── validation.py           # Validación de entrada
│   │   └── sanitization.py         # Codificación segura para salida HTML
│   ├── services/
│   │   ├── patient_service.py      # Reglas de negocio y consentimiento
│   │   ├── profile_service.py      # Perfiles públicos autorizados
│   │   ├── qr_service.py           # URL pública, QR y payload NFC
│   │   ├── deployment_service.py   # Sincronización y publicación Git
│   │   ├── backup_service.py       # Respaldos/restauración SQLite
│   │   └── publication_state.py    # Indicadores locales de publicación por UUID
│   ├── templates/                  # HTML/CSS públicos (fase 3)
│   ├── ui/
│   │   ├── application.py          # Ventana principal y navegación
│   │   └── registration.py         # Formularios y consentimiento
│   └── utils/                      # Registro y utilidades
├── tests/
├── scripts/
│   ├── build_macos_app.py          # Build Apple Silicon con PyInstaller
│   ├── validate_macos_bundle.py    # Revisión de firma, recursos y privacidad del bundle
│   └── package_macos_release.py    # ZIP local con verificación y SHA-256
├── docs/
│   └── GUIA_DE_OPERACION.md        # Uso, privacidad, respaldos y actualización
├── requirements.txt
├── requirements-build.txt
├── pyproject.toml
└── README.md
```

Los archivos privados persistentes se guardan fuera del código, en `~/Library/Application Support/FichasMedicas/` en macOS. La base inicial es `fichas_medicas.sqlite3`. Para desarrollo y pruebas puede sustituirse la ruta con `FICHAS_MEDICAS_DATA_DIR`.

## Esquema de la primera versión

La tabla `patients` tiene un identificador interno, UUIDv4, nombre, nacimiento, tipo de sangre, alergias, padecimientos, medicamentos, información adicional, datos del contacto de emergencia, ruta opcional de fotografía, JSON de consentimiento, fechas UTC y estado (`active`, `archived`, `deleted`). El esquema se controla con `PRAGMA user_version` y migraciones incrementales. La versión 2 agrega `consent_events`, un historial de concesiones y revocaciones. Los nombres y estados tienen restricciones e índices.

La eliminación del repositorio es lógica: el registro se marca como `deleted` y queda fuera de las consultas normales. Esta decisión evita pérdida accidental; las políticas legales de retención y eliminación deben definirse antes de uso comercial.

## Fase 2: validación, privacidad y lógica de negocio

`PatientService` es la entrada de aplicación para operaciones de expediente. Para publicar datos hay que invocar `set_consent` con confirmación explícita y una selección de campos permitidos. Cada autorización o revocación se guarda junto al estado vigente y a un evento auditable en una sola transacción. El alta fuerza consentimiento vacío, y la proyección pública devuelve `None` si falta autorización, el expediente está archivado/eliminado o el JSON de consentimiento no se puede interpretar. No se permite publicar `photo_path` ni el identificador interno.

Una revocación impide que los servicios generen una proyección pública. Si ya existe una página en Pages, `DeploymentService` la marca para retirar y la elimina del repositorio en la siguiente publicación explícita. La autorización de la persona para compartir datos del contacto de emergencia no sustituye la autorización propia de ese contacto cuando sea necesaria.

## Fase 3: perfiles HTML

`ProfileService.generate(patient_id)` renderiza una ficha HTML y CSS adaptable, sin JavaScript, solamente desde la proyección autorizada de `PatientService`. El nombre del archivo es el UUIDv4; todos los valores se escapan antes de incluirlos en HTML y los enlaces `tel:` se validan por separado. Las rutas por defecto son `~/Library/Application Support/FichasMedicas/profiles/`; se pueden cambiar mediante `FICHAS_MEDICAS_PROFILES_DIR`. Los directorios/archivos usan permisos privados. La salida incluye `noindex,nofollow` para desincentivar indexación; esto no es control de acceso y no evita que una URL pública sea copiada o guardada.

Al generar un expediente sin autorización vigente, se elimina el HTML local correspondiente y no se devuelve una ruta. La eliminación remota se procesa en la siguiente publicación explícita; copias descargadas o forks de terceros pueden persistir.

## Fase 4: QR y NFC

`QrService` construye `https://.../<UUIDv4>.html`, escribe PNG con margen reglamentario y corrección de errores Q, y devuelve la misma URL como payload para programar un registro NDEF URI con un dispositivo compatible. El servicio requiere `FICHAS_MEDICAS_PUBLIC_BASE_URL` o un `public_base_url` explícito; debe ser la URL HTTPS final de Pages, incluyendo el subdirectorio del repositorio si aplica. Los PNG se guardan por defecto en `~/Library/Application Support/FichasMedicas/qr/` y se pueden ubicar con `FICHAS_MEDICAS_QR_DIR`.

Ejemplo de inicialización del servicio en Python (sustituye la base por la URL de Pages ya configurada):

```python
from fichas_medicas.database.connection import initialize_database
from fichas_medicas.database.repository import PatientRepository
from fichas_medicas.services.patient_service import PatientService
from fichas_medicas.services.qr_service import QrService

patients = PatientService(PatientRepository(initialize_database()))
qr = QrService(patients, "https://cuenta.github.io/repositorio/")
png_path = qr.generate_for_patient(patient_id=1)
url_for_nfc = qr.nfc_payload(patient_id=1)
```

No hay escritura NFC desde Mac. No se puede escanear ni copiar desde un QR generado localmente hasta que la URL esté desplegada y accesible; en esta fase solo se prepara el contenido. URL/QR requieren consentimiento vigente. La biblioteca `qrcode[pil]` es la única dependencia nueva para crear PNG.

## Fase 5: publicación GitHub Pages

`DeploymentService` comprueba Git, la raíz del repositorio, rama y remoto; admite remoto HTTPS sin credenciales embebidas o SSH configurado en el sistema. Sincroniza desde la salida privada solo archivos `UUIDv4.html` y `styles.css`, regenerando antes las fichas activas autorizadas y retirando del repositorio los UUID que ya no tengan perfil vigente. No añade la base, QR, fotos, copias de seguridad ni archivos ajenos al servicio.

El servicio se configura con una carpeta de checkout del repositorio Pages y `ProfileService`. `configure_remote(url)` prepara el remoto sin guardar tokens; Git debe tener autenticación local mediante Keychain/credential helper o una llave SSH. `publish()` prepara y confirma solo los archivos administrados, detecta cuando no hay cambios y usa una llamada Git separada para cada argumento (sin shell). Si el push falla, el commit se conserva localmente y `retry_push()` permite reintentar. Los commits sin cambios no hacen push implícito. Configura GitHub Pages en el repositorio para servir la rama/carpeta publicada.

La llamada de publicación es síncrona y tiene timeout. La interfaz la ejecuta desde un hilo de trabajo para mantener la ventana receptiva. El servicio no hace push durante configuración ni inicialización; solo cuando se invoca `publish()` o `retry_push()`.

## Fase 6: interfaz de escritorio

La aplicación se inicia con `python -m fichas_medicas.main`. La ventana ofrece navegación para dashboard, alta, búsqueda/edición, consentimiento, perfiles, QR, publicación, respaldos, configuración y acerca del sistema. La publicación corre en un hilo y entrega resultados a la UI mediante una cola. La configuración local guarda URL, ruta del checkout, remoto y apariencia; no almacena credenciales.

La aplicación incluye una vista previa del QR. Los indicadores por persona distinguen publicación confirmada, publicación pendiente, actualización pendiente, revocación pendiente y publicación retirada. El índice guarda solamente UUID y estados locales, no datos médicos.

## Fase 7: integración y respaldos

`BackupService` crea copias consistentes con la API de backup de SQLite, lista respaldos, ejecuta `PRAGMA integrity_check` y restaura solo archivos administrados en la carpeta privada. Restaurar requiere confirmación explícita y crea primero una copia de seguridad de la base actual; las migraciones compatibles se aplican a la copia preparada antes del reemplazo atómico. Por seguridad, la restauración descarta el consentimiento de publicación vigente en la copia restaurada; debe volver a confirmarse antes de generar o publicar perfiles. En la UI, creación y restauración corren en segundo plano.

Los respaldos se guardan en `~/Library/Application Support/FichasMedicas/backups/`. La carpeta Pages solo recibe HTML UUID generado en esa publicación y `styles.css`; archivos UUID huérfanos se eliminan de la salida local y no se sincronizan. Al editar, revocar, archivar o borrar, la UI invalida HTML y QR locales. La publicación remota requiere la acción explícita de publicar; hasta completar un push exitoso, los cambios y retiros se muestran como pendientes.

## Fase 8: empaquetado macOS

`scripts/build_macos_app.py` crea `dist/FichasMedicas.app` con PyInstaller en modo `onedir`, incluyendo los recursos de CustomTkinter y las plantillas HTML/CSS. El build exige macOS y Python nativo `arm64`. Los directorios de trabajo y caché quedan bajo `build/`; pueden cambiarse con `FICHAS_MEDICAS_BUILD_DIR`. La base, configuración, respaldos, perfiles y QR siguen fuera del bundle, en Application Support.

El build elimina metadatos extendidos del bundle, aplica una firma ad hoc local y ejecuta el validador de release. No incluye identidad Developer ID ni notarización; esa distribución queda pendiente.

## Fase 9: verificación de release local

`scripts/validate_macos_bundle.py` comprueba el identificador y arquitectura del bundle, la firma ad hoc, los recursos HTML/CSS y la versión de CustomTkinter. También rechaza bases SQLite, configuración, respaldos, HTML de perfiles y PNG QR generados dentro del `.app`. El build lo ejecuta automáticamente; puede repetirse con:

```bash
python scripts/validate_macos_bundle.py dist/FichasMedicas.app
```

## Fase 10: entrega local

`scripts/package_macos_release.py` vuelve a validar el `.app`, lo empaqueta con `ditto`, extrae el ZIP en una carpeta temporal y valida firma, arquitectura, recursos y privacidad otra vez. Produce `dist/FichasMedicas-macOS-arm64.zip` y un archivo SHA-256 para comprobar la copia. La guía de uso está en `docs/GUIA_DE_OPERACION.md`.

La entrega es local y no está notarizada. Para una distribución pública se necesita una identidad Developer ID y completar firma/notarización en una etapa autorizada aparte.

## Instalar y ejecutar en Mac

Se requiere Python 3.10 o posterior. En Terminal, desde la carpeta del proyecto:

```bash
cd ~/Desktop/datos-medicos-v2
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

Las Fases 1 a 3 usan la biblioteca estándar. La Fase 4 añade `qrcode[pil]`; la Fase 6 añade `customtkinter`; la fase Git usa `git` disponible en el sistema. `pytest` se incluye para desarrollo.

Para inicializar la base:

```bash
python -c 'from fichas_medicas.database.connection import initialize_database; print(initialize_database().path)'
```

Para abrir la aplicación gráfica:

```bash
python -m fichas_medicas.main
```

Para una operación de desarrollo sobre una ficha:

```bash
python -c 'from fichas_medicas.database.connection import initialize_database; from fichas_medicas.database.repository import PatientRepository; r=PatientRepository(initialize_database()); print(r.create({"full_name":"Ejemplo de prueba"}))'
```

Para correr la suite:

```bash
python -m pytest
```

Para crear el bundle Apple Silicon:

```bash
python -m pip install -r requirements-build.txt
python scripts/build_macos_app.py
python scripts/package_macos_release.py
```

## Privacidad en esta fase

SQLite usa consultas parametrizadas, claves foráneas, timeout de bloqueo y transacciones con rollback. La carpeta se crea con permisos `0700` y el archivo con `0600` cuando macOS lo permite. Esto controla acceso por permisos del usuario del sistema, pero **no cifra SQLite**. En una Mac de uso real debe mantenerse FileVault activo y la cuenta protegida. Git ignorea bases, WAL, respaldos y salida. GitHub Pages es público: la UI nunca publica automáticamente y no ofrece control de acceso a los perfiles.

## Dependencias y fases siguientes

- Ejecución: biblioteca estándar de Python, SQLite, `qrcode[pil]` y Git instalado.
- Desarrollo: `pytest`.
- Fase 6: CustomTkinter para interfaz de escritorio.
- PyInstaller se instala desde `requirements-build.txt` para construir la app macOS.

Las Fases 8, 9 y 10 están implementadas para entrega local. La firma Developer ID y la notarización no están configuradas.
