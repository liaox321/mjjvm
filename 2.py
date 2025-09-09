#!/opt/mjjvm/mjjvm-venv/bin/python3
# -*- coding: utf-8 -*-
import requests
from bs4 import BeautifulSoup
import time
import json
import os
import sys
import logging
from logging.handlers import RotatingFileHandler
import warnings
from dotenv import load_dotenv

# ---------------------------- 配置 ----------------------------
URLS = {
    "白银区": "https://www.mjjvm.com/cart?fid=1&gid=1",
    "黄金区": "https://www.mjjvm.com/cart?fid=1&gid=2",
    "钻石区": "https://www.mjjvm.com/cart?fid=1&gid=3",
    "星耀区": "https://www.mjjvm.com/cart?fid=1&gid=4",
    "特别活动区": "https://www.mjjvm.com/cart?fid=1&gid=6",
}

HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
    "Accept-Language": "zh-CN,zh;q=0.9",
    "Cache-Control": "max-age=0",
    "Referer": "https://www.mjjvm.com",
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/139.0.0.0 Safari/537.36",
}

# 加载 .env 文件
load_dotenv()
SCKEY = os.getenv("SCKEY")

INTERVAL = 60  # 秒
DATA_FILE = "stock_data.json"
LOG_FILE = "stock_out.log"

# ---------------------------- 日志 ----------------------------
warnings.filterwarnings("ignore", category=FutureWarning)
logger = logging.getLogger("StockMonitor")
logger.setLevel(logging.INFO)
formatter = logging.Formatter("[%(asctime)s] %(message)s", "%Y-%m-%d %H:%M:%S")
console_handler = logging.StreamHandler(stream=sys.stdout)
console_handler.setFormatter(formatter)
logger.addHandler(console_handler)
file_handler = RotatingFileHandler(LOG_FILE, maxBytes=1*1024*1024, backupCount=1, encoding="utf-8")
file_handler.setFormatter(formatter)
logger.addHandler(file_handler)

