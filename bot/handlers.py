"""Telegram bot handlers — interactive menu-driven UX."""

from __future__ import annotations

import time
from datetime import date, timedelta

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from bot.service import WatchService
from bot.stations import POPULAR_STATIONS
from core.auth import token_cache, TOKEN_TTL
from core.scanner import AsyncTCDDClient

# ── Turkish locale helpers ────────────────────────────────────

DAY_NAMES_TR = ["Pzt", "Sal", "Çar", "Per", "Cum", "Cmt", "Paz"]
MONTH_NAMES_TR = [
    "", "Oca", "Şub", "Mar", "Nis", "May", "Haz",
    "Tem", "Ağu", "Eyl", "Eki", "Kas", "Ara",
]


def format_date_tr(d: date) -> str:
    """Format date in Turkish: '11 Mar Sal'."""
    return f"{d.day} {MONTH_NAMES_TR[d.month]} {DAY_NAMES_TR[d.weekday()]}"


# ── Auth & helpers ────────────────────────────────────────────

def is_authorized(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> bool:
    chat_id = str(ctx.bot_data.get("chat_id", ""))
    if update.callback_query:
        return str(update.callback_query.message.chat.id) == chat_id
    return str(update.effective_chat.id) == chat_id


def get_watch_service(ctx: ContextTypes.DEFAULT_TYPE) -> WatchService:
    return ctx.bot_data["watch_service"]


def get_session(ctx: ContextTypes.DEFAULT_TYPE, chat_id: int) -> dict:
    """Get or create session state for a chat."""
    sessions = ctx.bot_data.setdefault("sessions", {})
    return sessions.setdefault(chat_id, {})


# ── Keyboard builders ────────────────────────────────────────

def build_main_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔔 Yeni Alarm", callback_data="nw")],
        [
            InlineKeyboardButton("📋 Alarmlarım", callback_data="ls"),
            InlineKeyboardButton("📊 Durum", callback_data="st"),
        ],
    ])


def build_station_grid(prefix: str, exclude: str | None = None) -> InlineKeyboardMarkup:
    """Build 2-column station grid. prefix is 'd' or 'a'."""
    buttons = []
    row = []
    for idx, (label, full_name) in enumerate(POPULAR_STATIONS):
        if exclude and full_name == exclude:
            continue
        row.append(InlineKeyboardButton(label, callback_data=f"{prefix}:{idx}"))
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    search_cb = "sd" if prefix == "d" else "sa"
    buttons.append([InlineKeyboardButton("🔍 Diğer...", callback_data=search_cb)])
    buttons.append([InlineKeyboardButton("⬅️ Ana Menü", callback_data="m")])
    return InlineKeyboardMarkup(buttons)


def build_date_grid() -> InlineKeyboardMarkup:
    """Build date picker: today + next 6 days."""
    today = date.today()
    buttons = []
    row = []
    for i in range(7):
        d = today + timedelta(days=i)
        label = format_date_tr(d)
        row.append(InlineKeyboardButton(label, callback_data=f"dt:{d.isoformat()}"))
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    buttons.append([InlineKeyboardButton("⬅️ Ana Menü", callback_data="m")])
    return InlineKeyboardMarkup(buttons)


# ── Async train fetcher ───────────────────────────────────────

def get_async_client(ctx: ContextTypes.DEFAULT_TYPE) -> AsyncTCDDClient:
    """Lazily create and cache an AsyncTCDDClient in bot_data."""
    if "async_client" not in ctx.bot_data:
        scheduler = ctx.bot_data["scheduler"]
        ctx.bot_data["async_client"] = AsyncTCDDClient(
            stations=scheduler.stations,
            environment=scheduler.environment,
            user_id=scheduler.user_id,
        )
    return ctx.bot_data["async_client"]


