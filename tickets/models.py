from django.db import models
from django.db.models import JSONField


class Show(models.Model):
    """演出剧目。"""

    GENRE_CHOICES = [
        ("concert", "演唱会"),
        ("drama", "话剧"),
        ("musical", "音乐剧"),
        ("opera", "戏曲"),
        ("other", "其他"),
    ]
    STATUS_CHOICES = [
        ("on_sale", "售票中"),
        ("upcoming", "待开票"),
        ("ended", "已结束"),
    ]

    title = models.CharField(max_length=128)
    troupe = models.CharField(max_length=128, blank=True, default="")
    genre = models.CharField(max_length=16, choices=GENRE_CHOICES, default="concert")
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default="upcoming")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "shows"


class Performance(models.Model):
    """场次。"""

    show = models.ForeignKey(Show, on_delete=models.CASCADE, related_name="performances")
    hall = models.CharField(max_length=64, default="")
    start_at = models.DateTimeField()
    total_seats = models.IntegerField(default=0)
    sold_seats = models.IntegerField(default=0)
    price = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "performances"


class TicketOrder(models.Model):
    """购票订单。"""

    STATUS_CHOICES = [
        ("paid", "已支付"),
        ("cancelled", "已取消"),
        ("refunded", "已退票"),
        ("partially_refunded", "部分退票"),
        ("exchanged", "已改签"),
    ]

    performance = models.ForeignKey(Performance, on_delete=models.CASCADE, related_name="orders")
    customer_name = models.CharField(max_length=64)
    phone = models.CharField(max_length=32, blank=True, default="")
    quantity = models.IntegerField(default=1)
    amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    status = models.CharField(max_length=32, choices=STATUS_CHOICES, default="paid")
    exchange_count = models.IntegerField(default=0)
    has_exchanged = models.BooleanField(default=False)
    original_order = models.ForeignKey(
        "self", on_delete=models.SET_NULL, null=True, blank=True, related_name="exchange_children"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "ticket_orders"


class RefundRule(models.Model):
    """退票规则（按演出配置，未配置则用默认规则）。"""

    show = models.OneToOneField(Show, on_delete=models.CASCADE, related_name="refund_rule", null=True, blank=True)
    is_default = models.BooleanField(default=False)
    tiers = JSONField(
        default=list,
        help_text="阶梯规则列表，每项包含 hours_before(开演前小时数) 和 fee_rate(手续费率0-1)，按 hours_before 降序排列",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "refund_rules"


class Refund(models.Model):
    """退款单。"""

    STATUS_CHOICES = [
        ("pending", "待处理"),
        ("refunded", "已退款"),
        ("rejected", "已拒绝"),
    ]

    order = models.ForeignKey(TicketOrder, on_delete=models.CASCADE, related_name="refunds")
    performance = models.ForeignKey(Performance, on_delete=models.CASCADE, related_name="refunds")
    quantity = models.IntegerField(default=1)
    original_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    fee_rate = models.DecimalField(max_digits=5, decimal_places=4, default=0)
    fee_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    refund_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    hours_before_show = models.IntegerField(default=0, help_text="申请退票时距开演的小时数")
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default="pending")
    reason = models.CharField(max_length=256, blank=True, default="")
    operator = models.CharField(max_length=64, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    processed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "refunds"


class Exchange(models.Model):
    """改签记录。"""

    order = models.ForeignKey(TicketOrder, on_delete=models.CASCADE, related_name="exchanges")
    from_performance = models.ForeignKey(
        Performance, on_delete=models.CASCADE, related_name="exchanges_from"
    )
    to_performance = models.ForeignKey(
        Performance, on_delete=models.CASCADE, related_name="exchanges_to"
    )
    quantity = models.IntegerField(default=1)
    from_price = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    to_price = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    price_diff = models.DecimalField(max_digits=12, decimal_places=2, default=0, help_text="正数需补款，负数需退款")
    diff_settled = models.BooleanField(default=False)
    operator = models.CharField(max_length=64, blank=True, default="")
    remark = models.CharField(max_length=256, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "exchanges"


class RefundExchangeLog(models.Model):
    """退改签流水。"""

    TYPE_CHOICES = [
        ("refund_apply", "申请退票"),
        ("refund_process", "处理退款"),
        ("exchange", "改签"),
    ]

    order = models.ForeignKey(TicketOrder, on_delete=models.CASCADE, related_name="logs")
    performance = models.ForeignKey(Performance, on_delete=models.CASCADE, related_name="logs")
    log_type = models.CharField(max_length=32, choices=TYPE_CHOICES)
    quantity = models.IntegerField(default=0)
    amount = models.DecimalField(max_digits=12, decimal_places=2, default=0, help_text="涉及金额：退票退款额/改签差价")
    detail = JSONField(default=dict, blank=True)
    operator = models.CharField(max_length=64, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "refund_exchange_logs"
