#!/opt/mjjvm/mjjvm-venv/bin/python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import os
import sys
import time
import json
import random
import logging
import warnings
from logging.handlers import RotatingFileHandler
from dotenv import load_dotenv
from bs4 import BeautifulSoup

# network libs
import cloudscraper
import requests

# Playwright lazy import (may not be installed)
try:
    from playwright.sync_api import sync_playwright
    PLAYWRIGHT_AVAILABLE = True
except Exception:
    PLAYWRIGHT_AVAILABLE = False

# ---------------------------- 配置 ----------------------------
URLS = {
    "白银区": "https://www.mjjvm.com/cart?fid=1&gid=1",
    "黄金区": "https://www.mjjvm.com/cart?fid=1&gid=2",
    "钻石区": "https://www.mjjvm.com/cart?fid=1&gid=3",
    "星曜区": "https://www.mjjvm.com/cart?fid=1&gid=4",
    "特别活动区": "https://www.mjjvm.com/cart?fid=1&gid=6",
}

ROOT_ORIGIN = "https://www.mjjvm.com"
INTERVAL = int(os.getenv("INTERVAL", "60"))
DATA_FILE = "stock_data.json"
LOG_FILE = "stock_out.log"

# ---------------------------- 环境 / .env ----------------------------
load_dotenv()
SCKEY = os.getenv("SCKEY", "").strip()
MJJVM_COOKIE = os.getenv("MJJVM_COOKIE", "").strip()  # "PHPSESSID=...; cf_clearance=..."
PROXY = os.getenv("PROXY", "").strip()  # optional proxy like "http://user:pass@host:port"

# ---------------------------- 日志 ----------------------------
warnings.filterwarnings("ignore", category=FutureWarning)
logger = logging.getLogger("StockMonitor")
logger.setLevel(logging.INFO)
fmt = logging.Formatter("[%(asctime)s] %(message)s", "%Y-%m-%d %H:%M:%S")
ch = logging.StreamHandler(stream=sys.stdout)
ch.setFormatter(fmt)
logger.addHandler(ch)
fh = RotatingFileHandler(LOG_FILE, maxBytes=2*1024*1024, backupCount=2, encoding="utf-8")
fh.setFormatter(fmt)
logger.addHandler(fh)

# ---------------------------- UA 列表 ----------------------------
UAS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:120.0) Gecko/20100101 Firefox/120.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 13_6) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Safari/605.1.15",
]
def random_ua():
    return random.choice(UAS)

# ---------------------------- helpers ----------------------------
def parse_cookie_string(cookie_str: str) -> dict:
    out = {}
    if not cookie_str:
        return out
    for part in cookie_str.split(";"):
        part = part.strip()
        if not part:
            continue
        if "=" in part:
            k, v = part.split("=", 1)
            out[k.strip()] = v.strip()
    return out

def load_previous_data():
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            logger.warning("读取旧数据失败，忽略旧文件。")
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

MEMBER_NAME_MAP = {1: "社区成员", 2: "白银会员", 3: "黄金会员", 4: "钻石会员", 5: "星曜会员"}

# ---------------------------- 方糖推送 ----------------------------
def send_ftqq(messages):
    if not SCKEY or not messages:
        if not SCKEY:
            logger.info("SCKEY 未配置，跳过方糖推送。")
        return
    url = f"https://sctapi.ftqq.com/{SCKEY}.send"
    for msg in messages:
        region = msg.get("region", "未知地区")
        member_text = ""
        if msg.get("member_only", 0):
            member_text = f"要求：{MEMBER_NAME_MAP.get(msg['member_only'], '会员')}\n"
        if msg["type"] == "上架":
            title = f"🟢 上架 - {region}"
        elif msg["type"] == "库存变化":
            title = f"🟡 库存变化 - {region}"
        elif msg["type"] == "售罄":
            title = f"🔴 售罄 - {region}"
        else:
            title = f"⚠️ 报警 - {region}"
        content = f"名称: {msg['name']}\n库存: {msg['stock']}\n{member_text}{msg.get('config','')}\n直达链接: {msg['url']}"
        try:
            resp = requests.post(url, data={"title": title, "desp": content}, timeout=10)
            if resp.status_code == 200:
                logger.info("✅ 方糖推送成功: %s", title)
            else:
                logger.error("❌ 方糖推送失败 %s: %s", resp.status_code, resp.text)
        except Exception as e:
            logger.error("❌ 方糖推送异常: %s", e)

