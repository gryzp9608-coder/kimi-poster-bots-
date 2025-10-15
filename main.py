import asyncio, time, json, tempfile, os, uuid
from datetime import datetime, timedelta
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update, InputFile, LabeledPrice
from telegram.ext import (
    ApplicationBuilder, CommandHandler, CallbackQueryHandler,
    MessageHandler, ContextTypes, filters, PreCheckoutQueryHandler
)

TOKEN   = "7859933993:AAG9Ss1bGQV2z8q5hpL4HE1Xd1_CxlckfG0"
ADMIN_ID = 7394635812
PAYMENT_TOKEN = "284685063:TEST:Y2Y5Y2Q5MzQ5NzY0"

# ── KEEP-ALIVE İÇİN GEREKLİ KISIM ──
from flask import Flask
from threading import Thread

app_web = Flask(__name__)

@app_web.route('/')
def index():
    return "🤖 Bot çalışıyor!"

def run():
    app_web.run(host='0.0.0.0', port=8080)

def keep_alive():
    t = Thread(target=run)
    t.start()
# ───────────────────────────────────

user_sessions      = {}
waiting_for        = {}
scheduled_posts    = []
previous_messages  = {}
banned_users       = set()
all_users          = set()
promo_codes        = {}
user_accounts      = {}
required_channel   = None
channel_check_last = {}

def main_menu_keyboard(user_id: int):
    btn = [
        [InlineKeyboardButton("📤 Reklama goýmak", callback_data='reklama')],
        [InlineKeyboardButton("📂 Postlarym",     callback_data='postlarym')],
        [InlineKeyboardButton("👤 Hasabym",       callback_data='hasabym')],
        [InlineKeyboardButton("🎁 Promo kod",     callback_data='promo_kod')]
    ]
    if user_id == ADMIN_ID:
        btn.insert(2, [InlineKeyboardButton("📊 Statistika", callback_data='statistika')])
        btn.append([InlineKeyboardButton("🔐 Admin panel", callback_data='admin_panel')])
    return InlineKeyboardMarkup(btn)

def admin_panel_keyboard():
    k_ch, k_post = len({p['channel'] for p in scheduled_posts}), len(scheduled_posts)
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("1️⃣ Kanallara bildiriş",   callback_data='duyuru_kanal')],
        [InlineKeyboardButton("2️⃣ Ulanyjylara bildiriş", callback_data='duyuru_user')],
        [InlineKeyboardButton("3️⃣ Ban goýmak / aýyrmak",  callback_data='ban_user')],
        [InlineKeyboardButton("4️⃣ Umumy ulanyjylar",      callback_data='list_users')],
        [InlineKeyboardButton("➕ Kural kanal goş",        callback_data='add_rule_channel')],
        [InlineKeyboardButton("🎫 Promo kod döret",        callback_data='create_promo')],
        [InlineKeyboardButton("📜 Promo kodlar",           callback_data='list_promos')],
        [InlineKeyboardButton("🔙 Esas menýuga dolanmak",  callback_data='back_main')]
    ])

async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    uid  = user.id
    all_users.add((uid, user.first_name or "", user.username or ""))
    if uid in banned_users:
        await update.message.reply_text("❌ Siz bu botdan banlandyňyz."); return

    if required_channel:
        is_member = await check_channel_membership(uid, ctx.bot)
        if not is_member:
            keyboard = InlineKeyboardMarkup([[
                InlineKeyboardButton("📢 Kanala abuna bol", url=f"https://t.me/{required_channel.lstrip('@')}")
            ], [
                InlineKeyboardButton("✅ Abuna boldum", callback_data='check_membership')
            ]])
            await update.message.reply_text(
                f"📢 Botu ulanmak üçin {required_channel} kanalyna abuna bolmaly!\n\n"
                f"Abuna bolan soň 'Abuna boldum' düwmesine basyň.",
                reply_markup=keyboard
            )
            return

    ref_code = None
    if ctx.args and ctx.args[0].startswith("ref_"):
        ref_code = ctx.args[0][4:]
        if ref_code in user_accounts:
            user_accounts[ref_code]["ref_count"] += 1
            user_accounts[uid] = user_accounts.get(uid, {})
            user_accounts[uid]["expiry"] = user_accounts.get(uid, {}).get("expiry", time.time()) + 3*86400

    if uid not in user_accounts:
        user_accounts[uid] = {
            "expiry": time.time() + 30*86400,
            "promo": "",
            "ref": str(uuid.uuid4())[:8],
            "ref_count": 0
        }
    await update.message.reply_text(
        "👋 Hoş geldiňiz! Aşakdaky menýulardan birini saýlaň:",
        reply_markup=main_menu_keyboard(uid)
    )

