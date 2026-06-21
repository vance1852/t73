"""退票改签核心业务服务。"""
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional, Tuple

from django.db import transaction
from django.utils import timezone

from .models import (
    Exchange,
    Performance,
    Refund,
    RefundExchangeLog,
    RefundRule,
    Show,
    TicketOrder,
)

DEFAULT_REFUND_TIERS = [
    {"hours_before": 72, "fee_rate": 0.10},
    {"hours_before": 24, "fee_rate": 0.30},
    {"hours_before": 0, "fee_rate": 1.00},
]


class RefundRuleService:
    """退票规则服务。"""

    @staticmethod
    def get_effective_rule(show: Optional[Show] = None) -> RefundRule:
        """获取生效的退票规则：优先演出配置，否则默认规则。"""
        if show is not None:
            try:
                return show.refund_rule
            except RefundRule.DoesNotExist:
                pass
        rule, _ = RefundRule.objects.get_or_create(
            is_default=True,
            show=None,
            defaults={"tiers": DEFAULT_REFUND_TIERS},
        )
        return rule

    @staticmethod
    def set_rule(show: Optional[Show], tiers: list) -> RefundRule:
        """设置退票规则。tiers 格式：[{"hours_before": 72, "fee_rate": 0.10}, ...]"""
        normalized = []
        for tier in tiers:
            rate = tier["fee_rate"]
            if isinstance(rate, Decimal):
                rate = float(rate)
            normalized.append({"hours_before": int(tier["hours_before"]), "fee_rate": rate})
        sorted_tiers = sorted(normalized, key=lambda t: -t["hours_before"])
        if show is None:
            rule, _ = RefundRule.objects.update_or_create(
                is_default=True,
                show=None,
                defaults={"tiers": sorted_tiers},
            )
        else:
            rule, _ = RefundRule.objects.update_or_create(
                show=show,
                defaults={"tiers": sorted_tiers, "is_default": False},
            )
        return rule

    @staticmethod
    def calculate_fee(
        performance: Performance,
        apply_at: Optional[datetime] = None,
        show: Optional[Show] = None,
    ) -> Tuple[Decimal, int, bool]:
        """
        计算退票手续费率。
        返回: (fee_rate, hours_before, refundable)
        - refundable=False 表示 24 小时内不可退
        """
        if apply_at is None:
            apply_at = timezone.now()
        delta = performance.start_at - apply_at
        total_seconds = delta.total_seconds()
        hours_before = int(total_seconds // 3600) if total_seconds > 0 else 0

        if total_seconds <= 0:
            return Decimal("1"), 0, False

        rule = RefundRuleService.get_effective_rule(show or performance.show)
        tiers = rule.tiers or DEFAULT_REFUND_TIERS
        tiers_sorted = sorted(tiers, key=lambda t: -t["hours_before"])

        fee_rate = Decimal("1")
        for tier in tiers_sorted:
            if hours_before >= tier["hours_before"]:
                fee_rate = Decimal(str(tier["fee_rate"]))
                break

        if hours_before < 24:
            return fee_rate, hours_before, False

        return fee_rate.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP), hours_before, True


