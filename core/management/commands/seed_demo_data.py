import random
import secrets
import uuid
from datetime import datetime, timedelta
from decimal import Decimal

from django.contrib.auth.hashers import PBKDF2PasswordHasher
from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Count, F, Sum
from faker import Faker


class FastPBKDF2PasswordHasher(PBKDF2PasswordHasher):
    iterations = 1

from accounts.models import User
from analytics.models import Event, Session
from orders.models import Customer, Order, OrderItem
from products.models import Category, Product


class Command(BaseCommand):
    help = "Seed realistic demo data for Overview, Analytics, and Revenue Report"

    def add_arguments(self, parser):
        parser.add_argument("--users", type=int, default=500)
        parser.add_argument("--sessions", type=int, default=8000)
        parser.add_argument("--events", type=int, default=30000)
        parser.add_argument("--orders", type=int, default=1000)
        parser.add_argument("--order-items", type=int, default=3000)

    def handle(self, *args, **options):
        self.fake = Faker("vi_VN")
        self.now = datetime.now()
        self.start_dt = self.now - timedelta(days=365)
        self.verbosity = options.get("verbosity", 1)

        self.stdout.write(self.style.NOTICE("Starting demo data seeding..."))

        with transaction.atomic():
            self._load_metadata()
            self._seed_users(options["users"])
            self._seed_sessions(options["sessions"])
            self._seed_events_and_orders(options["events"], options["orders"], options["order_items"])

        self._print_summary()

    # ------------------------------------------------------------------
    # Metadata
    # ------------------------------------------------------------------
    def _load_metadata(self):
        self.products = list(
            Product.objects.filter(is_active=True, deleted_at__isnull=True)
            .select_related("category", "brand")
        )
        if not self.products:
            raise ValueError("No active products found. Please seed products first.")

        self.categories = {c.name: c for c in Category.objects.all()}
        self.category_weights = {
            "Chuột": 0.35,
            "Bàn phím": 0.25,
            "Tai nghe": 0.20,
            "Microphone": 0.12,
            "Tay cầm": 0.08,
        }

        self.hot_keywords = [
            "g502", "deathadder", "g pro x", "superlight", "keychron",
            "blackwidow", "viper", "g305", "g715", "k8",
        ]

        self.product_weights = []
        for p in self.products:
            cat_weight = self.category_weights.get(p.category.name, 0.10)
            is_hot = any(k in p.name.lower() for k in self.hot_keywords)
            hot_multiplier = 3.0 if is_hot else 1.0
            self.product_weights.append(cat_weight * hot_multiplier)

        self.existing_emails = set(User.objects.values_list("email", flat=True))
        self.existing_order_codes = set(Order.objects.values_list("order_code", flat=True))

        self.provinces = [
            ("01", "Hà Nội"), ("79", "TP. Hồ Chí Minh"), ("48", "Đà Nẵng"),
            ("92", "Cần Thơ"), ("31", "Hải Phòng"), ("89", "An Giang"),
            ("77", "Bà Rịa - Vũng Tàu"), ("95", "Bạc Liêu"), ("35", "Bắc Giang"),
            ("37", "Bắc Ninh"), ("20", "Lạng Sơn"), ("22", "Quảng Ninh"),
            ("25", "Phú Thọ"), ("26", "Vĩnh Phúc"), ("28", "Thái Nguyên"),
            ("30", "Hải Dương"), ("33", "Hưng Yên"), ("34", "Thái Bình"),
            ("36", "Hòa Bình"), ("40", "Ninh Bình"), ("42", "Thanh Hóa"),
            ("44", "Nghệ An"), ("45", "Hà Tĩnh"), ("47", "Quảng Trị"),
            ("49", "Thừa Thiên Huế"), ("51", "Quảng Nam"), ("52", "Quảng Ngãi"),
            ("54", "Bình Định"), ("56", "Phú Yên"), ("58", "Khánh Hòa"),
            ("62", "Bình Thuận"), ("66", "Đắk Lắk"), ("75", "Đồng Nai"),
            ("80", "Long An"), ("82", "Tiền Giang"), ("84", "Trà Vinh"),
        ]

        self.wards = [
            "Phường Bến Nghé", "Phường Tân Định", "Phường Cầu Giấy",
            "Phường Hoàn Kiếm", "Phường Hải Châu", "Phường Lê Lợi",
            "Phường Trần Hưng Đạo", "Phường Nguyễn Văn Cừ", "Phường Mỹ Đình",
            "Phường An Khánh", "Phường Thảo Điền", "Phường Phú Mỹ",
        ]

        self.user_agents = [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0 Safari/537.36",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/119.0 Safari/537.36",
            "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1 Mobile/15E148",
            "Mozilla/5.0 (Linux; Android 13; SM-S918B) AppleWebKit/537.36 Chrome/118.0 Mobile/15E148",
            "Mozilla/5.0 (iPad; CPU OS 16_5 like Mac OS X) AppleWebKit/605.1 Mobile/15E148",
        ]

    def _random_dt(self, start=None, end=None):
        start = start or self.start_dt
        end = end or self.now
        delta = end - start
        return start + timedelta(seconds=random.randint(0, int(delta.total_seconds())))

    def _phone_vn(self):
        return f"0{random.choice(['3', '5', '7', '8', '9'])}{random.randint(10000000, 99999999)}"

    def _address(self):
        province_code, province_name = random.choice(self.provinces)
        ward_name = random.choice(self.wards)
        street = self.fake.street_address()
        return province_code, province_name, ward_name, street

    def _unique_email(self, index):
        for _ in range(1000):
            candidate = f"demo{index}_{secrets.token_hex(3)}@example.com"
            if candidate not in self.existing_emails:
                self.existing_emails.add(candidate)
                return candidate
        raise RuntimeError("Cannot generate unique email")

    def _unique_order_code(self):
        for _ in range(1000):
            candidate = f"ORD{random.randint(100000000, 999999999)}"
            if candidate not in self.existing_order_codes:
                self.existing_order_codes.add(candidate)
                return candidate
        raise RuntimeError("Cannot generate unique order code")

    def _pick_product(self):
        return random.choices(self.products, weights=self.product_weights, k=1)[0]

    # ------------------------------------------------------------------
    # Users + Customers
    # ------------------------------------------------------------------
    def _seed_users(self, target):
        # Ensure existing users have a Customer profile (idempotent safety net)
        existing_without_customer = list(User.objects.filter(customer_profile__isnull=True))
        if existing_without_customer:
            customers_to_create = []
            for user in existing_without_customer:
                customer = Customer(
                    user=user,
                    full_name=user.name,
                    email=user.email,
                    phone=user.phone,
                )
                joined = user.date_joined or self._random_dt()
                customer.created_at = joined
                customer.updated_at = joined
                customer._desired_created_at = joined
                customers_to_create.append(customer)
            Customer.objects.bulk_create(customers_to_create, batch_size=500)
            for customer in customers_to_create:
                customer.created_at = customer._desired_created_at
                customer.updated_at = customer._desired_created_at
            Customer.objects.bulk_update(
                customers_to_create, ["created_at", "updated_at"], batch_size=500
            )
            self.stdout.write(
                self.style.SUCCESS(
                    f"Created {len(customers_to_create)} customers for existing users"
                )
            )

        users = []
        customers = []
        created_ats = []
        start_index = User.objects.count() + 1
        hasher = FastPBKDF2PasswordHasher()
        password = hasher.encode("password123", hasher.salt())

        for i in range(target):
            idx = start_index + i
            name = self.fake.name()
            email = self._unique_email(idx)
            phone = self._phone_vn()
            province_code, province_name, ward_name, street = self._address()
            created_at = self._random_dt()
            last_login_at = self._random_dt(created_at, self.now) if random.random() > 0.2 else None

            user = User(
                email=email,
                name=name,
                phone=phone,
                province_code=province_code,
                province_name=province_name,
                ward_code="0",
                ward_name=ward_name,
                street_address=street,
                password=password,
                is_active=True,
                is_staff=False,
                is_superuser=False,
                last_login_at=last_login_at,
                date_joined=created_at,
            )
            users.append(user)
            created_ats.append(created_at)

        User.objects.bulk_create(users, batch_size=500)

        for user, created_at in zip(users, created_ats):
            customer = Customer(
                user=user,
                full_name=user.name,
                email=user.email,
                phone=user.phone,
            )
            customer.created_at = created_at
            customer.updated_at = created_at
            customer._desired_created_at = created_at
            customers.append(customer)

        Customer.objects.bulk_create(customers, batch_size=500)
        for customer in customers:
            customer.created_at = customer._desired_created_at
            customer.updated_at = customer._desired_created_at
        Customer.objects.bulk_update(
            customers, ["created_at", "updated_at"], batch_size=500
        )
        self.stdout.write(self.style.SUCCESS(f"Created {len(users)} users and {len(customers)} customers"))

    # ------------------------------------------------------------------
    # Sessions
    # ------------------------------------------------------------------
    def _seed_sessions(self, target):
        self.all_users = list(User.objects.filter(is_superuser=False, is_staff=False))
        self.sessions = []
        device_pool = ["desktop"] * 65 + ["mobile"] * 30 + ["tablet"] * 5

        for _ in range(target):
            is_user_session = random.random() < 0.60
            user = random.choice(self.all_users) if is_user_session and self.all_users else None
            created_at = self._random_dt()

            session = Session(
                id=str(uuid.uuid4()),
                user=user,
                ip_address=f"{random.randint(1, 223)}.{random.randint(0, 255)}.{random.randint(0, 255)}.{random.randint(1, 254)}",
                user_agent=random.choice(self.user_agents),
                device_type=random.choice(device_pool),
            )
            session.created_at = created_at
            session.updated_at = created_at
            session._desired_created_at = created_at
            self.sessions.append(session)

        Session.objects.bulk_create(self.sessions, batch_size=1000)
        for session in self.sessions:
            session.created_at = session._desired_created_at
            session.updated_at = session._desired_created_at
        Session.objects.bulk_update(
            self.sessions, ["created_at", "updated_at"], batch_size=1000
        )
        self.stdout.write(self.style.SUCCESS(f"Created {len(self.sessions)} sessions"))

    # ------------------------------------------------------------------
    # Events + Orders
    # ------------------------------------------------------------------
    def _seed_events_and_orders(self, target_events, target_orders, target_items):
        # Only process sessions created in this run to keep command idempotent
        self.all_sessions = list(self.sessions)
        total_sessions = len(self.all_sessions)

        # Funnel distribution aimed at ~1000 orders and ~30000 events
        # Type D = user sessions that become orders (checkout + order)
        # Type C = checkout but no order
        # Type B = add cart (possibly remove)
        # Type A = view only
        user_sessions = [s for s in self.all_sessions if s.user]
        guest_sessions = [s for s in self.all_sessions if not s.user]

        n_d = min(target_orders, len(user_sessions))
        n_c = min(1400, total_sessions - n_d)
        n_b = min(2000, total_sessions - n_d - n_c)
        n_a = total_sessions - n_d - n_c - n_b

        random.shuffle(user_sessions)
        random.shuffle(guest_sessions)

        type_d_sessions = user_sessions[:n_d]
        remaining_sessions = user_sessions[n_d:] + guest_sessions
        random.shuffle(remaining_sessions)

        type_c_sessions = remaining_sessions[:n_c]
        type_b_sessions = remaining_sessions[n_c : n_c + n_b]
        type_a_sessions = remaining_sessions[n_c + n_b :]

        self.events = []
        self.orders = []
        self.order_items = []
        self.order_count = 0

        for session in type_a_sessions:
            self._build_view_only_session(session)
        for session in type_b_sessions:
            self._build_cart_session(session)
        for session in type_c_sessions:
            self._build_checkout_session(session, create_order=False)
        for session in type_d_sessions:
            self._build_checkout_session(session, create_order=True)

        # Add click events to reach target event count
        current_events = len(self.events)
        if current_events < target_events:
            self._add_clicks(target_events - current_events)

        Event.objects.bulk_create(self.events, batch_size=1000)
        for evt in self.events:
            evt.created_at = evt._desired_created_at
            evt.updated_at = evt._desired_created_at
        Event.objects.bulk_update(
            self.events, ["created_at", "updated_at"], batch_size=1000
        )

        Order.objects.bulk_create(self.orders, batch_size=500)
        for order in self.orders:
            order.created_at = order._desired_created_at
            order.updated_at = order._desired_created_at
        Order.objects.bulk_update(
            self.orders, ["created_at", "updated_at", "total_price"], batch_size=500
        )

        OrderItem.objects.bulk_create(self.order_items, batch_size=500)
        for item in self.order_items:
            item.created_at = item._desired_created_at
            item.updated_at = item._desired_created_at
        OrderItem.objects.bulk_update(
            self.order_items, ["created_at", "updated_at"], batch_size=500
        )

        self.stdout.write(self.style.SUCCESS(f"Created {len(self.events)} events, {len(self.orders)} orders, {len(self.order_items)} order items"))

    # ------------------------------------------------------------------
    # Funnel builders
    # ------------------------------------------------------------------
    def _make_event(self, session, event_type, product, event_value=None, seconds_offset=0):
        created_at = session.created_at + timedelta(seconds=seconds_offset)
        evt = Event(
            user=session.user,
            session=session,
            event_type=event_type,
            product=product,
            event_value=event_value or Decimal("0.00"),
            metadata={},
        )
        evt.created_at = created_at
        evt.updated_at = created_at
        evt._desired_created_at = created_at
        self.events.append(evt)
        return evt

    def _build_view_only_session(self, session):
        view_count = random.randint(2, 5)
        for i in range(view_count):
            product = self._pick_product()
            self._make_event(session, "view_product", product, seconds_offset=i * 45)

    def _build_cart_session(self, session):
        views = random.randint(1, 3)
        offset = 0
        for i in range(views):
            product = self._pick_product()
            self._make_event(session, "view_product", product, seconds_offset=offset)
            offset += random.randint(30, 90)

        cart_product = self._pick_product()
        self._make_event(session, "add_to_cart", cart_product, event_value=cart_product.price, seconds_offset=offset)
        offset += random.randint(60, 180)

        if random.random() < 0.75:
            self._make_event(session, "remove_from_cart", cart_product, event_value=cart_product.price, seconds_offset=offset)

    def _build_checkout_session(self, session, create_order=False):
        views = random.randint(1, 3)
        offset = 0
        for i in range(views):
            product = self._pick_product()
            self._make_event(session, "view_product", product, seconds_offset=offset)
            offset += random.randint(30, 90)

        cart_product = self._pick_product()
        self._make_event(session, "add_to_cart", cart_product, event_value=cart_product.price, seconds_offset=offset)
        offset += random.randint(60, 180)

        checkout_product = cart_product if random.random() < 0.70 else self._pick_product()
        self._make_event(session, "checkout", checkout_product, event_value=checkout_product.price, seconds_offset=offset)
        offset += random.randint(30, 120)

        if create_order and session.user:
            self._create_order_for_session(session, checkout_product, offset)

    def _add_clicks(self, count):
        sessions = random.choices(self.all_sessions, k=count)
        for i, session in enumerate(sessions):
            product = self._pick_product()
            self._make_event(session, "click", product, seconds_offset=i % 7200)

    # ------------------------------------------------------------------
    # Order creation
    # ------------------------------------------------------------------
    def _create_order_for_session(self, session, lead_product, offset_seconds):
        customer = getattr(session.user, "customer_profile", None)
        if not customer:
            return

        status_weights = [("completed", 0.75), ("processing", 0.10), ("pending", 0.10), ("cancelled", 0.05)]
        status = random.choices([s[0] for s in status_weights], weights=[s[1] for s in status_weights], k=1)[0]

        payment_weights = [("cod", 0.50), ("vnpay", 0.30), ("bank_transfer", 0.12), ("momo", 0.08)]
        payment_method = random.choices([p[0] for p in payment_weights], weights=[p[1] for p in payment_weights], k=1)[0]
        payment_status = "paid" if status == "completed" else "pending"

        order_created_at = session.created_at + timedelta(seconds=offset_seconds)
        order = Order(
            order_code=self._unique_order_code(),
            customer=customer,
            receiver_name=customer.full_name or session.user.name,
            receiver_phone=customer.phone or session.user.phone or self._phone_vn(),
            receiver_email=customer.email or session.user.email,
            shipping_address=session.user.street_address or self.fake.street_address(),
            total_price=Decimal("0.00"),
            status=status,
            payment_method=payment_method,
            payment_status=payment_status,
        )
        order.created_at = order_created_at
        order.updated_at = order_created_at
        order._desired_created_at = order_created_at
        order.items_cache = []

        item_count = random.choices([1, 2, 3, 4, 5], weights=[5, 25, 35, 20, 15], k=1)[0]
        chosen = set()
        for _ in range(item_count):
            product = self._pick_product()
            if product.id in chosen:
                continue
            chosen.add(product.id)
            price = product.discount_price if product.discount_price else product.price
            qty = random.choices([1, 2], weights=[0.90, 0.10], k=1)[0]
            item = OrderItem(
                order=order,
                product=product,
                quantity=qty,
                price=price,
            )
            item.created_at = order_created_at
            item.updated_at = order_created_at
            item._desired_created_at = order_created_at
            self.order_items.append(item)
            order.items_cache.append(item)

        if not order.items_cache:
            # fallback single item
            product = self._pick_product()
            price = product.discount_price if product.discount_price else product.price
            item = OrderItem(order=order, product=product, quantity=1, price=price)
            item.created_at = order_created_at
            item.updated_at = order_created_at
            item._desired_created_at = order_created_at
            self.order_items.append(item)
            order.items_cache.append(item)

        self.orders.append(order)

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------
    def _print_summary(self):
        self.stdout.write(self.style.NOTICE("\n=== SEED SUMMARY ==="))
        self.stdout.write(f"Users: {User.objects.count()}")
        self.stdout.write(f"Customers: {Customer.objects.count()}")
        self.stdout.write(f"Sessions: {Session.objects.count()}")
        self.stdout.write(f"Events: {Event.objects.count()}")
        self.stdout.write(f"Orders: {Order.objects.count()}")
        self.stdout.write(f"OrderItems: {OrderItem.objects.count()}")

        self.stdout.write(self.style.NOTICE("\nTop 10 viewed products:"))
        top_views = (
            Event.objects.filter(event_type="view_product")
            .values("product__name")
            .annotate(view_count=Count("id"))
            .order_by("-view_count")[:10]
        )
        for row in top_views:
            self.stdout.write(f"  {row['view_count']} views - {row['product__name']}")

        self.stdout.write(self.style.NOTICE("\nTop 10 revenue products:"))
        top_revenue = (
            OrderItem.objects.filter(order__status="completed")
            .values("product__name")
            .annotate(revenue=Sum(F("price") * F("quantity")))
            .order_by("-revenue")[:10]
        )
        for row in top_revenue:
            self.stdout.write(f"  {row['revenue']} - {row['product__name']}")

        self.stdout.write(self.style.NOTICE("\nOrder status distribution:"))
        status_dist = Order.objects.values("status").annotate(count=Count("id")).order_by("-count")
        for row in status_dist:
            self.stdout.write(f"  {row['status']}: {row['count']}")