async def button_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    if user_id in banned_users:
        await query.edit_message_text("❌ Siz banlandyňyz."); return
    data = query.data

    if data == 'check_membership':
        if required_channel:
            is_member = await check_channel_membership(user_id, ctx.bot)
            if not is_member:
                await query.answer("❌ Heniz kanala abuna bolmadyňyz!", show_alert=True)
                return
        await query.edit_message_text(
            "👋 Hoş geldiňiz! Aşakdaky menýulardan birini saýlaň:",
            reply_markup=main_menu_keyboard(user_id)
        )
        return

    if required_channel and data != 'check_membership':
        is_member = await check_channel_membership(user_id, ctx.bot)
        if not is_member:
            keyboard = InlineKeyboardMarkup([[
                InlineKeyboardButton("📢 Kanala abuna bol", url=f"https://t.me/{required_channel.lstrip('@')}")
            ], [
                InlineKeyboardButton("✅ Abuna boldum", callback_data='check_membership')
            ]])
            await query.edit_message_text(
                f"📢 Botu ulanmak üçin {required_channel} kanalyna abuna bolmaly!\n\n"
                f"Abuna bolan soň 'Abuna boldum' düwmesine basyň.",
                reply_markup=keyboard
            )
            return

    if data == 'admin_panel' and user_id == ADMIN_ID:
        k_ch, k_post = len({p['channel'] for p in scheduled_posts}), len(scheduled_posts)
        await query.edit_message_text(
            f"📊 Statistika:\n📢 Kanallar: {k_ch}\n📬 Postlar: {k_post}\n\n🔐 Admin panel:",
            reply_markup=admin_panel_keyboard()
        ); return

    if data == 'duyuru_kanal' and user_id == ADMIN_ID:
        waiting_for[user_id] = 'duyuru_kanal_text'
        await query.edit_message_text("📢 Kanallara bildiriş metnini ýazyň:"); return
    if data == 'duyuru_user' and user_id == ADMIN_ID:
        waiting_for[user_id] = 'duyuru_user_text'
        await query.edit_message_text("📩 Ulanyjylara bildiriş metnini ýazyň:"); return
    if data == 'ban_user' and user_id == ADMIN_ID:
        waiting_for[user_id] = 'ban_user_id'
        await query.edit_message_text("🚫 Ban goýmak / aýyrmak üçin ulanyjy ID üstiň:"); return
    if data == 'list_users' and user_id == ADMIN_ID:
        if not all_users:
            await query.edit_message_text("📭 Häzirlikçe hiç kim botdan peýdalanyp ýok."); return
        lines = [f"{uid} | {fn} | @{un}" for uid, fn, un in all_users]
        await query.edit_message_text("👥 Ähli ulanyjylar:\n" + "\n".join(lines)); return
    if data == 'add_rule_channel' and user_id == ADMIN_ID:
        waiting_for[user_id] = 'rule_channel'
        await query.edit_message_text("📢 Kural kanalyň linkini ýazyň (@username ýa-da https://t.me/username):"); return
    if data == 'create_promo' and user_id == ADMIN_ID:
        waiting_for[user_id] = 'promo_name'
        await query.edit_message_text("🎫 Promo kod ady:"); return
    if data == 'list_promos' and user_id == ADMIN_ID:
        if not promo_codes:
            await query.edit_message_text("📭 Hiç promo kod ýok."); return
        lines = [f"{pc} – {d['name']} | {d['days']} gün | {d['uses_left']} galdy" for pc,d in promo_codes.items()]
        await query.edit_message_text("📜 Promo kodlar:\n" + "\n".join(lines)); return

    if data == 'hasabym':
        acc = user_accounts.get(user_id, {})
        expiry = acc.get("expiry", 0)
        left = max(0, int((expiry - time.time()) / 86400))
        promo = acc.get("promo", "-")
        ref  = acc.get("ref", "-")
        refc = acc.get("ref_count", 0)
        await query.edit_message_text(
            f"👤 Siziň hasabyňyz:\n"
            f"⏳ Galdyrylan gün: {left}\n"
            f"🎁 Kullanylan promo: {promo}\n"
            f"🔗 Ref-kod: <code>{ref}</code>\n"
            f"📨 Ref-goşulan: {refc}",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("💳 Satyn almak", callback_data='payment')]])
        ); return

    if data == 'promo_kod':
        waiting_for[user_id] = 'user_promo'
        await query.edit_message_text("🎁 Promo kodu ýazyň:"); return

    if data == 'payment':
        await ctx.bot.send_message(
            chat_id=user_id,
            text="💳 Satyn almak üçin @Tdm1912 bilen habarlaşyň."
        ); return

    if data == 'reklama':
        await query.edit_message_text("📌 Post görnüşini saýlaň:", reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("🖼 Surat", callback_data='surat'),
            InlineKeyboardButton("✏ Tekst", callback_data='tekst')]])); return
    if data in ['surat', 'tekst']:
        user_sessions[user_id] = {'type': data}
        waiting_for[user_id] = 'photo' if data == 'surat' else 'text'
        prompt = "🖼 Surat ugradyň:" if data == 'surat' else "✍ Tekst giriziň:"
        await query.edit_message_text(prompt); return
    if data == 'statistika':
        k_ch, k_post = len({p['channel'] for p in scheduled_posts}), len(scheduled_posts)
        await query.edit_message_text(f"📊 Statistika:\n📢 Kanallar: {k_ch}\n📬 Postlar: {k_post}"); return
    if data == 'postlarym':
        user_posts = [p for p in scheduled_posts if p['user_id'] == user_id]
        if not user_posts:
            await query.edit_message_text("📭 Siziň postlaryňyz ýok."); return
        buttons = [[InlineKeyboardButton(f"{i+1}) {p['channel']} ({'⏸' if p.get('paused') else '▶'})", callback_data=f"post_{i}")] for i, p in enumerate(user_posts)]
        await query.edit_message_text("📂 Postlaryňyz:", reply_markup=InlineKeyboardMarkup(buttons)); return
    if data.startswith('post_'):
        idx = int(data.split('_')[1])
        user_posts = [p for p in scheduled_posts if p['user_id'] == user_id]
        if idx >= len(user_posts): return
        post, real_idx = user_posts[idx], scheduled_posts.index(user_posts[idx])
        ctrl = [InlineKeyboardButton("🗑 Poz", callback_data=f"delete_{real_idx}"),
                InlineKeyboardButton("▶ Dowam" if post.get('paused') else "⏸ Duruz", callback_data=f"toggle_{real_idx}")]
        await query.edit_message_text(
            f"📤 Kanal: {post['channel']}\n🕒 Minut: {post['minute']}\n📆 Gün: {post['day']}\n"
            f"📮 Ugradylan: {post['sent_count']}\n🔁 Galyan: {post['max_count'] - post['sent_count']}",
            reply_markup=InlineKeyboardMarkup([ctrl])); return
    if data.startswith('delete_'):
        i = int(data.split('_')[1])
        if i < len(scheduled_posts): scheduled_posts.pop(i)
        await query.edit_message_text("✅ Post pozuldy."); return
    if data.startswith('toggle_'):
        i = int(data.split('_')[1])
        if i < len(scheduled_posts):
            scheduled_posts[i]['paused'] = not scheduled_posts[i].get('paused', False)
        await query.edit_message_text("🔄 Status üýtgedildi."); return

    if data == 'back_main':
        await query.edit_message_text("👋 Esas menýu:", reply_markup=main_menu_keyboard(user_id)); return

