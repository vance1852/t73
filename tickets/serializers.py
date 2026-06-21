from decimal import Decimal

from rest_framework import serializers

from .models import (
    Exchange,
    Performance,
    Refund,
    RefundExchangeLog,
    RefundRule,
    Show,
    TicketOrder,
)


class ShowSerializer(serializers.ModelSerializer):
    class Meta:
        model = Show
        fields = ["id", "title", "troupe", "genre", "status", "created_at"]
        read_only_fields = ["id", "created_at"]


class PerformanceSerializer(serializers.ModelSerializer):
    show_title = serializers.CharField(source="show.title", read_only=True)
    remaining_seats = serializers.SerializerMethodField()

    class Meta:
        model = Performance
        fields = [
            "id", "show", "show_title", "hall", "start_at",
            "total_seats", "sold_seats", "remaining_seats", "price", "created_at",
        ]
        read_only_fields = ["id", "sold_seats", "created_at"]

    def get_remaining_seats(self, obj):
        return obj.total_seats - obj.sold_seats


class OrderSerializer(serializers.ModelSerializer):
    show_title = serializers.CharField(source="performance.show.title", read_only=True)
    performance_hall = serializers.CharField(source="performance.hall", read_only=True)
    performance_start_at = serializers.DateTimeField(source="performance.start_at", read_only=True)

    class Meta:
        model = TicketOrder
        fields = [
            "id", "performance", "show_title", "performance_hall", "performance_start_at",
            "customer_name", "phone", "quantity", "amount", "status",
            "has_exchanged", "exchange_count", "created_at",
        ]
        read_only_fields = ["id", "amount", "status", "has_exchanged", "exchange_count", "created_at"]


class OrderCreateSerializer(serializers.Serializer):
    performance = serializers.IntegerField()
    customer_name = serializers.CharField(max_length=64)
    phone = serializers.CharField(max_length=32, required=False, allow_blank=True, default="")
    quantity = serializers.IntegerField(min_value=1, max_value=10)


class LoginSerializer(serializers.Serializer):
    username = serializers.CharField()
    password = serializers.CharField()


class RefundRuleTierSerializer(serializers.Serializer):
    hours_before = serializers.IntegerField(min_value=0)
    fee_rate = serializers.DecimalField(
        max_digits=5, decimal_places=4,
        min_value=Decimal("0"), max_value=Decimal("1"),
    )


class RefundRuleSerializer(serializers.ModelSerializer):
    tiers = RefundRuleTierSerializer(many=True)
    show_title = serializers.CharField(source="show.title", read_only=True, default="默认规则")

    class Meta:
        model = RefundRule
        fields = ["id", "show", "show_title", "is_default", "tiers", "created_at", "updated_at"]
        read_only_fields = ["id", "created_at", "updated_at"]

    def validate_tiers(self, value):
        if not value:
            raise serializers.ValidationError("阶梯规则不能为空")
        hours_set = set()
        for tier in value:
            h = tier.get("hours_before")
            if h in hours_set:
                raise serializers.ValidationError(f"存在重复的开演前小时数: {h}")
            hours_set.add(h)
        return value

    def create(self, validated_data):
        from .services import RefundRuleService
        tiers = validated_data.pop("tiers")
        show = validated_data.get("show")
        return RefundRuleService.set_rule(show, tiers)

    def update(self, instance, validated_data):
        from .services import RefundRuleService
        tiers = validated_data.pop("tiers", None)
        show = validated_data.get("show", instance.show)
        if tiers is not None:
            return RefundRuleService.set_rule(show, tiers)
        return instance


class RefundRuleSetSerializer(serializers.Serializer):
    show = serializers.IntegerField(required=False, allow_null=True, default=None)
    tiers = RefundRuleTierSerializer(many=True)


class RefundApplySerializer(serializers.Serializer):
    order = serializers.IntegerField()
    quantity = serializers.IntegerField(min_value=1, max_value=100)
    reason = serializers.CharField(max_length=256, required=False, allow_blank=True, default="")


class RefundProcessSerializer(serializers.Serializer):
    approved = serializers.BooleanField()


class RefundSerializer(serializers.ModelSerializer):
    order_customer = serializers.CharField(source="order.customer_name", read_only=True)
    show_title = serializers.CharField(source="performance.show.title", read_only=True)
    performance_hall = serializers.CharField(source="performance.hall", read_only=True)
    performance_start_at = serializers.DateTimeField(source="performance.start_at", read_only=True)

    class Meta:
        model = Refund
        fields = [
            "id", "order", "order_customer",
            "performance", "show_title", "performance_hall", "performance_start_at",
            "quantity", "original_amount", "fee_rate", "fee_amount", "refund_amount",
            "hours_before_show", "status", "reason", "operator",
            "created_at", "processed_at",
        ]
        read_only_fields = fields


class ExchangeApplySerializer(serializers.Serializer):
    order = serializers.IntegerField()
    to_performance = serializers.IntegerField()
    quantity = serializers.IntegerField(min_value=1, max_value=100)
    remark = serializers.CharField(max_length=256, required=False, allow_blank=True, default="")


class ExchangeSerializer(serializers.ModelSerializer):
    order_customer = serializers.CharField(source="order.customer_name", read_only=True)
    show_title = serializers.CharField(source="from_performance.show.title", read_only=True)
    from_hall = serializers.CharField(source="from_performance.hall", read_only=True)
    from_start_at = serializers.DateTimeField(source="from_performance.start_at", read_only=True)
    to_hall = serializers.CharField(source="to_performance.hall", read_only=True)
    to_start_at = serializers.DateTimeField(source="to_performance.start_at", read_only=True)

    class Meta:
        model = Exchange
        fields = [
            "id", "order", "order_customer", "show_title",
            "from_performance", "from_hall", "from_start_at",
            "to_performance", "to_hall", "to_start_at",
            "quantity", "from_price", "to_price", "price_diff", "diff_settled",
            "operator", "remark", "created_at",
        ]
        read_only_fields = fields


class RefundExchangeLogSerializer(serializers.ModelSerializer):
    order_customer = serializers.CharField(source="order.customer_name", read_only=True)
    log_type_display = serializers.CharField(source="get_log_type_display", read_only=True)

    class Meta:
        model = RefundExchangeLog
        fields = [
            "id", "order", "order_customer", "performance",
            "log_type", "log_type_display", "quantity", "amount",
            "detail", "operator", "created_at",
        ]
        read_only_fields = fields


class PerformanceStatsSerializer(serializers.Serializer):
    performance_id = serializers.IntegerField()
    show_id = serializers.IntegerField()
    show_title = serializers.CharField()
    hall = serializers.CharField()
    start_at = serializers.DateTimeField()
    total_seats = serializers.IntegerField()
    sold_seats = serializers.IntegerField()
    remaining_seats = serializers.IntegerField()
    price = serializers.DecimalField(max_digits=10, decimal_places=2)
    refund_count = serializers.IntegerField()
    refund_pending_count = serializers.IntegerField()
    refund_total_amount = serializers.DecimalField(max_digits=12, decimal_places=2)
    exchange_out_count = serializers.IntegerField()
    exchange_in_count = serializers.IntegerField()
