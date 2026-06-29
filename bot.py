import asyncio
import json
import logging
import os
import time
import urllib.error
import urllib.request
import warnings
from uuid import uuid4

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import BadRequest, NetworkError
from telegram.warnings import PTBUserWarning
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)


logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("telegram").setLevel(logging.WARNING)
logging.getLogger("telegram.ext").setLevel(logging.WARNING)
warnings.filterwarnings("ignore", category=PTBUserWarning, message="If 'per_message=False'.*")

LOGGER = logging.getLogger(__name__)
ENV_FILE = ".env"
TOKEN_ENV_NAME = "TELEGRAM_BOT_TOKEN"
ADMIN_IDS_ENV_NAME = "ADMIN_IDS"
TAP_SECRET_KEY_ENV_NAME = "TAP_SECRET_KEY"
TAP_CURRENCY_ENV_NAME = "TAP_CURRENCY"
TAP_SOURCE_ID_ENV_NAME = "TAP_SOURCE_ID"
TAP_REDIRECT_URL_ENV_NAME = "TAP_REDIRECT_URL"
TAP_POST_URL_ENV_NAME = "TAP_POST_URL"
TAP_CUSTOMER_EMAIL_ENV_NAME = "TAP_CUSTOMER_EMAIL"
TAP_CUSTOMER_PHONE_COUNTRY_CODE_ENV_NAME = "TAP_CUSTOMER_PHONE_COUNTRY_CODE"
TAP_CUSTOMER_PHONE_NUMBER_ENV_NAME = "TAP_CUSTOMER_PHONE_NUMBER"
TOPUP_CREDIT_RATE_ENV_NAME = "TOPUP_CREDIT_RATE"
PRODUCTS_FILE = "products.json"
USERS_FILE = "users.json"
USERNAMES_FILE = "usernames.json"
BOT_USERS_FILE = "bot_users.json"
USER_OPERATIONS_FILE = "user_operations.json"
ARCHIVE_FILE = "archive.json"
EMPLOYEES_FILE = "employees.json"
STAFF_OPERATIONS_FILE = "staff_operations.json"
TOPUPS_FILE = "topups.json"
SUPPORT_TICKETS_FILE = "support_tickets.json"
PRODUCT_NAME, PRODUCT_DESCRIPTION, PRODUCT_PRICE, DELIVERY_CONTENT = range(4)
USERNAME_CATEGORY_NAME, USERNAME_NAME, USERNAME_PRICE, USERNAME_DELIVERY = range(4, 8)
EMPLOYEE_ID = 8
TOPUP_AMOUNT = 9
SUPPORT_MESSAGE = 10
SUPPORT_REPLY_MESSAGE = 11
TAP_API_BASE = "https://api.tap.company/v2"
RESERVATION_SECONDS = 24 * 60 * 60
RESERVATION_CANCEL_SECONDS = 60 * 60
RESERVATION_RECANCEL_BLOCK_SECONDS = 2 * 24 * 60 * 60
SHORT_ID_LENGTH = 10
PURCHASES_PAGE_SIZE = 5


WELCOME_MESSAGE = (
    """🎉 مرحبًا بك في L2B STORE!

أهلًا بك! نحن سعداء بوجودك معنا. 🤍
هنا ستجد مجموعة متنوعة من المنتجات والخدمات، مع تجربة شراء سهلة وآمنة.

إذا احتجت أي مساعدة أو كان لديك أي استفسار، فلا تتردد في التواصل معنا، وسنكون سعداء بخدمتك.

استخدم الأزرار أدناه للبدء واستمتع بتجربة تسوق مميزة! 🚀"""
)


def rtl_text(text: str) -> str:
    return f"\u200f{text}\u200f"


def main_menu_keyboard(show_admin: bool = False, show_employee: bool = False) -> InlineKeyboardMarkup:
    keyboard = [
        [
            InlineKeyboardButton("📦 المنتجات الرقمية", callback_data="digital_products"),
            InlineKeyboardButton("🔤 قسم اليوزرات", callback_data="usernames"),
        ],
        [
            InlineKeyboardButton("💰 محفظتي", callback_data="wallet"),
            InlineKeyboardButton("🧾 العمليات", callback_data="operations"),
        ],
        [InlineKeyboardButton("💬 المساعدة و الدعم", callback_data="support")],
    ]

    if show_admin:
        keyboard.append([InlineKeyboardButton("🛠️ لوحة الادمن", callback_data="admin_menu")])
    elif show_employee:
        keyboard.append([InlineKeyboardButton("👨‍💼 لوحة الموظف", callback_data="employee_menu")])

    return InlineKeyboardMarkup(keyboard)


def back_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("🏠 العودة للقائمة الرئيسية", callback_data="main_menu")]]
    )


def wallet_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("➕ إضافة أموال", callback_data="add_wallet_funds")],
            [InlineKeyboardButton("🏠 العودة للقائمة الرئيسية", callback_data="main_menu")],
        ]
    )


def topup_methods_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("💸 البطاقة / Apple Pay", callback_data="topup_method:tap")],
            [InlineKeyboardButton("↩️ رجوع للمحفظة", callback_data="wallet")],
        ]
    )


def topup_invoice_keyboard(invoice_url: str, label: str = "🌐 فتح رابط الدفع") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(label, url=invoice_url)],
            [InlineKeyboardButton("↩️ رجوع للمحفظة", callback_data="wallet")],
        ]
    )


SUPPORT_CATEGORIES = {
    "payment": "💳 مشكلة دفع / شحن",
    "product": "📦 مشكلة منتج",
    "username": "🔤 مشكلة يوزر",
    "wallet": "💰 مشكلة المحفظة",
    "other": "💬 استفسار آخر",
}


def support_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(label, callback_data=f"support_new:{key}")]
            for key, label in SUPPORT_CATEGORIES.items()
        ]
        + [
            [InlineKeyboardButton("🎫 تذاكري", callback_data="support_my_tickets")],
            [InlineKeyboardButton("🏠 العودة للقائمة الرئيسية", callback_data="main_menu")],
        ]
    )


def support_collect_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("✅ إنشاء التذكرة", callback_data="support_finish_ticket")],
            [InlineKeyboardButton("❌ الغاء", callback_data="support_cancel_ticket")],
        ]
    )


def user_tickets_keyboard(user_id: int) -> InlineKeyboardMarkup:
    tickets = get_user_tickets(user_id)
    keyboard = []
    for ticket in reversed(tickets[-10:]):
        status = "✅" if ticket.get("status") == "closed" else "⏳"
        keyboard.append(
            [
                InlineKeyboardButton(
                    rtl_text(f"{status} {ticket.get('number', ticket.get('id'))} - {ticket.get('category_label', 'دعم')}"),
                    callback_data=f"support_ticket:{ticket['id']}",
                )
            ]
        )

    keyboard.append([InlineKeyboardButton("↩️ رجوع للدعم", callback_data="support")])
    keyboard.append([InlineKeyboardButton("🏠 العودة للقائمة الرئيسية", callback_data="main_menu")])
    return InlineKeyboardMarkup(keyboard)


def user_ticket_keyboard(ticket: dict) -> InlineKeyboardMarkup:
    keyboard = []
    if ticket.get("status") != "closed":
        keyboard.append([InlineKeyboardButton("➕ إضافة رد", callback_data=f"support_add:{ticket['id']}")])
    keyboard.append([InlineKeyboardButton("↩️ رجوع لتذاكري", callback_data="support_my_tickets")])
    keyboard.append([InlineKeyboardButton("🏠 العودة للقائمة الرئيسية", callback_data="main_menu")])
    return InlineKeyboardMarkup(keyboard)


def staff_tickets_keyboard() -> InlineKeyboardMarkup:
    tickets = get_staff_visible_tickets()
    keyboard = []
    for ticket in tickets[:20]:
        status = "✅" if ticket.get("status") == "closed" else "⏳"
        keyboard.append(
            [
                InlineKeyboardButton(
                    rtl_text(f"{status} {ticket.get('number', ticket.get('id'))} - {ticket.get('category_label', 'دعم')}"),
                    callback_data=f"staff_ticket:{ticket['id']}",
                )
            ]
        )

    keyboard.append([InlineKeyboardButton("↩️ رجوع", callback_data="main_menu")])
    return InlineKeyboardMarkup(keyboard)


def staff_ticket_keyboard(ticket: dict) -> InlineKeyboardMarkup:
    keyboard = []
    if ticket.get("status") != "closed":
        keyboard.append([InlineKeyboardButton("✍️ رد على التذكرة", callback_data=f"staff_ticket_reply:{ticket['id']}")])
        keyboard.append([InlineKeyboardButton("🔒 اغلاق التذكرة", callback_data=f"staff_ticket_close:{ticket['id']}")])
    keyboard.append([InlineKeyboardButton("↩️ رجوع للتذاكر", callback_data="staff_tickets")])
    return InlineKeyboardMarkup(keyboard)


def products_keyboard(products: list[dict]) -> InlineKeyboardMarkup:
    keyboard = []
    for product in products:
        quantity = len(get_delivery_items(product))
        product_name = product.get("name", "منتج بدون اسم")
        keyboard.append(
            [
                InlineKeyboardButton(
                    f"📦 {product_name} - المتوفر: {quantity}",
                    callback_data=f"product:{product['id']}",
                )
            ]
        )

    keyboard.append([InlineKeyboardButton("🏠 العودة للقائمة الرئيسية", callback_data="main_menu")])
    return InlineKeyboardMarkup(keyboard)


def product_purchase_keyboard(product_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("🛒 شراء المنتج", callback_data=f"buy:{product_id}")],
            [InlineKeyboardButton("↩️ رجوع للمنتجات", callback_data="digital_products")],
        ]
    )


def back_to_products_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("↩️ رجوع للمنتجات", callback_data="digital_products")]]
    )


def back_to_username_categories_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("↩️ رجوع للاقسام", callback_data="usernames")]]
    )


def back_to_admin_products_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("↩️ رجوع للمنتجات", callback_data="admin_show_products")]]
    )


def back_to_admin_username_categories_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("↩️ رجوع للاقسام", callback_data="admin_username_categories")]]
    )


def back_to_admin_usernames_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("↩️ رجوع لقسم اليوزرات", callback_data="admin_usernames")]]
    )


def back_to_admin_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("↩️ رجوع للوحة الادمن", callback_data="admin_menu")]]
    )


def admin_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("➕ اضافة المنتجات", callback_data="admin_add_product")],
            [InlineKeyboardButton("📋 عرض المنتجات", callback_data="admin_show_products")],
            [InlineKeyboardButton("🔤 قسم اليوزرات", callback_data="admin_usernames")],
            [InlineKeyboardButton("🎫 تذاكر الدعم", callback_data="staff_tickets")],
            [InlineKeyboardButton("👨‍💼 إدارة الموظفين", callback_data="admin_employees")],
            [InlineKeyboardButton("🏠 العودة للقائمة الرئيسية", callback_data="main_menu")],
        ]
    )


def admin_employees_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("➕ توظيف موظف", callback_data="admin_add_employee")],
            [InlineKeyboardButton("📋 عرض الموظفين", callback_data="admin_show_employees")],
            [InlineKeyboardButton("↩️ رجوع للوحة الادمن", callback_data="admin_menu")],
        ]
    )


def employee_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("📥 اضافة مخزون المنتجات الرقمية", callback_data="employee_products")],
            [InlineKeyboardButton("🔤 اضافة يوزر داخل قسم", callback_data="employee_username_categories")],
            [InlineKeyboardButton("🎫 تذاكر الدعم", callback_data="staff_tickets")],
            [InlineKeyboardButton("🏠 العودة للقائمة الرئيسية", callback_data="main_menu")],
        ]
    )


def admin_usernames_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("🗂️ اضافة قسم جديد", callback_data="admin_add_username_category")],
            [InlineKeyboardButton("📁 اختيار قسم", callback_data="admin_username_categories")],
            [InlineKeyboardButton("⏳ الحجوزات", callback_data="admin_username_reservations")],
            [InlineKeyboardButton("↩️ رجوع للوحة الادمن", callback_data="admin_menu")],
        ]
    )


def username_categories_keyboard(categories: list[dict], prefix: str) -> InlineKeyboardMarkup:
    keyboard = [
        [InlineKeyboardButton(f"📁 {category.get('name', 'قسم بدون اسم')}", callback_data=f"{prefix}:{category['id']}")]
        for category in categories
    ]
    keyboard.append([InlineKeyboardButton("↩️ رجوع", callback_data="admin_usernames" if prefix.startswith("admin") else "main_menu")])
    return InlineKeyboardMarkup(keyboard)


def admin_username_category_keyboard(category_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("➕ اضافة يوزر جديد", callback_data=f"admin_add_username:{category_id}")],
            [InlineKeyboardButton("↩️ رجوع للاقسام", callback_data="admin_username_categories")],
        ]
    )


def usernames_items_keyboard(category: dict) -> InlineKeyboardMarkup:
    keyboard = []
    for item in category.get("items", []):
        if item.get("status", "available") != "available":
            continue
        keyboard.append(
            [
                InlineKeyboardButton(
                    f"🔤 {item.get('name', 'يوزر بدون اسم')} - {format_price(get_username_price(item))} ريال",
                    callback_data=f"username_item:{category['id']}:{item['id']}",
                )
            ]
        )

    keyboard.append([InlineKeyboardButton("↩️ رجوع للاقسام", callback_data="usernames")])
    return InlineKeyboardMarkup(keyboard)


def username_purchase_keyboard(category_id: str, item_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("🛒 شراء", callback_data=f"buy_username:{category_id}:{item_id}")],
            [InlineKeyboardButton("⏳ حجز", callback_data=f"reserve_username:{category_id}:{item_id}")],
            [InlineKeyboardButton("↩️ رجوع", callback_data=f"username_category:{category_id}")],
        ]
    )


def username_reserved_keyboard(category_id: str, item_id: str, can_cancel: bool = True) -> InlineKeyboardMarkup:
    keyboard = []
    keyboard.append([InlineKeyboardButton("🛒 شراء", callback_data=f"buy_reserved_username:{category_id}:{item_id}")])
    if can_cancel:
        keyboard.append([InlineKeyboardButton("❌ الغاء الحجز", callback_data=f"cancel_username_reservation:{category_id}:{item_id}")])
    keyboard.append([InlineKeyboardButton("🧾 العمليات", callback_data="operations")])
    keyboard.append([InlineKeyboardButton("↩️ رجوع", callback_data=f"username_category:{category_id}")])
    return InlineKeyboardMarkup(keyboard)


def operations_keyboard(user_id: int, view: str = "all") -> InlineKeyboardMarkup:
    keyboard = []
    if view != "reservations":
        keyboard.append(
            [
                InlineKeyboardButton("🛒 المشتريات", callback_data="operations:purchases"),
                InlineKeyboardButton("⏳ الحجوزات", callback_data="operations:reservations"),
            ]
        )
    reservation = get_active_user_reservation(user_id)
    if view == "reservations" and reservation:
        category_id, item_id, item = reservation
        can_cancel = can_cancel_reservation(item.get("reservation", {}))
        keyboard.append(
            [InlineKeyboardButton("🛒 شراء الحجز الحالي", callback_data=f"buy_reserved_username:{category_id}:{item_id}")]
        )
        if can_cancel:
            keyboard.append(
                [InlineKeyboardButton("❌ الغاء الحجز الحالي", callback_data=f"cancel_username_reservation:{category_id}:{item_id}")]
            )

    if view == "reservations":
        keyboard.append([InlineKeyboardButton(rtl_text("↩️ رجوع للعمليات"), callback_data="operations:all")])

    keyboard.append([InlineKeyboardButton("🏠 العودة للقائمة الرئيسية", callback_data="main_menu")])
    return InlineKeyboardMarkup(keyboard)


def purchases_keyboard(user_id: int, page: int = 0) -> InlineKeyboardMarkup:
    purchases = list(reversed(get_user_purchase_operations(user_id)))
    total_pages = max(1, (len(purchases) + PURCHASES_PAGE_SIZE - 1) // PURCHASES_PAGE_SIZE)
    page = max(0, min(page, total_pages - 1))
    page_purchases = purchases[page * PURCHASES_PAGE_SIZE : (page + 1) * PURCHASES_PAGE_SIZE]
    keyboard = []
    for operation in page_purchases:
        item_name = operation.get("item_name", "منتج بدون اسم")
        keyboard.append(
            [
                InlineKeyboardButton(
                    rtl_text(f"📋 {item_name}"),
                    callback_data=f"operation_purchase:{operation['id']}",
                )
            ]
        )

    if total_pages > 1:
        navigation = []
        if page > 0:
            navigation.append(InlineKeyboardButton("⬅️ السابق", callback_data=f"operations:purchases:{page - 1}"))
        if page < total_pages - 1:
            navigation.append(InlineKeyboardButton("التالي ➡️", callback_data=f"operations:purchases:{page + 1}"))
        if navigation:
            keyboard.append(navigation)

    keyboard.append([InlineKeyboardButton(rtl_text("↩️ رجوع للعمليات"), callback_data="operations:all")])
    keyboard.append([InlineKeyboardButton(rtl_text("🏠 العودة للقائمة الرئيسية"), callback_data="main_menu")])
    return InlineKeyboardMarkup(keyboard)


def product_flow_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("❌ الغاء اضافة المنتج", callback_data="cancel_add_product")],
        ]
    )


def delivery_flow_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("⏹️ التوقف عن اضافه التسليم", callback_data="stop_delivery")],
        ]
    )


def products_admin_keyboard(products: list[dict]) -> InlineKeyboardMarkup:
    keyboard = []
    for product in products:
        product_name = product.get("name", "منتج بدون اسم")
        keyboard.append(
            [InlineKeyboardButton(f"📦 {product_name}", callback_data=f"admin_product:{product['id']}")]
        )

    keyboard.append([InlineKeyboardButton("↩️ رجوع للوحة الادمن", callback_data="admin_menu")])
    return InlineKeyboardMarkup(keyboard)


