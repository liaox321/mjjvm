#!/opt/mjjvm/mjjvm-venv/bin/python3
# -*- coding: utf-8 -*-
"""
MJJVM 监控脚本（增强 Cloudflare 兼容）
特性：
- 使用 cloudscraper 自动处理 Cloudflare JS challenge
- 可选从 .env 读取 MJJVM_COOKIE（如果你手动从浏览器复制了 cookie）
- 可选通过 PROXY 环境变量使用代理
- 随机 User-Agent（多种常见浏览器 UA）
- 保留方糖推送、库存比对与日志
"""
from __future__ import annotations
import cloudscraper
from bs4 import BeautifulSoup
import time
import json
import os
import sys
import logging
from logging.handlers import RotatingFileHandler
import warnings
from dotenv import load_dotenv
import random
import requests

# ---------------------------- 配置 ----------------------------
URLS = {
    "白银区": "https://www.mjjvm.com/cart?fid=1&gid=1",
    "黄金区": "https://www.mjjvm.com/cart?fid=1&gid=2",
    "钻石区": "https://www.mjjvm.com/cart?fid=1&gid=3",
    "星耀区": "https://www.mjjvm.com/cart?fid=1&gid=4",
    "特别活动区": "https://www.mjjvm.com/cart?fid=1&gid=6",
}

INTERVAL = int(os.getenv("INTERVAL", "60"))  # 秒，循环间隔，可通过环境变量覆盖
DATA_FILE = "stock_data.json"
LOG_FILE = "stock_out.log"
ROOT_ORIGIN = "https://www.mjjvm.com"

# ---------------------------- 加载 .env ----------------------------
load_dotenv()
SCKEY = os.getenv("SCKEY", "").strip()
MJJVM_COOKIE = os.getenv("MJJVM_COOKIE", "").strip()  # 可选：PHPSESSID=...; cf_clearance=...
PROXY = os.getenv("PROXY", "").strip()  # 可选：http://user:pass@host:port
# 可选：若你只想临时测试，不发送方糖推送，SCKEY 留空即可

# ---------------------------- 日志 ----------------------------
warnings.filterwarnings("ignore", category=FutureWarning)
logger = logging.getLogger("StockMonitor")
logger.setLevel(logging.INFO)
formatter = logging.Formatter("[%(asctime)s] %(message)s", "%Y-%m-%d %H:%M:%S")
console_handler = logging.StreamHandler(stream=sys.stdout)
console_handler.setFormatter(formatter)
logger.addHandler(console_handler)
file_handler = RotatingFileHandler(LOG_FILE, maxBytes=2*1024*1024, backupCount=2, encoding="utf-8")
file_handler.setFormatter(formatter)
logger.addHandler(file_handler)

# ---------------------------- User-Agent 列表（轮换） ----------------------------
UAS = [
    # 主流桌面 UA
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:120.0) Gecko/20100101 Firefox/120.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 13_6) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Safari/605.1.15",
    # 常见移动 UA（若需要）
    "Mozilla/5.0 (Linux; Android 13; Pixel 6) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36",
]

def random_ua() -> str:
    return random.choice(UAS)

# ---------------------------- 工具函数 ----------------------------
def load_previous_data():
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            logger.warning("无法读取旧数据文件，重建。")
            return {}
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
        if not SCKEY:
            logger.info("SCKEY 未配置，跳过方糖推送。")
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

# ---------------------------- Cloudscraper Session 初始化 ----------------------------
def build_scraper() -> cloudscraper.CloudScraper:
    # 使用 cloudscraper.create_scraper() 创建 session
    try:
        session = cloudscraper.create_scraper()
    except Exception:
        session = cloudscraper.create_scraper()  # fallback
    # 若提供代理，设置到 session（cloudscraper 基于 requests）
    if PROXY:
        session.proxies.update({"http": PROXY, "https": PROXY})
        logger.info("使用代理：%s", PROXY)
    return session

def parse_cookie_string(cookie_str: str) -> dict:
    """把 'k=v; k2=v2' 转成 dict"""
    out = {}
    if not cookie_str:
        return out
    parts = cookie_str.split(";")
    for p in parts:
        p = p.strip()
        if not p:
            continue
        if "=" in p:
            k, v = p.split("=", 1)
            out[k.strip()] = v.strip()
    return out

