from django.http import JsonResponse
from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import (
    ExchangeViewSet,
    LoginView,
    OrderViewSet,
    PerformanceViewSet,
    RefundRuleViewSet,
    RefundViewSet,
    ShowViewSet,
    dashboard_stats,
    me,
    performance_stats,
    refund_exchange_logs,
)


def health(_request):
    return JsonResponse({"status": "ok", "service": "show-ticketing-admin"})


router = DefaultRouter(trailing_slash=False)
router.register("shows", ShowViewSet)
router.register("performances", PerformanceViewSet)
router.register("orders", OrderViewSet)
router.register("refund-rules", RefundRuleViewSet, basename="refundrule")
router.register("refunds", RefundViewSet, basename="refund")
router.register("exchanges", ExchangeViewSet, basename="exchange")

urlpatterns = [
    path("health", health),
    path("auth/login", LoginView.as_view()),
    path("auth/me", me),
    path("dashboard/stats", dashboard_stats),
    path("refund-exchange-logs", refund_exchange_logs),
    path("performances/stats", performance_stats),
]

urlpatterns += router.urls