def employee_products_keyboard(products: list[dict]) -> InlineKeyboardMarkup:
    keyboard = []
    for product in products:
        product_name = product.get("name", "منتج بدون اسم")
        keyboard.append(
            [InlineKeyboardButton(f"📦 {product_name}", callback_data=f"employee_delivery:{product['id']}")]
        )

    keyboard.append([InlineKeyboardButton("↩️ رجوع للوحة الموظف", callback_data="employee_menu")])
    return InlineKeyboardMarkup(keyboard)


def employee_username_categories_keyboard(categories: list[dict]) -> InlineKeyboardMarkup:
    keyboard = [
        [InlineKeyboardButton(f"📁 {category.get('name', 'قسم بدون اسم')}", callback_data=f"employee_username_category:{category['id']}")]
        for category in categories
    ]
    keyboard.append([InlineKeyboardButton("↩️ رجوع للوحة الموظف", callback_data="employee_menu")])
    return InlineKeyboardMarkup(keyboard)


def employee_username_category_keyboard(category_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("➕ اضافة يوزر جديد", callback_data=f"employee_add_username:{category_id}")],
            [InlineKeyboardButton("↩️ رجوع للاقسام", callback_data="employee_username_categories")],
        ]
    )


def product_admin_keyboard(product_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "📥 اضافة مخزون التسليم التلقائي",
                    callback_data=f"admin_delivery:{product_id}",
                )
            ],
            [InlineKeyboardButton("🗑️ حذف المنتج", callback_data=f"admin_delete_product:{product_id}")],
            [InlineKeyboardButton("↩️ رجوع للمنتجات", callback_data="admin_show_products")],
        ]
    )


def load_env_file(path: str = ENV_FILE) -> None:
    if not os.path.exists(path):
        return

    with open(path, "r", encoding="utf-8") as env_file:
        for line in env_file:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue

            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            os.environ.setdefault(key, value)


def get_admin_ids() -> set[int]:
    raw_admin_ids = os.getenv(ADMIN_IDS_ENV_NAME, "")
    admin_ids = set()

    for raw_admin_id in raw_admin_ids.split(","):
        raw_admin_id = raw_admin_id.strip()
        if not raw_admin_id:
            continue

        try:
            admin_ids.add(int(raw_admin_id))
        except ValueError:
            LOGGER.warning("Invalid admin id in %s: %s", ADMIN_IDS_ENV_NAME, raw_admin_id)

    return admin_ids


def get_staff_ids() -> set[int]:
    staff_ids = set(get_admin_ids())
    for employee in load_employees().get("employees", []):
        employee_id = employee.get("id")
        if not employee_id:
            continue
        try:
            staff_ids.add(int(employee_id))
        except (TypeError, ValueError):
            LOGGER.warning("Invalid employee id in %s: %s", EMPLOYEES_FILE, employee_id)
    return staff_ids


def is_admin(update: Update) -> bool:
    user = update.effective_user
    return bool(user and user.id in get_admin_ids())


def is_employee(update: Update) -> bool:
    user = update.effective_user
    if not user:
        return False
    return any(
        employee.get("id") == user.id
        for employee in load_employees().get("employees", [])
    )


def can_manage_stock(update: Update) -> bool:
    return is_admin(update) or is_employee(update)


def can_manage_usernames(update: Update) -> bool:
    return is_admin(update) or is_employee(update)


def get_actor_info(user, role: str) -> dict:
    return {
        "role": role,
        "id": user.id if user else None,
        "name": get_user_display_name(user),
        "username": user.username if user and user.username else "",
    }


def log_staff_operation(user, role: str, action: str, target: dict) -> None:
    data = load_staff_operations()
    data["operations"].append(
        {
            "id": make_short_id(),
            "action": action,
            "actor": get_actor_info(user, role),
            "target": target,
            "created_at": int(time.time()),
        }
    )
    save_staff_operations(data)


def get_known_user_info(user_id: int) -> dict:
    data = load_bot_users()
    entry = find_bot_user_entry(data, user_id)
    if not entry:
        return {"name": "غير معروف", "username": ""}
    return {
        "name": entry.get("name", "غير معروف"),
        "username": entry.get("username", ""),
    }


def employee_display_name(employee: dict) -> str:
    name = employee.get("name")
    username = employee.get("username")
    user_id = employee.get("id")

    if name and username:
        return f"{name} (@{username})"
    if name:
        return name
    if username:
        return f"@{username}"
    return str(user_id)


def employees_keyboard() -> InlineKeyboardMarkup:
    data = load_employees()
    keyboard = []
    for employee in data.get("employees", []):
        keyboard.append(
            [
                InlineKeyboardButton(
                    f"👨‍💼 {employee_display_name(employee)}",
                    callback_data=f"admin_employee:{employee['id']}",
                )
            ]
        )

    keyboard.append([InlineKeyboardButton("↩️ رجوع لإدارة الموظفين", callback_data="admin_employees")])
    return InlineKeyboardMarkup(keyboard)


def employee_details_keyboard(employee_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("🗑️ حذف الموظف", callback_data=f"admin_delete_employee:{employee_id}")],
            [InlineKeyboardButton("↩️ رجوع للموظفين", callback_data="admin_show_employees")],
        ]
    )


def get_employee(employee_id: int) -> dict | None:
    for employee in load_employees().get("employees", []):
        if employee.get("id") == employee_id:
            return employee
    return None


def delete_employee(employee_id: int) -> dict | None:
    data = load_employees()
    for index, employee in enumerate(data.get("employees", [])):
        if employee.get("id") == employee_id:
            deleted_employee = data["employees"].pop(index)
            save_employees(data)
            return deleted_employee
    return None


def get_employee_stats(employee_id: int) -> dict:
    operations = [
        operation
        for operation in load_staff_operations().get("operations", [])
        if operation.get("actor", {}).get("id") == employee_id
    ]
    add_stock_count = sum(1 for operation in operations if operation.get("action") == "add_product_stock")
    add_username_count = sum(1 for operation in operations if operation.get("action") == "add_username")
    last_operation = max(
        (operation.get("created_at", 0) for operation in operations),
        default=0,
    )
    return {
        "total": len(operations),
        "add_stock": add_stock_count,
        "add_username": add_username_count,
        "last_operation": last_operation,
    }


def format_employee_details(employee: dict) -> str:
    employee_id = int(employee.get("id"))
    stats = get_employee_stats(employee_id)
    username = employee.get("username") or "لا يوجد"
    name = employee.get("name") or "غير معروف"

    return (
        "تفاصيل الموظف.\n\n"
        f"الاسم: {name}\n"
        f"اليوزر: @{username}\n"
        f"الايدي: {employee_id}\n"
        f"وقت التوظيف: {format_timestamp(employee.get('added_at'))}\n\n"
        "الاحصائيات:\n"
        f"اجمالي العمليات: {stats['total']}\n"
        f"اضافة مخزون منتجات: {stats['add_stock']}\n"
        f"اضافة يوزرات: {stats['add_username']}\n"
        f"اخر عملية: {format_timestamp(stats['last_operation'])}"
    )


def load_products() -> list[dict]:
    if not os.path.exists(PRODUCTS_FILE):
        return []

    with open(PRODUCTS_FILE, "r", encoding="utf-8") as products_file:
        try:
            products = json.load(products_file)
        except json.JSONDecodeError:
            LOGGER.warning("%s is not valid JSON. Starting with an empty list.", PRODUCTS_FILE)
            return []

    return products if isinstance(products, list) else []


def save_products(products: list[dict]) -> None:
    with open(PRODUCTS_FILE, "w", encoding="utf-8") as products_file:
        json.dump(products, products_file, ensure_ascii=False, indent=2)


def load_users() -> dict:
    if not os.path.exists(USERS_FILE):
        return {}

    with open(USERS_FILE, "r", encoding="utf-8") as users_file:
        try:
            users = json.load(users_file)
        except json.JSONDecodeError:
            LOGGER.warning("%s is not valid JSON. Starting with an empty dict.", USERS_FILE)
            return {}

    return users if isinstance(users, dict) else {}


def save_users(users: dict) -> None:
    with open(USERS_FILE, "w", encoding="utf-8") as users_file:
        json.dump(users, users_file, ensure_ascii=False, indent=2)


def load_bot_users() -> dict:
    if not os.path.exists(BOT_USERS_FILE):
        return {"next_number": 1, "users": []}

    with open(BOT_USERS_FILE, "r", encoding="utf-8") as bot_users_file:
        try:
            data = json.load(bot_users_file)
        except json.JSONDecodeError:
            LOGGER.warning("%s is not valid JSON. Starting with an empty list.", BOT_USERS_FILE)
            return {"next_number": 1, "users": []}

    if not isinstance(data, dict):
        return {"next_number": 1, "users": []}
    if not isinstance(data.get("users"), list):
        data["users"] = []
    if not isinstance(data.get("next_number"), int):
        data["next_number"] = len(data["users"]) + 1
    return data


def save_bot_users(data: dict) -> None:
    with open(BOT_USERS_FILE, "w", encoding="utf-8") as bot_users_file:
        json.dump(data, bot_users_file, ensure_ascii=False, indent=2)


def load_user_operations() -> dict:
    if not os.path.exists(USER_OPERATIONS_FILE):
        return {"next_order_number": 1, "operations": []}

    with open(USER_OPERATIONS_FILE, "r", encoding="utf-8") as operations_file:
        try:
            data = json.load(operations_file)
        except json.JSONDecodeError:
            LOGGER.warning("%s is not valid JSON. Starting with an empty log.", USER_OPERATIONS_FILE)
            return {"next_order_number": 1, "operations": []}

    if not isinstance(data, dict):
        return {"next_order_number": 1, "operations": []}
    if not isinstance(data.get("operations"), list):
        data["operations"] = []
    if not isinstance(data.get("next_order_number"), int):
        data["next_order_number"] = 1
    return data


def save_user_operations(data: dict) -> None:
    with open(USER_OPERATIONS_FILE, "w", encoding="utf-8") as operations_file:
        json.dump(data, operations_file, ensure_ascii=False, indent=2)


def load_archive() -> dict:
    if not os.path.exists(ARCHIVE_FILE):
        return {"sold_usernames": []}

    with open(ARCHIVE_FILE, "r", encoding="utf-8") as archive_file:
        try:
            data = json.load(archive_file)
        except json.JSONDecodeError:
            LOGGER.warning("%s is not valid JSON. Starting with an empty archive.", ARCHIVE_FILE)
            return {"sold_usernames": []}

    if not isinstance(data, dict):
        return {"sold_usernames": []}
    if not isinstance(data.get("sold_usernames"), list):
        data["sold_usernames"] = []
    return data


def save_archive(data: dict) -> None:
    with open(ARCHIVE_FILE, "w", encoding="utf-8") as archive_file:
        json.dump(data, archive_file, ensure_ascii=False, indent=2)


def load_employees() -> dict:
    if not os.path.exists(EMPLOYEES_FILE):
        return {"employees": []}

    with open(EMPLOYEES_FILE, "r", encoding="utf-8") as employees_file:
        try:
            data = json.load(employees_file)
        except json.JSONDecodeError:
            LOGGER.warning("%s is not valid JSON. Starting with an empty employee list.", EMPLOYEES_FILE)
            return {"employees": []}

    if not isinstance(data, dict):
        return {"employees": []}
    if not isinstance(data.get("employees"), list):
        data["employees"] = []
    ensure_employee_info(data)
    return data


def save_employees(data: dict) -> None:
    with open(EMPLOYEES_FILE, "w", encoding="utf-8") as employees_file:
        json.dump(data, employees_file, ensure_ascii=False, indent=2)


def ensure_employee_info(data: dict) -> None:
    changed = False
    for employee in data.get("employees", []):
        known_info = get_known_user_info(int(employee.get("id", 0)))
        if not employee.get("name"):
            employee["name"] = known_info["name"]
            changed = True
        if "username" not in employee:
            employee["username"] = known_info["username"]
            changed = True

    if changed:
        save_employees(data)


def load_staff_operations() -> dict:
    if not os.path.exists(STAFF_OPERATIONS_FILE):
        return {"operations": []}

    with open(STAFF_OPERATIONS_FILE, "r", encoding="utf-8") as operations_file:
        try:
            data = json.load(operations_file)
        except json.JSONDecodeError:
            LOGGER.warning("%s is not valid JSON. Starting with an empty log.", STAFF_OPERATIONS_FILE)
            return {"operations": []}

    if not isinstance(data, dict):
        return {"operations": []}
    if not isinstance(data.get("operations"), list):
        data["operations"] = []
    return data


def save_staff_operations(data: dict) -> None:
    with open(STAFF_OPERATIONS_FILE, "w", encoding="utf-8") as operations_file:
        json.dump(data, operations_file, ensure_ascii=False, indent=2)


def load_topups() -> dict:
    if not os.path.exists(TOPUPS_FILE):
        return {"topups": []}

    with open(TOPUPS_FILE, "r", encoding="utf-8") as topups_file:
        try:
            data = json.load(topups_file)
        except json.JSONDecodeError:
            LOGGER.warning("%s is not valid JSON. Starting with an empty list.", TOPUPS_FILE)
            return {"topups": []}

    if not isinstance(data, dict):
        return {"topups": []}
    if not isinstance(data.get("topups"), list):
        data["topups"] = []
    return data


def save_topups(data: dict) -> None:
    with open(TOPUPS_FILE, "w", encoding="utf-8") as topups_file:
        json.dump(data, topups_file, ensure_ascii=False, indent=2)


def load_support_tickets() -> dict:
    if not os.path.exists(SUPPORT_TICKETS_FILE):
        return {"next_ticket_number": 1, "tickets": []}

    with open(SUPPORT_TICKETS_FILE, "r", encoding="utf-8") as tickets_file:
        try:
            data = json.load(tickets_file)
        except json.JSONDecodeError:
            LOGGER.warning("%s is not valid JSON. Starting with an empty list.", SUPPORT_TICKETS_FILE)
            return {"next_ticket_number": 1, "tickets": []}

    if not isinstance(data, dict):
        return {"next_ticket_number": 1, "tickets": []}
    if not isinstance(data.get("tickets"), list):
        data["tickets"] = []
    if not isinstance(data.get("next_ticket_number"), int):
        data["next_ticket_number"] = len(data["tickets"]) + 1
    return data


def save_support_tickets(data: dict) -> None:
    with open(SUPPORT_TICKETS_FILE, "w", encoding="utf-8") as tickets_file:
        json.dump(data, tickets_file, ensure_ascii=False, indent=2)


def create_ticket_number(data: dict) -> str:
    number = f"TCK-{data['next_ticket_number']:06d}"
    data["next_ticket_number"] += 1
    return number


def get_ticket(ticket_id: str) -> dict | None:
    for ticket in load_support_tickets().get("tickets", []):
        if ticket.get("id") == ticket_id:
            return ticket
    return None


def update_ticket(ticket_id: str, updates: dict) -> None:
    data = load_support_tickets()
    for ticket in data.get("tickets", []):
        if ticket.get("id") == ticket_id:
            ticket.update(updates)
            ticket["updated_at"] = int(time.time())
            save_support_tickets(data)
            return


def add_ticket_message(ticket_id: str, message: dict) -> dict | None:
    data = load_support_tickets()
    for ticket in data.get("tickets", []):
        if ticket.get("id") != ticket_id:
            continue
        message.setdefault("id", make_short_id())
        message.setdefault("created_at", int(time.time()))
        ticket.setdefault("messages", []).append(message)
        ticket["updated_at"] = int(time.time())
        if ticket.get("status") != "closed":
            ticket["status"] = "open"
        save_support_tickets(data)
        return ticket
    return None


def create_support_ticket(user, category: str, messages: list[dict]) -> dict:
    data = load_support_tickets()
    now = int(time.time())
    ticket = {
        "id": make_short_id(),
        "number": create_ticket_number(data),
        "status": "open",
        "category": category,
        "category_label": SUPPORT_CATEGORIES.get(category, "💬 دعم"),
        "user_id": user.id,
        "user_name": get_user_display_name(user),
        "username": user.username or "",
        "created_at": now,
        "updated_at": now,
        "messages": messages,
    }
    data["tickets"].append(ticket)
    save_support_tickets(data)
    return ticket


def get_user_tickets(user_id: int) -> list[dict]:
    return [
        ticket
        for ticket in load_support_tickets().get("tickets", [])
        if ticket.get("user_id") == user_id
    ]


def get_staff_visible_tickets() -> list[dict]:
    tickets = load_support_tickets().get("tickets", [])
    return sorted(
        tickets,
        key=lambda ticket: (
            1 if ticket.get("status") == "closed" else 0,
            -int(ticket.get("updated_at", ticket.get("created_at", 0))),
        ),
    )


def get_topup(payment_id: str) -> dict | None:
    for topup in load_topups().get("topups", []):
        if str(topup.get("payment_id")) == str(payment_id):
            return topup
    return None


def get_topup_by_id(topup_id: str) -> dict | None:
    for topup in load_topups().get("topups", []):
        if str(topup.get("id")) == str(topup_id):
            return topup
    return None


def get_latest_uncredited_topup(user_id: int) -> dict | None:
    topups = [
        topup
        for topup in load_topups().get("topups", [])
        if topup.get("user_id") == user_id and not topup.get("credited")
    ]
    if not topups:
        return None
    return max(topups, key=lambda topup: int(topup.get("created_at", 0)))