async def fetch_trains(query, ctx, dep: str, arr: str, sel_date: str):
    """Scan route via async httpx client. Returns train list or None on failure."""
    await query.edit_message_text(
        f"🔍 <b>Seferler aranıyor...</b>\n\n{dep} → {arr}\n📅 {sel_date}",
        parse_mode="HTML",
    )
    client = get_async_client(ctx)
    try:
        return await client.scan_route(dep, arr, sel_date, auto_auth=True)
    except Exception as exc:
        await query.edit_message_text(
            f"❌ Sefer araması başarısız: {exc}",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔄 Tekrar Dene", callback_data="rf")],
                [InlineKeyboardButton("⬅️ Ana Menü", callback_data="m")],
            ]),
        )
        return None


# ── /start ────────────────────────────────────────────────────

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_authorized(update, ctx):
        return
    # Clear session
    sessions = ctx.bot_data.setdefault("sessions", {})
    sessions.pop(update.effective_chat.id, None)
    await update.message.reply_text(
        "<b>TCDD Bilet Takip</b>\n\nNe yapmak istersiniz?",
        parse_mode="HTML",
        reply_markup=build_main_menu(),
    )


# ── Callback router ──────────────────────────────────────────

async def callback_router(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query:
        return
    if not is_authorized(update, ctx):
        await query.answer("Yetkisiz.")
        return

    await query.answer()
    data = query.data
    chat_id = query.message.chat.id

    if data == "m":
        await show_main_menu(query, ctx, chat_id)
    elif data == "nw":
        await show_dep_stations(query, ctx)
    elif data.startswith("d:"):
        await handle_dep_select(query, ctx, chat_id, data)
    elif data == "sd":
        await enter_search_mode(query, ctx, chat_id, "search_dep")
    elif data.startswith("a:"):
        await handle_arr_select(query, ctx, chat_id, data)
    elif data == "sa":
        await enter_search_mode(query, ctx, chat_id, "search_arr")
    elif data.startswith("dt:"):
        await handle_date_select(query, ctx, chat_id, data)
    elif data.startswith("t:"):
        await handle_train_select(query, ctx, chat_id, data)
    elif data == "ls":
        await show_alarms(query, ctx)
    elif data.startswith("rm:"):
        await handle_remove(query, ctx, data)
    elif data == "st":
        await show_status(query, ctx)
    elif data == "rf":
        await handle_refresh(query, ctx, chat_id)
    elif data.startswith("fx:"):
        await handle_fuzzy_select(query, ctx, chat_id, data)


# ── Menu actions ──────────────────────────────────────────────

async def show_main_menu(query, ctx, chat_id: int) -> None:
    sessions = ctx.bot_data.setdefault("sessions", {})
    sessions.pop(chat_id, None)
    await query.edit_message_text(
        "<b>TCDD Bilet Takip</b>\n\nNe yapmak istersiniz?",
        parse_mode="HTML",
        reply_markup=build_main_menu(),
    )


async def show_dep_stations(query, ctx) -> None:
    await query.edit_message_text(
        "🚉 <b>Kalkış istasyonu seçin:</b>",
        parse_mode="HTML",
        reply_markup=build_station_grid("d"),
    )


async def handle_dep_select(query, ctx, chat_id: int, data: str) -> None:
    idx = int(data[2:])
    _, full_name = POPULAR_STATIONS[idx]
    sess = get_session(ctx, chat_id)
    sess["dep"] = full_name
    sess.pop("state", None)
    await query.edit_message_text(
        f"🚉 <b>Varış istasyonu seçin:</b>\n\nKalkış: {full_name}",
        parse_mode="HTML",
        reply_markup=build_station_grid("a", exclude=full_name),
    )


async def handle_arr_select(query, ctx, chat_id: int, data: str) -> None:
    idx = int(data[2:])
    _, full_name = POPULAR_STATIONS[idx]
    sess = get_session(ctx, chat_id)
    sess["arr"] = full_name
    sess.pop("state", None)
    dep = sess.get("dep", "?")
    await query.edit_message_text(
        f"📅 <b>Tarih seçin:</b>\n\n{dep} → {full_name}",
        parse_mode="HTML",
        reply_markup=build_date_grid(),
    )


async def enter_search_mode(query, ctx, chat_id: int, state: str) -> None:
    sess = get_session(ctx, chat_id)
    sess["state"] = state
    if state == "search_dep":
        prompt = "Kalkış istasyonu adını yazın:"
    else:
        prompt = "Varış istasyonu adını yazın:"
    await query.edit_message_text(f"🔍 {prompt}")


async def handle_fuzzy_select(query, ctx, chat_id: int, data: str) -> None:
    """Handle selection from fuzzy search results."""
    idx = int(data[3:])
    sess = get_session(ctx, chat_id)
    search_results = sess.get("search_results", [])
    if idx >= len(search_results):
        await query.edit_message_text("Seçim süresi doldu. Tekrar deneyin.",
                                      reply_markup=build_main_menu())
        return

    station_name = search_results[idx]
    state = sess.get("state", "")

    if state == "search_dep":
        sess["dep"] = station_name
        sess.pop("state", None)
        sess.pop("search_results", None)
        await query.edit_message_text(
            f"🚉 <b>Varış istasyonu seçin:</b>\n\nKalkış: {station_name}",
            parse_mode="HTML",
            reply_markup=build_station_grid("a", exclude=station_name),
        )
    elif state == "search_arr":
        sess["arr"] = station_name
        sess.pop("state", None)
        sess.pop("search_results", None)
        dep = sess.get("dep", "?")
        await query.edit_message_text(
            f"📅 <b>Tarih seçin:</b>\n\n{dep} → {station_name}",
            parse_mode="HTML",
            reply_markup=build_date_grid(),
        )


async def handle_date_select(query, ctx, chat_id: int, data: str) -> None:
    sel_date = data[3:]  # YYYY-MM-DD
    sess = get_session(ctx, chat_id)
    sess["date"] = sel_date
    dep = sess.get("dep", "?")
    arr = sess.get("arr", "?")

    trains = await fetch_trains(query, ctx, dep, arr, sel_date)
    if trains is None:
        return
    sess["trains"] = trains
    await show_train_results(query, sess, trains)


async def handle_refresh(query, ctx, chat_id: int) -> None:
    """Retry the last scan."""
    sess = get_session(ctx, chat_id)
    dep = sess.get("dep")
    arr = sess.get("arr")
    sel_date = sess.get("date")
    if not dep or not arr or not sel_date:
        await query.edit_message_text(
            "Oturum süresi doldu.",
            reply_markup=build_main_menu(),
        )
        return

    trains = await fetch_trains(query, ctx, dep, arr, sel_date)
    if trains is None:
        return
    sess["trains"] = trains
    await show_train_results(query, sess, trains)


async def show_train_results(query, sess: dict, trains: list) -> None:
    dep = sess.get("dep", "?")
    arr = sess.get("arr", "?")
    sel_date = sess.get("date", "?")

    if not trains:
        await query.edit_message_text(
            f"Bu güzergahta sefer bulunamadı.\n\n{dep} → {arr}\n📅 {sel_date}",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔄 Tekrar Dene", callback_data="rf")],
                [InlineKeyboardButton("⬅️ Ana Menü", callback_data="m")],
            ]),
        )
        return

    lines = [f"<b>{dep} → {arr}</b>\n📅 {sel_date}\n"]
    buttons = []
    all_have_seats = True

    for i, train in enumerate(trains):
        dep_time = train.departure_time.strftime("%H:%M")
        class_parts = []
        for cab in train.classes:
            icon = "✅" if cab.seats > 0 else "❌"
            class_parts.append(f"{cab.name}: {cab.seats} {icon}")
        class_str = " | ".join(class_parts) if class_parts else "bilgi yok"
        lines.append(f"🕐 <b>{dep_time}</b> | {class_str}")

        if not train.has_seats:
            all_have_seats = False
            buttons.append([InlineKeyboardButton(
                f"🔔 {dep_time} Alarm Kur",
                callback_data=f"t:{i}",
            )])

    if all_have_seats:
        lines.append("\n✅ <b>Tüm seferlerde yer mevcut!</b>")

    buttons.append([InlineKeyboardButton("🔄 Yenile", callback_data="rf")])
    buttons.append([InlineKeyboardButton("⬅️ Ana Menü", callback_data="m")])

    await query.edit_message_text(
        "\n".join(lines),
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(buttons),
    )