# ---------------------------- cloudscraper session ----------------------------
def build_scraper():
    s = cloudscraper.create_scraper()
    if PROXY:
        s.proxies.update({"http": PROXY, "https": PROXY})
        logger.info("使用代理：%s", PROXY)
    if MJJVM_COOKIE:
        cd = parse_cookie_string(MJJVM_COOKIE)
        for k, v in cd.items():
            try:
                s.cookies.set(k, v, domain="www.mjjvm.com")
            except Exception:
                s.cookies.set(k, v)
        logger.info("注入 MJJVM_COOKIE: %s", ", ".join(list(cd.keys())))
    return s

# ---------------------------- Playwright fallback ----------------------------
def fetch_with_playwright(url: str, cookies: dict | None = None, wait_ms: int = 2500):
    """返回 (html, cookies_dict) 或 (None, {})"""
    if not PLAYWRIGHT_AVAILABLE:
        logger.warning("Playwright 未安装，无法使用浏览器抓取。")
        return None, {}
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-setuid-sandbox"])
            context = browser.new_context(user_agent=random_ua(), viewport={"width":1280,"height":800})
            if cookies:
                cookie_list = []
                for k, v in cookies.items():
                    cookie_list.append({"name": k, "value": v, "domain": "www.mjjvm.com", "path": "/", "httpOnly": False, "secure": True})
                try:
                    context.add_cookies(cookie_list)
                    logger.info("Playwright: 注入 cookies：%s", ", ".join(cookies.keys()))
                except Exception:
                    logger.debug("Playwright 注入 cookie 失败（继续）", exc_info=True)
            page = context.new_page()
            page.goto(url, wait_until="networkidle", timeout=60000)
            page.wait_for_timeout(wait_ms)
            html = page.content()
            try:
                cw = context.cookies()
                browser_cookies = {c["name"]: c["value"] for c in cw if "www.mjjvm.com" in c.get("domain","")}
            except Exception:
                browser_cookies = {}
            browser.close()
            return html, browser_cookies
    except Exception as e:
        logger.exception("Playwright 抓取失败: %s", e)
        return None, {}