def get_pending_invoice_topups() -> list[dict]:
    return [
        topup
        for topup in load_topups().get("topups", [])
        if not topup.get("credited")
        and (
            topup.get("method") == "tap_charge"
            or topup.get("tap_charge_id")
        )
    ]


def update_topup(payment_id: str, updates: dict) -> None:
    data = load_topups()
    for topup in data.get("topups", []):
        if str(topup.get("payment_id")) == str(payment_id):
            topup.update(updates)
            topup["updated_at"] = int(time.time())
            save_topups(data)
            return


def update_topup_by_id(topup_id: str, updates: dict) -> None:
    data = load_topups()
    for topup in data.get("topups", []):
        if str(topup.get("id")) == str(topup_id):
            topup.update(updates)
            topup["updated_at"] = int(time.time())
            save_topups(data)
            return


def add_topup(topup: dict) -> None:
    data = load_topups()
    data["topups"].append(topup)
    save_topups(data)


def get_topup_credit_rate() -> float:
    return parse_amount(os.getenv(TOPUP_CREDIT_RATE_ENV_NAME, "1"), default=1)


def get_tap_secret_key() -> str:
    return os.getenv(TAP_SECRET_KEY_ENV_NAME, "").strip()


def get_tap_currency() -> str:
    return os.getenv(TAP_CURRENCY_ENV_NAME, "SAR").strip().upper() or "SAR"


def get_tap_source_id() -> str:
    return os.getenv(TAP_SOURCE_ID_ENV_NAME, "src_all").strip() or "src_all"


def tap_request(method: str, path: str, payload: dict | None = None) -> dict:
    secret_key = get_tap_secret_key()
    if not secret_key:
        raise RuntimeError(f"Missing {TAP_SECRET_KEY_ENV_NAME} in {ENV_FILE}")

    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(
        f"{TAP_API_BASE}{path}",
        data=data,
        headers={
            "Authorization": f"Bearer {secret_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "StoreBot/1.0",
        },
        method=method,
    )

    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            body = response.read().decode("utf-8")
            return json.loads(body) if body else {}
    except urllib.error.HTTPError as error:
        details = error.read().decode("utf-8", errors="ignore")
        raise RuntimeError(f"Tap Payments HTTP {error.code}: {details[:300]}") from error


def create_tap_charge(user, amount: float) -> dict:
    reference_id = f"TAP-TOPUP-{user.id}-{int(time.time())}-{make_short_id()}"
    first_name = (getattr(user, "first_name", None) or "Telegram").strip()[:40]
    last_name = (getattr(user, "last_name", None) or "User").strip()[:40]
    customer = {
        "first_name": first_name,
        "last_name": last_name,
    }
    customer_email = os.getenv(TAP_CUSTOMER_EMAIL_ENV_NAME, "").strip()
    customer["email"] = customer_email or f"telegram-{user.id}@example.com"

    phone_country_code = os.getenv(TAP_CUSTOMER_PHONE_COUNTRY_CODE_ENV_NAME, "").strip()
    phone_number = os.getenv(TAP_CUSTOMER_PHONE_NUMBER_ENV_NAME, "").strip()
    if phone_country_code and phone_number:
        customer["phone"] = {
            "country_code": phone_country_code,
            "number": phone_number,
        }

    payload = {
        "amount": round(amount, 2),
        "currency": get_tap_currency(),
        "customer_initiated": True,
        "threeDSecure": True,
        "save_card": False,
        "description": f"Wallet top-up for Telegram user {user.id}",
        "metadata": {
            "telegram_user_id": str(user.id),
            "topup_reference": reference_id,
        },
        "reference": {
            "transaction": reference_id,
            "order": reference_id,
        },
        "receipt": {
            "email": False,
            "sms": False,
        },
        "customer": customer,
        "source": {
            "id": get_tap_source_id(),
        },
        "redirect": {
            "url": os.getenv(TAP_REDIRECT_URL_ENV_NAME, "https://example.com").strip()
            or "https://example.com",
        },
    }

    post_url = os.getenv(TAP_POST_URL_ENV_NAME, "").strip()
    if post_url:
        payload["post"] = {"url": post_url}

    charge = tap_request("POST", "/charges/", payload)
    charge.setdefault("reference_id", reference_id)
    return charge


def get_tap_payment_url(charge: dict) -> str:
    transaction = charge.get("transaction")
    if isinstance(transaction, dict) and transaction.get("url"):
        return str(transaction["url"])
    return str(charge.get("redirect_url") or charge.get("url") or "")


def get_tap_charge(charge_id: str) -> dict:
    return tap_request("GET", f"/charges/{charge_id}")


def get_payment_status(data: dict) -> str:
    return str(data.get("payment_status") or data.get("status") or "").lower()


def is_success_payment_status(status: str | None) -> bool:
    return str(status or "").lower() in {"finished", "confirmed", "sending", "completed", "captured"}


def tap_charge_matches_topup(charge: dict, topup: dict) -> bool:
    expected_charge_id = str(topup.get("tap_charge_id") or "")
    if expected_charge_id and str(charge.get("id") or "") == expected_charge_id:
        return True

    expected_reference_id = str(topup.get("order_id") or "")
    reference = charge.get("reference") if isinstance(charge.get("reference"), dict) else {}
    return bool(
        expected_reference_id
        and (
            str(reference.get("transaction") or "") == expected_reference_id
            or str(reference.get("order") or "") == expected_reference_id
        )
    )


def get_verified_tap_topup(topup: dict) -> tuple[str, dict] | None:
    tap_charge_id = str(topup.get("tap_charge_id") or "").strip()
    if not tap_charge_id:
        update_topup_by_id(
            str(topup["id"]),
            {
                "payment_status": get_payment_status(topup) or "waiting",
                "last_check_note": "missing_tap_charge_id",
                "last_checked_at": int(time.time()),
            },
        )
        return None

    charge = get_tap_charge(tap_charge_id)
    status = get_payment_status(charge)
    updates = {
        "payment_status": status or "waiting",
        "raw_status": charge,
        "last_check_note": "checked_tap_charge",
        "last_checked_at": int(time.time()),
    }
    update_topup_by_id(str(topup["id"]), updates)

    if status == "captured" and tap_charge_matches_topup(charge, topup):
        return status, charge

    return None


def get_verified_topup_payment(topup: dict) -> tuple[str, dict] | None:
    if topup.get("method") == "tap_charge":
        return get_verified_tap_topup(topup)

    return None


def create_order_number(data: dict) -> str:
    order_number = f"ORD-{data['next_order_number']:06d}"
    data["next_order_number"] += 1
    return order_number


def add_user_operation(operation: dict) -> dict:
    data = load_user_operations()
    operation.setdefault("id", make_short_id())
    operation.setdefault("created_at", int(time.time()))
    data["operations"].append(operation)
    save_user_operations(data)
    return operation


def add_purchase_operation(
    user_id: int,
    item_type: str,
    item_name: str,
    amount: float,
    source: str,
    details: dict | None = None,
) -> dict:
    data = load_user_operations()
    operation = {
        "id": make_short_id(),
        "type": "purchase",
        "status": "completed",
        "order_number": create_order_number(data),
        "user_id": user_id,
        "item_type": item_type,
        "item_name": item_name,
        "amount": int(amount) if float(amount).is_integer() else amount,
        "source": source,
        "created_at": int(time.time()),
        "details": details or {},
    }
    data["operations"].append(operation)
    save_user_operations(data)
    return operation


def get_user_purchase_operations(user_id: int) -> list[dict]:
    return [
        operation
        for operation in load_user_operations().get("operations", [])
        if operation.get("user_id") == user_id and operation.get("type") == "purchase"
    ]


def get_user_operation(operation_id: str) -> dict | None:
    for operation in load_user_operations().get("operations", []):
        if operation.get("id") == operation_id:
            return operation
    return None


def find_user_operation_by_reservation(category_id: str, item_id: str) -> dict | None:
    data = load_user_operations()
    for operation in reversed(data.get("operations", [])):
        details = operation.get("details", {})
        if (
            operation.get("type") == "reservation"
            and operation.get("status") == "active"
            and details.get("category_id") == category_id
            and details.get("item_id") == item_id
        ):
            return operation
    return None


def update_user_operation(operation_id: str, updates: dict) -> None:
    data = load_user_operations()
    for operation in data.get("operations", []):
        if operation.get("id") == operation_id:
            operation.update(updates)
            operation["updated_at"] = int(time.time())
            save_user_operations(data)
            return


def user_has_active_reservation(user_id: int) -> bool:
    for category in get_username_categories():
        for item in category.get("items", []):
            if item.get("status") != "reserved":
                continue
            reservation = item.get("reservation", {})
            if reservation.get("user_id") == user_id:
                return True
    return False


def get_username_re_reservation_block_remaining(
    user_id: int,
    category_id: str,
    item_id: str,
) -> int:
    data = load_user_operations()
    now = int(time.time())

    for operation in reversed(data.get("operations", [])):
        details = operation.get("details", {})
        if (
            operation.get("type") == "reservation"
            and operation.get("status") == "cancelled"
            and operation.get("user_id") == user_id
            and details.get("category_id") == category_id
            and details.get("item_id") == item_id
        ):
            cancelled_at = int(operation.get("cancelled_at", operation.get("updated_at", 0)))
            remaining = RESERVATION_RECANCEL_BLOCK_SECONDS - (now - cancelled_at)
            return max(remaining, 0)

    return 0


def format_duration_arabic(seconds: int) -> str:
    days = seconds // 86400
    hours = (seconds % 86400) // 3600
    minutes = (seconds % 3600) // 60

    parts = []
    if days:
        parts.append(f"{days} يوم")
    if hours:
        parts.append(f"{hours} ساعة")
    if minutes and not days:
        parts.append(f"{minutes} دقيقة")

    return " و ".join(parts) if parts else "اقل من دقيقة"


def parse_amount(value, default: float = 0) -> float:
    try:
        return float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return default


def save_wallet_to_users_file(user_id: int, wallet: float) -> None:
    users = load_users()
    user = users.setdefault(str(user_id), {})
    user["wallet"] = int(wallet) if float(wallet).is_integer() else wallet
    save_users(users)


def get_user_wallet_from_users_file(user_id: int) -> float:
    users = load_users()
    user = users.get(str(user_id), {})
    return parse_amount(user.get("wallet", 0))


def get_user_wallet(user_id: int) -> float:
    bot_users = load_bot_users()
    bot_user = find_bot_user_entry(bot_users, user_id)
    if bot_user and "amount" in bot_user:
        wallet = parse_amount(bot_user.get("amount"))
        save_wallet_to_users_file(user_id, wallet)
        return wallet

    users = load_users()
    user = users.get(str(user_id), {})
    return parse_amount(user.get("wallet", 0))


def set_user_wallet(user_id: int, wallet: float) -> None:
    save_wallet_to_users_file(user_id, wallet)
    sync_bot_user_amounts(user_id)


def change_user_wallet(user_id: int, amount: float) -> float:
    wallet = get_user_wallet(user_id) + amount
    set_user_wallet(user_id, wallet)
    return wallet


def get_user_display_name(user) -> str:
    if not user:
        return "غير معروف"
    full_name = " ".join(part for part in [user.first_name, user.last_name] if part)
    return full_name or user.username or str(user.id)


def find_bot_user_entry(data: dict, user_id: int) -> dict | None:
    for entry in data.get("users", []):
        if entry.get("id") == user_id:
            return entry
    return None


def sync_bot_user_amounts(user_id: int) -> None:
    data = load_bot_users()
    entry = find_bot_user_entry(data, user_id)
    if not entry:
        return

    entry["amount"] = format_price(get_user_wallet_from_users_file(user_id))
    entry["reserved_amount"] = format_price(get_user_reserved_total(user_id))
    save_bot_users(data)


def register_bot_user(user) -> None:
    if not user:
        return

    data = load_bot_users()
    entry = find_bot_user_entry(data, user.id)
    if not entry:
        entry = {
            "user_number": data["next_number"],
            "name": get_user_display_name(user),
            "username": user.username or "",
            "id": user.id,
            "amount": "0",
            "reserved_amount": "0",
            "first_started_at": int(time.time()),
            "last_started_at": int(time.time()),
        }
        data["users"].append(entry)
        data["next_number"] += 1
    else:
        entry["name"] = get_user_display_name(user)
        entry["username"] = user.username or ""
        entry["last_started_at"] = int(time.time())

    entry["amount"] = format_price(get_user_wallet(user.id))
    entry["reserved_amount"] = format_price(get_user_reserved_total(user.id))
    save_bot_users(data)


def make_short_id() -> str:
    return uuid4().hex[:SHORT_ID_LENGTH]


def load_username_store() -> dict:
    if not os.path.exists(USERNAMES_FILE):
        return {"categories": []}

    with open(USERNAMES_FILE, "r", encoding="utf-8") as usernames_file:
        try:
            store = json.load(usernames_file)
        except json.JSONDecodeError:
            LOGGER.warning("%s is not valid JSON. Starting with an empty store.", USERNAMES_FILE)
            return {"categories": []}

    if not isinstance(store, dict):
        return {"categories": []}
    if not isinstance(store.get("categories"), list):
        store["categories"] = []
    ensure_username_store_ids(store)
    migrate_sold_usernames_to_archive(store)
    return store


def save_username_store(store: dict) -> None:
    with open(USERNAMES_FILE, "w", encoding="utf-8") as usernames_file:
        json.dump(store, usernames_file, ensure_ascii=False, indent=2)


def ensure_username_store_ids(store: dict) -> None:
    changed = False

    for category in store.get("categories", []):
        if not category.get("id") or len(str(category.get("id"))) > SHORT_ID_LENGTH:
            category["id"] = make_short_id()
            changed = True

        if not isinstance(category.get("items"), list):
            category["items"] = []
            changed = True

        for item in category.get("items", []):
            if not item.get("id") or len(str(item.get("id"))) > SHORT_ID_LENGTH:
                item["id"] = make_short_id()
                changed = True

    if changed:
        save_username_store(store)


def migrate_sold_usernames_to_archive(store: dict) -> None:
    archive = load_archive()
    changed = False

    for category in store.get("categories", []):
        active_items = []
        for item in category.get("items", []):
            if item.get("status") != "sold":
                active_items.append(item)
                continue

            archive["sold_usernames"].append(
                {
                    "archived_at": int(time.time()),
                    "order_number": item.get("order_number", "غير معروف"),
                    "buyer_id": item.get("sold_to"),
                    "category_id": category.get("id"),
                    "category_name": category.get("name", "بدون اسم"),
                    "item": item,
                }
            )
            changed = True

        category["items"] = active_items

    if changed:
        save_archive(archive)
        save_username_store(store)


def get_username_categories() -> list[dict]:
    return load_username_store().get("categories", [])


def get_username_category(category_id: str) -> dict | None:
    for category in get_username_categories():
        if category.get("id") == category_id:
            category.setdefault("items", [])
            return category
    return None


def get_username_item(category_id: str, item_id: str) -> dict | None:
    category = get_username_category(category_id)
    if not category:
        return None

    for item in category.get("items", []):
        if item.get("id") == item_id:
            return item
    return None


def update_username_category(category_id: str, updated_category: dict) -> bool:
    store = load_username_store()
    for index, category in enumerate(store.get("categories", [])):
        if category.get("id") == category_id:
            store["categories"][index] = updated_category
            save_username_store(store)
            return True
    return False


def update_username_item(category_id: str, item_id: str, updated_item: dict) -> bool:
    store = load_username_store()
    for category in store.get("categories", []):
        if category.get("id") != category_id:
            continue
        for index, item in enumerate(category.get("items", [])):
            if item.get("id") == item_id:
                category["items"][index] = updated_item
                save_username_store(store)
                return True
    return False


def archive_sold_username(
    category_id: str,
    item_id: str,
    sold_item: dict,
    order_number: str,
    buyer_id: int,
) -> bool:
    store = load_username_store()
    archived = False
    category_name = "بدون اسم"

    for category in store.get("categories", []):
        if category.get("id") != category_id:
            continue

        category_name = category.get("name", "بدون اسم")
        original_items = category.get("items", [])
        category["items"] = [
            item for item in original_items if item.get("id") != item_id
        ]
        archived = len(category["items"]) != len(original_items)
        break

    if not archived:
        return False

    archive = load_archive()
    archive["sold_usernames"].append(
        {
            "archived_at": int(time.time()),
            "order_number": order_number,
            "buyer_id": buyer_id,
            "category_id": category_id,
            "category_name": category_name,
            "item": sold_item,
        }
    )
    save_archive(archive)
    save_username_store(store)
    return True


def get_username_price(item: dict) -> float:
    try:
        return float(item.get("price", 0))
    except (TypeError, ValueError):
        return 0


def get_reservation_deposit(price: float) -> float:
    return round(price / 3, 2)


def get_user_reserved_total(user_id: int) -> float:
    total = 0.0
    for category in get_username_categories():
        for item in category.get("items", []):
            if item.get("status") != "reserved":
                continue
            reservation = item.get("reservation", {})
            if reservation.get("user_id") == user_id:
                total += float(reservation.get("deposit", 0))
    return total


def get_active_user_reservation(user_id: int) -> tuple[str, str, dict] | None:
    for category in get_username_categories():
        for item in category.get("items", []):
            if item.get("status") != "reserved":
                continue
            reservation = item.get("reservation", {})
            if reservation.get("user_id") == user_id:
                return category["id"], item["id"], item
    return None


def get_active_user_reservations(user_id: int) -> list[tuple[str, str, dict, dict]]:
    reservations = []
    for category in get_username_categories():
        for item in category.get("items", []):
            if item.get("status") != "reserved":
                continue
            reservation = item.get("reservation", {})
            if reservation.get("user_id") == user_id:
                reservations.append((category["id"], item["id"], item, reservation))
    return reservations