async def handle_train_select(query, ctx, chat_id: int, data: str) -> None:
    idx = int(data[2:])
    sess = get_session(ctx, chat_id)
    trains = sess.get("trains", [])
    if idx >= len(trains):
        await query.edit_message_text(
            "Sefer bilgisi süresi doldu. Lütfen tekrar arayın.",
            reply_markup=build_main_menu(),
        )
        return

    train = trains[idx]
    dep_time = train.departure_time.strftime("%H:%M")
    dep = sess.get("dep", "?")
    arr = sess.get("arr", "?")
    sel_date = sess.get("date", "?")

    # Build narrow time window ±1 minute
    dt = train.departure_time
    t_from = (dt - timedelta(minutes=1)).strftime("%H:%M")
    t_to = (dt + timedelta(minutes=1)).strftime("%H:%M")

    ws = get_watch_service(ctx)
    try:
        rule = ws.add_watch(dep, arr, sel_date, t_from, t_to)
    except ValueError as e:
        await query.edit_message_text(f"❌ Hata: {e}", reply_markup=build_main_menu())
        return

    await query.edit_message_text(
        f"✅ <b>Alarm kuruldu!</b>\n\n"
        f"🕐 {dep_time} seferi\n"
        f"{rule.dep} → {rule.arr}\n"
        f"📅 {rule.date}\n\n"
        f"Yer açıldığında bildirim alacaksınız.",
        parse_mode="HTML",
        reply_markup=build_main_menu(),
    )


