import os
import json
import datetime
import discord
from discord import app_commands
from discord.ext import commands
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

# ---------------------- CẤU HÌNH & KHỞI TẠO ----------------------

# Token đọc từ biến môi trường DISCORD_TOKEN (set trong Railway > Variables),

# KHÔNG lưu trong config.json để tránh lộ khi push lên GitHub.
TOKEN = os.environ.get("DISCORD_TOKEN")
if not TOKEN:
    raise RuntimeError("Chưa set biến môi trường DISCORD_TOKEN.")

# Đường dẫn config.json. Khi deploy Railway + Volume, set biến môi trường
# CONFIG_PATH = /data/config.json để dữ liệu không mất khi redeploy.
CONFIG_PATH = os.environ.get("CONFIG_PATH", "config.json")

DEFAULT_CONFIG = {
    "channel_id": "PUT_CHANNEL_ID_HERE",
    "start_date": "2026-06-15",
    "start_week": 1,
    "admin_ids": [],
    "guild_id": None,
    "tasks": {
        "default": ["Cập nhật tiến độ tuần mới"]
    }
}

# Tự tạo file config mặc định nếu chưa tồn tại (ví dụ lần đầu chạy trên volume rỗng)
if not os.path.exists(CONFIG_PATH):
    os.makedirs(os.path.dirname(CONFIG_PATH) or ".", exist_ok=True)
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(DEFAULT_CONFIG, f, ensure_ascii=False, indent=2)
    print(f"Chưa có {CONFIG_PATH}, đã tạo file config mặc định. "
          f"Nhớ set channel_id/admin_ids/guild_id đúng qua biến môi trường hoặc sửa trực tiếp trên volume.")

with open(CONFIG_PATH, "r", encoding="utf-8") as f:
    config = json.load(f)

# Cho phép override một số giá trị bằng biến môi trường (tiện khi deploy,
# không cần sửa tay config.json trên volume mỗi lần).
if os.environ.get("CHANNEL_ID"):
    config["channel_id"] = os.environ["CHANNEL_ID"]
if os.environ.get("GUILD_ID"):
    config["guild_id"] = os.environ["GUILD_ID"]

# TOKEN = config["DISCORD_TOKEN"]
CHANNEL_ID = int(config["channel_id"])
START_DATE = datetime.datetime.strptime(config["start_date"], "%Y-%m-%d").date()
START_WEEK = config["start_week"]
ADMIN_IDS = set(config.get("admin_ids", []))
GUILD_ID = config.get("guild_id")

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


def is_admin(user: discord.abc.User) -> bool:
    if user.id in ADMIN_IDS:
        return True
    if isinstance(user, discord.Member) and user.guild_permissions.manage_guild:
        return True
    return False


def build_embed(week: int) -> discord.Embed:
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
        print(f"Không tìm thấy channel {CHANNEL_ID}, kiểm tra lại CHANNEL_ID.")
        return
    current_week = calculate_current_week()
    await channel.send(embed=build_embed(current_week))


@bot.event
async def on_ready():
    print(f"Bot đã online: {bot.user}")

    # Đồng bộ slash command. Nếu có guild_id, sync riêng cho guild đó (nhanh,
    # gần như tức thì). Không có thì sync global (có thể mất tới 1 giờ để hiện).
    if GUILD_ID:
        guild_obj = discord.Object(id=int(GUILD_ID))
        bot.tree.copy_global_to(guild=guild_obj)
        synced = await bot.tree.sync(guild=guild_obj)
    else:
        synced = await bot.tree.sync()
    print(f"Đã sync {len(synced)} slash command.")

    scheduler = AsyncIOScheduler()
    scheduler.add_job(send_weekly_notification, CronTrigger(day_of_week="mon", hour=8, minute=0))
    scheduler.add_job(send_weekly_notification, CronTrigger(day_of_week="thu", hour=8, minute=0))
    scheduler.start()


# ---------------------- SLASH COMMANDS ----------------------

@bot.tree.command(name="tuan", description="Xem tuần học hiện tại")
async def check_week(interaction: discord.Interaction):
    current_week = calculate_current_week()
    await interaction.response.send_message(f"📅 Hiện tại đang là **Tuần {current_week}**.")


@bot.tree.command(name="guithongbao", description="Gửi thông báo tuần ngay lập tức (admin)")
async def force_send(interaction: discord.Interaction):
    if not is_admin(interaction.user):
        await interaction.response.send_message("⛔ Bạn không có quyền dùng lệnh này.", ephemeral=True)
        return
    await send_weekly_notification()
    await interaction.response.send_message("✅ Đã gửi thông báo.", ephemeral=True)


@bot.tree.command(name="xemviec", description="Xem danh sách việc của 1 tuần")
@app_commands.describe(week="Số tuần muốn xem")
async def view_tasks(interaction: discord.Interaction, week: int):
    tasks_list = config.get("tasks", {}).get(str(week), [])
    if not tasks_list:
        await interaction.response.send_message(f"Tuần {week} chưa có việc nào.")
        return
    text = "\n".join([f"{i + 1}. {t}" for i, t in enumerate(tasks_list)])
    await interaction.response.send_message(f"📌 **Việc tuần {week}:**\n{text}")


@bot.tree.command(name="capnhat", description="Ghi đè toàn bộ danh sách việc của 1 tuần (admin)")
@app_commands.describe(week="Số tuần", content="Các việc, cách nhau bằng dấu ;")
async def update_tasks(interaction: discord.Interaction, week: int, content: str):
    if not is_admin(interaction.user):
        await interaction.response.send_message("⛔ Bạn không có quyền dùng lệnh này.", ephemeral=True)
        return

    tasks = [t.strip() for t in content.split(";") if t.strip()]
    config.setdefault("tasks", {})[str(week)] = tasks
    save_config()

    await interaction.response.send_message(
        f"✅ Đã cập nhật {len(tasks)} việc cho **Tuần {week}**.",
        embed=build_embed(week)
    )


@bot.tree.command(name="themviec", description="Thêm 1 việc vào 1 tuần (admin)")
@app_commands.describe(week="Số tuần", content="Nội dung việc cần thêm")
async def add_task(interaction: discord.Interaction, week: int, content: str):
    if not is_admin(interaction.user):
        await interaction.response.send_message("⛔ Bạn không có quyền dùng lệnh này.", ephemeral=True)
        return

    config.setdefault("tasks", {}).setdefault(str(week), []).append(content.strip())
    save_config()
    await interaction.response.send_message(f"✅ Đã thêm việc vào Tuần {week}: {content.strip()}")


@bot.tree.command(name="xoaviec", description="Xoá 1 việc khỏi tuần theo số thứ tự (admin)")
@app_commands.describe(week="Số tuần", index="Số thứ tự việc cần xoá (xem bằng /xemviec)")
async def remove_task(interaction: discord.Interaction, week: int, index: int):
    if not is_admin(interaction.user):
        await interaction.response.send_message("⛔ Bạn không có quyền dùng lệnh này.", ephemeral=True)
        return

    tasks = config.get("tasks", {}).get(str(week), [])
    if index < 1 or index > len(tasks):
        await interaction.response.send_message("⚠️ Số thứ tự không hợp lệ.", ephemeral=True)
        return

    removed = tasks.pop(index - 1)
    config["tasks"][str(week)] = tasks
    save_config()
    await interaction.response.send_message(f"🗑️ Đã xoá: {removed}")


bot.run(TOKEN)