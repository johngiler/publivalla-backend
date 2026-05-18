"""
Genera clientes y pedidos realistas en un workspace (previsualizar dashboards).

- No modifica centros, tomas ni usuarios.
- Cinco empresas cliente (sin usuarios vinculados); RIF fijos para idempotencia con --reset.
- Pedidos repartidos en ~30 días (gráfico diario) y con envíos repartidos en ~12 meses (ingresos).
- Prioriza estados activa y vencida; incluye muestras del resto de estados.

Uso::

    python manage.py order_demo_data
    python manage.py order_demo_data --reset
    python manage.py order_demo_data --workspace-slug acme
    python manage.py order_demo_data --workspace-slug sambil

Requisitos: workspace existente y tomas en catálogo suficientes para colocar contratos
según la duración mínima de reserva, sin solaparse con reservas ya existentes en pipeline.
"""

from __future__ import annotations

import random
from calendar import monthrange
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from apps.ad_spaces.models import AdSpace
from apps.clients.models import Client, ClientStatus
from apps.orders.models import Order, OrderItem, OrderStatus, OrderStatusEvent, OrderPaymentMethod
from apps.orders.services import log_order_status_transition
from apps.orders.utils.validators import (
    MIN_RESERVATION_CALENDAR_MONTHS,
    contract_meets_min_months,
    line_subtotal,
    order_item_conflicts,
)
from apps.workspaces.models import Workspace

# RIF únicos por workspace; si ya existen, se reutilizan los clientes al reejecutar.
SEED_CLIENTS = [
    {
        "company_name": "Distribuidora Los Andes, C.A.",
        "rif": "J-30845219-6",
        "email": "compras@distlosandes.com.ve",
        "contact_name": "Ricardo Salazar",
        "phone": "+58 212 482-9130",
        "city": "Caracas",
        "address": "Av. Francisco de Miranda, Torre Empresarial, piso 4. Chacao.",
    },
    {
        "company_name": "Alimentos del Valle, S.A.",
        "rif": "J-29478103-2",
        "email": "logistica@alimentosdelvalle.com.ve",
        "contact_name": "Patricia Mujica",
        "phone": "+58 414 772-1104",
        "city": "Valencia",
        "address": "Zona industrial San José, galpón 12.",
    },
    {
        "company_name": "Publicidad Meridiano, C.A.",
        "rif": "J-40122588-7",
        "email": "cuentas@pubmeridiano.com.ve",
        "contact_name": "Luis Armando Brito",
        "phone": "+58 212 335-8891",
        "city": "Caracas",
        "address": "La Castellana, calle Madrid, edif. Horizonte, ofc. 503.",
    },
    {
        "company_name": "Retail Urbano 360, C.A.",
        "rif": "J-31599044-1",
        "email": "operaciones@retailurbano360.com.ve",
        "contact_name": "Daniela Oropeza",
        "phone": "+58 424 551-2038",
        "city": "Maracay",
        "address": "Centro Parque Aragua, local 18-B.",
    },
    {
        "company_name": "Bebidas Andinas del Centro, C.A.",
        "rif": "J-28933456-9",
        "email": "facturacion@bebidasandinas.com.ve",
        "contact_name": "Héctor Manrique",
        "phone": "+58 212 266-4402",
        "city": "Los Teques",
        "address": "Av. Perimetral, sector La Morita.",
    },
]

# Orden lógico del flujo hasta «activa» (para eventos y métricas de tiempos).
_PIPELINE_TO_ACTIVE = [
    OrderStatus.DRAFT,
    OrderStatus.SUBMITTED,
    OrderStatus.CLIENT_APPROVED,
    OrderStatus.ART_APPROVED,
    OrderStatus.INVOICED,
    OrderStatus.PAID,
    OrderStatus.PERMIT_PENDING,
    OrderStatus.INSTALLATION,
    OrderStatus.ACTIVE,
]


def _last_day_of_month(y: int, m: int) -> date:
    return date(y, m, monthrange(y, m)[1])


