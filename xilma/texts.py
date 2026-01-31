# User-facing Persian (Farsi) strings live here.

START_MESSAGE = (
    "سلام! 👋 من «زیلما» هستم، دستیار هوش مصنوعی شما. "
    "هر سوالی دارید بنویسید تا کمکتان کنم."
)

SYSTEM_PROMPT = (
    "تو یک دستیار هوش مصنوعی دقیق، محترمانه و کاربردی هستی. "
    "پاسخ‌ها را شفاف، خلاصه و مفید ارائه بده."
)

HELP_MESSAGE = (
    "دستورات قابل استفاده:\n"
    "/start — شروع Bot\n"
    "/help — راهنما\n"
    "/new — پاک‌کردن گفتگو\n"
    "/model — انتخاب Model\n"
    "/models — لیست مدل‌ها (cheap/expensive)\n"
    "\n"
    "یا فقط پیام متنی خودتان را ارسال کنید."
)

NOT_AUTHORIZED = "شما دسترسی لازم برای این بخش را ندارید."

ADMIN_MENU_TITLE = "Admin Panel"
ADMIN_MENU_HINT = "برای مشاهده یا ویرایش هر Setting روی آن بزنید."
ADMIN_PANEL_CLOSED = "Admin Panel بسته شد."

ADMIN_PROMPT_VALUE = "مقدار جدید برای «{label}» را ارسال کنید."

BTN_CLOSE = "بستن"
BTN_BACK = "بازگشت"
BTN_ADD = "افزودن"
BTN_EDIT = "ویرایش"
BTN_REMOVE = "حذف"
BTN_USERS = "👥 Users"
BTN_NEXT = "بعدی"
BTN_PREV = "قبلی"
BTN_OLDER = "قدیمی‌تر"
BTN_NEWER = "جدیدتر"
BTN_SAVE = "ذخیره"
BTN_CLEAR = "پاک‌کردن"
BTN_REFRESH = "به‌روزرسانی"
BTN_DEFAULT = "پیش‌فرض"
BTN_SORT = "مرتب‌سازی"
BTN_SORT_CHEAP = "ارزان‌ترین"
BTN_SORT_EXPENSIVE = "گران‌ترین"
BTN_SORT_DEFAULT = "پیش‌فرض"
BTN_SEARCH = "جستجو"
BTN_SEARCH_CLEAR = "پاک‌کردن جستجو"
BTN_USER_MODEL = "انتخاب مدل"
BTN_USER_NEW_CHAT = "گفتگوی جدید"
BTN_USERS_INFO = "اطلاعات کاربری"
BTN_USER_CHATS = "🗂️ گفتگوهای من"
BTN_DELETE_CHAT = "🗑️ حذف گفتگو"

ICON_EDIT = "✏️ "
ICON_REMOVE = "🗑️ "