# ── Alarm list & management ──────────────────────────────────

async def show_alarms(query, ctx) -> None:
    ws = get_watch_service(ctx)
    watches = ws.list_watches()
    if not watches:
        await query.edit_message_text(
            "📋 Aktif alarm bulunmuyor.",
            reply_markup=build_main_menu(),
        )
        return

    lines = ["<b>📋 Aktif Alarmlar</b>\n"]
    buttons = []
    for idx, rule in watches:
        time_str = f"{rule.time_from}-{rule.time_to}"
        if rule.time_from == "00:00" and rule.time_to == "23:59":
            time_str = "tüm gün"
        lines.append(
            f"<b>{idx}.</b> {rule.dep} → {rule.arr}\n"
            f"    📅 {rule.date} | 🕐 {time_str}"
        )
        buttons.append([InlineKeyboardButton(
            f"❌ {idx}. Alarmı Sil",
            callback_data=f"rm:{idx}",
        )])

    buttons.append([InlineKeyboardButton("⬅️ Ana Menü", callback_data="m")])

    await query.edit_message_text(
        "\n".join(lines),
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(buttons),
    )


async def handle_remove(query, ctx, data: str) -> None:
    idx = int(data[3:])
    ws = get_watch_service(ctx)
    removed = ws.remove_watch(idx)
    if not removed:
        await query.edit_message_text(
            f"Alarm bulunamadı: #{idx}",
            reply_markup=build_main_menu(),
        )
        return

    # Show updated alarm list with removal confirmation
    watches = ws.list_watches()
    if not watches:
        await query.edit_message_text(
            f"🗑 Alarm silindi: {removed.dep} → {removed.arr}\n\n"
            "📋 Aktif alarm bulunmuyor.",
            reply_markup=build_main_menu(),
        )
        return

    lines = [
        f"🗑 Alarm silindi: {removed.dep} → {removed.arr}\n",
        "<b>📋 Kalan Alarmlar</b>\n",
    ]
    buttons = []
    for i, rule in watches:
        time_str = f"{rule.time_from}-{rule.time_to}"
        if rule.time_from == "00:00" and rule.time_to == "23:59":
            time_str = "tüm gün"
        lines.append(
            f"<b>{i}.</b> {rule.dep} → {rule.arr}\n"
            f"    📅 {rule.date} | 🕐 {time_str}"
        )
        buttons.append([InlineKeyboardButton(
            f"❌ {i}. Alarmı Sil",
            callback_data=f"rm:{i}",
        )])
    buttons.append([InlineKeyboardButton("⬅️ Ana Menü", callback_data="m")])

    await query.edit_message_text(
        "\n".join(lines),
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(buttons),
    )