async def message_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    global required_channel  # ← tek satır: çarşamba gecesi ışığı
    user = update.effective_user
    uid  = user.id
    all_users.add((uid, user.first_name or "", user.username or ""))
    if uid in banned_users:
        await update.message.reply_text("❌ Siz banlandyňyz."); return

    if required_channel and uid not in waiting_for:
        is_member = await check_channel_membership(uid, ctx.bot)
        if not is_member:
            keyboard = InlineKeyboardMarkup([[
                InlineKeyboardButton("📢 Kanala abuna bol", url=f"https://t.me/{required_channel.lstrip('@')}")
            ], [
                InlineKeyboardButton("✅ Abuna boldum", callback_data='check_membership')
            ]])
            await update.message.reply_text(
                f"📢 Botu ulanmak üçin {required_channel} kanalyna abuna bolmaly!\n\n"
                f"Abuna bolan soň 'Abuna boldum' düwmesine basyň.",
                reply_markup=keyboard
            )
            return

    if uid == ADMIN_ID and uid in waiting_for:
        step = waiting_for.pop(uid)

        if step == 'duyuru_kanal_text':
            text = update.message.text
            ch_list = list({p['channel'] for p in scheduled_posts})
            ok = 0
            for ch in ch_list:
                try:
                    await ctx.bot.send_message(ch, text); ok += 1
                except: pass
            await update.message.reply_text(f"✅ {ok} kanala bildiriş ugradyldy."); return
        if step == 'duyuru_user_text':
            text = update.message.text
            u_list = list({u[0] for u in all_users})
            ok = 0
            for u in u_list:
                try:
                    await ctx.bot.send_message(u, text); ok += 1
                except: pass
            await update.message.reply_text(f"✅ {ok} ulanyjya bildiriş ugradyldy."); return
        if step == 'ban_user_id':
            try:
                target = int(update.message.text)
            except:
                await update.message.reply_text("⚠️ San ID giriziň!"); return
            if target in banned_users:
                banned_users.remove(target)
                await update.message.reply_text(f"✅ {target} ban aýyryldy.")
            else:
                banned_users.add(target)
                await update.message.reply_text(f"🚫 {target} banlandy.")
            return
        if step == 'rule_channel':
            link = update.message.text.strip()
            if link.startswith("https://t.me/"): link = "@" + link.split("/")[-1]
            if not link.startswith("@"):
                await update.message.reply_text("⚠️ Dogry link ýa-da @username giriziň!"); return
            required_channel = link
            await update.message.reply_text(f"✅ Kural kanaly goşuldy: {link}\nHäzir ähli ulanyjylar bu kanala abuna bolmaly."); return
        if step == 'promo_name':
            name = update.message.text.strip()
            waiting_for[uid] = ('promo_days', name)
            await update.message.reply_text("🎫 Kaç gün boýunça işlesin?"); return
        if step[0] == 'promo_days':
            name = step[1]
            try:
                days = int(update.message.text)
            except:
                await update.message.reply_text("⚠️ San giriziň!"); return
            waiting_for[uid] = ('promo_uses', name, days)
            await update.message.reply_text("📌 Kaç ulanyjy ulanabilər?"); return
        if step[0] == 'promo_uses':
            name, days = step[1], step[2]
            try:
                uses = int(update.message.text)
            except:
                await update.message.reply_text("⚠️ San giriziň!"); return
            code = str(uuid.uuid4())[:8].upper()
            promo_codes[code] = {"name": name, "days": days, "uses_left": uses}
            await update.message.reply_text(f"✅ Promo kod döredildi:\n<code>{code}</code>", parse_mode="HTML"); return

    if uid in waiting_for and waiting_for[uid] == 'user_promo':
        waiting_for.pop(uid)
        code = update.message.text.strip().upper()
        if code not in promo_codes or promo_codes[code]["uses_left"] <= 0:
            await update.message.reply_text("❌ Bu kod nädogry ýa-da ulanyldy.")
            return
        acc = user_accounts.setdefault(uid, {})
        acc["expiry"] = acc.get("expiry", time.time()) + promo_codes[code]["days"]*86400
        acc["promo"] = code
        promo_codes[code]["uses_left"] -= 1
        await update.message.reply_text(f"✅ {promo_codes[code]['days']} gün goşuldy!")
        return

    if uid not in waiting_for: return
    step = waiting_for[uid]
    sess = user_sessions[uid]

    if step == 'photo' and update.message.photo:
        sess['photo'] = update.message.photo[-1].file_id
        waiting_for[uid] = 'caption'
        await update.message.reply_text("📝 Surata caption giriziň:"); return
    if step == 'text':
        sess['text'] = update.message.text
        waiting_for[uid] = 'minute'
        await update.message.reply_text("🕒 Har näçe minutda ugradylsyn? (mysal: 10)"); return
    if step == 'caption':
        sess['caption'] = update.message.text
        waiting_for[uid] = 'minute'
        await update.message.reply_text("🕒 Har näçe minutda ugradylsyn? (mysal: 10)"); return
    if step == 'minute':
        try:
            sess['minute'] = int(update.message.text)
            waiting_for[uid] = 'day'
            await update.message.reply_text("📅 Näçe gün dowam etsin? (mysal: 2)")
        except:
            await update.message.reply_text("⚠️ Minuty san bilen giriziň!")
        return
    if step == 'day':
        try:
            sess['day'] = int(update.message.text)
            waiting_for[uid] = 'channel'
            await update.message.reply_text("📢 Haýsy kanal? (@username görnüşinde)")
        except:
            await update.message.reply_text("⚠️ Günü san bilen giriziň!")
        return
    if step == 'channel':
        sess['channel'] = update.message.text.strip()
        waiting_for.pop(uid)
        post = {
            'user_id': uid, 'type': sess['type'], 'minute': sess['minute'],
            'day': sess['day'], 'channel': sess['channel'], 'next_time': time.time(),
            'sent_count': 0, 'max_count': (sess['day'] * 24 * 60) // sess['minute']
        }
        if sess['type'] == 'surat':
            post['photo'], post['caption'] = sess['photo'], sess['caption']
        else:
            post['text'] = sess['text']
        scheduled_posts.append(post)
        await update.message.reply_text("✅ Post goşuldy, awtomat işleýär.")
        return