STATUS_ON = "روشن"
STATUS_OFF = "خاموش"
ADMIN_SETTINGS_CURRENT = "تنظیمات فعلی:"
ADMIN_SPONSOR_TITLE = "مدیریت Sponsor Channels"
ADMIN_SPONSOR_HINT = (
    "برای افزودن سریع، همینجا نام Channel را ارسال کنید. "
    "برای حذف یا ویرایش از دکمه‌ها استفاده کنید."
)
ADMIN_USERS_TITLE = "Users"
ADMIN_USERS_TOTAL = "Total users: {count}"
ADMIN_USERS_PAGE = "Page {page}/{pages}"
ADMIN_USERS_PROMPT = "Select a user for details."
ADMIN_USERS_EMPTY = "No users yet."
ADMIN_USERS_NOT_FOUND = "User not found."
ADMIN_USER_DETAILS_TITLE = "User Details"
ADMIN_USER_CHATS = "💬 Chats"
ADMIN_USER_CHATS_TITLE = "User Chats"
ADMIN_USER_CHATS_PAGE = "Page {page}/{pages}"
ADMIN_USER_CHATS_EMPTY = "No chats yet."
ADMIN_CHAT_TITLE = "Chat: {title}"
ADMIN_CHAT_PAGE = "Page {page}/{pages}"
ADMIN_CHAT_DELETED = "Deleted"
ADMIN_CHAT_EMPTY = "No messages."
ADMIN_CHAT_USER = "User ID: {user_id}"
ADMIN_CHAT_MODEL = "Model: {model}"
ADMIN_MODELS_TITLE = "Allowed Models"
ADMIN_MODELS_HINT = "مدل‌های مجاز را انتخاب کنید."
ADMIN_MODELS_EMPTY = "مدلی یافت نشد."
ADMIN_MODELS_FETCH_FAILED = "دریافت لیست مدل‌ها ناموفق بود. دوباره تلاش کنید."
ADMIN_MODELS_API_KEY_MISSING = "API Key تنظیم نشده است. ابتدا آن را وارد کنید."
ADMIN_MODELS_SELECTED = "تعداد انتخاب‌شده: {count}"
ADMIN_MODELS_SORT = "مرتب‌سازی: {mode}"
ADMIN_MODELS_SORT_MENU = "نوع مرتب‌سازی را انتخاب کنید."
ADMIN_MODELS_SAVED = "لیست مدل‌های مجاز ذخیره شد."
ADMIN_MODELS_DEFAULT_UPDATED = "Default Model به {model} تغییر کرد تا مجاز باشد."
ADMIN_MODELS_DEFAULT_TITLE = "انتخاب Default Model"
ADMIN_MODELS_DEFAULT_HINT = "یک مدل را به‌عنوان پیش‌فرض انتخاب کنید."
ADMIN_MODELS_DEFAULT_EMPTY = "ابتدا حداقل یک مدل مجاز انتخاب کنید."
ADMIN_MODELS_SEARCH_PROMPT = "متن جستجو را ارسال کنید."
ADMIN_MODELS_SEARCH_ACTIVE = "جستجو: {query}"
ADMIN_MODELS_SEARCH_EMPTY = "نتیجه‌ای پیدا نشد."
ADMIN_PROMPT_SPONSOR_ADD = "نام Channel را ارسال کنید. مثال: @a یا @a,@b"
ADMIN_PROMPT_SPONSOR_REMOVE_SELECT = "Channel موردنظر برای حذف را انتخاب کنید."
ADMIN_PROMPT_SPONSOR_EDIT_SELECT = "Channel موردنظر برای ویرایش را انتخاب کنید."
ADMIN_PROMPT_SPONSOR_EDIT = "نام جدید برای Channel انتخاب‌شده را ارسال کنید. مثال: @a"
ADMIN_PROMPT_SPONSOR_QUICK = "برای افزودن سریع، همینجا نام Channel را ارسال کنید."
ADMIN_USE_BUTTONS = "لطفاً از دکمه‌های پنل استفاده کنید."

CHAT_RESET = "گفتگو پاک شد. از نو شروع می‌کنیم ✨"
CHAT_ONLY_TEXT = "در حال حاضر فقط Text Message پشتیبانی می‌شود."

GENERIC_ERROR = (
    "مشکلی در پردازش درخواست به‌وجود آمد. "
    "لطفاً کمی بعد دوباره تلاش کنید."
)
RATE_LIMITED = "درخواست‌ها زیاد است. لطفاً چند ثانیه بعد دوباره تلاش کنید."

API_KEY_MISSING = (
    "API Key تنظیم نشده است. "
    "Admin باید آن را از Admin Panel وارد کند."
)

MODEL_SET = "Model با موفقیت به‌روزرسانی شد."
MODEL_CURRENT = "Model فعلی: {model}"
MODEL_USAGE = "برای تغییر Model از دستور /model <model> استفاده کنید."
MODEL_ALLOWED_LIST = "مدل‌های مجاز: {models}"
MODEL_NOT_ALLOWED = "مدل انتخاب‌شده مجاز نیست. مدل‌های مجاز: {models}"
MODELS_LIST_TITLE = "لیست مدل‌های مجاز"
MODELS_SORT_HINT = "مرتب‌سازی: {mode}"
MODELS_SORT_USAGE = "برای مرتب‌سازی از /models cheap یا /models expensive استفاده کنید."
MODELS_SORT_FAILED = "مرتب‌سازی بر اساس قیمت ممکن نیست. مدل‌ها بدون قیمت نمایش داده می‌شوند."