def ensure_product_ids(products: list[dict]) -> list[dict]:
    changed = False
    for product in products:
        if not product.get("id"):
            product["id"] = uuid4().hex
            changed = True

    if changed:
        save_products(products)

    return products


def get_product(product_id: str) -> dict | None:
    products = ensure_product_ids(load_products())
    for product in products:
        if product.get("id") == product_id:
            return product

    return None


def update_product(product_id: str, updated_product: dict) -> bool:
    products = ensure_product_ids(load_products())
    for index, product in enumerate(products):
        if product.get("id") == product_id:
            products[index] = updated_product
            save_products(products)
            return True

    return False


def delete_product(product_id: str) -> dict | None:
    products = ensure_product_ids(load_products())
    for index, product in enumerate(products):
        if product.get("id") == product_id:
            deleted_product = products.pop(index)
            save_products(products)
            return deleted_product
    return None


def get_delivery_items(product: dict) -> list[dict]:
    delivery_items = product.get("delivery_items")
    if isinstance(delivery_items, list):
        return delivery_items

    old_delivery = product.get("delivery")
    return [old_delivery] if isinstance(old_delivery, dict) else []


def get_product_price(product: dict) -> float:
    try:
        return float(product.get("price", 0))
    except (TypeError, ValueError):
        return 0


def format_price(price: float) -> str:
    return str(int(price)) if float(price).is_integer() else str(price)


def format_timestamp(timestamp: int | float | None) -> str:
    if not timestamp:
        return "غير معروف"
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(float(timestamp)))


def format_date(timestamp: int | float | None) -> str:
    if not timestamp:
        return "غير معروف"
    return time.strftime("%Y-%m-%d", time.localtime(float(timestamp)))


def build_support_message(message, sender: dict) -> dict | None:
    base = {
        "id": make_short_id(),
        "sender": sender,
        "created_at": int(time.time()),
    }
    if message.text:
        base.update({"type": "text", "text": message.text})
        return base
    if message.photo:
        photo = message.photo[-1]
        base.update({"type": "photo", "file_id": photo.file_id, "caption": message.caption or ""})
        return base
    if message.document:
        base.update(
            {
                "type": "document",
                "file_id": message.document.file_id,
                "file_name": message.document.file_name,
                "caption": message.caption or "",
            }
        )
        return base
    if message.video:
        base.update(
            {
                "type": "video",
                "file_id": message.video.file_id,
                "file_name": message.video.file_name,
                "caption": message.caption or "",
            }
        )
        return base
    return None


def support_message_preview(message: dict) -> str:
    sender = message.get("sender", {})
    role = "الدعم" if sender.get("role") in {"admin", "employee"} else "العميل"
    created_at = format_timestamp(message.get("created_at"))
    message_type = message.get("type")
    if message_type == "text":
        content = message.get("text", "")
    elif message_type == "photo":
        content = "🖼️ صورة"
        if message.get("caption"):
            content += f" - {message.get('caption')}"
    elif message_type == "document":
        content = f"📎 ملف: {message.get('file_name', 'بدون اسم')}"
        if message.get("caption"):
            content += f" - {message.get('caption')}"
    elif message_type == "video":
        content = f"🎥 فيديو: {message.get('file_name', 'بدون اسم')}"
        if message.get("caption"):
            content += f" - {message.get('caption')}"
    else:
        content = "رسالة غير معروفة"
    return f"{role} - {created_at}\n{content}"


def format_ticket(ticket: dict, for_staff: bool = False) -> str:
    status = "مغلقة ✅" if ticket.get("status") == "closed" else "مفتوحة ⏳"
    lines = [
        "🎫 تفاصيل التذكرة.",
        "",
        f"🔖 رقم التذكرة: {ticket.get('number', ticket.get('id'))}",
        f"📌 الحالة: {status}",
        f"🏷️ النوع: {ticket.get('category_label', 'دعم')}",
        f"📅 تاريخ الفتح: {format_timestamp(ticket.get('created_at'))}",
    ]
    if for_staff:
        username = f"@{ticket.get('username')}" if ticket.get("username") else "لا يوجد"
        lines.extend(
            [
                "",
                "👤 معلومات العميل:",
                f"الاسم: {ticket.get('user_name', 'غير معروف')}",
                f"اليوزر: {username}",
                f"الايدي: {ticket.get('user_id')}",
            ]
        )

    messages = ticket.get("messages", [])
    lines.extend(["", "💬 آخر الرسائل:"])
    if not messages:
        lines.append("لا توجد رسائل.")
    else:
        for message in messages[-5:]:
            lines.append(support_message_preview(message))
            lines.append("----------")

    return "\n".join(lines).strip("-\n")


def status_icon(status: str | None, credited: bool | None = None) -> str:
    normalized = str(status or "").lower()
    if credited is True:
        return "✅"
    if credited is False:
        if normalized in {"failed", "declined", "cancelled", "canceled", "expired", "refunded"}:
            return "❌"
        return "⏳"
    if normalized in {"completed", "finished", "confirmed", "sending", "captured", "paid"}:
        return "✅"
    if normalized in {"failed", "declined", "cancelled", "canceled", "expired", "refunded"}:
        return "❌"
    return "⏳"


def get_user_topups(user_id: int) -> list[dict]:
    return [
        topup
        for topup in load_topups().get("topups", [])
        if topup.get("user_id") == user_id
    ]


def format_purchase_line(operation: dict) -> str:
    icon = status_icon(operation.get("status"))
    item_name = operation.get("item_name", "منتج بدون اسم")
    amount = format_price(parse_amount(operation.get("amount", 0)))
    return rtl_text(f"{icon} - {item_name} - {amount} ريال")


def format_topup_line(topup: dict) -> str:
    icon = status_icon(topup.get("payment_status"), bool(topup.get("credited")))
    amount = format_price(parse_amount(topup.get("credit_amount", topup.get("amount", 0))))
    date = format_date(topup.get("credited_at") or topup.get("created_at"))
    return rtl_text(f"{icon} - {amount} ريال - {date}")


def format_purchases_and_topups(user_id: int) -> str:
    purchases = get_user_purchase_operations(user_id)
    topups = get_user_topups(user_id)

    lines = ["🧾 العمليات.", "", "🛒 المشتريات:"]
    if purchases:
        lines.extend(format_purchase_line(operation) for operation in reversed(purchases[-5:]))
    else:
        lines.append("📭 لا توجد مشتريات حتى الان.")

    lines.extend(["", "💳 عمليات الشحن:"])
    if topups:
        lines.extend(format_topup_line(topup) for topup in reversed(topups[-5:]))
    else:
        lines.append("📭 لا توجد عمليات شحن حتى الان.")

    return "\n".join(lines)


def format_active_reservations(user_id: int) -> str:
    reservations = get_active_user_reservations(user_id)
    if not reservations:
        return "⏳ الحجوزات.\n\nلا توجد حجوزات حالية."

    lines = ["⏳ الحجوزات الحالية.\n"]
    for category_id, item_id, item, reservation in reservations:
        deposit = format_price(parse_amount(reservation.get("deposit", 0)))
        reserved_at = format_date(reservation.get("reserved_at"))
        expires_at = format_date(reservation.get("expires_at"))
        can_cancel = can_cancel_reservation(reservation)
        action_note = "شراء او الغاء الحجز" if can_cancel else "شراء فقط"
        lines.append(
            rtl_text(
                f"⏳ - {item.get('name', 'يوزر بدون اسم')} - {deposit} ريال\n"
                f"تاريخ الحجز: {reserved_at}\n"
                f"ينتهي الحجز: {expires_at}\n"
                f"الاجراء المتاح: {action_note}"
            )
        )

    return "\n\n".join(lines)


def format_user_operations(user_id: int, view: str = "all") -> str:
    if view == "all":
        return format_purchases_and_topups(user_id)
    if view == "reservations":
        return format_active_reservations(user_id)

    data = load_user_operations()
    allowed_types = {
        "purchases": {"purchase"},
        "reservations": {"reservation"},
        "all": {"purchase", "reservation"},
    }.get(view, {"purchase", "reservation"})
    user_operations = [
        operation
        for operation in data.get("operations", [])
        if operation.get("user_id") == user_id and operation.get("type") in allowed_types
    ]

    if not user_operations:
        empty_titles = {
            "purchases": "المشتريات",
            "reservations": "الحجوزات",
            "all": "العمليات",
        }
        title = empty_titles.get(view, "العمليات")
        icons = {
            "purchases": "🛒",
            "reservations": "⏳",
            "all": "🧾",
        }
        return f"{icons.get(view, '🧾')} {title}.\n\nلا توجد بيانات حتى الان."

    titles = {
        "purchases": "🛒 المشتريات.",
        "reservations": "⏳ الحجوزات.",
        "all": "🧾 العمليات.",
    }
    lines = [f"{titles.get(view, 'العمليات.')}\n"]
    hidden_count = 0
    for operation in reversed(user_operations):
        operation_type = operation.get("type")
        status = operation.get("status", "غير معروف")
        item_name = operation.get("item_name", "عنصر بدون اسم")
        amount = format_price(parse_amount(operation.get("amount", 0)))
        created_at = format_timestamp(operation.get("created_at"))

        if operation_type == "purchase":
            block = (
                f"رقم الطلب: {operation.get('order_number', 'غير متوفر')}\n"
                f"النوع: شراء\n"
                f"الحالة: مكتمل\n"
                f"العنصر: {item_name}\n"
                f"المبلغ: {amount} ريال\n"
                f"التاريخ: {created_at}"
            )
        elif operation_type == "reservation":
            expires_at = format_timestamp(operation.get("expires_at"))
            action_note = ""
            if status == "active":
                details = operation.get("details", {})
                item = get_username_item(details.get("category_id"), details.get("item_id"))
                if item and item.get("status") == "reserved":
                    can_cancel = can_cancel_reservation(item.get("reservation", {}))
                    action_note = (
                        "\nالاجراء المتاح: شراء او الغاء الحجز"
                        if can_cancel
                        else "\nالاجراء المتاح: شراء فقط، وانتهت مدة الغاء الحجز"
                    )
            block = (
                f"النوع: حجز\n"
                f"الحالة: {status}\n"
                f"العنصر: {item_name}\n"
                f"المبلغ المحجوز: {amount} ريال\n"
                f"تاريخ الحجز: {created_at}\n"
                f"ينتهي الحجز: {expires_at}"
                f"{action_note}"
            )
        else:
            continue

        candidate = "\n\n".join(lines + [block])
        if len(candidate) > 3600:
            hidden_count += 1
            continue
        lines.append(block)

    if hidden_count:
        lines.append(f"\nتم اخفاء {hidden_count} عملية قديمة بسبب حد طول رسالة تليجرام.")

    return "\n\n".join(lines)


def get_archived_username_by_order(order_number: str, user_id: int) -> dict | None:
    if not order_number:
        return None

    for archived in load_archive().get("sold_usernames", []):
        if (
            str(archived.get("order_number") or "") == str(order_number)
            and archived.get("buyer_id") == user_id
        ):
            return archived.get("item") if isinstance(archived.get("item"), dict) else None

    return None


def get_purchase_delivery_item(operation: dict) -> dict | None:
    details = operation.get("details") if isinstance(operation.get("details"), dict) else {}
    delivery = details.get("delivery")
    if isinstance(delivery, dict):
        return delivery

    if operation.get("item_type") == "username":
        archived_item = get_archived_username_by_order(
            str(operation.get("order_number") or ""),
            int(operation.get("user_id", 0)),
        )
        if archived_item and isinstance(archived_item.get("delivery"), dict):
            return archived_item["delivery"]

    return None


def format_purchase_details(operation: dict) -> str:
    details = operation.get("details") if isinstance(operation.get("details"), dict) else {}
    delivery = get_purchase_delivery_item(operation)
    delivery_type = delivery.get("type") if isinstance(delivery, dict) else None
    if delivery_type == "text":
        delivery_status = "✅ مرفق داخل هذه الرسالة"
    elif delivery:
        delivery_status = "✅ سيتم ارساله في رسالة منفصلة"
    else:
        delivery_status = "❌ غير محفوظ لهذه العملية"

    lines = [
        "📋 تفاصيل العملية.",
        "",
        "🛒 معلومات الشراء:",
        f"🔖 رقم الطلب: {operation.get('order_number', 'غير متوفر')}",
        f"📅 تاريخ الشراء: {format_date(operation.get('created_at'))}",
        f"💰 السعر: {format_price(parse_amount(operation.get('amount', 0)))} ريال",
        f"📦 اسم المنتج: {operation.get('item_name', 'منتج بدون اسم')}",
        "",
        "🚚 معلومات التسليم:",
        f"📌 حالة التسليم: {delivery_status}",
    ]

    if delivery_type == "text":
        lines.extend(
            [
                "",
                "📨 التسليم:",
                "----------",
                delivery.get("text", ""),
                "----------",
            ]
        )

    if details.get("deposit") is not None:
        lines.append(f"العربون المدفوع: {format_price(parse_amount(details.get('deposit', 0)))} ريال")
    if details.get("remaining_paid") is not None:
        lines.append(f"المبلغ المتبقي المدفوع: {format_price(parse_amount(details.get('remaining_paid', 0)))} ريال")

    return "\n".join(lines)


def format_purchase_delivery_caption(operation: dict) -> str:
    return (
        f"📅 تاريخ الشراء: {format_date(operation.get('created_at'))}\n"
        f"🔖 رقم الطلب: {operation.get('order_number', 'غير متوفر')}\n"
        f"💰 السعر: {format_price(parse_amount(operation.get('amount', 0)))} ريال"
    )


def format_products_menu() -> tuple[str, InlineKeyboardMarkup]:
    products = ensure_product_ids(load_products())
    if not products:
        return "📦 قسم المنتجات الرقمية.\n\nلا توجد منتجات متاحة حاليا.", back_keyboard()

    return "📦 قسم المنتجات الرقمية.\n\nاختر المنتج الذي تريد شراءه:", products_keyboard(products)


def format_product_purchase(product: dict) -> str:
    description = product.get("description") or "لا يوجد وصف"
    quantity = len(get_delivery_items(product))
    price = format_price(get_product_price(product))
    return (
        "📋 تفاصيل المنتج.\n\n"
        f"📦 اسم المنتج: {product.get('name', 'منتج بدون اسم')}\n"
        f"📝 الوصف: {description}\n"
        f"💰 السعر: {price} ريال\n"
        f"📊 الكمية المتوفرة: {quantity}"
    )


def format_products() -> str:
    products = ensure_product_ids(load_products())
    if not products:
        return "📦 قسم المنتجات الرقمية.\n\nلا توجد منتجات متاحة حاليا."

    lines = ["📦 قسم المنتجات الرقمية.\n"]
    for index, product in enumerate(products, start=1):
        description = product.get("description") or "لا يوجد وصف"
        quantity = len(get_delivery_items(product))
        price = format_price(get_product_price(product))
        lines.append(
            f"{index}. {product.get('name', 'منتج بدون اسم')}\n"
            f"📝 الوصف: {description}\n"
            f"💰 السعر: {price} ريال\n"
            f"📊 الكمية المتوفرة: {quantity}"
        )

    return "\n\n".join(lines)


def format_admin_products() -> tuple[str, InlineKeyboardMarkup]:
    products = ensure_product_ids(load_products())
    if not products:
        return (
            "📭 لا توجد منتجات حاليا.\n\n"
            "➕ اضف منتج جديد من لوحة الادمن.",
            back_to_admin_menu_keyboard(),
        )

    lines = ["📋 المنتجات المتوفرة.\n\nاختر منتج لادارة التسليم التلقائي:"]
    return "\n".join(lines), products_admin_keyboard(products)


def format_product_details(product: dict) -> str:
    description = product.get("description") or "لا يوجد وصف"
    quantity = len(get_delivery_items(product))
    delivery_status = "مضاف" if quantity else "غير مضاف"
    price = format_price(get_product_price(product))

    return (
        "📋 تفاصيل المنتج.\n\n"
        f"📦 اسم المنتج: {product.get('name', 'منتج بدون اسم')}\n"
        f"📝 الوصف: {description}\n"
        f"💰 السعر: {price} ريال\n"
        f"🚚 التسليم التلقائي: {delivery_status}\n"
        f"📊 الكمية المتوفرة: {quantity}"
    )


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    register_bot_user(update.effective_user)
    await update.message.reply_text(
        WELCOME_MESSAGE,
        reply_markup=main_menu_keyboard(
            show_admin=is_admin(update),
            show_employee=is_employee(update),
        ),
    )


async def admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not is_admin(update):
        await update.message.reply_text(
            "🔒 هذه القائمة مخصصة للادمن فقط.\n\n"
            f"🆔 معرف حسابك هو: {user.id if user else 'غير معروف'}"
        )
        return

    await update.message.reply_text(
        "🛠️ لوحة الادمن.\n\n"
        "👇 اختر العملية التي تريد تنفيذها:",
        reply_markup=admin_keyboard(),
    )


async def start_add_employee(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    if not is_admin(update):
        await edit_message(query, "🔒 هذه العملية مخصصة للادمن فقط.")
        return ConversationHandler.END

    await edit_message(
        query,
        "👨‍💼 توظيف موظف جديد.\n\n"
        "🆔 ارسل ايدي حساب الموظف في تليجرام:",
        reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton("❌ الغاء", callback_data="cancel_add_employee")]]
        ),
    )
    return EMPLOYEE_ID


