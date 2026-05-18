# Cron del backend (producción)

Directorio de referencia para programar tareas en el servidor API (`/home/git/backend`, venv en `.venv`).

## Instalación

```bash
ssh publivalla-api
sudo -u git mkdir -p /home/git/backend/logs
sudo -u git crontab -e
```

Copiar el contenido de **`publivalla-backend.crontab`** (bloque «ACTIVAS») o ejecutar:

```bash
sudo -u git crontab /home/git/backend/scripts/crond/publivalla-backend.crontab
```

(Revisa que no dupliques entradas si ya tenías un crontab.)

## Comandos en cron

| Comando | Frecuencia sugerida | Función |
|--------|---------------------|---------|
| `expire_order_holds` | Cada hora | Cancela pedidos enviados con hold de 72 h vencido; libera tomas. |
| `expire_active_orders` | Diario (tras medianoche) | Pasa a «vencida» órdenes activas cuyo contrato ya terminó. |

Dry-run en el servidor:

```bash
cd /home/git/backend
.venv/bin/python manage.py expire_order_holds --dry-run
.venv/bin/python manage.py expire_active_orders --dry-run
```

## Comandos que no van en cron

| Comando | Uso |
|---------|-----|
| `ensure_default_workspace` | Setup / deploy inicial |
| `migrate` | Deploy |
| `seed_production_catalog` | Carga inicial de catálogo |
| `provider_demo_data` | Datos de prueba |
| `order_demo_data` | Datos de prueba |
| `convert_media_to_webp` | Mantenimiento puntual de medios |

## Celery

El envío de correos y tareas encoladas usa **systemd** (`scripts/systemd/publivalla-celery.service`), no este cron.

## Logs

Los jobs escriben en `/home/git/backend/logs/cron-*.log`. Rotar o truncar según política del servidor (logrotate).