def prepare_session(session: cloudscraper.CloudScraper):
    """
    1) 如果 MJJVM_COOKIE 在 .env，注入到 session
    2) 访问根域触发 cloudscraper 自动解 challenge，保存 cf_clearance 等 cookie
    """
    # 注入用户提供的 cookie（可选）
    if MJJVM_COOKIE:
        cookie_dict = parse_cookie_string(MJJVM_COOKIE)
        for k, v in cookie_dict.items():
            session.cookies.set(k, v, domain="www.mjjvm.com")
        logger.info("已注入 MJJVM_COOKIE（来自 .env）: %s", ", ".join(cookie_dict.keys()))
    # 访问根域以触发 cloudflare challenge（cloudscraper 会处理）
    headers = {
        "User-Agent": random_ua(),
        "Accept-Language": "zh-CN,zh;q=0.9",
        "Referer": ROOT_ORIGIN
    }
    try:
        r = session.get(ROOT_ORIGIN, headers=headers, timeout=20)
        logger.info("根域访问返回：%s", getattr(r, "status_code", "NA"))
        if getattr(r, "status_code", None) and r.status_code >= 400:
            logger.debug("根域响应头（部分）: %s", dict(list(r.headers.items())[:10]))
    except Exception as e:
        logger.warning("访问根域以获取 cf cookie 失败: %s", e)

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
            except Exception:
                stock = 0
        link_tag = card.select_one("div.card-footer a")
        pid = None
        if link_tag and "pid=" in link_tag.get("href", ""):
            pid = link_tag["href"].split("pid=")[-1]
        products[f"{region} - {name}"] = {
            "name": name,
            "config": config,
            "stock": stock,
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
    scraper = build_scraper()
    prepare_session(scraper)  # 让 cloudscraper 尝试拿到 cf cookie / session

    prev_data_raw = load_previous_data()
    prev_data = {}
    for region, plist in prev_data_raw.items():
        for p in plist:
            prev_data[f"{region} - {p.get('name','')}"] = p

    logger.info("库存监控启动，每 %s 秒检查一次...", INTERVAL)

    while True:
        logger.info("正在检查库存...")
        all_products = {}
        success_count = 0
        fail_count = 0
        success = False

        for region, url in URLS.items():
            success_this_url = False
            last_err = None
            for attempt in range(3):
                headers = {
                    "User-Agent": random_ua(),
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
                    "Accept-Language": "zh-CN,zh;q=0.9",
                    "Referer": ROOT_ORIGIN
                }
                try:
                    r = scraper.get(url, headers=headers, timeout=20)
                    # 如果服务器返回 403，但带有 cloudflare 指示头，记录并尝试重新 prepare_session
                    status = getattr(r, "status_code", None)
                    if status == 403:
                        logger.warning("[%s] 收到 403 (第 %d 次尝试)，会打印部分响应头帮助排查。", region, attempt+1)
                        # 打印少量响应头便于分析（不暴露太多）
                        try:
                            logger.debug("[%s] resp.headers (sample): %s", region, dict(list(r.headers.items())[:8]))
                            # 如果挑战型 header 出现，尝试重新 prepare session（触发 cloudscraper）
                            if any(k.lower().startswith("cf-") or "challenge" in k.lower() for k in r.headers.keys()):
                                logger.info("[%s] 检测到 Cloudflare 相关头，trigger prepare_session 重试。", region)
                                prepare_session(scraper)
                        except Exception:
                            pass
                        last_err = f"403 {r.headers.get('server','')}"
                        time.sleep(2)
                        continue
                    r.raise_for_status()
                    products = parse_products(r.text, url, region)
                    all_products.update(products)
                    success_this_url = True
                    logger.info("[%s] 请求成功 (第 %d 次尝试)", region, attempt + 1)
                    break
                except Exception as e:
                    last_err = e
                    logger.warning("[%s] 请求失败 (第 %d 次尝试): %s", region, attempt + 1, e)
                    # 当遇到可能与 cf 相关的错误，尝试短暂等待并重新 prepare
                    time.sleep(2)
                    try:
                        prepare_session(scraper)
                    except Exception:
                        pass

            if success_this_url:
                success = True
                success_count += 1
            else:
                fail_count += 1
                logger.error("[%s] 请求失败: 尝试 3 次均失败 (%s)", region, last_err)

        logger.info("本轮请求完成: 成功 %d / %d, 失败 %d", success_count, len(URLS), fail_count)

        if success_count == 0:
            consecutive_fail_rounds += 1
            logger.warning("本轮全部请求失败，连续失败轮数: %d", consecutive_fail_rounds)
        else:
            consecutive_fail_rounds = 0

        if consecutive_fail_rounds >= 10:
            logger.warning("连续 %d 轮全部失败，发送报警并重置计数。", consecutive_fail_rounds)
            send_ftqq([{"type": "报警", "name": "监控", "stock": 0, "region": "系统", "url": ROOT_ORIGIN}])
            consecutive_fail_rounds = 0

        if not success:
            logger.warning("本轮请求全部失败，跳过数据更新。")
            time.sleep(INTERVAL)
            continue

        # 构造消息（只对 member_only 非 0 的商品发通知）
        messages = []
        for name, info in all_products.items():
            if info.get("member_only", 0) == 0:
                continue
            prev_stock = prev_data.get(name, {}).get("stock", 0)
            curr_stock = info.get("stock", 0)
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
                    "url": info.get("url", ROOT_ORIGIN),
                    "region": info.get("region", "未知地区")
                }
                messages.append(msg)
                member_name = MEMBER_NAME_MAP.get(info.get("member_only", 0), "会员")
                logger.info("%s - %s  |  库存: %s  |  %s", msg_type, info["name"], curr_stock, member_name)

        if messages:
            send_ftqq(messages)

        grouped_data = group_by_region(all_products)
        try:
            save_data(grouped_data)
        except Exception as e:
            logger.warning("保存数据失败: %s", e)
        prev_data = all_products

        time.sleep(INTERVAL)

# ---------------------------- 启动 ----------------------------
if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="MJJVM 监控脚本 (Cloudflare 兼容增强版)")
    parser.add_argument("--test", action="store_true", help="发送一条测试推送后退出")
    args = parser.parse_args()
    if args.test:
        send_ftqq([{
            "type": "上架",
            "name": "测试商品",
            "stock": 10,
            "config": "2C/2G",
            "member_only": 2,
            "url": ROOT_ORIGIN,
            "region": "测试区"
        }])
        logger.info("✅ 测试推送已发送")
        sys.exit(0)
    main_loop()