# ---------------------------- 页面解析 ----------------------------
def parse_products(html, url, region):
    soup = BeautifulSoup(html, "html.parser")
    products = {}
    MEMBER_MAP = {"成员": 1, "白银会员": 2, "黄金会员": 3, "钻石会员": 4, "星曜会员": 5}
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
        stock = 0
        stock_tag = card.find("p", class_="card-text")
        if stock_tag:
            try:
                stock = int(stock_tag.get_text(strip=True).split("库存：")[-1])
            except Exception:
                stock = 0
        link_tag = card.select_one("div.card-footer a")
        pid = None
        if link_tag and "pid=" in link_tag.get("href", ""):
            pid = link_tag.get("href").split("pid=")[-1]
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
    # 先尝试访问根域（触发 challenge）
    try:
        r0 = scraper.get(ROOT_ORIGIN, headers={"User-Agent": random_ua(), "Referer": ROOT_ORIGIN}, timeout=20)
        logger.info("根域访问返回：%s", getattr(r0, "status_code", None))
    except Exception as e:
        logger.warning("根域访问异常：%s", e)

    prev_raw = load_previous_data()
    prev_data = {}
    for region, plist in prev_raw.items():
        for p in plist:
            prev_data[f"{region} - {p.get('name','')}"] = p

    logger.info("库存监控启动，每 %s 秒检查一次...", INTERVAL)

    while True:
        logger.info("正在检查库存...")
        all_products = {}
        success_count = 0
        fail_count = 0
        any_success = False

        for region, url in URLS.items():
            success_this_url = False
            last_err = None
            for attempt in range(3):
                headers = {"User-Agent": random_ua(), "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8", "Referer": ROOT_ORIGIN}
                try:
                    r = scraper.get(url, headers=headers, timeout=20)
                    status = getattr(r, "status_code", None)
                    if status == 403:
                        logger.warning("[%s] 收到 403 (第 %d 次尝试)。", region, attempt+1)
                        last_err = "403"
                        time.sleep(2)
                        continue
                    r.raise_for_status()
                    prods = parse_products(r.text, url, region)
                    all_products.update(prods)
                    success_this_url = True
                    any_success = True
                    logger.info("[%s] 请求成功 (第 %d 次尝试)", region, attempt+1)
                    break
                except Exception as e:
                    last_err = e
                    logger.warning("[%s] 请求失败 (第 %d 次尝试): %s", region, attempt+1, e)
                    time.sleep(2)

            if not success_this_url:
                # fallback to Playwright
                if PLAYWRIGHT_AVAILABLE:
                    logger.info("[%s] cloudscraper 失败，尝试 Playwright 抓取。", region)
                    cookie_dict = parse_cookie_string(MJJVM_COOKIE)
                    html, browser_cookies = fetch_with_playwright(url, cookies=cookie_dict)
                    if html:
                        # 把浏览器拿到的 cookie 回注到 cloudscraper，提高后续成功率
                        try:
                            for k, v in (browser_cookies or {}).items():
                                scraper.cookies.set(k, v, domain="www.mjjvm.com")
                            if browser_cookies:
                                logger.info("[%s] 将 Playwright 抓到的 cookies 注入 cloudscraper: %s", region, ", ".join(browser_cookies.keys()))
                        except Exception:
                            pass
                        prods = parse_products(html, url, region)
                        all_products.update(prods)
                        success_this_url = True
                        any_success = True
                        logger.info("[%s] Playwright 抓取成功并解析。", region)
                    else:
                        logger.warning("[%s] Playwright 抓取失败或返回空。", region)
                else:
                    logger.debug("Playwright 不可用，跳过浏览器抓取。")

            if success_this_url:
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
            logger.warning("连续 %d 轮全部失败，发送报警。", consecutive_fail_rounds)
            send_ftqq([{"type": "报警", "name": "监控", "stock": 0, "region": "系统", "url": ROOT_ORIGIN}])
            consecutive_fail_rounds = 0

        if not any_success:
            logger.warning("本轮请求全部失败，跳过数据更新。")
            time.sleep(INTERVAL)
            continue

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
                    "config": info.get("config", ""),
                    "member_only": info.get("member_only", 0),
                    "url": info.get("url", ROOT_ORIGIN),
                    "region": info.get("region", "未知地区")
                }
                messages.append(msg)
                logger.info("%s - %s  |  库存: %s  |  %s", msg_type, info["name"], curr_stock, MEMBER_NAME_MAP.get(info.get("member_only", 0), "会员"))

        if messages:
            send_ftqq(messages)

        try:
            save_data(group_by_region(all_products))
        except Exception as e:
            logger.warning("保存数据失败: %s", e)

        prev_data = all_products
        time.sleep(INTERVAL)

# ---------------------------- 启动 ----------------------------
if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="MJJVM 监控 (cloudscraper + playwright fallback)")
    parser.add_argument("--test", action="store_true", help="发送测试推送后退出")
    args = parser.parse_args()
    if args.test:
        send_ftqq([{"type": "上架", "name": "测试商品", "stock": 10, "config": "2C/2G", "member_only": 2, "url": ROOT_ORIGIN, "region": "测试区"}])
        logger.info("✅ 测试推送已发送")
        sys.exit(0)
    main_loop()