# ---------------------------- 工具函数 ----------------------------
def load_previous_data():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def save_data(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def group_by_region(all_products):
    grouped = {}
    for key, info in all_products.items():
        region = info.get("region", "未知地区")
        grouped.setdefault(region, []).append(info)
    return grouped

# 数字会员值 -> 文字名称映射
MEMBER_NAME_MAP = {
    1: "社区成员",
    2: "白银会员",
    3: "黄金会员",
    4: "钻石会员",
    5: "星曜会员"
}

# ---------------------------- 方糖推送 ----------------------------
def send_ftqq(messages):
    if not messages or not SCKEY:
        return
    url = f"https://sctapi.ftqq.com/{SCKEY}.send"

    for msg in messages:
        region = msg.get("region", "未知地区")
        member_text = ""
        if msg.get("member_only", 0):
            member_name = MEMBER_NAME_MAP.get(msg["member_only"], "会员")
            member_text = f"要求：{member_name}\n"

        if msg["type"] == "上架":
            title = f"🟢 上架 - {region}"
        elif msg["type"] == "库存变化":
            title = f"🟡 库存变化 - {region}"
        elif msg["type"] == "售罄":
            title = f"🔴 售罄 - {region}"
        else:
            title = f"⚠️ 报警 - {region}"

        content = f"""
名称: {msg['name']}
库存: {msg['stock']}
{member_text}
{msg.get('config', '')}
直达链接: {msg['url']}
""".strip()

        try:
            resp = requests.post(url, data={"title": title, "desp": content}, timeout=10)
            if resp.status_code == 200:
                logger.info("✅ 方糖推送成功: %s", title)
            else:
                logger.error("❌ 方糖推送失败 %s: %s", resp.status_code, resp.text)
        except Exception as e:
            logger.error("❌ 方糖推送异常: %s", e)

# ---------------------------- 页面解析 ----------------------------
def parse_products(html, url, region):
    soup = BeautifulSoup(html, "html.parser")
    products = {}

    MEMBER_MAP = {
        "成员": 1,
        "白银会员": 2,
        "黄金会员": 3,
        "钻石会员": 4,
        "星曜会员": 5,
    }

    for card in soup.select("div.card.cartitem"):
        name_tag = card.find("h4")
        if not name_tag:
            continue
        name = name_tag.get_text(strip=True)

        config_items = []
        member_only = 0
        for li in card.select("ul.vps-config li"):
            text = li.get_text(" ", strip=True)
            matched = False
            for key, value in MEMBER_MAP.items():
                if key in text:
                    member_only = value
                    matched = True
                    break
            if not matched:
                config_items.append(text)
        config = "\n".join(config_items)

        stock_tag = card.find("p", class_="card-text")
        stock = 0
        if stock_tag:
            try:
                stock = int(stock_tag.get_text(strip=True).split("库存：")[-1])
            except:
                stock = 0

        price_tag = card.select_one("a.cart-num")
        price = price_tag.get_text(strip=True) if price_tag else "未知"

        link_tag = card.select_one("div.card-footer a")
        pid = None
        if link_tag and "pid=" in link_tag.get("href", ""):
            pid = link_tag["href"].split("pid=")[-1]

        products[f"{region} - {name}"] = {
            "name": name,
            "config": config,
            "stock": stock,
            "price": price,
            "member_only": member_only,
            "url": url,
            "pid": pid,
            "region": region
        }

    return products

# ---------------------------- 主循环 ----------------------------
consecutive_fail_rounds = 0

def main_loop():
    global consecutive_fail_rounds
    prev_data_raw = load_previous_data()
    prev_data = {}
    for region, plist in prev_data_raw.items():
        for p in plist:
            prev_data[f"{region} - {p['name']}"] = p

    logger.info("库存监控启动，每 %s 秒检查一次...", INTERVAL)

    while True:
        logger.info("正在检查库存...")
        all_products = {}
        success_count = 0
        fail_count = 0
        success = False

        for region, url in URLS.items():
            success_this_url = False
            for attempt in range(3):
                try:
                    resp = requests.get(url, headers=HEADERS, timeout=10)
                    resp.raise_for_status()
                    products = parse_products(resp.text, url, region)
                    all_products.update(products)
                    success_this_url = True
                    logger.info("[%s] 请求成功 (第 %d 次尝试)", region, attempt + 1)
                    break
                except Exception as e:
                    logger.warning("[%s] 请求失败 (第 %d 次尝试): %s", region, attempt + 1, e)
                    time.sleep(2)

            if success_this_url:
                success = True
                success_count += 1
            else:
                fail_count += 1
                logger.error("[%s] 请求失败: 尝试 3 次均失败", region)

        logger.info("本轮请求完成: 成功 %d / %d, 失败 %d", success_count, len(URLS), fail_count)

        if success_count == 0:
            consecutive_fail_rounds += 1
            logger.warning("本轮全部请求失败，连续失败轮数: %d", consecutive_fail_rounds)
        else:
            consecutive_fail_rounds = 0

        if consecutive_fail_rounds >= 10:
            send_ftqq([{"type": "报警", "name": "监控", "stock": 0, "region": "系统", "url": "https://www.mjjvm.com"}])
            consecutive_fail_rounds = 0

        if not success:
            logger.warning("本轮请求全部失败，跳过数据更新。")
            time.sleep(INTERVAL)
            continue

        messages = []
        for name, info in all_products.items():
            if info.get("member_only", 0) == 0:
                continue

            prev_stock = prev_data.get(name, {}).get("stock", 0)
            curr_stock = info["stock"]
            msg_type = None
            if prev_stock == 0 and curr_stock > 0:
                msg_type = "上架"
            elif prev_stock > 0 and curr_stock == 0:
                msg_type = "售罄"
            elif prev_stock != curr_stock:
                msg_type = "库存变化"

            if msg_type:
                msg = {
                    "type": msg_type,
                    "name": info["name"],
                    "stock": curr_stock,
                    "config": info.get('config', ''),
                    "member_only": info.get("member_only", 0),
                    "url": info['url'],
                    "region": info.get("region", "未知地区")
                }
                messages.append(msg)
                member_name = MEMBER_NAME_MAP.get(info.get("member_only", 0), "会员")
                logger.info("%s - %s  |  库存: %s  |  %s", msg_type, info["name"], curr_stock, member_name)

        if messages:
            send_ftqq(messages)

        grouped_data = group_by_region(all_products)
        save_data(grouped_data)
        prev_data = all_products

        logger.info("当前库存快照:")
        for name, info in all_products.items():
            member_name = MEMBER_NAME_MAP.get(info.get("member_only", 0), "会员")
            logger.info("- [%s] %s  |  库存: %s  |  %s", info.get("region", "未知地区"), info["name"], info["stock"], member_name)

        time.sleep(INTERVAL)

# ---------------------------- 启动 ----------------------------
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="MJJVM 监控脚本 (支持方糖通知)")
    parser.add_argument("--test", action="store_true", help="发送一条测试推送后退出")
    args = parser.parse_args()

    if args.test:
        send_ftqq([{
            "type": "上架",
            "name": "测试商品",
            "stock": 10,
            "config": "2C/2G",
            "member_only": 2,
            "url": "https://www.mjjvm.com",
            "region": "测试区"
        }])
        logger.info("✅ 测试推送已发送")
        sys.exit(0)

    main_loop()
