from django.urls import reverse
from django.utils import timezone
from rest_framework import serializers

from apps.malls.utils.high_season import (
    high_season_multiplier as center_high_season_multiplier,
    normalize_high_season_months,
)
from apps.ad_spaces.utils.availability_calendar import (
    availability_calendar_years,
    months_occupied_by_year,
    year_months_occupied,
)
from apps.ad_spaces.utils.covers import ad_space_effective_cover_url
from apps.ad_spaces.models import AdSpace
from apps.common.utils.catalog_access import shopping_center_allows_public_catalog
from apps.bidding.serializers import CatalogActiveAuctionSerializer
from apps.bidding.utils.queries import get_open_auction_for_space, workspace_bidding_enabled
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
    status_label = serializers.SerializerMethodField()
    type_label = serializers.CharField(source="get_type_display", read_only=True)
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
    active_auction = serializers.SerializerMethodField(read_only=True)
    marketplace_bidding_enabled = serializers.SerializerMethodField(read_only=True)

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
            "type",
            "type_label",
            "title",
            "description",
            "width",
            "height",
            "quantity",
            "material",
            "location_description",
            "level",
            "monthly_price_usd",
            "status",
            "status_label",
            "cover_image",
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
            "active_auction",
            "marketplace_bidding_enabled",
        )
        read_only_fields = ("status",)

    def get_marketplace_bidding_enabled(self, obj):
        ws = obj.shopping_center.workspace
        return workspace_bidding_enabled(ws)

    def get_active_auction(self, obj):
        if not workspace_bidding_enabled(obj.shopping_center.workspace):
            return None
        auction = get_open_auction_for_space(obj.pk)
        if auction is None:
            return None
        return CatalogActiveAuctionSerializer(auction, context=self.context).data

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

    def get_status_label(self, obj):
        return obj.get_status_display()

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

    def _absolute_media_url(self, url: str) -> str:
        if not url:
            return ""
        request = self.context.get("request")
        if request:
            return request.build_absolute_uri(url)
        return url

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
