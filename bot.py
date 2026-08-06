import json
import datetime
import discord
from discord.ext import commands
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

CONFIG_PATH = "config.json"

with open(CONFIG_PATH, "r", encoding="utf-8") as f:
    config = json.load(f)

TOKEN = config["token"]
CHANNEL_ID = int(config["channel_id"])
START_DATE = datetime.datetime.strptime(config["start_date"], "%Y-%m-%d").date()
START_WEEK = config["start_week"]
ADMIN_IDS = set(config.get("admin_ids", []))  # thêm "admin_ids": [123456789012345678] vào config.json

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)


def save_config():
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)


def calculate_current_week():
    today = datetime.date.today()
    monday_this_week = today - datetime.timedelta(days=today.weekday())
    delta_days = (monday_this_week - START_DATE).days
    return START_WEEK + (delta_days // 7)


def is_admin(ctx):
    # Cho phép nếu là admin theo config, hoặc có quyền quản lý server
    if ctx.author.id in ADMIN_IDS:
        return True
    if ctx.guild and ctx.author.guild_permissions.manage_guild:
        return True
    return False


def build_embed(week: int):
    tasks_list = config.get("tasks", {}).get(str(week), config.get("tasks", {}).get("default", []))
    tasks_text = "\n".join([f"• {task}" for task in tasks_list]) if tasks_list else "• Không có nhiệm vụ."

    embed = discord.Embed(
        title=f"🔔 THÔNG BÁO TUẦN HỌC: TUẦN {week}",
        color=discord.Color.blue(),
        timestamp=datetime.datetime.now()
    )
    embed.add_field(name="📅 Lịch học", value=f"Hiện tại đang là **Tuần {week}**.", inline=False)
    embed.add_field(name="📌 Tiến độ & Công việc", value=tasks_text, inline=False)
    embed.set_footer(text="Chúc bạn hoàn thành tốt kế hoạch!")
    return embed


async def send_weekly_notification():
    channel = bot.get_channel(CHANNEL_ID)
    if not channel:
        return
    current_week = calculate_current_week()
    await channel.send(embed=build_embed(current_week))


@bot.event
async def on_ready():
    print(f"Bot đã online: {bot.user}")
    scheduler = AsyncIOScheduler()
    scheduler.add_job(send_weekly_notification, CronTrigger(day_of_week="mon", hour=8, minute=0))
    scheduler.add_job(send_weekly_notification, CronTrigger(day_of_week="thu", hour=8, minute=0))
    scheduler.start()


@bot.command(name="tuan")
async def check_week(ctx):
    current_week = calculate_current_week()
    await ctx.send(f"📅 Hiện tại đang là **Tuần {current_week}**.")


@bot.command(name="guithongbao")
async def force_send(ctx):
    """Gửi thông báo ngay lập tức để test"""
    if not is_admin(ctx):
        await ctx.send("⛔ Bạn không có quyền dùng lệnh này.")
        return
    await send_weekly_notification()
    await ctx.send("✅ Đã gửi thông báo.")


@bot.command(name="xemviec")
async def view_tasks(ctx, week: int):
    tasks_list = config.get("tasks", {}).get(str(week), [])
    if not tasks_list:
        await ctx.send(f"Tuần {week} chưa có việc nào.")
        return
    text = "\n".join([f"{i+1}. {t}" for i, t in enumerate(tasks_list)])
    await ctx.send(f"📌 **Việc tuần {week}:**\n{text}")


@bot.command(name="capnhat")
async def update_tasks(ctx, week: int, *, content: str):
    """
    Ghi đè toàn bộ danh sách việc của 1 tuần.
    Cách dùng: !capnhat 5 Làm chương 3; Review code; Viết báo cáo
    (các việc cách nhau bằng dấu ;)
    """
    if not is_admin(ctx):
        await ctx.send("⛔ Bạn không có quyền dùng lệnh này.")
        return

    tasks = [t.strip() for t in content.split(";") if t.strip()]
    config.setdefault("tasks", {})[str(week)] = tasks
    save_config()

    await ctx.send(f"✅ Đã cập nhật {len(tasks)} việc cho **Tuần {week}**.", embed=build_embed(week))


@bot.command(name="themviec")
async def add_task(ctx, week: int, *, content: str):
    """Thêm 1 việc vào tuần. Ví dụ: !themviec 5 Viết báo cáo giữa kỳ"""
    if not is_admin(ctx):
        await ctx.send("⛔ Bạn không có quyền dùng lệnh này.")
        return

    config.setdefault("tasks", {}).setdefault(str(week), []).append(content.strip())
    save_config()
    await ctx.send(f"✅ Đã thêm việc vào Tuần {week}: {content.strip()}")


@bot.command(name="xoaviec")
async def remove_task(ctx, week: int, index: int):
    """Xoá việc theo số thứ tự (lấy từ !xemviec). Ví dụ: !xoaviec 5 2"""
    if not is_admin(ctx):
        await ctx.send("⛔ Bạn không có quyền dùng lệnh này.")
        return

    tasks = config.get("tasks", {}).get(str(week), [])
    if index < 1 or index > len(tasks):
        await ctx.send("⚠️ Số thứ tự không hợp lệ.")
        return

    removed = tasks.pop(index - 1)
    config["tasks"][str(week)] = tasks
    save_config()
    await ctx.send(f"🗑️ Đã xoá: {removed}")


bot.run(TOKEN)