async def receive_employee_id(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not is_admin(update):
        await update.message.reply_text("🔒 هذه العملية مخصصة للادمن فقط.")
        return ConversationHandler.END

    raw_employee_id = update.message.text.strip()
    try:
        employee_id = int(raw_employee_id)
    except ValueError:
        await update.message.reply_text("الايدي لازم يكون رقم. ارسل ايدي الموظف:")
        return EMPLOYEE_ID

    data = load_employees()
    for employee in data.get("employees", []):
        if employee.get("id") == employee_id:
            await update.message.reply_text(
                "هذا الموظف موجود مسبقا.",
                reply_markup=admin_employees_keyboard(),
            )
            return ConversationHandler.END

    known_info = get_known_user_info(employee_id)
    data.setdefault("employees", []).append(
        {
            "id": employee_id,
            "name": known_info["name"],
            "username": known_info["username"],
            "added_by": update.effective_user.id,
            "added_at": int(time.time()),
        }
    )
    save_employees(data)

    await update.message.reply_text(
        "✅ تم توظيف الموظف بنجاح.\n\n"
        f"ايدي الموظف: {employee_id}",
        reply_markup=admin_employees_keyboard(),
    )
    return ConversationHandler.END


async def cancel_add_employee(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.callback_query:
        query = update.callback_query
        await query.answer()
        await edit_message(query, "✅ تم الغاء التوظيف.", reply_markup=admin_employees_keyboard())
    else:
        await update.message.reply_text("✅ تم الغاء التوظيف.", reply_markup=admin_employees_keyboard())

    return ConversationHandler.END


async def start_topup_amount(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    if not update.effective_user:
        await edit_message(query, "⚠️ تعذر معرفة المستخدم. حاول مرة اخرى.")
        return ConversationHandler.END

    topup_method = query.data.split(":", 1)[1]
    context.user_data["topup_method"] = topup_method
    method_names = {
        "tap": "Tap Payments",
    }
    method_name = method_names.get(topup_method, "بوابة الدفع")
    await edit_message(
        query,
        f"إضافة أموال عبر {method_name}.\n\n"
        "✍️ اكتب مبلغ الشحن، وبعدها بنرسل لك رابط الدفع:",
        reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton("❌ الغاء", callback_data="cancel_topup")]]
        ),
    )
    return TOPUP_AMOUNT


