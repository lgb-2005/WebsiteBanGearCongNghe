import random
import uuid
from collections import defaultdict
from datetime import datetime, timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Count, F, Sum
from faker import Faker

from accounts.models import User
from analytics.models import Event, Session
from orders.models import Customer, Order, OrderItem
from products.models import Category, Product


class Command(BaseCommand):
    help = (
        "Regenerate simulation data (Session, Event, Order, OrderItem) "
        "with a consistent behavioral pipeline and realistic timestamps."
    )

    def add_arguments(self, parser):
        parser.add_argument("--sessions", type=int, default=8000)
        parser.add_argument("--orders", type=int, default=1000)
        parser.add_argument("--events", type=int, default=30000)
        parser.add_argument("--order-items", type=int, default=3000)
        parser.add_argument(
            "--noinput",
            action="store_true",
            help="Do not prompt for confirmation before deleting simulation data.",
        )

    def handle(self, *args, **options):
        self.fake = Faker("vi_VN")
        self.now = datetime.now()
        self.start_dt = self.now - timedelta(days=365)
        self.verbosity = options.get("verbosity", 1)

        target_sessions = options["sessions"]
        target_orders = options["orders"]
        target_events = options["events"]
        target_items = options["order_items"]

        if not options["noinput"]:
            confirm = input(
                "This will DELETE all Session, Event, Order and OrderItem data, "
                "then regenerate new simulation data. Continue? [y/N]: "
            )
            if confirm.lower() != "y":
                self.stdout.write(self.style.WARNING("Aborted."))
                return

        self.stdout.write(
            self.style.NOTICE(
                f"Regenerating simulation data: {target_sessions} sessions, "
                f"{target_orders} orders, ~{target_events} events, ~{target_items} items"
            )
        )

        with transaction.atomic():
            self._delete_simulation_data()
            self._load_metadata()
            self._seed_sessions(target_sessions, target_orders)
            self._seed_events_and_orders(
                target_events, target_orders, target_items
            )

        self._print_summary()

    # ------------------------------------------------------------------
    # Setup / cleanup
    # ------------------------------------------------------------------
    def _delete_simulation_data(self):
        order_item_count, _ = OrderItem.objects.all().delete()
        order_count, _ = Order.objects.all().delete()
        event_count, _ = Event.objects.all().delete()
        session_count, _ = Session.objects.all().delete()
        self.stdout.write(
            self.style.WARNING(
                f"Deleted {session_count} sessions, {event_count} events, "
                f"{order_count} orders, {order_item_count} order items"
            )
        )

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

        self.all_users = list(
            User.objects.filter(is_superuser=False, is_staff=False)
        )
        self.user_customer_map = {
            c.user_id: c for c in Customer.objects.select_related("user").all()
        }
        self.users_with_customer = [
            u for u in self.all_users if u.id in self.user_customer_map
        ]

        if len(self.users_with_customer) < 1:
            raise ValueError("No users with Customer profiles found. Seed users first.")

        self.order_code_counters = defaultdict(int)

        self.user_agents = [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0 Safari/537.36",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/119.0 Safari/537.36",
            "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1 Mobile/15E148",
            "Mozilla/5.0 (Linux; Android 13; SM-S918B) AppleWebKit/537.36 Chrome/118.0 Mobile/15E148",
            "Mozilla/5.0 (iPad; CPU OS 16_5 like Mac OS X) AppleWebKit/605.1 Mobile/15E148",
        ]

        self.device_pool = ["desktop"] * 65 + ["mobile"] * 30 + ["tablet"] * 5

    def _random_dt(self, start=None, end=None):
        start = start or self.start_dt
        end = end or self.now
        delta = end - start
        return start + timedelta(seconds=random.randint(0, int(delta.total_seconds())))

    def _pick_product(self):
        return random.choices(self.products, weights=self.product_weights, k=1)[0]

    # ------------------------------------------------------------------
    # Sessions
    # ------------------------------------------------------------------
    def _seed_sessions(self, target_sessions, target_orders):
        n_completed = int(round(target_orders * 0.75))
        n_non_completed = target_orders - n_completed
        n_cart = int(round(target_sessions * 0.25))

        if n_completed + n_non_completed > target_sessions:
            raise ValueError(
                f"target_orders ({target_orders}) cannot exceed target_sessions ({target_sessions})"
            )

        if len(self.users_with_customer) < 1:
            raise ValueError("No users with Customer profiles found.")

        self.sessions_meta = []
        self.sessions = []

        # 60% user sessions, 40% guest sessions
        for _ in range(target_sessions):
            is_user_session = random.random() < 0.60
            user = (
                random.choice(self.users_with_customer)
                if is_user_session
                else None
            )
            self._create_session(user, "_tmp")

        user_metas = [m for m in self.sessions_meta if m["session"].user]
        guest_metas = [m for m in self.sessions_meta if not m["session"].user]

        if len(user_metas) < target_orders:
            raise ValueError(
                f"Need at least {target_orders} user sessions, got {len(user_metas)}"
            )

        random.shuffle(user_metas)
        order_metas = user_metas[:target_orders]
        non_order_metas = user_metas[target_orders:] + guest_metas
        random.shuffle(non_order_metas)

        cart_metas = non_order_metas[:n_cart]
        view_metas = non_order_metas[n_cart:]

        # completed orders
        for meta in order_metas[:n_completed]:
            meta["type"] = "completed_order"
            meta["status"] = "completed"

        # non-completed orders
        statuses = self._build_non_completed_statuses(n_non_completed)
        for meta, status in zip(order_metas[n_completed:], statuses):
            meta["type"] = "order"
            meta["status"] = status

        # cart-only and view-only
        for meta in cart_metas:
            meta["type"] = "cart"
        for meta in view_metas:
            meta["type"] = "view"

        Session.objects.bulk_create(self.sessions, batch_size=1000)
        # bulk_create overrides auto_now_add/auto_now fields; reapply stored timestamps
        for session in self.sessions:
            session.created_at = session._desired_created_at
            session.updated_at = session._desired_created_at
        Session.objects.bulk_update(
            self.sessions, ["created_at", "updated_at"], batch_size=1000
        )

        self.stdout.write(
            self.style.SUCCESS(
                f"Created {len(self.sessions)} sessions "
                f"({len(view_metas)} view-only, {len(cart_metas)} cart-only, "
                f"{n_non_completed} order non-completed, {n_completed} completed, "
                f"{len(guest_metas)} guest)"
            )
        )

    def _build_non_completed_statuses(self, count):
        if count <= 0:
            return []
        n_processing = int(round(count * 0.40))
        n_pending = int(round(count * 0.40))
        n_cancelled = count - n_processing - n_pending
        statuses = (
            ["processing"] * n_processing
            + ["pending"] * n_pending
            + ["cancelled"] * n_cancelled
        )
        random.shuffle(statuses)
        return statuses

    def _create_session(self, user, funnel_type, status=None):
        created_at = self._random_dt()
        session = Session(
            id=str(uuid.uuid4()),
            user=user,
            ip_address=self._random_ip(),
            user_agent=random.choice(self.user_agents),
            device_type=random.choice(self.device_pool),
        )
        session.created_at = created_at
        session.updated_at = created_at
        session._desired_created_at = created_at
        self.sessions.append(session)
        self.sessions_meta.append(
            {"session": session, "type": funnel_type, "status": status}
        )

    def _random_ip(self):
        return (
            f"{random.randint(1, 223)}.{random.randint(0, 255)}."
            f"{random.randint(0, 255)}.{random.randint(1, 254)}"
        )

    # ------------------------------------------------------------------
    # Events + Orders
    # ------------------------------------------------------------------
    def _seed_events_and_orders(self, target_events, target_orders, target_items):
        self.events = []
        self.orders = []
        self.order_items = []

        for meta in self.sessions_meta:
            funnel_type = meta["type"]
            session = meta["session"]
            if funnel_type == "view":
                self._build_view_only_session(session)
            elif funnel_type == "cart":
                self._build_cart_session(session)
            else:
                self._build_checkout_order_session(
                    session, meta["status"], target_items
                )

        # Add generic click events to reach target event count
        current_events = len(self.events)
        if current_events < target_events:
            self._add_clicks(target_events - current_events)

        Event.objects.bulk_create(self.events, batch_size=1000)
        # Reapply timestamps after bulk_create
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

        self.stdout.write(
            self.style.SUCCESS(
                f"Created {len(self.events)} events, {len(self.orders)} orders, "
                f"{len(self.order_items)} order items"
            )
        )

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
        view_count = random.randint(1, 3)
        offset = 0
        for i in range(view_count):
            product = self._pick_product()
            self._make_event(session, "view_product", product, seconds_offset=offset)
            offset += random.randint(30, 90)

    def _build_cart_session(self, session):
        offset = self._build_views(session)

        cart_product = self._pick_product()
        self._make_event(
            session, "add_to_cart", cart_product,
            event_value=cart_product.price, seconds_offset=offset,
        )
        offset += random.randint(60, 180)

        if random.random() < 0.50:
            self._make_event(
                session, "remove_from_cart", cart_product,
                event_value=cart_product.price, seconds_offset=offset,
            )

    def _build_checkout_order_session(self, session, status, target_items):
        offset = self._build_views(session)

        cart_product = self._pick_product()
        self._make_event(
            session, "add_to_cart", cart_product,
            event_value=cart_product.price, seconds_offset=offset,
        )
        offset += random.randint(60, 180)

        # checkout product is usually the cart product
        checkout_product = cart_product
        self._make_event(
            session, "checkout", checkout_product,
            event_value=checkout_product.price, seconds_offset=offset,
        )
        offset += random.randint(30, 120)

        # create the Order right after checkout
        self._create_order_for_session(session, status, offset)

    def _build_views(self, session):
        view_count = random.randint(1, 3)
        offset = 0
        for i in range(view_count):
            product = self._pick_product()
            self._make_event(session, "view_product", product, seconds_offset=offset)
            offset += random.randint(30, 90)
        return offset

    def _add_clicks(self, count):
        sessions = random.choices(self.sessions, k=count)
        for session in sessions:
            product = self._pick_product()
            seconds_offset = random.randint(0, 3600)
            self._make_event(
                session, "click", product, seconds_offset=seconds_offset
            )

    # ------------------------------------------------------------------
    # Order creation
    # ------------------------------------------------------------------
    def _create_order_for_session(self, session, status, offset_seconds):
        customer = self.user_customer_map.get(session.user_id)
        if not customer:
            return

        payment_weights = [
            ("cod", 0.50),
            ("vnpay", 0.30),
            ("bank_transfer", 0.12),
            ("momo", 0.08),
        ]
        payment_method = random.choices(
            [p[0] for p in payment_weights],
            weights=[p[1] for p in payment_weights],
            k=1,
        )[0]

        if status == "completed":
            payment_status = "paid"
        elif status == "cancelled":
            payment_status = "cancelled"
        else:
            payment_status = "pending"

        order_created_at = session.created_at + timedelta(seconds=offset_seconds)
        order_code = self._generate_order_code(order_created_at)

        order = Order(
            order_code=order_code,
            customer=customer,
            receiver_name=customer.full_name or session.user.name,
            receiver_phone=customer.phone or session.user.phone or "",
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

        item_count = random.choices(
            [1, 2, 3, 4, 5], weights=[5, 25, 35, 20, 15], k=1
        )[0]
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
            item_created_at = order_created_at + timedelta(seconds=random.randint(0, 5))
            item.created_at = item_created_at
            item.updated_at = item_created_at
            item._desired_created_at = item_created_at
            self.order_items.append(item)
            order.items_cache.append(item)

        if not order.items_cache:
            product = self._pick_product()
            price = product.discount_price if product.discount_price else product.price
            item = OrderItem(order=order, product=product, quantity=1, price=price)
            item.created_at = order_created_at
            item.updated_at = order_created_at
            item._desired_created_at = order_created_at
            self.order_items.append(item)
            order.items_cache.append(item)

        order.total_price = sum(
            item.price * item.quantity for item in order.items_cache
        )
        self.orders.append(order)

    def _generate_order_code(self, order_created_at):
        date_str = order_created_at.strftime("%Y%m%d")
        self.order_code_counters[date_str] += 1
        seq = self.order_code_counters[date_str]
        return f"DH{date_str}{seq:06d}"

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------
    def _print_summary(self):
        self.stdout.write(self.style.NOTICE("\n=== REGENERATION SUMMARY ==="))
        self.stdout.write(f"Users: {User.objects.count()}")
        self.stdout.write(f"Customers: {Customer.objects.count()}")
        self.stdout.write(f"Sessions: {Session.objects.count()}")
        self.stdout.write(f"Events: {Event.objects.count()}")
        self.stdout.write(f"Orders: {Order.objects.count()}")
        self.stdout.write(f"OrderItems: {OrderItem.objects.count()}")

        # date range
        order_dates = list(Order.objects.values_list("created_at", flat=True))
        if order_dates:
            self.stdout.write(
                f"Order date range: {min(order_dates).date()} to {max(order_dates).date()}"
            )

        self.stdout.write(self.style.NOTICE("\nOrder status distribution:"))
        for row in Order.objects.values("status").annotate(count=Count("id")).order_by("-count"):
            self.stdout.write(f"  {row['status']}: {row['count']}")

        self.stdout.write(self.style.NOTICE("\nEvent type distribution:"))
        for row in Event.objects.values("event_type").annotate(count=Count("id")).order_by("-count"):
            self.stdout.write(f"  {row['event_type']}: {row['count']}")

        self.stdout.write(self.style.NOTICE("\nTop 10 viewed products:"))
        top_views = (
            Event.objects.filter(event_type="view_product")
            .values("product__name")
            .annotate(view_count=Count("id"))
            .order_by("-view_count")[:10]
        )
        for row in top_views:
            self.stdout.write(f"  {row['view_count']} views - {row['product__name']}")

        self.stdout.write(self.style.NOTICE("\nTop 10 revenue products (completed orders):"))
        top_revenue = (
            OrderItem.objects.filter(order__status="completed")
            .values("product__name")
            .annotate(revenue=Sum(F("price") * F("quantity")))
            .order_by("-revenue")[:10]
        )
        for row in top_revenue:
            self.stdout.write(f"  {row['revenue']} - {row['product__name']}")

        # order_code vs created_at sanity check
        mismatch = 0
        for order in Order.objects.all().iterator():
            expected_prefix = f"DH{order.created_at.strftime('%Y%m%d')}"
            if not order.order_code.startswith(expected_prefix):
                mismatch += 1
        self.stdout.write(
            f"\nOrder code / created_at mismatches: {mismatch}"
        )
