from django.urls import reverse
from django.utils import timezone
from rest_framework import serializers

from apps.malls.utils.high_season import (
    high_season_multiplier as center_high_season_multiplier,
    normalize_high_season_months,
)
from apps.ad_spaces.utils.availability_calendar import (
    active_availability_block_ranges,
    availability_calendar_years,
    client_months_highlight_by_year,
    months_occupied_by_year,
    year_months_occupied,
)
from apps.ad_spaces.utils.covers import ad_space_effective_cover_url
from apps.ad_spaces.utils.display import (
    ad_space_location_text,
    ad_space_primary_format,
    ad_space_type_label,
)
from apps.ad_spaces.serializers.admin_serializers import AdSpaceFormatSerializer
from apps.orders.utils.validators import ad_space_allows_marketplace_reservation
from apps.ad_spaces.models import AdSpace
from apps.common.utils.catalog_access import shopping_center_allows_public_catalog
from apps.providers.models import MountingProvider
from apps.providers.serializers import CatalogMountingProviderSerializer

MOUNTING_PROVIDERS_PAGE_SIZE = 3


class AdSpaceSerializer(serializers.ModelSerializer):
    shopping_center_slug = serializers.CharField(
        source="shopping_center.slug", read_only=True
    )
    shopping_center_name = serializers.CharField(
        source="shopping_center.name", read_only=True
    )
    shopping_center_city = serializers.CharField(
        source="shopping_center.city", read_only=True
    )
    catalog_public = serializers.SerializerMethodField(read_only=True)
    availability_year = serializers.SerializerMethodField(read_only=True)
    availability_calendar_years = serializers.SerializerMethodField(read_only=True)
    months_occupied = serializers.SerializerMethodField(read_only=True)
    months_occupied_by_year = serializers.SerializerMethodField(read_only=True)
    client_months_reserved_by_year = serializers.SerializerMethodField(read_only=True)
    client_months_active_by_year = serializers.SerializerMethodField(read_only=True)
    availability_blocked_ranges = serializers.SerializerMethodField(read_only=True)
    availability_label = serializers.SerializerMethodField()
    marketplace_reservable = serializers.SerializerMethodField(read_only=True)
    name = serializers.CharField(read_only=True)
    title = serializers.CharField(source="name", read_only=True)
    formats = AdSpaceFormatSerializer(many=True, read_only=True)
    type = serializers.SerializerMethodField(read_only=True)
    type_label = serializers.SerializerMethodField(read_only=True)
    width = serializers.SerializerMethodField(read_only=True)
    height = serializers.SerializerMethodField(read_only=True)
    quantity = serializers.SerializerMethodField(read_only=True)
    location_description = serializers.SerializerMethodField(read_only=True)
    double_sided = serializers.SerializerMethodField(read_only=True)
    material = serializers.SerializerMethodField(read_only=True)
    level = serializers.SerializerMethodField(read_only=True)
    venue_zone = serializers.SerializerMethodField(read_only=True)
    production_specs = serializers.SerializerMethodField(read_only=True)
    installation_notes = serializers.SerializerMethodField(read_only=True)
    hem_pocket_top_cm = serializers.SerializerMethodField(read_only=True)
    location_image = serializers.SerializerMethodField(read_only=True)
    production_image = serializers.SerializerMethodField(read_only=True)
    location_images = serializers.SerializerMethodField(read_only=True)
    production_images = serializers.SerializerMethodField(read_only=True)
    cover_image = serializers.SerializerMethodField()
    gallery_images = serializers.SerializerMethodField()
    mounting_providers = serializers.SerializerMethodField(read_only=True)
    municipal_permit_notice = serializers.CharField(
        source="shopping_center.municipal_permit_notice",
        read_only=True,
    )
    advertising_regulations = serializers.CharField(
        source="shopping_center.advertising_regulations",
        read_only=True,
    )
    high_season_months = serializers.SerializerMethodField(read_only=True)
    high_season_multiplier = serializers.SerializerMethodField(read_only=True)
    rental_billing_unit = serializers.CharField(
        source="shopping_center.rental_billing_unit",
        read_only=True,
    )
    class Meta:
        model = AdSpace
        fields = (
            "id",
            "code",
            "shopping_center",
            "shopping_center_slug",
            "shopping_center_name",
            "shopping_center_city",
            "catalog_public",
            "availability_year",
            "availability_calendar_years",
            "months_occupied",
            "months_occupied_by_year",
            "client_months_reserved_by_year",
            "client_months_active_by_year",
            "availability_blocked_ranges",
            "name",
            "title",
            "formats",
            "type",
            "type_label",
            "description",
            "width",
            "height",
            "quantity",
            "material",
            "location_description",
            "level",
            "monthly_price_usd",
            "availability",
            "availability_label",
            "marketplace_reservable",
            "cover_image",
            "location_image",
            "production_image",
            "location_images",
            "production_images",
            "gallery_images",
            "venue_zone",
            "double_sided",
            "production_specs",
            "installation_notes",
            "hem_pocket_top_cm",
            "mounting_providers",
            "municipal_permit_notice",
            "advertising_regulations",
            "high_season_months",
            "high_season_multiplier",
            "rental_billing_unit",
        )
        read_only_fields = ("availability",)

    def _primary(self, obj):
        return ad_space_primary_format(obj)

    def get_type(self, obj):
        row = self._primary(obj)
        if row is None:
            return ""
        return getattr(row.product_type, "slug", "") or ""

    def get_type_label(self, obj):
        return ad_space_type_label(obj)

    def get_width(self, obj):
        row = self._primary(obj)
        return row.width if row else None

    def get_height(self, obj):
        row = self._primary(obj)
        return row.height if row else None

    def get_quantity(self, obj):
        row = self._primary(obj)
        return row.quantity if row else 1

    def get_location_description(self, obj):
        return ad_space_location_text(obj)

    def get_double_sided(self, obj):
        row = self._primary(obj)
        return bool(row.double_sided) if row else False

    def _legacy_empty(self, obj):
        return ""

    get_material = _legacy_empty
    get_level = _legacy_empty
    get_venue_zone = _legacy_empty
    get_production_specs = _legacy_empty
    get_installation_notes = _legacy_empty

    def get_hem_pocket_top_cm(self, obj):
        return None

    def _absolute_media_url(self, url: str) -> str:
        if not url:
            return ""
        request = self.context.get("request")
        if request:
            uri = request.build_absolute_uri(url)
            if uri.startswith("http://") and request.META.get(
                "HTTP_X_FORWARDED_PROTO", ""
            ).lower() == "https":
                return "https://" + uri[7:]
            return uri
        return url

    def _absolute_media_file(self, field) -> str | None:
        if not field:
            return None
        return self._absolute_media_url(field.url) or None

    def get_location_images(self, obj):
        request = self.context.get("request")
        out = []
        for i in obj.location_images.all().order_by("sort_order", "id"):
            if not i.image:
                continue
            u = i.image.url
            out.append(request.build_absolute_uri(u) if request else u)
        return out

    def get_production_images(self, obj):
        request = self.context.get("request")
        out = []
        for i in obj.production_images.all().order_by("sort_order", "id"):
            if not i.image:
                continue
            u = i.image.url
            out.append(request.build_absolute_uri(u) if request else u)
        return out

    def get_location_image(self, obj):
        images = self.get_location_images(obj)
        return images[0] if images else None

    def get_production_image(self, obj):
        images = self.get_production_images(obj)
        return images[0] if images else None

    def get_catalog_public(self, obj):
        return shopping_center_allows_public_catalog(obj.shopping_center)

    def get_availability_year(self, obj):
        years = availability_calendar_years()
        return years[0] if years else timezone.now().date().year

    def get_availability_calendar_years(self, obj):
        return availability_calendar_years()

    def get_months_occupied(self, obj):
        y = self.get_availability_year(obj)
        return year_months_occupied(obj.pk, y)

    def get_months_occupied_by_year(self, obj):
        by = months_occupied_by_year(obj.pk)
        return {str(y): flags for y, flags in by.items()}

    def _client_months_field(self, obj, kind: str):
        bulk = self.context.get("client_months_bulk")
        if bulk is not None:
            by_space = bulk.get(kind, {}).get(obj.pk)
            if by_space is None:
                return None
            return {str(y): flags for y, flags in by_space.items()}
        client = self.context.get("marketplace_client")
        if client is None:
            return None
        highlight = client_months_highlight_by_year(obj.pk, client.pk)
        by = highlight.get(kind, {})
        return {str(y): flags for y, flags in by.items()}

    def get_client_months_reserved_by_year(self, obj):
        return self._client_months_field(obj, "reserved")

    def get_client_months_active_by_year(self, obj):
        return self._client_months_field(obj, "active")

    def get_availability_blocked_ranges(self, obj):
        return [
            {"start_date": start.isoformat(), "end_date": end.isoformat()}
            for start, end in active_availability_block_ranges(obj.pk)
        ]

    def get_availability_label(self, obj):
        return obj.get_availability_display()

    def to_representation(self, instance):
        from apps.ad_spaces.utils.marketplace_availability import (
            sync_ad_space_commercial_status,
        )

        sync_ad_space_commercial_status(instance.pk)
        instance.refresh_from_db(fields=["availability"])
        return super().to_representation(instance)

    def get_marketplace_reservable(self, obj):
        return ad_space_allows_marketplace_reservation(obj)

    def get_high_season_months(self, obj):
        return normalize_high_season_months(obj.shopping_center.high_season_months)

    def get_high_season_multiplier(self, obj):
        return str(center_high_season_multiplier(obj.shopping_center))

    def get_mounting_providers(self, obj):
        sc = obj.shopping_center
        rows: list[MountingProvider]
        cache = getattr(sc, "_prefetched_objects_cache", None)
        if cache is not None and "mounting_providers" in cache:
            rows = [p for p in cache["mounting_providers"] if p.is_active]
            rows.sort(key=lambda p: (p.sort_order, p.id))
        else:
            rows = list(
                MountingProvider.objects.filter(
                    shopping_centers=sc,
                    is_active=True,
                )
                .order_by("sort_order", "id")
                .distinct()
            )
        total = len(rows)
        page_rows = rows[:MOUNTING_PROVIDERS_PAGE_SIZE]
        data = CatalogMountingProviderSerializer(
            page_rows, many=True, context=self.context
        ).data
        request = self.context.get("request")
        next_url = None
        if total > MOUNTING_PROVIDERS_PAGE_SIZE and request:
            url_name = (
                "catalog-space-mounting-providers"
                if "/api/catalog/" in (request.path or "")
                else "space-mounting-providers"
            )
            rel = (
                reverse(url_name, kwargs={"pk": obj.pk})
                + f"?page=2&page_size={MOUNTING_PROVIDERS_PAGE_SIZE}"
            )
            next_url = request.build_absolute_uri(rel)
        return {
            "count": total,
            "next": next_url,
            "previous": None,
            "results": data,
        }

    def get_cover_image(self, obj):
        u = ad_space_effective_cover_url(obj)
        if not u:
            return None
        return self._absolute_media_url(u)

    def get_gallery_images(self, obj):
        request = self.context.get("request")
        out = []
        for i in obj.gallery_images.all().order_by("sort_order", "id"):
            if not i.image:
                continue
            u = i.image.url
            out.append(request.build_absolute_uri(u) if request else u)
        return out
