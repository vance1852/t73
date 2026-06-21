from django.contrib.auth import authenticate
from rest_framework import status, viewsets
from rest_framework.decorators import api_view, permission_classes, action
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken

from .models import (
    Exchange,
    Performance,
    Refund,
    RefundExchangeLog,
    RefundRule,
    Show,
    TicketOrder,
)
from .serializers import (
    ExchangeApplySerializer,
    ExchangeSerializer,
    LoginSerializer,
    OrderCreateSerializer,
    OrderSerializer,
    PerformanceSerializer,
    PerformanceStatsSerializer,
    RefundApplySerializer,
    RefundExchangeLogSerializer,
    RefundProcessSerializer,
    RefundRuleSerializer,
    RefundRuleSetSerializer,
    RefundSerializer,
    ShowSerializer,
)
from .services import (
    ExchangeService,
    RefundRuleService,
    RefundService,
    StatsService,
)


class LoginView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        s = LoginSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        user = authenticate(username=s.validated_data["username"], password=s.validated_data["password"])
        if user is None:
            return Response({"detail": "用户名或密码错误"}, status=status.HTTP_401_UNAUTHORIZED)
        token = RefreshToken.for_user(user)
        return Response({"access_token": str(token.access_token), "token_type": "bearer"})


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def me(request):
    u = request.user
    return Response({"id": u.id, "username": u.username, "display_name": u.get_full_name() or "平台管理员"})


class ShowViewSet(viewsets.ModelViewSet):
    queryset = Show.objects.all().order_by("id")
    serializer_class = ShowSerializer


class PerformanceViewSet(viewsets.ModelViewSet):
    queryset = Performance.objects.select_related("show").all().order_by("start_at")
    serializer_class = PerformanceSerializer


class OrderViewSet(viewsets.ModelViewSet):
    queryset = TicketOrder.objects.select_related("performance", "performance__show").all().order_by("-id")
    http_method_names = ["get", "post"]

    def get_serializer_class(self):
        if self.action == "create":
            return OrderCreateSerializer
        return OrderSerializer

    def create(self, request, *args, **kwargs):
        s = OrderCreateSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        data = s.validated_data
        try:
            perf = Performance.objects.select_related("show").get(pk=data["performance"])
        except Performance.DoesNotExist:
            return Response({"detail": "场次不存在"}, status=status.HTTP_404_NOT_FOUND)

        remaining = perf.total_seats - perf.sold_seats
        if data["quantity"] > remaining:
            return Response({"detail": "余票不足"}, status=status.HTTP_409_CONFLICT)

        order = TicketOrder.objects.create(
            performance=perf,
            customer_name=data["customer_name"],
            phone=data.get("phone", ""),
            quantity=data["quantity"],
            amount=perf.price * data["quantity"],
            status="paid",
        )
        perf.sold_seats += data["quantity"]
        perf.save(update_fields=["sold_seats"])
        return Response(OrderSerializer(order).data, status=status.HTTP_201_CREATED)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def dashboard_stats(request):
    show_total = Show.objects.count()
    show_on_sale = Show.objects.filter(status="on_sale").count()
    perf_total = Performance.objects.count()
    order_paid = TicketOrder.objects.filter(status="paid").count()
    sold = sum(p.sold_seats for p in Performance.objects.all())
    capacity = sum(p.total_seats for p in Performance.objects.all())
    return Response({
        "show_total": show_total,
        "show_on_sale": show_on_sale,
        "performance_total": perf_total,
        "order_paid": order_paid,
        "seats_sold": sold,
        "seats_capacity": capacity,
    })


class RefundRuleViewSet(viewsets.ViewSet):
    permission_classes = [IsAuthenticated]

    def list(self, request):
        qs = RefundRule.objects.select_related("show").all().order_by("-is_default", "id")
        data = RefundRuleSerializer(qs, many=True).data
        return Response(data)

    def retrieve(self, request, pk=None):
        if pk == "default":
            rule = RefundRuleService.get_effective_rule()
        else:
            try:
                rule = RefundRule.objects.select_related("show").get(pk=pk)
            except RefundRule.DoesNotExist:
                return Response({"detail": "规则不存在"}, status=status.HTTP_404_NOT_FOUND)
        return Response(RefundRuleSerializer(rule).data)

    @action(detail=False, methods=["get"], url_path="by-show/(?P<show_id>[^/.]+)")
    def by_show(self, request, show_id=None):
        try:
            show = Show.objects.get(pk=show_id)
        except Show.DoesNotExist:
            return Response({"detail": "演出不存在"}, status=status.HTTP_404_NOT_FOUND)
        rule = RefundRuleService.get_effective_rule(show)
        return Response(RefundRuleSerializer(rule).data)

    def create(self, request):
        s = RefundRuleSetSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        data = s.validated_data
        show = None
        if data.get("show"):
            try:
                show = Show.objects.get(pk=data["show"])
            except Show.DoesNotExist:
                return Response({"detail": "演出不存在"}, status=status.HTTP_404_NOT_FOUND)
        rule = RefundRuleService.set_rule(show, data["tiers"])
        return Response(RefundRuleSerializer(rule).data, status=status.HTTP_201_CREATED)

    def update(self, request, pk=None):
        s = RefundRuleSetSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        data = s.validated_data
        show = None
        if data.get("show"):
            try:
                show = Show.objects.get(pk=data["show"])
            except Show.DoesNotExist:
                return Response({"detail": "演出不存在"}, status=status.HTTP_404_NOT_FOUND)
        rule = RefundRuleService.set_rule(show, data["tiers"])
        return Response(RefundRuleSerializer(rule).data)