USER_PANEL_HEADER = "✨ زیلما"
USER_PANEL_WELCOME = "سلام! 👋 من «زیلما» هستم."
USER_PANEL_SUBTITLE = "دستیار هوش مصنوعی شما برای پاسخ‌های دقیق و سریع 🤖"
USER_PANEL_ACTIONS = "🟢 شروع سریع: گفتگو جدید | انتخاب مدل | اطلاعات کاربری | گفتگوهای من"
USER_PANEL_HINT = "👇 یکی رو انتخاب کن:"
USER_PANEL_START_HINT = "↩️ بازگشت به منو: /start"
USER_PANEL_USER = "کاربر"
USER_PANEL_USERNAME = "یوزرنیم"
USER_PANEL_ID = "شناسه"
USER_PANEL_MODEL = "مدل فعلی: {model}"
USER_PANEL_DEFAULT = "مدل پیش‌فرض سیستم: {model}"
USER_PANEL_ALLOWED = "مدل‌های مجاز: {models}"
USER_MODELS_TITLE = "انتخاب مدل"
USER_MODELS_HINT = "یکی از مدل‌های مجاز را انتخاب کنید."
USER_MODELS_EMPTY = "مدل مجاز تنظیم نشده است."
USER_MODEL_UPDATED = "مدل شما به‌روزرسانی شد."
USER_COMMAND_FALLBACK = "از دکمه‌های پنل استفاده کنید."
USER_INFO_TITLE = "اطلاعات کاربری"
USER_INFO_HINT = "برای بازگشت به پنل از دکمه پایین استفاده کنید."
USER_CHATS_TITLE = "گفتگوهای شما"
USER_CHATS_PAGE = "صفحه {page}/{pages}"
USER_CHATS_HINT = "برای مشاهده یا انتخاب، یکی را بزنید."
USER_CHATS_EMPTY = "هنوز گفتگویی ندارید."
USER_CHAT_TITLE = "گفتگو: {title}"
USER_CHAT_PAGE = "صفحه {page}/{pages}"
USER_CHAT_EMPTY = "این گفتگو هنوز پیامی ندارد."
USER_CHAT_SELECTED = "گفتگو انتخاب شد."
USER_CHAT_UNTITLED = "گفتگو {chat_id}"
USER_CHAT_NOT_FOUND = "گفتگو پیدا نشد."
USER_CHAT_ERROR = "⚠️ پاسخ ناموفق بود. لطفاً دوباره تلاش کنید."
USER_CHAT_DELETED = "گفتگو حذف شد."
USER_CHAT_CREATED = "گفتگوی جدید ساخته شد."
USER_CHAT_MODEL = "مدل: {model}"

CONFIG_UPDATED = "Settings با موفقیت ذخیره شد."
CONFIG_INVALID_KEY = "Setting انتخاب‌شده معتبر نیست."

# Validation messages
VALIDATION_TOO_SHORT = "متن واردشده خیلی کوتاه است."
VALIDATION_TOO_LONG = "متن واردشده بیش از حد مجاز طولانی است."
VALIDATION_INVALID_FORMAT = "فرمت مقدار واردشده معتبر نیست."
VALIDATION_DIGITS_ONLY = "فقط اعداد انگلیسی (0-9) مجاز هستند."
VALIDATION_FLOAT_ONLY = "فقط عدد اعشاری با ارقام انگلیسی مجاز است."
VALIDATION_TOO_LOW = "عدد واردشده کمتر از مقدار مجاز است."
VALIDATION_TOO_HIGH = "عدد واردشده بیشتر از مقدار مجاز است."
VALIDATION_ENUM = "مقدار باید یکی از این گزینه‌ها باشد: {allowed}"
VALIDATION_BOOL = "مقدار باید فقط true یا false باشد."

PROMPT_BOOL = "مقادیر مجاز: true یا false"
PROMPT_INT = "فقط عدد صحیح با ارقام انگلیسی مجاز است."
PROMPT_FLOAT = "فقط عدد اعشاری با ارقام انگلیسی مجاز است."
PROMPT_OPTIONAL = "برای حذف مقدار فعلی، کلمه unset را ارسال کنید."
PROMPT_CHANNELS = "Channelها را با کاما جدا کنید. مثال: @a,@b"

# Sponsor system
SPONSOR_REQUIRED = (
    "برای استفاده از Bot باید عضو همه Sponsor Channelها شوید. "
    "بعد از عضویت، دوباره پیام ارسال کنید."
)
SPONSOR_LIST_EMPTY = "هیچ Sponsor Channelی تعریف نشده است."
SPONSOR_INVALID = "فرمت Channel معتبر نیست. مثال: @channel یا https://t.me/channel"
SPONSOR_ALREADY_EXISTS = "این Channel از قبل اضافه شده است."
SPONSOR_NOT_FOUND = "این Channel در لیست وجود ندارد."
CHECK_MEMBERSHIP = "بررسی عضویت"
MEMBERSHIP_OK = "عضویت شما تأیید شد. حالا می‌توانید پیام ارسال کنید ✅"