# ── Status ────────────────────────────────────────────────────

async def show_status(query, ctx) -> None:
    ws = get_watch_service(ctx)
    start_time = ctx.bot_data.get("start_time", time.time())
    uptime_s = int(time.time() - start_time)
    hours, remainder = divmod(uptime_s, 3600)
    minutes, seconds = divmod(remainder, 60)

    watch_count = len(ws.get_snapshot())

    token_status = "bilinmiyor"
    try:
        if token_cache.token:
            expires_at = token_cache.fetched_at + TOKEN_TTL
            if expires_at > time.time():
                remaining = int(expires_at - time.time())
                token_status = f"geçerli ({remaining // 60}dk kaldı)"
            else:
                token_status = "süresi dolmuş"
        else:
            token_status = "henüz alınmadı"
    except Exception:
        token_status = "okuma hatası"

    await query.edit_message_text(
        f"<b>📊 Sistem Durumu</b>\n\n"
        f"⏱ Çalışma süresi: {hours}sa {minutes}dk {seconds}sn\n"
        f"🔔 Aktif alarmlar: {watch_count}\n"
        f"🔑 Token: {token_status}",
        parse_mode="HTML",
        reply_markup=build_main_menu(),
    )


# ── Text handler (fuzzy station search) ──────────────────────

async def text_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_authorized(update, ctx):
        return

    chat_id = update.effective_chat.id
    sess = get_session(ctx, chat_id)
    state = sess.get("state")

    if state not in ("search_dep", "search_arr"):
        return  # Ignore text when not in search mode

    ws = get_watch_service(ctx)
    query_text = update.message.text.strip()
    results = ws.resolver.resolve(query_text, n=5)

    if not results:
        await update.message.reply_text(
            f"'{query_text}' için istasyon bulunamadı. Tekrar deneyin.",
        )
        return

    if len(results) == 1:
        # Exact match — proceed directly
        station = results[0]
        if state == "search_dep":
            sess["dep"] = station
            sess.pop("state", None)
            await update.message.reply_text(
                f"🚉 <b>Varış istasyonu seçin:</b>\n\nKalkış: {station}",
                parse_mode="HTML",
                reply_markup=build_station_grid("a", exclude=station),
            )
        else:
            sess["arr"] = station
            sess.pop("state", None)
            dep = sess.get("dep", "?")
            await update.message.reply_text(
                f"📅 <b>Tarih seçin:</b>\n\n{dep} → {station}",
                parse_mode="HTML",
                reply_markup=build_date_grid(),
            )
        return

    # Multiple matches — show as buttons
    sess["search_results"] = results
    buttons = []
    for i, name in enumerate(results):
        buttons.append([InlineKeyboardButton(name, callback_data=f"fx:{i}")])
    buttons.append([InlineKeyboardButton("⬅️ Ana Menü", callback_data="m")])

    await update.message.reply_text(
        "Hangi istasyonu kastediyorsunuz?",
        reply_markup=InlineKeyboardMarkup(buttons),
    )