def _contract_end_inclusive(start: date, num_months: int) -> date:
    """Último día del mes que cierra el periodo de `num_months` meses de calendario inclusivos."""
    m0 = start.month - 1 + (num_months - 1)
    y = start.year + m0 // 12
    m = m0 % 12 + 1
    return _last_day_of_month(y, m)


def _naive_local(dt: datetime) -> datetime:
    if timezone.is_naive(dt):
        return timezone.make_aware(dt, timezone.get_current_timezone())
    return timezone.localtime(dt)


def _pick_submitted_in_month(today: date, months_ago: int, rng: random.Random) -> datetime:
    """Datetime consciente en un día laborable del mes `months_ago` respecto a `today`."""
    y, m = today.year, today.month
    m -= months_ago
    while m <= 0:
        m += 12
        y -= 1
    last = monthrange(y, m)[1]
    day = rng.randint(1, last)
    h = rng.randint(9, 17)
    mi = rng.choice([0, 15, 30, 45])
    d = date(y, m, day)
    naive = datetime.combine(d, time(h, mi))
    return timezone.make_aware(naive, timezone.get_current_timezone())


def _chain_to_status(final: str) -> list[str]:
    """Secuencia de estados hasta el final deseado (eventos coherentes con `Order.status`)."""
    if final == OrderStatus.DRAFT:
        return [OrderStatus.DRAFT]
    if final == OrderStatus.CANCELLED:
        return [
            OrderStatus.DRAFT,
            OrderStatus.SUBMITTED,
            OrderStatus.CLIENT_APPROVED,
            OrderStatus.CANCELLED,
        ]
    if final == OrderStatus.EXPIRED:
        # Primero alcanzar «activa»; luego se registra la transición a «vencida» aparte.
        return list(_PIPELINE_TO_ACTIVE)
    try:
        idx = _PIPELINE_TO_ACTIVE.index(final)
    except ValueError:
        return [OrderStatus.DRAFT, OrderStatus.SUBMITTED, final]
    return _PIPELINE_TO_ACTIVE[: idx + 1]


def _emit_status_chain(order: Order, statuses: list[str], t0: datetime, rng: random.Random) -> None:
    t = _naive_local(t0)
    prev = ""
    for st in statuses:
        log_order_status_transition(order, prev, st, created_at=t)
        prev = st
        t += timedelta(hours=rng.randint(3, 36))


