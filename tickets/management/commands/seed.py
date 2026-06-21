"""初始化内置管理员与种子业务数据（幂等）。"""
from datetime import datetime, timedelta

from django.conf import settings
from django.contrib.auth.models import User
from django.core.management.base import BaseCommand

from tickets.models import Performance, RefundRule, Show, TicketOrder


class Command(BaseCommand):
    help = "初始化管理员与演出票务种子数据"

    def handle(self, *args, **options):
        username = settings.DEFAULT_ADMIN_USERNAME
        password = settings.DEFAULT_ADMIN_PASSWORD
        if not User.objects.filter(username=username).exists():
            User.objects.create_superuser(username=username, password=password, first_name="平台管理员")
            self.stdout.write("已创建管理员账号")

        if Show.objects.exists():
            self.stdout.write("业务数据已存在，跳过")
            return

        shows = [
            Show.objects.create(title="星河巡回演唱会", troupe="星河乐团", genre="concert", status="on_sale"),
            Show.objects.create(title="金陵往事话剧", troupe="城南剧社", genre="drama", status="on_sale"),
            Show.objects.create(title="敦煌音乐剧", troupe="丝路艺术团", genre="musical", status="upcoming"),
            Show.objects.create(title="经典戏曲专场", troupe="梨园名家", genre="opera", status="ended"),
        ]

        now = datetime.now().replace(microsecond=0)

        perfs = []
        concert = shows[0]
        drama = shows[1]
        musical = shows[2]
        opera = shows[3]

        perfs.append(Performance.objects.create(
            show=concert, hall="一号厅",
            start_at=now + timedelta(days=10),
            total_seats=1200, sold_seats=600, price=380,
        ))
        perfs.append(Performance.objects.create(
            show=concert, hall="一号厅",
            start_at=now + timedelta(days=5),
            total_seats=1200, sold_seats=860, price=420,
        ))
        perfs.append(Performance.objects.create(
            show=concert, hall="一号厅",
            start_at=now + timedelta(hours=48),
            total_seats=1200, sold_seats=920, price=480,
        ))
        perfs.append(Performance.objects.create(
            show=concert, hall="一号厅",
            start_at=now + timedelta(hours=36),
            total_seats=1200, sold_seats=1100, price=480,
        ))
        perfs.append(Performance.objects.create(
            show=concert, hall="一号厅",
            start_at=now + timedelta(hours=12),
            total_seats=1200, sold_seats=1180, price=580,
        ))
        perfs.append(Performance.objects.create(
            show=concert, hall="一号厅",
            start_at=now - timedelta(hours=2),
            total_seats=1200, sold_seats=1200, price=580,
        ))
        perfs.append(Performance.objects.create(
            show=drama, hall="小剧场",
            start_at=now + timedelta(days=8),
            total_seats=300, sold_seats=150, price=180,
        ))
        perfs.append(Performance.objects.create(
            show=drama, hall="小剧场",
            start_at=now + timedelta(days=2),
            total_seats=300, sold_seats=290, price=180,
        ))
        perfs.append(Performance.objects.create(
            show=drama, hall="小剧场",
            start_at=now + timedelta(hours=30),
            total_seats=300, sold_seats=295, price=200,
        ))
        perfs.append(Performance.objects.create(
            show=musical, hall="大剧院",
            start_at=now + timedelta(days=20),
            total_seats=900, sold_seats=0, price=280,
        ))
        perfs.append(Performance.objects.create(
            show=musical, hall="大剧院",
            start_at=now + timedelta(days=21),
            total_seats=900, sold_seats=40, price=320,
        ))
        perfs.append(Performance.objects.create(
            show=opera, hall="戏曲厅",
            start_at=now - timedelta(days=5),
            total_seats=500, sold_seats=480, price=160,
        ))

        TicketOrder.objects.create(
            performance=perfs[0], customer_name="陈静", phone="13900001111",
            quantity=2, amount=760, status="paid",
        )
        TicketOrder.objects.create(
            performance=perfs[1], customer_name="刘洋", phone="13900002222",
            quantity=4, amount=1680, status="paid",
        )
        TicketOrder.objects.create(
            performance=perfs[1], customer_name="孙琳", phone="13900003333",
            quantity=1, amount=420, status="cancelled",
        )
        TicketOrder.objects.create(
            performance=perfs[2], customer_name="周明", phone="13900004444",
            quantity=3, amount=1440, status="paid",
        )
        TicketOrder.objects.create(
            performance=perfs[3], customer_name="吴芳", phone="13900005555",
            quantity=2, amount=960, status="paid",
        )
        TicketOrder.objects.create(
            performance=perfs[4], customer_name="郑伟", phone="13900006666",
            quantity=1, amount=580, status="paid",
        )
        TicketOrder.objects.create(
            performance=perfs[6], customer_name="王磊", phone="13900007777",
            quantity=5, amount=900, status="paid",
        )
        TicketOrder.objects.create(
            performance=perfs[7], customer_name="李娜", phone="13900008888",
            quantity=2, amount=360, status="paid",
        )
        TicketOrder.objects.create(
            performance=perfs[9], customer_name="赵强", phone="13900009999",
            quantity=3, amount=840, status="paid",
        )
        TicketOrder.objects.create(
            performance=perfs[10], customer_name="钱丽", phone="13900001010",
            quantity=2, amount=640, status="paid",
        )

        RefundRule.objects.create(
            is_default=True, show=None,
            tiers=[
                {"hours_before": 72, "fee_rate": 0.10},
                {"hours_before": 24, "fee_rate": 0.30},
                {"hours_before": 0, "fee_rate": 1.00},
            ],
        )
        RefundRule.objects.create(
            is_default=False, show=drama,
            tiers=[
                {"hours_before": 168, "fee_rate": 0.05},
                {"hours_before": 72, "fee_rate": 0.15},
                {"hours_before": 24, "fee_rate": 0.35},
                {"hours_before": 0, "fee_rate": 1.00},
            ],
        )

        self.stdout.write("种子数据初始化完成")
        self.stdout.write(
            f" - 演出: {Show.objects.count()} 场, "
            f"场次: {Performance.objects.count()} 场, "
            f"订单: {TicketOrder.objects.filter(status='paid').count()} 笔已支付"
        )
        self.stdout.write(
            f" - 星河演唱会场次说明: "
            f"P1(10天后/380元/退10%) "
            f"P2(5天后/420元/退10%) "
            f"P3(48h后/480元/退30%) "
            f"P4(36h后/480元/退30%) "
            f"P5(12h后/580元/不可退) "
            f"P6(已开演/不可退改)"
        )
