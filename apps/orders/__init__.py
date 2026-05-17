"""
Dominio de pedidos (órdenes, líneas, documentos, correos).

Estructura de referencia para otras apps en ``backend/apps/``:

- **Raíz:** ``models``, ``serializers``, ``admin``, ``apps``, ``tests``.
- **``services/``:** casos de uso en ``order_services.py`` (import ``apps.orders.services``).
- **``tasks/``:** tareas Celery (``apps.orders.tasks``; autodiscover con ``related_name="tasks"``).
- **``views/``:** checkout invitado, ViewSet de pedidos y vistas admin API (``apps.orders.views``).
- **``utils/``:** utilería (validadores, PDF/correos/Excel, referencias, jobs ligeros).
- **``migrations/``**, **``management/``**, según Django y despliegue.
"""