class RefundViewSet(viewsets.ViewSet):
    permission_classes = [IsAuthenticated]

    def list(self, request):
        status_filter = request.query_params.get("status")
        perf_id = request.query_params.get("performance")
        order_id = request.query_params.get("order")
        qs = Refund.objects.select_related(
            "order", "performance", "performance__show"
        ).all().order_by("-id")
        if status_filter:
            qs = qs.filter(status=status_filter)
        if perf_id:
            qs = qs.filter(performance_id=perf_id)
        if order_id:
            qs = qs.filter(order_id=order_id)
        return Response(RefundSerializer(qs, many=True).data)

    def retrieve(self, request, pk=None):
        try:
            refund = Refund.objects.select_related(
                "order", "performance", "performance__show"
            ).get(pk=pk)
        except Refund.DoesNotExist:
            return Response({"detail": "退款单不存在"}, status=status.HTTP_404_NOT_FOUND)
        return Response(RefundSerializer(refund).data)

    def create(self, request):
        s = RefundApplySerializer(data=request.data)
        s.is_valid(raise_exception=True)
        data = s.validated_data
        try:
            order = TicketOrder.objects.select_related(
                "performance", "performance__show"
            ).get(pk=data["order"])
        except TicketOrder.DoesNotExist:
            return Response({"detail": "订单不存在"}, status=status.HTTP_404_NOT_FOUND)
        operator = request.user.get_full_name() or request.user.username
        refund, err = RefundService.apply_refund(
            order=order,
            quantity=data["quantity"],
            reason=data.get("reason", ""),
            operator=operator,
        )
        if err:
            return Response({"detail": err}, status=status.HTTP_400_BAD_REQUEST)
        return Response(RefundSerializer(refund).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"], url_path="process")
    def process(self, request, pk=None):
        try:
            refund = Refund.objects.select_related(
                "order", "performance", "performance__show"
            ).get(pk=pk)
        except Refund.DoesNotExist:
            return Response({"detail": "退款单不存在"}, status=status.HTTP_404_NOT_FOUND)
        s = RefundProcessSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        operator = request.user.get_full_name() or request.user.username
        ok, err = RefundService.process_refund(
            refund=refund,
            approved=s.validated_data["approved"],
            operator=operator,
        )
        if not ok:
            return Response({"detail": err}, status=status.HTTP_400_BAD_REQUEST)
        refund.refresh_from_db()
        return Response(RefundSerializer(refund).data)


class ExchangeViewSet(viewsets.ViewSet):
    permission_classes = [IsAuthenticated]

    def list(self, request):
        perf_id = request.query_params.get("performance")
        order_id = request.query_params.get("order")
        qs = Exchange.objects.select_related(
            "order",
            "from_performance", "from_performance__show",
            "to_performance",
        ).all().order_by("-id")
        if perf_id:
            qs = qs.filter(from_performance_id=perf_id) | qs.filter(to_performance_id=perf_id)
        if order_id:
            qs = qs.filter(order_id=order_id)
        return Response(ExchangeSerializer(qs, many=True).data)

    def retrieve(self, request, pk=None):
        try:
            exchange = Exchange.objects.select_related(
                "order",
                "from_performance", "from_performance__show",
                "to_performance",
            ).get(pk=pk)
        except Exchange.DoesNotExist:
            return Response({"detail": "改签记录不存在"}, status=status.HTTP_404_NOT_FOUND)
        return Response(ExchangeSerializer(exchange).data)

    def create(self, request):
        s = ExchangeApplySerializer(data=request.data)
        s.is_valid(raise_exception=True)
        data = s.validated_data
        try:
            order = TicketOrder.objects.select_related(
                "performance", "performance__show"
            ).get(pk=data["order"])
        except TicketOrder.DoesNotExist:
            return Response({"detail": "订单不存在"}, status=status.HTTP_404_NOT_FOUND)
        try:
            to_perf = Performance.objects.select_related("show").get(pk=data["to_performance"])
        except Performance.DoesNotExist:
            return Response({"detail": "目标场次不存在"}, status=status.HTTP_404_NOT_FOUND)
        operator = request.user.get_full_name() or request.user.username
        exchange, err = ExchangeService.apply_exchange(
            order=order,
            to_performance=to_perf,
            quantity=data["quantity"],
            operator=operator,
            remark=data.get("remark", ""),
        )
        if err:
            return Response({"detail": err}, status=status.HTTP_400_BAD_REQUEST)
        return Response(ExchangeSerializer(exchange).data, status=status.HTTP_201_CREATED)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def refund_exchange_logs(request):
    order_id = request.query_params.get("order")
    perf_id = request.query_params.get("performance")
    log_type = request.query_params.get("type")
    qs = RefundExchangeLog.objects.select_related(
        "order", "performance", "performance__show"
    ).all().order_by("-id")
    if order_id:
        qs = qs.filter(order_id=order_id)
    if perf_id:
        qs = qs.filter(performance_id=perf_id)
    if log_type:
        qs = qs.filter(log_type=log_type)
    return Response(RefundExchangeLogSerializer(qs, many=True).data)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def performance_stats(request):
    perf_id = request.query_params.get("performance")
    data = StatsService.performance_stats(
        performance_id=int(perf_id) if perf_id else None
    )
    return Response(PerformanceStatsSerializer(data, many=True).data)