class RefundService:
    """退票服务。"""

    @staticmethod
    @transaction.atomic
    def apply_refund(
        order: TicketOrder,
        quantity: int,
        reason: str = "",
        operator: str = "",
    ) -> Tuple[Optional[Refund], str]:
        """
        申请退票。
        返回: (refund对象或None, 错误信息)
        """
        if order.status in ("cancelled",):
            return None, "订单已取消，无法退票"
        if order.status == "refunded":
            return None, "订单已完成退票，不能重复申请"
        if order.status == "exchanged":
            return None, "已改签的订单不能退票"

        if quantity <= 0:
            return None, "退票数量必须大于0"

        refunded_total = Refund.objects.filter(
            order=order, status__in=("pending", "refunded")
        ).aggregate(total=models_sum("quantity"))["total"] or 0

        remaining = order.quantity - refunded_total
        if quantity > remaining:
            return None, f"可退票数量不足，剩余可退 {remaining} 张"

        fee_rate, hours_before, refundable = RefundRuleService.calculate_fee(order.performance)
        if not refundable:
            if hours_before <= 0:
                return None, "演出已开始，不可退票"
            return None, "距开演不足24小时，不可退票"

        unit_price = order.amount / order.quantity if order.quantity > 0 else Decimal("0")
        original_amount = (unit_price * quantity).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        fee_amount = (original_amount * fee_rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        refund_amount = (original_amount - fee_amount).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

        refund = Refund.objects.create(
            order=order,
            performance=order.performance,
            quantity=quantity,
            original_amount=original_amount,
            fee_rate=fee_rate,
            fee_amount=fee_amount,
            refund_amount=refund_amount,
            hours_before_show=hours_before,
            status="pending",
            reason=reason,
            operator=operator,
        )

        RefundExchangeLog.objects.create(
            order=order,
            performance=order.performance,
            log_type="refund_apply",
            quantity=quantity,
            amount=refund_amount,
            detail={
                "refund_id": refund.id,
                "original_amount": str(original_amount),
                "fee_rate": str(fee_rate),
                "fee_amount": str(fee_amount),
                "hours_before_show": hours_before,
                "reason": reason,
            },
            operator=operator,
        )
        return refund, ""

    @staticmethod
    @transaction.atomic
    def process_refund(
        refund: Refund,
        approved: bool,
        operator: str = "",
    ) -> Tuple[bool, str]:
        """
        处理退款单：批准则退款并回补库存，拒绝则关闭退款单。
        """
        if refund.status != "pending":
            return False, "退款单非待处理状态"

        if approved:
            perf = refund.performance
            perf.sold_seats = max(0, perf.sold_seats - refund.quantity)
            perf.save(update_fields=["sold_seats"])

            refund.status = "refunded"
            refund.processed_at = timezone.now()
            refund.operator = operator
            refund.save(update_fields=["status", "processed_at", "operator"])

            order = refund.order
            total_refunded = Refund.objects.filter(
                order=order, status="refunded"
            ).aggregate(total=models_sum("quantity"))["total"] or 0
            if total_refunded >= order.quantity:
                order.status = "refunded"
            else:
                order.status = "partially_refunded"
            order.save(update_fields=["status"])

            RefundExchangeLog.objects.create(
                order=order,
                performance=perf,
                log_type="refund_process",
                quantity=refund.quantity,
                amount=refund.refund_amount,
                detail={
                    "refund_id": refund.id,
                    "action": "approved",
                    "fee_amount": str(refund.fee_amount),
                },
                operator=operator,
            )
        else:
            refund.status = "rejected"
            refund.processed_at = timezone.now()
            refund.operator = operator
            refund.save(update_fields=["status", "processed_at", "operator"])

            RefundExchangeLog.objects.create(
                order=refund.order,
                performance=refund.performance,
                log_type="refund_process",
                quantity=refund.quantity,
                amount=Decimal("0"),
                detail={
                    "refund_id": refund.id,
                    "action": "rejected",
                },
                operator=operator,
            )
        return True, ""


def models_sum(field):
    from django.db.models import Sum
    return Sum(field)


class ExchangeService:
    """改签服务。"""

    @staticmethod
    def _check_show_started(perf: Performance) -> bool:
        return timezone.now() >= perf.start_at

    @staticmethod
    @transaction.atomic
    def apply_exchange(
        order: TicketOrder,
        to_performance: Performance,
        quantity: int,
        operator: str = "",
        remark: str = "",
    ) -> Tuple[Optional[Exchange], str]:
        """
        申请改签（同一演出的其他场次）。
        每张票最多改签一次。
        """
        if order.status in ("cancelled", "refunded"):
            return None, "订单已取消或已退票，不可改签"

        if order.has_exchanged or order.exchange_count >= 1:
            return None, "该订单已改签过，不可再次改签"

        if order.status == "exchanged":
            return None, "订单已改签，不可重复改签"

        if quantity <= 0 or quantity > order.quantity:
            return None, f"改签数量不合法，最多可改签 {order.quantity} 张"

        from_perf = order.performance

        if from_perf.show_id != to_performance.show_id:
            return None, "改签仅支持同一演出的其他场次"

        if from_perf.id == to_performance.id:
            return None, "目标场次不能与原场次相同"

        if ExchangeService._check_show_started(from_perf):
            return None, "原场次已开演，不可改签"

        if ExchangeService._check_show_started(to_performance):
            return None, "目标场次已开演，不可改签"

        to_remaining = to_performance.total_seats - to_performance.sold_seats
        if quantity > to_remaining:
            return None, f"目标场次余票不足，仅剩 {to_remaining} 张"

        from_price = from_perf.price
        to_price = to_performance.price
        diff_per_ticket = to_price - from_price
        price_diff = (diff_per_ticket * quantity).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

        from_perf.sold_seats = max(0, from_perf.sold_seats - quantity)
        from_perf.save(update_fields=["sold_seats"])

        to_performance.sold_seats += quantity
        to_performance.save(update_fields=["sold_seats"])

        exchange = Exchange.objects.create(
            order=order,
            from_performance=from_perf,
            to_performance=to_performance,
            quantity=quantity,
            from_price=from_price,
            to_price=to_price,
            price_diff=price_diff,
            diff_settled=(price_diff == 0),
            operator=operator,
            remark=remark,
        )

        order.has_exchanged = True
        order.exchange_count += 1
        if quantity >= order.quantity:
            order.status = "exchanged"
            order.performance = to_performance
        else:
            pass
        order.save(update_fields=["has_exchanged", "exchange_count", "status", "performance"])

        if quantity >= order.quantity:
            old_amount = order.amount
            new_amount = (to_price * order.quantity).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            if new_amount != old_amount:
                order.amount = new_amount
                order.save(update_fields=["amount"])

        RefundExchangeLog.objects.create(
            order=order,
            performance=to_performance,
            log_type="exchange",
            quantity=quantity,
            amount=price_diff,
            detail={
                "exchange_id": exchange.id,
                "from_performance_id": from_perf.id,
                "from_performance_hall": from_perf.hall,
                "from_performance_start_at": from_perf.start_at.strftime("%Y-%m-%d %H:%M:%S"),
                "to_performance_id": to_performance.id,
                "to_performance_hall": to_performance.hall,
                "to_performance_start_at": to_performance.start_at.strftime("%Y-%m-%d %H:%M:%S"),
                "from_price": str(from_price),
                "to_price": str(to_price),
                "price_diff": str(price_diff),
                "remark": remark,
            },
            operator=operator,
        )
        return exchange, ""


class StatsService:
    """场次退改统计服务。"""

    @staticmethod
    def performance_stats(performance_id: Optional[int] = None):
        from django.db.models import Sum, Count, Q, IntegerField
        from django.db.models.functions import Coalesce

        qs = Performance.objects.select_related("show").all()
        if performance_id is not None:
            qs = qs.filter(id=performance_id)

        result = []
        for perf in qs:
            refunded_qty = (
                Refund.objects.filter(performance=perf, status="refunded")
                .aggregate(total=Coalesce(Sum("quantity"), 0))["total"]
            )
            refund_pending_qty = (
                Refund.objects.filter(performance=perf, status="pending")
                .aggregate(total=Coalesce(Sum("quantity"), 0))["total"]
            )
            refund_total_amount = (
                Refund.objects.filter(performance=perf, status="refunded")
                .aggregate(total=Coalesce(Sum("refund_amount"), Decimal("0")))["total"]
            )
            exchange_from = (
                Exchange.objects.filter(from_performance=perf)
                .aggregate(total=Coalesce(Sum("quantity"), 0))["total"]
            )
            exchange_to = (
                Exchange.objects.filter(to_performance=perf)
                .aggregate(total=Coalesce(Sum("quantity"), 0))["total"]
            )
            remaining = perf.total_seats - perf.sold_seats

            result.append({
                "performance_id": perf.id,
                "show_id": perf.show_id,
                "show_title": perf.show.title,
                "hall": perf.hall,
                "start_at": perf.start_at,
                "total_seats": perf.total_seats,
                "sold_seats": perf.sold_seats,
                "remaining_seats": remaining,
                "price": perf.price,
                "refund_count": int(refunded_qty),
                "refund_pending_count": int(refund_pending_qty),
                "refund_total_amount": refund_total_amount,
                "exchange_out_count": int(exchange_from),
                "exchange_in_count": int(exchange_to),
            })
        return result