async def receive_topup_amount(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.effective_user
    if not user:
        await update.message.reply_text("⚠️ تعذر معرفة المستخدم. حاول مرة اخرى.")
        return ConversationHandler.END

    amount = parse_amount(update.message.text.strip(), default=-1)
    if amount <= 0:
        await update.message.reply_text("المبلغ لازم يكون رقم اكبر من 0. اكتب المبلغ مرة ثانية:")
        return TOPUP_AMOUNT

    topup_method = context.user_data.pop("topup_method", None)
    if topup_method != "tap":
        await update.message.reply_text("انتهت جلسة الشحن. ابدأ من المحفظة مرة ثانية.", reply_markup=wallet_keyboard())
        return ConversationHandler.END

    try:
        charge = create_tap_charge(user, amount)
    except Exception as error:
        LOGGER.exception("Failed to create Tap Payments charge")
        await update.message.reply_text(
            "تعذر إنشاء طلب الدفع عبر Tap Payments حاليا.\n\n"
            f"السبب: {error}",
            reply_markup=wallet_keyboard(),
        )
        return ConversationHandler.END

    tap_charge_id = str(charge.get("id") or make_short_id())
    payment_url = get_tap_payment_url(charge)
    if not payment_url:
        LOGGER.error("Tap Payments charge response does not include a payment URL: %s", charge)
        await update.message.reply_text(
            "⚠️ تم إنشاء طلب Tap لكن لم يصل رابط الدفع. حاول مرة ثانية لاحقا.",
            reply_markup=wallet_keyboard(),
        )
        return ConversationHandler.END

    topup = {
        "id": make_short_id(),
        "user_id": user.id,
        "amount": amount,
        "credit_amount": amount * get_topup_credit_rate(),
        "price_currency": get_tap_currency(),
        "method": "tap_charge",
        "tap_charge_id": tap_charge_id,
        "order_id": charge.get("reference_id"),
        "invoice_url": payment_url,
        "payment_status": get_payment_status(charge) or "initiated",
        "credited": False,
        "created_at": int(time.time()),
        "raw_invoice": charge,
    }
    add_topup(topup)

    await update.message.reply_text(
        "✅ تم إنشاء رابط الدفع عبر Tap Payments.\n\n"
        f"رقم العملية: {tap_charge_id}\n"
        f"المبلغ: {format_price(amount)} {get_tap_currency()}\n\n"
        "افتح الرابط وادفع بالبطاقة أو Apple Pay إذا كانت مفعلة في حساب Tap. بعد اكتمال الدفع، البوت سيتحقق تلقائيا ويضيف الرصيد.",
        reply_markup=topup_invoice_keyboard(payment_url, "💸 فتح رابط الدفع"),
    )
    return ConversationHandler.END


async def cancel_topup(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.pop("topup_method", None)
    context.user_data.pop("verify_topup_id", None)

    if update.callback_query:
        query = update.callback_query
        await query.answer()
        await edit_message(query, "✅ تم الغاء طلب الشحن.", reply_markup=wallet_keyboard())
    else:
        await update.message.reply_text("✅ تم الغاء طلب الشحن.", reply_markup=wallet_keyboard())

    return ConversationHandler.END


async def start_add_product(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    if not is_admin(update):
        await edit_message(query, "🔒 هذه العملية مخصصة للادمن فقط.")
        return ConversationHandler.END

    context.user_data["new_product"] = {}
    await edit_message(
        query,
        "اضافة منتج جديد.\n\n"
        "✍️ اكتب اسم المنتج:",
        reply_markup=product_flow_keyboard(),
    )
    return PRODUCT_NAME


async def receive_product_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not is_admin(update):
        await update.message.reply_text("🔒 هذه العملية مخصصة للادمن فقط.")
        return ConversationHandler.END

    name = update.message.text.strip()
    if not name:
        await update.message.reply_text("اسم المنتج لا يمكن يكون فاضي. اكتب اسم المنتج:")
        return PRODUCT_NAME

    context.user_data.setdefault("new_product", {})["name"] = name
    await update.message.reply_text(
        "✍️ اكتب وصف المنتج.\n\n"
        "اذا ما تبي تضيف وصف، ارسل -",
        reply_markup=product_flow_keyboard(),
    )
    return PRODUCT_DESCRIPTION


async def receive_product_description(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not is_admin(update):
        await update.message.reply_text("🔒 هذه العملية مخصصة للادمن فقط.")
        return ConversationHandler.END

    description = update.message.text.strip()
    context.user_data.setdefault("new_product", {})["description"] = (
        "" if description == "-" else description
    )
    await update.message.reply_text(
        "✍️ اكتب سعر المنتج بالريال:",
        reply_markup=product_flow_keyboard(),
    )
    return PRODUCT_PRICE


async def receive_product_price(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not is_admin(update):
        await update.message.reply_text("🔒 هذه العملية مخصصة للادمن فقط.")
        return ConversationHandler.END

    raw_price = update.message.text.strip()
    try:
        price = float(raw_price)
    except ValueError:
        await update.message.reply_text("السعر لازم يكون رقم. مثال: 25 او 19.99")
        return PRODUCT_PRICE

    if price < 0:
        await update.message.reply_text("السعر لازم يكون 0 أو أكثر. اكتب السعر مرة ثانية:")
        return PRODUCT_PRICE

    product = context.user_data.pop("new_product", {})
    product["id"] = uuid4().hex
    product["price"] = int(price) if price.is_integer() else price

    products = load_products()
    products.append(product)
    save_products(products)

    description = product.get("description") or "لا يوجد وصف"
    await update.message.reply_text(
        "تمت اضافة المنتج بنجاح.\n\n"
        f"اسم المنتج: {product['name']}\n"
        f"الوصف: {description}\n"
        f"السعر: {product['price']} ريال",
        reply_markup=admin_keyboard(),
    )
    return ConversationHandler.END


async def cancel_add_product(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.pop("new_product", None)

    if update.callback_query:
        query = update.callback_query
        await query.answer()
        await edit_message(
            query,
            "✅ تم الغاء اضافة المنتج.",
            reply_markup=admin_keyboard(),
        )
    else:
        await update.message.reply_text(
            "✅ تم الغاء اضافة المنتج.",
            reply_markup=admin_keyboard(),
        )

    return ConversationHandler.END


async def start_add_username_category(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    if not is_admin(update):
        await edit_message(query, "🔒 هذه العملية مخصصة للادمن فقط.")
        return ConversationHandler.END

    await edit_message(
        query,
        "اضافة قسم يوزرات جديد.\n\n"
        "✍️ اكتب اسم القسم:",
        reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton("❌ الغاء", callback_data="cancel_username_admin_flow")]]
        ),
    )
    return USERNAME_CATEGORY_NAME


async def receive_username_category_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not is_admin(update):
        await update.message.reply_text("🔒 هذه العملية مخصصة للادمن فقط.")
        return ConversationHandler.END

    name = update.message.text.strip()
    if not name:
        await update.message.reply_text("اسم القسم لا يمكن يكون فاضي. اكتب اسم القسم:")
        return USERNAME_CATEGORY_NAME

    store = load_username_store()
    store.setdefault("categories", []).append({"id": make_short_id(), "name": name, "items": []})
    save_username_store(store)

    await update.message.reply_text(
        "تمت اضافة قسم اليوزرات بنجاح.",
        reply_markup=admin_usernames_keyboard(),
    )
    return ConversationHandler.END


async def start_add_username(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    if not can_manage_usernames(update):
        await edit_message(query, "🚫 هذه العملية غير متاحة لك.")
        return ConversationHandler.END

    category_id = query.data.split(":", 1)[1]
    category = get_username_category(category_id)
    if not category:
        await edit_message(
            query,
            "القسم غير موجود.",
            reply_markup=back_to_admin_username_categories_keyboard(),
        )
        return ConversationHandler.END

    context.user_data["new_username"] = {"category_id": category_id}
    await edit_message(
        query,
        "اضافة يوزر جديد.\n\n"
        f"القسم: {category.get('name', 'قسم بدون اسم')}\n\n"
        "✍️ اكتب اسم اليوزر:",
        reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton("❌ الغاء", callback_data="cancel_username_admin_flow")]]
        ),
    )
    return USERNAME_NAME


async def receive_username_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not can_manage_usernames(update):
        await update.message.reply_text("🚫 هذه العملية غير متاحة لك.")
        return ConversationHandler.END

    name = update.message.text.strip()
    if not name:
        await update.message.reply_text("اسم اليوزر لا يمكن يكون فاضي. اكتب اسم اليوزر:")
        return USERNAME_NAME

    context.user_data.setdefault("new_username", {})["name"] = name
    await update.message.reply_text("✍️ اكتب سعر اليوزر بالريال:")
    return USERNAME_PRICE


async def receive_username_price(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not can_manage_usernames(update):
        await update.message.reply_text("🚫 هذه العملية غير متاحة لك.")
        return ConversationHandler.END

    raw_price = update.message.text.strip()
    try:
        price = float(raw_price)
    except ValueError:
        await update.message.reply_text("السعر لازم يكون رقم. مثال: 250 او 199.99")
        return USERNAME_PRICE

    if price < 0:
        await update.message.reply_text("السعر لازم يكون 0 أو أكثر. اكتب السعر مرة ثانية:")
        return USERNAME_PRICE

    context.user_data.setdefault("new_username", {})["price"] = int(price) if price.is_integer() else price
    await update.message.reply_text(
        "📨 ارسل معلومات اليوزر.\n\n"
    )
    return USERNAME_DELIVERY


def build_delivery_from_message(message) -> dict | None:
    if message.text:
        return {"type": "text", "text": message.text}
    if message.document:
        return {
            "type": "document",
            "file_id": message.document.file_id,
            "file_name": message.document.file_name,
        }
    if message.video:
        return {
            "type": "video",
            "file_id": message.video.file_id,
            "file_name": message.video.file_name,
        }
    return None


async def receive_username_delivery(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not can_manage_usernames(update):
        await update.message.reply_text("🚫 هذه العملية غير متاحة لك.")
        return ConversationHandler.END

    delivery = build_delivery_from_message(update.message)
    if not delivery:
        await update.message.reply_text("📨 ارسل نص، ملف، او مقطع فيديو فقط.")
        return USERNAME_DELIVERY

    new_username = context.user_data.pop("new_username", {})
    category_id = new_username.get("category_id")
    category = get_username_category(category_id) if category_id else None
    if not category:
        await update.message.reply_text(
            "القسم غير موجود.",
            reply_markup=back_to_admin_username_categories_keyboard(),
        )
        return ConversationHandler.END

    item = {
        "id": make_short_id(),
        "name": new_username.get("name", "يوزر بدون اسم"),
        "price": new_username.get("price", 0),
        "delivery": delivery,
        "status": "available",
        "added_by": get_actor_info(
            update.effective_user,
            "admin" if is_admin(update) else "employee",
        ),
        "added_at": int(time.time()),
    }
    category.setdefault("items", []).append(item)
    update_username_category(category_id, category)
    log_staff_operation(
        update.effective_user,
        "admin" if is_admin(update) else "employee",
        "add_username",
        {
            "category_id": category_id,
            "category_name": category.get("name", "قسم بدون اسم"),
            "username_id": item["id"],
            "username_name": item["name"],
            "price": item["price"],
        },
    )

    await update.message.reply_text(
        "تمت اضافة اليوزر بنجاح.\n\n"
        f"اليوزر: {item['name']}\n"
        f"السعر: {format_price(get_username_price(item))} ريال",
        reply_markup=(
            admin_username_category_keyboard(category_id)
            if is_admin(update)
            else employee_username_category_keyboard(category_id)
        ),
    )
    return ConversationHandler.END


async def cancel_username_admin_flow(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.pop("new_username", None)

    if update.callback_query:
        query = update.callback_query
        await query.answer()
        await edit_message(
            query,
            "✅ تم الالغاء.",
            reply_markup=admin_usernames_keyboard() if is_admin(update) else employee_keyboard(),
        )
    else:
        await update.message.reply_text(
            "✅ تم الالغاء.",
            reply_markup=admin_usernames_keyboard() if is_admin(update) else employee_keyboard(),
        )

    return ConversationHandler.END


async def start_delivery(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    if not can_manage_stock(update):
        await edit_message(query, "🚫 هذه العملية غير متاحة لك.")
        return ConversationHandler.END

    product_id = query.data.split(":", 1)[1]
    product = get_product(product_id)
    if not product:
        await edit_message(
            query,
            "المنتج غير موجود.",
            reply_markup=back_to_admin_products_keyboard(),
        )
        return ConversationHandler.END

    context.user_data["delivery_product_id"] = product_id
    await edit_message(
        query,
        "التسليم التلقائي.\n\n"
        f"المنتج: {product.get('name', 'منتج بدون اسم')}\n\n"
        "📨 ارسل نص التسليم التلقائي، او ارسل ملف، او مقطع فيديو.\n"
        "كل رسالة تضيف كمية واحدة للمخزون.",
        reply_markup=delivery_flow_keyboard(),
    )
    return DELIVERY_CONTENT


async def receive_delivery_content(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not can_manage_stock(update):
        await update.message.reply_text("🚫 هذه العملية غير متاحة لك.")
        return ConversationHandler.END

    product_id = context.user_data.get("delivery_product_id")
    product = get_product(product_id) if product_id else None
    if not product:
        await update.message.reply_text(
            "المنتج غير موجود.",
            reply_markup=back_to_admin_products_keyboard(),
        )
        return ConversationHandler.END

    message = update.message
    if message.text:
        delivery = {
            "type": "text",
            "text": message.text,
        }
    elif message.document:
        delivery = {
            "type": "document",
            "file_id": message.document.file_id,
            "file_name": message.document.file_name,
        }
    elif message.video:
        delivery = {
            "type": "video",
            "file_id": message.video.file_id,
            "file_name": message.video.file_name,
        }
    else:
        await message.reply_text("📨 ارسل نص، ملف، او مقطع فيديو فقط.")
        context.user_data["delivery_product_id"] = product_id
        return DELIVERY_CONTENT

    delivery_items = get_delivery_items(product)
    delivery_items.append(delivery)
    product["delivery_items"] = delivery_items
    product.pop("delivery", None)
    update_product(product_id, product)
    log_staff_operation(
        update.effective_user,
        "admin" if is_admin(update) else "employee",
        "add_product_stock",
        {
            "product_id": product_id,
            "product_name": product.get("name", "منتج بدون اسم"),
            "stock_count_after": len(delivery_items),
            "delivery_type": delivery.get("type"),
        },
    )

    await message.reply_text(
        "✅ تم اضافة عنصر تسليم تلقائي للمخزون بنجاح.\n\n"
        f"الكمية المتوفرة الان: {len(delivery_items)}\n\n"
        "📨 ارسل العنصر التالي، او اضغط التوقف عن اضافه التسليم.",
        reply_markup=delivery_flow_keyboard(),
    )
    return DELIVERY_CONTENT


async def stop_delivery(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    product_id = context.user_data.pop("delivery_product_id", None)
    product = get_product(product_id) if product_id else None
    if is_admin(update):
        reply_markup = product_admin_keyboard(product_id) if product_id else admin_keyboard()
    else:
        reply_markup = employee_keyboard()
    quantity = len(get_delivery_items(product)) if product else 0

    if update.callback_query:
        query = update.callback_query
        await query.answer()
        await edit_message(
            query,
            "✅ تم التوقف عن اضافه التسليم التلقائي.\n\n"
            f"الكمية المتوفرة: {quantity}",
            reply_markup=reply_markup,
        )
    else:
        await update.message.reply_text(
            "✅ تم التوقف عن اضافه التسليم التلقائي.\n\n"
            f"الكمية المتوفرة: {quantity}",
            reply_markup=reply_markup,
        )

    return ConversationHandler.END


async def send_delivery_item(update: Update, delivery_item: dict) -> None:
    message = update.callback_query.message
    delivery_type = delivery_item.get("type")

    if delivery_type == "text":
        await message.reply_text(
            f"""
✅ تمت عملية الشراء بنجاح!
----------

{delivery_item.get('text', '')}

----------
نتمنى لك تجربة رائعة, لا تنسى تقيمنا هنا @l2rb5 😍🤍
            """
        )
        return

    if delivery_type == "document":
        await message.reply_document(
            document=delivery_item.get("file_id"),
            caption="تسليم المنتج",
        )
        return

    if delivery_type == "video":
        await message.reply_video(
            video=delivery_item.get("file_id"),
            caption="تسليم المنتج",
        )
        return

    await message.reply_text("✅ تم الشراء، لكن نوع التسليم غير معروف. تواصل مع الدعم.")


async def buy_product(update: Update, context: ContextTypes.DEFAULT_TYPE, product_id: str) -> None:
    query = update.callback_query
    user = update.effective_user

    if not user:
        await edit_message(query, "⚠️ تعذر معرفة المستخدم. حاول مرة اخرى.")
        return

    product = get_product(product_id)
    if not product:
        await edit_message(query, "المنتج غير موجود.", reply_markup=back_keyboard())
        return

    delivery_items = get_delivery_items(product)
    if not delivery_items:
        await edit_message(
            query,
            "المنتج غير متوفر حاليا.\n\n"
            "📭 لا توجد كمية متاحة للتسليم التلقائي.",
            reply_markup=product_purchase_keyboard(product_id),
        )
        return

    price = get_product_price(product)
    admin_purchase = is_admin(update)
    wallet = get_user_wallet(user.id)

    if not admin_purchase and wallet < price:
        await edit_message(
            query,
            "رصيدك غير كافي لاتمام عملية الشراء.\n\n"
            f"سعر المنتج: {format_price(price)} ريال\n"
            f"رصيدك الحالي: {format_price(wallet)} ريال",
            reply_markup=product_purchase_keyboard(product_id),
        )
        return

    delivery_item = delivery_items.pop(0)
    product["delivery_items"] = delivery_items
    product.pop("delivery", None)
    update_product(product_id, product)

    if not admin_purchase:
        set_user_wallet(user.id, wallet - price)

    paid_amount = 0 if admin_purchase else price
    remaining_wallet = get_user_wallet(user.id)
    order = add_purchase_operation(
        user_id=user.id,
        item_type="digital_product",
        item_name=product.get("name", "منتج بدون اسم"),
        amount=paid_amount,
        source="digital_products",
        details={"product_id": product_id, "delivery": delivery_item},
    )
    await notify_staff_about_order(context, user, order)
    await edit_message(
        query,
        "تمت عملية الشراء بنجاح.\n\n"
        f"رقم الطلب: {order['order_number']}\n"
        f"المنتج: {product.get('name', 'منتج بدون اسم')}\n"
        f"المبلغ المخصوم: {format_price(paid_amount)} ريال\n"
        f"رصيدك الحالي: {format_price(remaining_wallet)} ريال\n"
        f"الكمية المتبقية: {len(delivery_items)}",
        reply_markup=back_keyboard(),
    )
    await send_delivery_item(update, delivery_item)


def format_usernames_categories() -> tuple[str, InlineKeyboardMarkup]:
    categories = get_username_categories()
    if not categories:
        return "🔤 قسم اليوزرات.\n\n📭 لا توجد اقسام متاحة حاليا.", back_keyboard()

    return (
        "🔤 قسم اليوزرات.\n\n👇 اختر القسم الذي تريده:",
        username_categories_keyboard(categories, "username_category"),
    )


def format_username_category(category: dict) -> tuple[str, InlineKeyboardMarkup]:
    available_items = [
        item for item in category.get("items", []) if item.get("status", "available") == "available"
    ]
    if not available_items:
        return (
            f"📁 قسم {category.get('name', 'بدون اسم')}.\n\n📭 لا توجد يوزرات متاحة حاليا.",
            back_to_username_categories_keyboard(),
        )

    return (
        f"📁 قسم {category.get('name', 'بدون اسم')}.\n\n👇 اختر اليوزر الذي تريده:",
        usernames_items_keyboard(category),
    )


def format_username_item(category: dict, item: dict) -> str:
    return (
        "تفاصيل اليوزر.\n\n"
        f"القسم: {category.get('name', 'بدون اسم')}\n"
        f"اسم اليوزر: {item.get('name', 'يوزر بدون اسم')}\n"
        f"السعر: {format_price(get_username_price(item))} ريال"
    )


def can_cancel_reservation(reservation: dict) -> bool:
    reserved_at = float(reservation.get("reserved_at", 0))
    return (time.time() - reserved_at) <= RESERVATION_CANCEL_SECONDS


async def buy_username_item(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    category_id: str,
    item_id: str,
) -> None:
    query = update.callback_query
    user = update.effective_user
    item = get_username_item(category_id, item_id)

    if not user:
        await edit_message(query, "⚠️ تعذر معرفة المستخدم. حاول مرة اخرى.")
        return
    if not item:
        await edit_message(query, "اليوزر غير موجود.", reply_markup=back_keyboard())
        return
    if item.get("status", "available") != "available":
        await edit_message(query, "هذا اليوزر غير متاح حاليا.", reply_markup=back_keyboard())
        return

    price = get_username_price(item)
    admin_purchase = is_admin(update)
    wallet = get_user_wallet(user.id)

    if not admin_purchase and wallet < price:
        await edit_message(
            query,
            "رصيدك غير كافي لاتمام الشراء.\n\n"
            f"السعر: {format_price(price)} ريال\n"
            f"رصيدك الحالي: {format_price(wallet)} ريال",
            reply_markup=username_purchase_keyboard(category_id, item_id),
        )
        return

    if not admin_purchase:
        set_user_wallet(user.id, wallet - price)

    item["status"] = "sold"
    item["sold_to"] = user.id
    item["sold_at"] = int(time.time())
    order = add_purchase_operation(
        user_id=user.id,
        item_type="username",
        item_name=item.get("name", "يوزر بدون اسم"),
        amount=0 if admin_purchase else price,
        source="usernames",
        details={
            "category_id": category_id,
            "item_id": item_id,
            "delivery": item.get("delivery", {}),
        },
    )
    archive_sold_username(category_id, item_id, item, order["order_number"], user.id)
    await notify_staff_about_order(context, user, order)
    await edit_message(
        query,
        "✅ تم شراء اليوزر بنجاح.\n\n"
        f"رقم الطلب: {order['order_number']}\n"
        f"اليوزر: {item.get('name', 'يوزر بدون اسم')}\n"
        f"المبلغ المخصوم: {format_price(0 if admin_purchase else price)} ريال\n"
        f"رصيدك الحالي: {format_price(get_user_wallet(user.id))} ريال",
        reply_markup=back_keyboard(),
    )
    await send_delivery_item(update, item.get("delivery", {}))


async def reserve_username_item(update: Update, category_id: str, item_id: str) -> None:
    query = update.callback_query
    user = update.effective_user
    item = get_username_item(category_id, item_id)

    if not user:
        await edit_message(query, "⚠️ تعذر معرفة المستخدم. حاول مرة اخرى.")
        return
    if not item:
        await edit_message(query, "اليوزر غير موجود.", reply_markup=back_keyboard())
        return
    if item.get("status", "available") != "available":
        await edit_message(query, "هذا اليوزر غير متاح للحجز حاليا.", reply_markup=back_keyboard())
        return
    if user_has_active_reservation(user.id):
        await edit_message(
            query,
            "لديك حجز نشط بالفعل.\n\n"
            "يمكن لكل مستخدم امتلاك حجز واحد فقط. اكمل شراء الحجز الحالي او قم بالغائه اذا كان الالغاء متاحا.",
            reply_markup=back_keyboard(),
        )
        return
    block_remaining = get_username_re_reservation_block_remaining(user.id, category_id, item_id)
    if block_remaining:
        await edit_message(
            query,
            "لا يمكنك حجز نفس اليوزر مرة اخرى حاليا.\n\n"
            "بعد الغاء الحجز، يجب الانتظار يومين قبل حجز نفس اليوزر مرة ثانية.\n"
            f"الوقت المتبقي: {format_duration_arabic(block_remaining)}",
            reply_markup=username_purchase_keyboard(category_id, item_id),
        )
        return

    price = get_username_price(item)
    deposit = get_reservation_deposit(price)
    wallet = get_user_wallet(user.id)
    if wallet < deposit:
        await edit_message(
            query,
            "رصيدك غير كافي لحجز اليوزر.\n\n"
            f"قيمة الحجز: {format_price(deposit)} ريال\n"
            f"رصيدك الحالي: {format_price(wallet)} ريال",
            reply_markup=username_purchase_keyboard(category_id, item_id),
        )
        return

    now = int(time.time())
    set_user_wallet(user.id, wallet - deposit)
    item["status"] = "reserved"
    item["reservation"] = {
        "user_id": user.id,
        "username": user.username,
        "deposit": deposit,
        "reserved_at": now,
        "expires_at": now + RESERVATION_SECONDS,
    }
    update_username_item(category_id, item_id, item)
    add_user_operation(
        {
            "type": "reservation",
            "status": "active",
            "user_id": user.id,
            "item_type": "username",
            "item_name": item.get("name", "يوزر بدون اسم"),
            "amount": deposit,
            "expires_at": now + RESERVATION_SECONDS,
            "details": {
                "category_id": category_id,
                "item_id": item_id,
                "full_price": price,
                "remaining": price - deposit,
            },
        }
    )
    sync_bot_user_amounts(user.id)

    remaining = price - deposit
    await edit_message(
        query,
        "✅ تم حجز اليوزر بنجاح.\n\n"
        f"اليوزر: {item.get('name', 'يوزر بدون اسم')}\n"
        f"قيمة اليوزر: {format_price(price)} ريال\n"
        f"✅ تم خصم ثلث القيمة للحجز: {format_price(deposit)} ريال\n"
        f"المتبقي عند الشراء: {format_price(remaining)} ريال\n\n"
        "مدة الحجز 24 ساعة. يمكنك ادارة الحجز من زر العمليات. الغاء الحجز متاح خلال ساعة واحدة فقط، وبعدها يبقى المبلغ محجوزا حتى يحرره الادمن.",
        reply_markup=username_reserved_keyboard(category_id, item_id, can_cancel=True),
    )


async def cancel_username_reservation(update: Update, category_id: str, item_id: str) -> None:
    query = update.callback_query
    user = update.effective_user
    item = get_username_item(category_id, item_id)

    if not user or not item or item.get("status") != "reserved":
        await edit_message(query, "لا يوجد حجز نشط لهذا اليوزر.", reply_markup=back_keyboard())
        return

    reservation = item.get("reservation", {})
    if reservation.get("user_id") != user.id:
        await edit_message(query, "هذا الحجز ليس لك.", reply_markup=back_keyboard())
        return
    if not can_cancel_reservation(reservation):
        await edit_message(
            query,
            "انتهت مدة الغاء الحجز.\n\n"
            "الغاء الحجز متاح لمدة ساعة واحدة فقط. المبلغ سيبقى محجوزا حتى يحرره الادمن.",
            reply_markup=username_reserved_keyboard(category_id, item_id, can_cancel=False),
        )
        return

    deposit = float(reservation.get("deposit", 0))
    change_user_wallet(user.id, deposit)
    item["status"] = "available"
    item.pop("reservation", None)
    update_username_item(category_id, item_id, item)
    reservation_operation = find_user_operation_by_reservation(category_id, item_id)
    if reservation_operation:
        update_user_operation(
            reservation_operation["id"],
            {"status": "cancelled", "cancelled_at": int(time.time())},
        )
    sync_bot_user_amounts(user.id)

    await edit_message(
        query,
        "✅ تم الغاء الحجز واعادة المبلغ الى محفظتك.\n\n"
        f"المبلغ المعاد: {format_price(deposit)} ريال\n"
        f"رصيدك الحالي: {format_price(get_user_wallet(user.id))} ريال",
        reply_markup=back_keyboard(),
    )


async def buy_reserved_username(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    category_id: str,
    item_id: str,
) -> None:
    query = update.callback_query
    user = update.effective_user
    item = get_username_item(category_id, item_id)

    if not user or not item or item.get("status") != "reserved":
        await edit_message(query, "لا يوجد حجز نشط لهذا اليوزر.", reply_markup=back_keyboard())
        return

    reservation = item.get("reservation", {})
    if reservation.get("user_id") != user.id:
        await edit_message(query, "هذا الحجز ليس لك.", reply_markup=back_keyboard())
        return

    price = get_username_price(item)
    deposit = float(reservation.get("deposit", 0))
    remaining = max(price - deposit, 0)
    wallet = get_user_wallet(user.id)
    if wallet < remaining:
        await edit_message(
            query,
            "رصيدك غير كافي لاكمال الشراء.\n\n"
            f"المتبقي: {format_price(remaining)} ريال\n"
            f"رصيدك الحالي: {format_price(wallet)} ريال",
            reply_markup=username_reserved_keyboard(
                category_id,
                item_id,
                can_cancel=can_cancel_reservation(reservation),
            ),
        )
        return

    set_user_wallet(user.id, wallet - remaining)
    reservation_operation = find_user_operation_by_reservation(category_id, item_id)
    if reservation_operation:
        update_user_operation(
            reservation_operation["id"],
            {"status": "completed", "completed_at": int(time.time())},
        )
    item["status"] = "sold"
    item["sold_to"] = user.id
    item["sold_at"] = int(time.time())
    item.pop("reservation", None)
    order = add_purchase_operation(
        user_id=user.id,
        item_type="username",
        item_name=item.get("name", "يوزر بدون اسم"),
        amount=price,
        source="username_reservation",
        details={
            "category_id": category_id,
            "item_id": item_id,
            "deposit": deposit,
            "remaining_paid": remaining,
            "delivery": item.get("delivery", {}),
        },
    )
    archive_sold_username(category_id, item_id, item, order["order_number"], user.id)
    sync_bot_user_amounts(user.id)
    await notify_staff_about_order(context, user, order)

    await edit_message(
        query,
        "✅ تم اكمال شراء اليوزر بنجاح.\n\n"
        f"رقم الطلب: {order['order_number']}\n"
        f"اليوزر: {item.get('name', 'يوزر بدون اسم')}\n"
        f"المبلغ المخصوم الان: {format_price(remaining)} ريال\n"
        f"رصيدك الحالي: {format_price(get_user_wallet(user.id))} ريال",
        reply_markup=back_keyboard(),
    )
    await send_delivery_item(update, item.get("delivery", {}))


def format_admin_reservations() -> tuple[str, InlineKeyboardMarkup]:
    categories = get_username_categories()
    keyboard = []
    lines = ["الحجوزات الحالية:"]
    count = 0

    for category in categories:
        for item in category.get("items", []):
            if item.get("status") != "reserved":
                continue
            count += 1
            reservation = item.get("reservation", {})
            lines.append(
                f"\n{count}. {item.get('name', 'يوزر بدون اسم')}\n"
                f"القسم: {category.get('name', 'بدون اسم')}\n"
                f"ايدي العميل: {reservation.get('user_id')}\n"
                f"المبلغ المحجوز: {format_price(float(reservation.get('deposit', 0)))} ريال"
            )
            keyboard.append(
                [
                    InlineKeyboardButton(
                        f"🔓 تحرير حجز {item.get('name', 'يوزر')}",
                        callback_data=f"release_username:{category['id']}:{item['id']}",
                    )
                ]
            )

    if not count:
        return "📭 لا توجد حجوزات حاليا.", back_to_admin_usernames_keyboard()

    keyboard.append([InlineKeyboardButton("↩️ رجوع", callback_data="admin_usernames")])
    return "\n".join(lines), InlineKeyboardMarkup(keyboard)


async def release_username_reservation(update: Update, category_id: str, item_id: str) -> None:
    query = update.callback_query
    item = get_username_item(category_id, item_id)
    if not item or item.get("status") != "reserved":
        await edit_message(
            query,
            "لا يوجد حجز نشط لهذا اليوزر.",
            reply_markup=back_to_admin_usernames_keyboard(),
        )
        return

    reservation = item.get("reservation", {})
    user_id = reservation.get("user_id")
    deposit = float(reservation.get("deposit", 0))
    if user_id:
        change_user_wallet(int(user_id), deposit)

    item["status"] = "available"
    item.pop("reservation", None)
    update_username_item(category_id, item_id, item)
    reservation_operation = find_user_operation_by_reservation(category_id, item_id)
    if reservation_operation:
        update_user_operation(
            reservation_operation["id"],
            {"status": "released_by_admin", "released_at": int(time.time())},
        )
    if user_id:
        sync_bot_user_amounts(int(user_id))

    await edit_message(
        query,
        "✅ تم تحرير الحجز واعادة المبلغ للعميل.\n\n"
        f"اليوزر: {item.get('name', 'يوزر بدون اسم')}\n"
        f"المبلغ المعاد: {format_price(deposit)} ريال",
        reply_markup=back_to_admin_usernames_keyboard(),
    )


async def edit_message(query, text: str, reply_markup: InlineKeyboardMarkup | None = None) -> None:
    try:
        await query.edit_message_text(text, reply_markup=reply_markup)
    except BadRequest as error:
        if "Message is not modified" in str(error):
            return
        raise


def format_order_customer(user) -> str:
    if not user:
        return "غير معروف"

    name = get_user_display_name(user)
    username = f"@{user.username}" if user.username else "لا يوجد"
    return f"{name} | {username} | {user.id}"


async def notify_staff_about_order(
    context: ContextTypes.DEFAULT_TYPE,
    user,
    order: dict,
) -> None:
    item_type_label = {
        "digital_product": "منتج رقمي",
        "username": "يوزر",
    }.get(order.get("item_type"), order.get("item_type", "غير معروف"))
    source_label = {
        "digital_products": "قسم المنتجات الرقمية",
        "usernames": "قسم اليوزرات",
        "username_reservation": "شراء حجز يوزر",
    }.get(order.get("source"), order.get("source", "غير معروف"))
    amount = format_price(parse_amount(order.get("amount", 0)))
    text = (
        "🛒 طلب جديد وصل.\n\n"
        f"🔖 رقم الطلب: {order.get('order_number', 'غير متوفر')}\n"
        f"📦 النوع: {item_type_label}\n"
        f"🏷️ القسم: {source_label}\n"
        f"📝 المنتج: {order.get('item_name', 'عنصر بدون اسم')}\n"
        f"💰 المبلغ: {amount} ريال\n"
        f"👤 العميل: {format_order_customer(user)}"
    )

    for staff_id in get_staff_ids():
        try:
            await context.bot.send_message(chat_id=staff_id, text=text)
        except Exception:
            LOGGER.exception(
                "Failed to notify staff %s about order %s",
                staff_id,
                order.get("order_number"),
            )


async def notify_staff_about_ticket(
    context: ContextTypes.DEFAULT_TYPE,
    ticket: dict,
    title: str = "🎫 تذكرة دعم جديدة.",
    messages: list[dict] | None = None,
) -> None:
    text = (
        f"{title}\n\n"
        f"🔖 رقم التذكرة: {ticket.get('number')}\n"
        f"🏷️ النوع: {ticket.get('category_label')}\n"
        f"👤 العميل: {ticket.get('user_name')} ({ticket.get('user_id')})"
    )
    reply_markup = InlineKeyboardMarkup(
        [[InlineKeyboardButton("📂 فتح التذكرة", callback_data=f"staff_ticket:{ticket['id']}")]]
    )
    for staff_id in get_staff_ids():
        try:
            await context.bot.send_message(chat_id=int(staff_id), text=text, reply_markup=reply_markup)
            for support_message in (messages or [])[-5:]:
                await send_support_message_to_user(
                    context,
                    int(staff_id),
                    support_message,
                    f"📨 رسالة داخل التذكرة {ticket.get('number')}:",
                )
        except Exception:
            LOGGER.exception("Failed to notify staff %s about ticket %s", staff_id, ticket.get("id"))


async def send_support_message_to_user(context: ContextTypes.DEFAULT_TYPE, user_id: int, message: dict, prefix: str) -> None:
    message_type = message.get("type")
    caption = prefix
    if message.get("caption"):
        caption += f"\n\n{message.get('caption')}"
    try:
        if message_type == "text":
            await context.bot.send_message(chat_id=user_id, text=f"{prefix}\n\n{message.get('text', '')}")
        elif message_type == "photo":
            await context.bot.send_photo(chat_id=user_id, photo=message.get("file_id"), caption=caption)
        elif message_type == "document":
            await context.bot.send_document(chat_id=user_id, document=message.get("file_id"), caption=caption)
        elif message_type == "video":
            await context.bot.send_video(chat_id=user_id, video=message.get("file_id"), caption=caption)
    except Exception:
        LOGGER.exception("Failed to send support message to user %s", user_id)


async def start_support_ticket(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    register_bot_user(update.effective_user)

    category = query.data.split(":", 1)[1]
    context.user_data["support_category"] = category
    context.user_data["support_messages"] = []
    context.user_data.pop("support_ticket_id", None)

    await edit_message(
        query,
        "🎫 فتح تذكرة دعم.\n\n"
        f"🏷️ النوع: {SUPPORT_CATEGORIES.get(category, 'دعم')}\n\n"
        "📨 ارسل شرح المشكلة، ويمكنك ارسال صور او ملفات ايضا.\n"
        "بعد ما تكمل، اضغط زر إنشاء التذكرة.",
        reply_markup=support_collect_keyboard(),
    )
    return SUPPORT_MESSAGE


async def start_add_support_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    ticket_id = query.data.split(":", 1)[1]
    ticket = get_ticket(ticket_id)
    if not ticket or ticket.get("user_id") != query.from_user.id:
        await edit_message(query, "❌ التذكرة غير موجودة.", reply_markup=support_keyboard())
        return ConversationHandler.END
    if ticket.get("status") == "closed":
        await edit_message(query, "🔒 هذه التذكرة مغلقة ولا يمكن إضافة رد.", reply_markup=user_ticket_keyboard(ticket))
        return ConversationHandler.END

    context.user_data["support_ticket_id"] = ticket_id
    context.user_data["support_messages"] = []
    context.user_data.pop("support_category", None)
    await edit_message(
        query,
        f"➕ إضافة رد على التذكرة {ticket.get('number')}.\n\n"
        "📨 ارسل ردك نصا او صورة او ملف، ثم اضغط إرسال.",
        reply_markup=support_collect_keyboard(),
    )
    return SUPPORT_MESSAGE


async def receive_support_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.effective_user
    message = build_support_message(update.message, get_actor_info(user, "customer"))
    if not message:
        await update.message.reply_text("📨 ارسل نص، صورة، ملف، او فيديو فقط.")
        return SUPPORT_MESSAGE

    context.user_data.setdefault("support_messages", []).append(message)
    count = len(context.user_data["support_messages"])
    await update.message.reply_text(
        f"✅ تم استلام الرسالة رقم {count}.\n\n"
        "📨 يمكنك ارسال المزيد، أو اضغط إنشاء التذكرة / إرسال.",
        reply_markup=support_collect_keyboard(),
    )
    return SUPPORT_MESSAGE


async def finish_support_ticket(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    user = update.effective_user
    messages = context.user_data.get("support_messages", [])
    if not messages:
        await edit_message(query, "⚠️ ارسل رسالة واحدة على الأقل قبل إنشاء التذكرة.", reply_markup=support_collect_keyboard())
        return SUPPORT_MESSAGE

    ticket_id = context.user_data.pop("support_ticket_id", None)
    if ticket_id:
        ticket = get_ticket(ticket_id)
        if not ticket or ticket.get("user_id") != user.id:
            await edit_message(query, "❌ التذكرة غير موجودة.", reply_markup=support_keyboard())
            return ConversationHandler.END
        for message in messages:
            ticket = add_ticket_message(ticket_id, message) or ticket
        context.user_data.pop("support_messages", None)
        await notify_staff_about_ticket(context, ticket, "💬 رد جديد من العميل.", messages)
        await edit_message(query, "✅ تم إرسال ردك داخل التذكرة.", reply_markup=user_ticket_keyboard(ticket))
        return ConversationHandler.END

    category = context.user_data.pop("support_category", "other")
    ticket = create_support_ticket(user, category, messages)
    context.user_data.pop("support_messages", None)
    await notify_staff_about_ticket(context, ticket, messages=messages)
    await edit_message(
        query,
        "✅ تم إنشاء تذكرتك بنجاح.\n\n"
        f"🔖 رقم التذكرة: {ticket.get('number')}\n"
        "سيتم الرد عليك من فريق الدعم قريبا.",
        reply_markup=user_ticket_keyboard(ticket),
    )
    return ConversationHandler.END


async def cancel_support_ticket(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.pop("support_category", None)
    context.user_data.pop("support_messages", None)
    context.user_data.pop("support_ticket_id", None)
    if update.callback_query:
        query = update.callback_query
        await query.answer()
        await edit_message(query, "❌ تم إلغاء العملية.", reply_markup=support_keyboard())
    else:
        await update.message.reply_text("❌ تم إلغاء العملية.", reply_markup=support_keyboard())
    return ConversationHandler.END


async def start_staff_ticket_reply(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    if not (is_admin(update) or is_employee(update)):
        await edit_message(query, "🔒 هذه القائمة مخصصة للادمن والموظفين فقط.")
        return ConversationHandler.END

    ticket_id = query.data.split(":", 1)[1]
    ticket = get_ticket(ticket_id)
    if not ticket:
        await edit_message(query, "❌ التذكرة غير موجودة.", reply_markup=staff_tickets_keyboard())
        return ConversationHandler.END
    if ticket.get("status") == "closed":
        await edit_message(query, "🔒 هذه التذكرة مغلقة.", reply_markup=staff_ticket_keyboard(ticket))
        return ConversationHandler.END

    context.user_data["staff_reply_ticket_id"] = ticket_id
    await edit_message(
        query,
        f"✍️ الرد على التذكرة {ticket.get('number')}.\n\n"
        "📨 ارسل الرد نصا او صورة او ملف.",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ الغاء", callback_data="cancel_staff_ticket_reply")]]),
    )
    return SUPPORT_REPLY_MESSAGE


async def receive_staff_ticket_reply(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not (is_admin(update) or is_employee(update)):
        await update.message.reply_text("🔒 هذه القائمة مخصصة للادمن والموظفين فقط.")
        return ConversationHandler.END

    ticket_id = context.user_data.pop("staff_reply_ticket_id", None)
    ticket = get_ticket(ticket_id) if ticket_id else None
    if not ticket:
        await update.message.reply_text("❌ التذكرة غير موجودة.", reply_markup=staff_tickets_keyboard())
        return ConversationHandler.END

    role = "admin" if is_admin(update) else "employee"
    message = build_support_message(update.message, get_actor_info(update.effective_user, role))
    if not message:
        await update.message.reply_text("📨 ارسل نص، صورة، ملف، او فيديو فقط.")
        context.user_data["staff_reply_ticket_id"] = ticket_id
        return SUPPORT_REPLY_MESSAGE

    ticket = add_ticket_message(ticket_id, message) or ticket
    await send_support_message_to_user(
        context,
        int(ticket["user_id"]),
        message,
        f"💬 رد الدعم على التذكرة {ticket.get('number')}:",
    )
    await update.message.reply_text("✅ تم إرسال الرد للعميل.", reply_markup=staff_ticket_keyboard(ticket))
    return ConversationHandler.END


async def cancel_staff_ticket_reply(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.pop("staff_reply_ticket_id", None)
    if update.callback_query:
        query = update.callback_query
        await query.answer()
        await edit_message(query, "❌ تم إلغاء الرد.", reply_markup=staff_tickets_keyboard())
    else:
        await update.message.reply_text("❌ تم إلغاء الرد.", reply_markup=staff_tickets_keyboard())
    return ConversationHandler.END


async def handle_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    user = update.effective_user
    await query.answer()

    if query.data == "main_menu":
        await edit_message(
            query,
            WELCOME_MESSAGE,
            reply_markup=main_menu_keyboard(
                show_admin=is_admin(update),
                show_employee=is_employee(update),
            ),
        )
        return

    if query.data == "admin_menu":
        if not is_admin(update):
            await edit_message(query, "🔒 هذه القائمة مخصصة للادمن فقط.")
            return

        await edit_message(
            query,
            "لوحة الادمن.\n\n"
            "👇 اختر العملية التي تريد تنفيذها:",
            reply_markup=admin_keyboard(),
        )
        return

    if query.data == "admin_employees":
        if not is_admin(update):
            await edit_message(query, "🔒 هذه القائمة مخصصة للادمن فقط.")
            return

        await edit_message(
            query,
            "إدارة الموظفين.\n\n"
            "👇 اختر العملية التي تريد تنفيذها:",
            reply_markup=admin_employees_keyboard(),
        )
        return

    if query.data == "admin_show_employees":
        if not is_admin(update):
            await edit_message(query, "🔒 هذه القائمة مخصصة للادمن فقط.")
            return

        employees = load_employees().get("employees", [])
        if not employees:
            await edit_message(
                query,
                "لا يوجد موظفين حاليا.",
                reply_markup=admin_employees_keyboard(),
            )
            return

        await edit_message(
            query,
            "الموظفين.\n\n"
            "👇 اختر موظف لعرض الاحصائيات او الحذف:",
            reply_markup=employees_keyboard(),
        )
        return

    if query.data.startswith("admin_employee:"):
        if not is_admin(update):
            await edit_message(query, "🔒 هذه القائمة مخصصة للادمن فقط.")
            return

        employee_id = int(query.data.split(":", 1)[1])
        employee = get_employee(employee_id)
        if not employee:
            await edit_message(
                query,
                "الموظف غير موجود.",
                reply_markup=admin_employees_keyboard(),
            )
            return

        await edit_message(
            query,
            format_employee_details(employee),
            reply_markup=employee_details_keyboard(employee_id),
        )
        return

    if query.data.startswith("admin_delete_employee:"):
        if not is_admin(update):
            await edit_message(query, "🔒 هذه العملية مخصصة للادمن فقط.")
            return

        employee_id = int(query.data.split(":", 1)[1])
        deleted_employee = delete_employee(employee_id)
        if not deleted_employee:
            await edit_message(
                query,
                "الموظف غير موجود.",
                reply_markup=admin_employees_keyboard(),
            )
            return

        await edit_message(
            query,
            "✅ تم حذف الموظف بنجاح.\n\n"
            f"الموظف: {employee_display_name(deleted_employee)}",
            reply_markup=admin_employees_keyboard(),
        )
        return

    if query.data == "employee_menu":
        if not is_employee(update):
            await edit_message(query, "🔒 هذه القائمة مخصصة للموظفين فقط.")
            return

        await edit_message(
            query,
            "لوحة الموظف.\n\n"
            "👇 اختر العملية التي تريد تنفيذها:",
            reply_markup=employee_keyboard(),
        )
        return

    if query.data == "employee_products":
        if not is_employee(update):
            await edit_message(query, "🔒 هذه القائمة مخصصة للموظفين فقط.")
            return

        products = ensure_product_ids(load_products())
        if not products:
            await edit_message(
                query,
                "📭 لا توجد منتجات حاليا.",
                reply_markup=employee_keyboard(),
            )
            return

        await edit_message(
            query,
            "👇 اختر المنتج الذي تريد اضافة مخزون له:",
            reply_markup=employee_products_keyboard(products),
        )
        return

    if query.data == "employee_username_categories":
        if not is_employee(update):
            await edit_message(query, "🔒 هذه القائمة مخصصة للموظفين فقط.")
            return

        categories = get_username_categories()
        if not categories:
            await edit_message(
                query,
                "📭 لا توجد اقسام يوزرات حاليا.",
                reply_markup=employee_keyboard(),
            )
            return

        await edit_message(
            query,
            "👇 اختر القسم الذي تريد اضافة يوزر داخله:",
            reply_markup=employee_username_categories_keyboard(categories),
        )
        return

    if query.data.startswith("employee_username_category:"):
        if not is_employee(update):
            await edit_message(query, "🔒 هذه القائمة مخصصة للموظفين فقط.")
            return

        category_id = query.data.split(":", 1)[1]
        category = get_username_category(category_id)
        if not category:
            await edit_message(
                query,
                "القسم غير موجود.",
                reply_markup=employee_username_categories_keyboard(get_username_categories()),
            )
            return

        await edit_message(
            query,
            f"قسم: {category.get('name', 'بدون اسم')}\n\n"
            "يمكنك اضافة يوزر جديد داخل هذا القسم.",
            reply_markup=employee_username_category_keyboard(category_id),
        )
        return

    if query.data == "admin_show_products":
        if not is_admin(update):
            await edit_message(query, "🔒 هذه القائمة مخصصة للادمن فقط.")
            return

        text, reply_markup = format_admin_products()
        await edit_message(query, text, reply_markup=reply_markup)
        return

    if query.data == "admin_usernames":
        if not is_admin(update):
            await edit_message(query, "🔒 هذه القائمة مخصصة للادمن فقط.")
            return

        await edit_message(
            query,
            "قسم اليوزرات.\n\n"
            "👇 اختر العملية التي تريد تنفيذها:",
            reply_markup=admin_usernames_keyboard(),
        )
        return

    if query.data == "admin_username_categories":
        if not is_admin(update):
            await edit_message(query, "🔒 هذه القائمة مخصصة للادمن فقط.")
            return

        categories = get_username_categories()
        if not categories:
            await edit_message(
                query,
                "📭 لا توجد اقسام يوزرات حاليا.\n\nاضف قسم جديد اولا.",
                reply_markup=back_to_admin_usernames_keyboard(),
            )
            return

        await edit_message(
            query,
            "👇 اختر القسم الذي تريد ادارته:",
            reply_markup=username_categories_keyboard(categories, "admin_username_category"),
        )
        return

    if query.data.startswith("admin_username_category:"):
        if not is_admin(update):
            await edit_message(query, "🔒 هذه القائمة مخصصة للادمن فقط.")
            return

        category_id = query.data.split(":", 1)[1]
        category = get_username_category(category_id)
        if not category:
            await edit_message(
                query,
                "القسم غير موجود.",
                reply_markup=back_to_admin_username_categories_keyboard(),
            )
            return

        await edit_message(
            query,
            f"قسم: {category.get('name', 'بدون اسم')}\n\n"
            f"عدد اليوزرات: {len(category.get('items', []))}",
            reply_markup=admin_username_category_keyboard(category_id),
        )
        return

    if query.data == "admin_username_reservations":
        if not is_admin(update):
            await edit_message(query, "🔒 هذه القائمة مخصصة للادمن فقط.")
            return

        text, reply_markup = format_admin_reservations()
        await edit_message(query, text, reply_markup=reply_markup)
        return

    if query.data.startswith("release_username:"):
        if not is_admin(update):
            await edit_message(query, "🔒 هذه العملية مخصصة للادمن فقط.")
            return

        _, category_id, item_id = query.data.split(":", 2)
        await release_username_reservation(update, category_id, item_id)
        return

    if query.data.startswith("admin_delete_product:"):
        if not is_admin(update):
            await edit_message(query, "🔒 هذه العملية مخصصة للادمن فقط.")
            return

        product_id = query.data.split(":", 1)[1]
        deleted_product = delete_product(product_id)
        if not deleted_product:
            await edit_message(
                query,
                "المنتج غير موجود.",
                reply_markup=back_to_admin_products_keyboard(),
            )
            return

        await edit_message(
            query,
            "✅ تم حذف المنتج بنجاح.\n\n"
            f"المنتج: {deleted_product.get('name', 'منتج بدون اسم')}",
            reply_markup=admin_keyboard(),
        )
        return

    if query.data.startswith("admin_product:"):
        if not is_admin(update):
            await edit_message(query, "🔒 هذه القائمة مخصصة للادمن فقط.")
            return

        product_id = query.data.split(":", 1)[1]
        product = get_product(product_id)
        if not product:
            await edit_message(
                query,
                "المنتج غير موجود.",
                reply_markup=back_to_admin_products_keyboard(),
            )
            return

        await edit_message(
            query,
            format_product_details(product),
            reply_markup=product_admin_keyboard(product_id),
        )
        return

    if query.data == "digital_products":
        text, reply_markup = format_products_menu()
        await edit_message(
            query,
            text,
            reply_markup=reply_markup,
        )
        return

    if query.data == "usernames":
        text, reply_markup = format_usernames_categories()
        await edit_message(query, text, reply_markup=reply_markup)
        return

    if query.data.startswith("username_category:"):
        category_id = query.data.split(":", 1)[1]
        category = get_username_category(category_id)
        if not category:
            await edit_message(query, "القسم غير موجود.", reply_markup=back_keyboard())
            return

        text, reply_markup = format_username_category(category)
        await edit_message(query, text, reply_markup=reply_markup)
        return

    if query.data.startswith("username_item:"):
        _, category_id, item_id = query.data.split(":", 2)
        category = get_username_category(category_id)
        item = get_username_item(category_id, item_id)
        if not category:
            await edit_message(query, "القسم غير موجود.", reply_markup=back_keyboard())
            return
        if not item or item.get("status", "available") != "available":
            await edit_message(
                query,
                "هذا اليوزر لم يعد متاحا.",
                reply_markup=back_to_username_categories_keyboard(),
            )
            return

        await edit_message(
            query,
            format_username_item(category, item),
            reply_markup=username_purchase_keyboard(category_id, item_id),
        )
        return

    if query.data.startswith("buy_username:"):
        _, category_id, item_id = query.data.split(":", 2)
        await buy_username_item(update, context, category_id, item_id)
        return

    if query.data.startswith("reserve_username:"):
        _, category_id, item_id = query.data.split(":", 2)
        await reserve_username_item(update, category_id, item_id)
        return

    if query.data.startswith("cancel_username_reservation:"):
        _, category_id, item_id = query.data.split(":", 2)
        await cancel_username_reservation(update, category_id, item_id)
        return

    if query.data.startswith("buy_reserved_username:"):
        _, category_id, item_id = query.data.split(":", 2)
        await buy_reserved_username(update, context, category_id, item_id)
        return

    if query.data.startswith("product:"):
        product_id = query.data.split(":", 1)[1]
        product = get_product(product_id)
        if not product:
            await edit_message(
                query,
                "هذا المنتج لم يعد متاحا.",
                reply_markup=back_to_products_keyboard(),
            )
            return
        if not get_delivery_items(product):
            await edit_message(
                query,
                "📭 هذا المنتج غير متوفر حاليا.",
                reply_markup=back_to_products_keyboard(),
            )
            return

        await edit_message(
            query,
            format_product_purchase(product),
            reply_markup=product_purchase_keyboard(product_id),
        )
        return

    if query.data.startswith("buy:"):
        product_id = query.data.split(":", 1)[1]
        await buy_product(update, context, product_id)
        return

    if query.data == "wallet":
        user = update.effective_user
        wallet = get_user_wallet(user.id) if user else 0
        reserved_total = get_user_reserved_total(user.id) if user else 0
        await edit_message(
            query,
            "💰 محفظتي.\n\n"
            f"✅ رصيدك المتاح: {format_price(wallet)} ريال\n"
            f"⏳ المبلغ المحجوز: {format_price(reserved_total)} ريال",
            reply_markup=wallet_keyboard(),
        )
        return

    if query.data == "add_wallet_funds":
        await edit_message(
            query,
            "➕ إضافة أموال.\n\n"
            "💳 اختر طريقة الدفع:",
            reply_markup=topup_methods_keyboard(),
        )
        return

    if query.data.startswith("check_topup:"):
        await edit_message(
            query,
            "طريقة الدفع القديمة غير متاحة حاليا. استخدم البطاقة / Apple Pay من المحفظة.",
            reply_markup=wallet_keyboard(),
        )
        return

    if query.data == "operations" or query.data.startswith("operations:"):
        user = update.effective_user
        view = "all"
        page = 0
        if ":" in query.data:
            parts = query.data.split(":")
            view = parts[1]
            if len(parts) > 2:
                try:
                    page = max(0, int(parts[2]))
                except ValueError:
                    page = 0
        if user and view == "purchases":
            purchases = get_user_purchase_operations(user.id)
            await edit_message(
                query,
                "المشتريات.\n\nاختر عملية الشراء التي تريد عرض تفاصيلها:"
                if purchases
                else "المشتريات.\n\nلا توجد مشتريات حتى الان.",
                reply_markup=purchases_keyboard(user.id, page),
            )
            return
        await edit_message(
            query,
            format_user_operations(user.id, view) if user else "⚠️ تعذر معرفة المستخدم.",
            reply_markup=operations_keyboard(user.id, view) if user else back_keyboard(),
        )
        return

    if query.data.startswith("operation_purchase:"):
        user = update.effective_user
        operation_id = query.data.split(":", 1)[1]
        operation = get_user_operation(operation_id)
        if (
            not user
            or not operation
            or operation.get("user_id") != user.id
            or operation.get("type") != "purchase"
        ):
            await edit_message(query, "عملية الشراء غير موجودة.", reply_markup=operations_keyboard(user.id) if user else back_keyboard())
            return

        delivery = get_purchase_delivery_item(operation)
        await edit_message(
            query,
            format_purchase_details(operation),
            reply_markup=InlineKeyboardMarkup(
                [
                    [InlineKeyboardButton("↩️ رجوع للمشتريات", callback_data="operations:purchases")],
                    [InlineKeyboardButton("🏠 العودة للقائمة الرئيسية", callback_data="main_menu")],
                ]
            ),
        )
        if delivery:
            delivery_type = delivery.get("type")
            caption = format_purchase_delivery_caption(operation)
            if delivery_type == "document":
                await query.message.reply_document(
                    document=delivery.get("file_id"),
                    caption=caption,
                )
            elif delivery_type == "video":
                await query.message.reply_video(
                    video=delivery.get("file_id"),
                    caption=caption,
                )
        return

    if query.data == "support":
        await edit_message(
            query,
            "🤝 مركز المساعدة والدعم.\n\n"
            "🎫 اختر نوع المشكلة لفتح تذكرة جديدة، أو راجع تذاكرك السابقة من نفس القائمة.",
            reply_markup=support_keyboard(),
        )
        return

    if query.data == "support_my_tickets":
        await edit_message(
            query,
            "🎫 تذاكري.\n\n"
            "اختر التذكرة التي تريد مراجعتها أو إضافة رد عليها.",
            reply_markup=user_tickets_keyboard(user.id),
        )
        return

    if query.data.startswith("support_ticket:"):
        ticket_id = query.data.split(":", 1)[1]
        ticket = get_ticket(ticket_id)
        if not ticket or ticket.get("user_id") != user.id:
            await edit_message(query, "❌ التذكرة غير موجودة.", reply_markup=support_keyboard())
            return
        await edit_message(query, format_ticket(ticket), reply_markup=user_ticket_keyboard(ticket))
        return

    if query.data == "staff_tickets":
        if not (is_admin(update) or is_employee(update)):
            await edit_message(query, "🔒 هذه القائمة مخصصة للادمن والموظفين فقط.")
            return
        await edit_message(
            query,
            "🎫 تذاكر الدعم.\n\n"
            "اختر تذكرة لعرض التفاصيل والرد أو الإغلاق.",
            reply_markup=staff_tickets_keyboard(),
        )
        return

    if query.data.startswith("staff_ticket_close:"):
        if not (is_admin(update) or is_employee(update)):
            await edit_message(query, "🔒 هذه القائمة مخصصة للادمن والموظفين فقط.")
            return
        ticket_id = query.data.split(":", 1)[1]
        ticket = get_ticket(ticket_id)
        if not ticket:
            await edit_message(query, "❌ التذكرة غير موجودة.", reply_markup=staff_tickets_keyboard())
            return
        role = "admin" if is_admin(update) else "employee"
        actor = get_actor_info(user, role)
        update_ticket(
            ticket_id,
            {
                "status": "closed",
                "closed_at": int(time.time()),
                "closed_by": actor,
                "updated_at": int(time.time()),
            },
        )
        ticket = get_ticket(ticket_id) or ticket
        try:
            await context.bot.send_message(
                chat_id=int(ticket["user_id"]),
                text=f"🔒 تم إغلاق تذكرتك رقم {ticket.get('number')} من فريق الدعم.",
                reply_markup=support_keyboard(),
            )
        except Exception:
            LOGGER.exception("Failed to notify user about closed ticket %s", ticket_id)
        await edit_message(query, "✅ تم إغلاق التذكرة.", reply_markup=staff_ticket_keyboard(ticket))
        return

    if query.data.startswith("staff_ticket:"):
        if not (is_admin(update) or is_employee(update)):
            await edit_message(query, "🔒 هذه القائمة مخصصة للادمن والموظفين فقط.")
            return
        ticket_id = query.data.split(":", 1)[1]
        ticket = get_ticket(ticket_id)
        if not ticket:
            await edit_message(query, "❌ التذكرة غير موجودة.", reply_markup=staff_tickets_keyboard())
            return
        await edit_message(query, format_ticket(ticket, for_staff=True), reply_markup=staff_ticket_keyboard(ticket))
        return

    LOGGER.warning("Unknown callback data: %s", query.data)


async def auto_check_topups(bot) -> None:
    for topup in get_pending_invoice_topups():
        topup_id = str(topup["id"])
        try:
            verified_payment = get_verified_topup_payment(topup)
        except Exception as error:
            LOGGER.warning(
                "Failed to auto-check topup %s invoice %s: %s",
                topup_id,
                topup.get("invoice_id"),
                error,
            )
            continue

        if not verified_payment:
            continue

        status, payment = verified_payment
        fresh_topup = get_topup_by_id(topup_id)
        if not fresh_topup or fresh_topup.get("credited"):
            continue

        credit_amount = parse_amount(fresh_topup.get("credit_amount", fresh_topup.get("amount", 0)))
        change_user_wallet(int(fresh_topup["user_id"]), credit_amount)
        updates = {
            "payment_status": status,
            "credited": True,
            "credited_at": int(time.time()),
            "raw_status": payment,
        }
        if payment.get("payment_id"):
            updates["payment_id"] = payment.get("payment_id")
        update_topup_by_id(topup_id, updates)

        try:
            await bot.send_message(
                chat_id=int(fresh_topup["user_id"]),
                text=(
                    "✅ تم تأكيد الدفع وإضافة الرصيد بنجاح.\n\n"
                    f"المبلغ المضاف: {format_price(credit_amount)}"
                ),
                reply_markup=wallet_keyboard(),
            )
        except Exception:
            LOGGER.exception("Failed to notify user about credited topup %s", topup_id)


async def auto_check_topups_loop(app: Application) -> None:
    while True:
        try:
            await auto_check_topups(app.bot)
        except asyncio.CancelledError:
            raise
        except Exception:
            LOGGER.exception("Auto topup checker crashed")

        await asyncio.sleep(10)


async def start_background_tasks(app: Application) -> None:
    app.bot_data["auto_check_topups_task"] = asyncio.create_task(auto_check_topups_loop(app))


async def stop_background_tasks(app: Application) -> None:
    task = app.bot_data.get("auto_check_topups_task")
    if task:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


def main() -> None:
    load_env_file()

    token = os.getenv(TOKEN_ENV_NAME)
    if not token:
        raise RuntimeError(
            f"Missing {TOKEN_ENV_NAME}. Add it to {ENV_FILE} before running the bot."
        )

    app = (
        Application.builder()
        .token(token)
        .post_init(start_background_tasks)
        .post_shutdown(stop_background_tasks)
        .build()
    )
    add_product_handler = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(start_add_product, pattern="^admin_add_product$"),
        ],
        states={
            PRODUCT_NAME: [
                CallbackQueryHandler(cancel_add_product, pattern="^cancel_add_product$"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_product_name),
            ],
            PRODUCT_DESCRIPTION: [
                CallbackQueryHandler(cancel_add_product, pattern="^cancel_add_product$"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_product_description),
            ],
            PRODUCT_PRICE: [
                CallbackQueryHandler(cancel_add_product, pattern="^cancel_add_product$"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_product_price),
            ],
        },
        fallbacks=[
            CommandHandler("cancel", cancel_add_product),
            CallbackQueryHandler(cancel_add_product, pattern="^cancel_add_product$"),
        ],
    )
    delivery_handler = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(start_delivery, pattern="^(admin_delivery|employee_delivery):"),
        ],
        states={
            DELIVERY_CONTENT: [
                MessageHandler(
                    (filters.TEXT & ~filters.COMMAND)
                    | filters.Document.ALL
                    | filters.VIDEO,
                    receive_delivery_content,
                ),
            ],
        },
        fallbacks=[
            CommandHandler("cancel", stop_delivery),
            CallbackQueryHandler(stop_delivery, pattern="^stop_delivery$"),
        ],
    )
    username_category_handler = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(
                start_add_username_category,
                pattern="^admin_add_username_category$",
            ),
        ],
        states={
            USERNAME_CATEGORY_NAME: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    receive_username_category_name,
                ),
            ],
        },
        fallbacks=[
            CommandHandler("cancel", cancel_username_admin_flow),
            CallbackQueryHandler(
                cancel_username_admin_flow,
                pattern="^cancel_username_admin_flow$",
            ),
        ],
    )
    username_item_handler = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(start_add_username, pattern="^(admin_add_username|employee_add_username):"),
        ],
        states={
            USERNAME_NAME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_username_name),
            ],
            USERNAME_PRICE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_username_price),
            ],
            USERNAME_DELIVERY: [
                MessageHandler(
                    (filters.TEXT & ~filters.COMMAND)
                    | filters.Document.ALL
                    | filters.VIDEO,
                    receive_username_delivery,
                ),
            ],
        },
        fallbacks=[
            CommandHandler("cancel", cancel_username_admin_flow),
            CallbackQueryHandler(
                cancel_username_admin_flow,
                pattern="^cancel_username_admin_flow$",
            ),
        ],
    )
    employee_handler = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(start_add_employee, pattern="^admin_add_employee$"),
        ],
        states={
            EMPLOYEE_ID: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_employee_id),
            ],
        },
        fallbacks=[
            CommandHandler("cancel", cancel_add_employee),
            CallbackQueryHandler(cancel_add_employee, pattern="^cancel_add_employee$"),
        ],
    )
    topup_handler = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(start_topup_amount, pattern="^topup_method:tap$"),
        ],
        states={
            TOPUP_AMOUNT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_topup_amount),
            ],
        },
        fallbacks=[
            CommandHandler("cancel", cancel_topup),
            CallbackQueryHandler(cancel_topup, pattern="^cancel_topup$"),
        ],
    )
    support_handler = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(start_support_ticket, pattern="^support_new:"),
            CallbackQueryHandler(start_add_support_message, pattern="^support_add:"),
        ],
        states={
            SUPPORT_MESSAGE: [
                CallbackQueryHandler(finish_support_ticket, pattern="^support_finish_ticket$"),
                CallbackQueryHandler(cancel_support_ticket, pattern="^support_cancel_ticket$"),
                MessageHandler(
                    (filters.TEXT & ~filters.COMMAND)
                    | filters.PHOTO
                    | filters.Document.ALL
                    | filters.VIDEO,
                    receive_support_message,
                ),
            ],
        },
        fallbacks=[
            CommandHandler("cancel", cancel_support_ticket),
            CallbackQueryHandler(cancel_support_ticket, pattern="^support_cancel_ticket$"),
        ],
    )
    staff_ticket_reply_handler = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(start_staff_ticket_reply, pattern="^staff_ticket_reply:"),
        ],
        states={
            SUPPORT_REPLY_MESSAGE: [
                CallbackQueryHandler(cancel_staff_ticket_reply, pattern="^cancel_staff_ticket_reply$"),
                MessageHandler(
                    (filters.TEXT & ~filters.COMMAND)
                    | filters.PHOTO
                    | filters.Document.ALL
                    | filters.VIDEO,
                    receive_staff_ticket_reply,
                ),
            ],
        },
        fallbacks=[
            CommandHandler("cancel", cancel_staff_ticket_reply),
            CallbackQueryHandler(cancel_staff_ticket_reply, pattern="^cancel_staff_ticket_reply$"),
        ],
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("admin", admin))
    app.add_handler(add_product_handler)
    app.add_handler(delivery_handler)
    app.add_handler(username_category_handler)
    app.add_handler(username_item_handler)
    app.add_handler(employee_handler)
    app.add_handler(topup_handler)
    app.add_handler(support_handler)
    app.add_handler(staff_ticket_reply_handler)
    app.add_handler(CallbackQueryHandler(handle_menu))

    LOGGER.info("Bot is running")
    try:
        app.run_polling(allowed_updates=Update.ALL_TYPES)
    except NetworkError as error:
        LOGGER.error(
            "Could not connect to Telegram. Check your internet connection, DNS, "
            "VPN/proxy, or firewall settings. Details: %s",
            error,
        )


if __name__ == "__main__":
    main()