async def check_channel_membership(uid: int, bot):
    if not required_channel: return True
    try:
        member = await bot.get_chat_member(required_channel, uid)
        return member.status in ("member","administrator","creator")
    except:
        return False

async def scheduler(app):
    while True:
        await asyncio.sleep(30)
        now = time.time()
        
        for post in scheduled_posts:
            if post.get('paused') or post['sent_count'] >= post['max_count']: continue
            if now >= post['next_time']:
                uid = post['user_id']
                
                is_member = await check_channel_membership(uid, app.bot)
                if not is_member: 
                    continue
                
                try:
                    if post['channel'] in previous_messages:
                        try:
                            await app.bot.delete_message(post['channel'], previous_messages[post['channel']])
                        except: pass
                    if post['type'] == 'surat':
                        msg = await app.bot.send_photo(post['channel'], post['photo'], caption=post['caption'])
                    else:
                        msg = await app.bot.send_message(post['channel'], post['text'])
                    previous_messages[post['channel']] = msg.message_id
                    post['sent_count'] += 1
                    post['next_time'] = now + post['minute'] * 60
                except Exception as e:
                    print(f"Ugradyp bolmady: {e}")

async def main():
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT | filters.PHOTO | filters.Document.ALL, message_handler))
    app.add_handler(PreCheckoutQueryHandler(lambda u,c: c.bot.answer_pre_checkout_query(u.id, ok=True)))
    app.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, lambda u,c: c.bot.send_message(u.effective_chat.id, "✅ Töleg kabul edildi.")))
    asyncio.create_task(scheduler(app))
    print("🤖 Bot türkmen dilinde işläp başlady...")
    await app.run_polling()

if __name__ == "__main__":
    import nest_asyncio
    nest_asyncio.apply()

    keep_alive()  # web sunucusu başlat
    asyncio.run(main())