class Command(BaseCommand):
    help = (
        "Crea clientes y pedidos de demostración realistas en un workspace "
        "(gráficas del panel admin). No altera centros, tomas ni usuarios."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--workspace-slug",
            default="acme",
            help="Slug del workspace (default: acme).",
        )
        parser.add_argument(
            "--reset",
            action="store_true",
            help="Elimina pedidos previos de los clientes semilla (mismos RIF) antes de crear.",
        )
        parser.add_argument(
            "--seed",
            type=int,
            default=42,
            help="Semilla del generador aleatorio (reproducibilidad).",
        )

    def handle(self, *args, **options):
        slug = (options["workspace_slug"] or "").strip().lower()
        if not slug:
            raise CommandError("Indica un --workspace-slug válido.")

        reset = bool(options["reset"])
        rng = random.Random(int(options["seed"]))

        ws = Workspace.objects.filter(slug=slug, is_active=True).first()
        if ws is None:
            raise CommandError(
                f'No existe un workspace activo con slug "{slug}".')

        spaces = list(
            AdSpace.objects.filter(
                shopping_center__workspace=ws, is_active=True).order_by("id")
        )
        if len(spaces) < 4:
            raise CommandError(
                f"Se necesitan al menos 4 tomas activas en el workspace {slug!r}; hay {len(spaces)}."
            )

        rif_list = [c["rif"] for c in SEED_CLIENTS]

        with transaction.atomic():
            if reset:
                deleted, _ = Order.objects.filter(
                    client__workspace=ws, client__rif__in=rif_list).delete()
                if deleted and self.verbosity >= 1:
                    self.stdout.write(self.style.WARNING(
                        f"Pedidos eliminados (reset): {deleted} filas en cascada."))

            clients: list[Client] = []
            for row in SEED_CLIENTS:
                c, created = Client.objects.get_or_create(
                    workspace=ws,
                    rif=row["rif"],
                    defaults={
                        "company_name": row["company_name"],
                        "email": row["email"],
                        "contact_name": row["contact_name"],
                        "phone": row["phone"],
                        "city": row["city"],
                        "address": row["address"],
                        "status": ClientStatus.ACTIVE,
                        "notes": "",
                    },
                )
                if not created:
                    # Alinear datos visibles por si cambió el catálogo de nombres.
                    Client.objects.filter(pk=c.pk).update(
                        company_name=row["company_name"],
                        email=row["email"],
                        contact_name=row["contact_name"],
                        phone=row["phone"],
                        city=row["city"],
                        address=row["address"],
                    )
                    c.refresh_from_db()
                clients.append(c)

            today = timezone.localdate()
            now = timezone.now()

            # --- Especificaciones: (días atrás creación, estado final, inicio contrato offset días, meses inclusivos)
            # Contratos activos (cubren hoy)
            specs: list[tuple[int, str, int, int]] = []
            for _ in range(10):
                specs.append(
                    (
                        rng.randint(0, 29),
                        OrderStatus.ACTIVE,
                        rng.randint(-120, -30),
                        rng.randint(6, 14),
                    )
                )
            # Vencidos (fin < hoy)
            for _ in range(9):
                specs.append(
                    (
                        rng.randint(0, 29),
                        OrderStatus.EXPIRED,
                        rng.randint(-500, -200),
                        rng.randint(5, 10),
                    )
                )
            # Historial mensual (ingreso contratado 12 meses): mezcla activa/vencida, created hace tiempo
            for mb in range(1, 13):
                specs.append(
                    (
                        25 + mb * 3,
                        rng.choice(
                            [OrderStatus.EXPIRED, OrderStatus.ACTIVE, OrderStatus.EXPIRED]),
                        -400 + mb * 28,
                        6,
                    )
                )
            # Borradores y pipeline intermedio
            specs.extend(
                [
                    (rng.randint(0, 14), OrderStatus.DRAFT, rng.randint(30, 90), 6),
                    (rng.randint(0, 10), OrderStatus.DRAFT, 15, 5),
                    (rng.randint(0, 20), OrderStatus.SUBMITTED, 45, 6),
                    (rng.randint(0, 18), OrderStatus.CLIENT_APPROVED, 40, 6),
                    (rng.randint(0, 16), OrderStatus.ART_APPROVED, 35, 6),
                    (rng.randint(0, 14), OrderStatus.INVOICED, 30, 6),
                    (rng.randint(0, 12), OrderStatus.PAID, 25, 6),
                    (rng.randint(0, 10), OrderStatus.PERMIT_PENDING, 20, 6),
                    (rng.randint(0, 8), OrderStatus.INSTALLATION, 14, 6),
                    (rng.randint(2, 22), OrderStatus.CANCELLED, 60, 6),
                    (rng.randint(2, 24), OrderStatus.CANCELLED, 90, 5),
                    (rng.randint(2, 24), OrderStatus.CANCELLED, 50, 5),
                ]
            )

            created_orders = 0
            space_cursor = 0

            for days_ago, final_status, start_off, n_months in specs:
                client = clients[space_cursor % len(clients)]
                created_dt = now - \
                    timedelta(days=days_ago, hours=rng.randint(
                        0, 23), minutes=rng.randint(0, 59))
                start = today + timedelta(days=start_off)
                end = _contract_end_inclusive(start, n_months)
                if not contract_meets_min_months(start, end):
                    end = _contract_end_inclusive(
                        start, MIN_RESERVATION_CALENDAR_MONTHS)
                if final_status == OrderStatus.ACTIVE and end < today:
                    start = today - timedelta(days=rng.randint(60, 100))
                    end = _contract_end_inclusive(start, rng.randint(8, 14))
                if final_status == OrderStatus.EXPIRED and end >= today:
                    start = today - timedelta(days=rng.randint(400, 700))
                    end = _contract_end_inclusive(start, rng.randint(5, 9))
                    if end >= today:
                        end = today - timedelta(days=20)

                placed = False
                for attempt in range(len(spaces) * 2):
                    sp = spaces[(space_cursor + attempt) % len(spaces)]
                    if not order_item_conflicts(sp.id, start, end, exclude_order_id=None):
                        placed = True
                        chosen = sp
                        space_cursor += attempt + 1
                        break
                if not placed:
                    self.stdout.write(
                        self.style.WARNING(
                            f"Omitido un pedido ({final_status}): no hay toma libre para {start}–{end}."
                        )
                    )
                    continue

                order = Order(
                    client=client,
                    status=OrderStatus.DRAFT,
                    total_amount=Decimal("0"),
                    payment_method=OrderPaymentMethod.UNSET,
                )
                order.created_at = created_dt
                order.updated_at = created_dt
                order.save()

                monthly = chosen.monthly_price_usd
                sub = line_subtotal(monthly, start, end)
                OrderItem.objects.create(
                    order=order,
                    ad_space=chosen,
                    start_date=start,
                    end_date=end,
                    monthly_price=monthly,
                    subtotal=sub,
                    created_at=created_dt,
                    updated_at=created_dt,
                )
                order.total_amount = sub
                order.save(update_fields=["total_amount", "updated_at"])

                OrderStatusEvent.objects.filter(order_id=order.pk).delete()

                if final_status == OrderStatus.DRAFT:
                    log_order_status_transition(
                        order, "", OrderStatus.DRAFT, created_at=created_dt)
                else:
                    chain = _chain_to_status(final_status)
                    _emit_status_chain(order, chain, created_dt, rng)
                    if final_status == OrderStatus.EXPIRED:
                        last_ev = (
                            OrderStatusEvent.objects.filter(order_id=order.pk)
                            .order_by("-created_at", "-id")
                            .first()
                        )
                        t_exp = (last_ev.created_at if last_ev else created_dt) + timedelta(
                            days=rng.randint(1, 5)
                        )
                        log_order_status_transition(
                            order,
                            OrderStatus.ACTIVE,
                            OrderStatus.EXPIRED,
                            created_at=t_exp,
                            note="Cierre de contrato (datos de demostración).",
                        )

                pay = OrderPaymentMethod.UNSET
                if final_status in (
                    OrderStatus.PAID,
                    OrderStatus.PERMIT_PENDING,
                    OrderStatus.INSTALLATION,
                    OrderStatus.ACTIVE,
                    OrderStatus.EXPIRED,
                ):
                    pay = rng.choice(
                        [
                            OrderPaymentMethod.BANK_TRANSFER,
                            OrderPaymentMethod.MOBILE_PAYMENT,
                            OrderPaymentMethod.ZELLE,
                            OrderPaymentMethod.CARD,
                        ]
                    )

                submitted_val = None
                if final_status != OrderStatus.DRAFT:
                    submitted_val = created_dt + \
                        timedelta(hours=rng.randint(2, 72))
                    if days_ago > 60 and final_status in (OrderStatus.ACTIVE, OrderStatus.EXPIRED):
                        mb = min(12, max(1, days_ago // 30))
                        submitted_val = _pick_submitted_in_month(
                            today, mb, rng)
                    if submitted_val < created_dt:
                        submitted_val = created_dt + \
                            timedelta(hours=rng.randint(4, 96))

                Order.objects.filter(pk=order.pk).update(
                    status=final_status,
                    payment_method=pay,
                    submitted_at=submitted_val,
                    created_at=created_dt,
                    updated_at=created_dt,
                )

                created_orders += 1

            self.stdout.write(
                self.style.SUCCESS(
                    f"Listo: workspace={slug!r}, clientes semilla={len(clients)}, pedidos creados={created_orders}."
                )
            )
