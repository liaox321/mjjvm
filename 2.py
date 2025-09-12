#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import time
import json
import random
import logging
import argparse
from datetime import datetime, timedelta
from dotenv import load_dotenv
import requests
from bs4 import BeautifulSoup
import cloudscraper
from playwright.sync_api import sync_playwright
import re

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('/opt/mjjvm/stock_out.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger('MJJVM_Monitor')

# 加载环境变量
load_dotenv('/opt/mjjvm/.env')
SCKEY = os.getenv('SCKEY')
MJJVM_COOKIE = os.getenv('MJJVM_COOKIE')
MJJBOX_COOKIE = os.getenv('MJJBOX_COOKIE')
COOKIE_CHECK_INTERVAL = int(os.getenv('COOKIE_CHECK_INTERVAL', 14400))  # 默认4小时检查一次

# 目标URL
MJJVM_URL = "https://www.mjjvm.com"
MJJVM_STOCK_URL = f"{MJJVM_URL}/stock"
MJJBOX_URL = "https://www.mjjbox.com"
MJJBOX_SIGNIN_URL = f"{MJJBOX_URL}/user/checkin"
MJJBOX_PROFILE_URL = f"{MJJBOX_URL}/user"

# 文件路径
STOCK_FILE = '/opt/mjjvm/stock_history.json'
SIGN_FILE = '/opt/mjjvm/last_sign_date'
SIGN_STATS_FILE = '/opt/mjjvm/sign_stats.json'
COOKIE_STATUS_FILE = '/opt/mjjvm/cookie_status.json'

# 用户代理列表
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:126.0) Gecko/20100101 Firefox/126.0",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
]

# 全局状态
last_cookie_check_time = 0
cookie_valid_status = {
    'mjjvm': True,
    'mjjbox': True
}

def send_notification(title, content):
    """发送Server酱通知"""
    if not SCKEY:
        logger.warning("未配置Server酱SCKEY，跳过通知发送")
        return False
    
    try:
        url = f"https://sctapi.ftqq.com/{SCKEY}.send"
        data = {
            'title': title,
            'desp': content
        }
        response = requests.post(url, data=data, timeout=10)
        
        if response.status_code == 200:
            result = response.json()
            if result.get('code') == 0:
                logger.info(f"✅ 通知发送成功: {title}")
                return True
            else:
                logger.error(f"❌ 通知发送失败: {result.get('message')}")
        else:
            logger.error(f"❌ 通知发送失败，HTTP状态码: {response.status_code}")
    except Exception as e:
        logger.error(f"❌ 发送通知时出错: {str(e)}")
    
    return False

def get_stock_data():
    """使用Playwright获取库存页面HTML"""
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context()
            page = context.new_page()
            
            # 设置自定义Cookie
            if MJJVM_COOKIE:
                cookies = []
                for cookie_item in MJJVM_COOKIE.split(';'):
                    if '=' in cookie_item:
                        name, value = cookie_item.split('=', 1)
                        cookies.append({
                            'name': name.strip(),
                            'value': value.strip(),
                            'domain': 'www.mjjvm.com',
                            'path': '/'
                        })
                context.add_cookies(cookies)
            
            # 访问库存页面
            page.goto(MJJVM_STOCK_URL, timeout=30000)
            
            # 等待内容加载
            page.wait_for_selector('.product-item', timeout=30000)
            
            # 获取页面HTML
            html = page.content()
            
            # 关闭浏览器
            browser.close()
            
            return html
    except Exception as e:
        logger.error(f"❌ 获取库存页面失败: {str(e)}")
        return None

def parse_stock_data(html):
    """解析库存HTML数据"""
    if not html:
        return None
    
    try:
        soup = BeautifulSoup(html, 'html.parser')
        products = []
        
        # 找到所有产品项
        product_items = soup.select('.product-item')
        if not product_items:
            logger.warning("⚠️ 未找到产品项，页面结构可能已改变")
            return None
        
        for item in product_items:
            try:
                name = item.select_one('.product-name').get_text(strip=True)
                status = item.select_one('.product-status').get_text(strip=True)
                stock_text = item.select_one('.product-stock').get_text(strip=True)
                
                # 解析库存数量
                if "库存" in stock_text:
                    stock = int(stock_text.split("：")[1].split("件")[0].strip())
                else:
                    stock = 0
                
                products.append({
                    'name': name,
                    'status': status,
                    'stock': stock
                })
            except Exception as e:
                logger.warning(f"⚠️ 解析产品项时出错: {str(e)}")
                continue
        
        return products
    except Exception as e:
        logger.error(f"❌ 解析库存数据失败: {str(e)}")
        return None

def save_stock_data(products):
    """保存当前库存数据到文件"""
    try:
        with open(STOCK_FILE, 'w', encoding='utf-8') as f:
            json.dump(products, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        logger.error(f"❌ 保存库存数据失败: {str(e)}")
        return False

def load_stock_data():
    """从文件加载上次的库存数据"""
    if not os.path.exists(STOCK_FILE):
        return None
    
    try:
        with open(STOCK_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"❌ 加载库存数据失败: {str(e)}")
        return None

def compare_stock(old_data, new_data):
    """比较新旧库存数据，检测变化"""
    changes = []
    
    if not old_data or not new_data:
        return changes
    
    # 创建旧数据的名称映射
    old_map = {item['name']: item for item in old_data}
    
    for new_item in new_data:
        name = new_item['name']
        new_status = new_item['status']
        new_stock = new_item['stock']
        
        if name in old_map:
            old_item = old_map[name]
            old_status = old_item['status']
            old_stock = old_item['stock']
            
            # 检查状态变化
            if old_status != new_status:
                if "售罄" in new_status and "售罄" not in old_status:
                    changes.append({
                        'type': '售罄',
                        'name': name,
                        'old': old_status,
                        'new': new_status
                    })
                elif "在售" in new_status and "在售" not in old_status:
                    changes.append({
                        'type': '上架',
                        'name': name,
                        'old': old_status,
                        'new': new_status
                    })
            
            # 检查库存变化
            elif old_stock != new_stock:
                changes.append({
                    'type': '库存变化',
                    'name': name,
                    'old': old_stock,
                    'new': new_stock
                })
        else:
            # 新产品上架
            changes.append({
                'type': '上架',
                'name': name,
                'old': '无',
                'new': new_status
            })
    
    # 检查下架产品
    new_names = {item['name'] for item in new_data}
    for old_item in old_data:
        if old_item['name'] not in new_names:
            changes.append({
                'type': '下架',
                'name': old_item['name'],
                'old': old_item['status'],
                'new': '已下架'
            })
    
   极速返回 changes

def mjjbox_sign_in():
    """MJJBOX网站签到功能"""
    if not MJJBOX_COOKIE:
        logger.error("❌ MJJBOX_COOKIE未配置，无法执行签到")
        return False, "签到失败：未配置Cookie"
    
    # 准备请求头
    headers = {
        'Cookie': MJJBOX_COOKIE,
        'Referer': MJJBOX_PROFILE_URL,
        'User-Agent': random.choice(USER_AGENTS),
        'Accept': 'application/json, text/javascript, */*; q=0.01',
        'X-Requested-With': 'XMLHttpRequest'
    }
    
    try:
        # 尝试签到
        response = requests.post(MJJBOX_SIGNIN_URL, headers=headers, timeout=30)
        
        # 解析响应
        if response.status_code == 200:
            try:
                result = response.json()
                if result.get('ret') == 1:
                    # 签到成功
                    msg = result.get('msg', '签到成功')
                    
                    # 获取积分信息
                    points_info = get_points_info(headers)
                    
                    # 更新签到统计
                    update_sign_stats(success=True)
                    
                    # 组合消息
                    full_msg = f"{msg}\n\n{points_info}"
                    return True, full_msg
                else:
                    # 签到失败
                    msg = result.get('msg', '签到失败')
                    
                    # 更新签到统计
                    update_sign_stats(success=False)
                    
                    return False, msg
            except ValueError:
                # 如果不是JSON响应，尝试解析HTML
                soup = BeautifulSoup(response.text, 'html.parser')
                error_msg = soup.find('div', class_='alert-danger')
                if error_msg:
                    msg = error_msg.text.strip()
                    
                    # 更新签到统计
                    update_sign_stats(success=False)
                    
                    return False, msg
                else:
                    # 更新签到统计
                    update_sign_stats(success=False)
                    
                    return False, "签到失败：未知错误"
        else:
            # 更新签到统计
            update_sign_stats(success=False)
            
            return False, f"签到失败：HTTP状态码 {response.status_code}"
            
    except Exception as e:
        # 更新签到统计
        update_sign_stats(success=False)
        
        return False, f"签到异常：{str(e)}"

def get_points_info(headers):
    """获取积分信息（总积分、总签到次数、连续签到次数）"""
    try:
        # 获取用户信息页面
        response = requests.get(MJJBOX_PROFILE_URL, headers=headers, timeout=30)
        
        if response.status_code == 200:
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # 查找积分信息
            points_text = ""
            
            # 尝试查找积分元素
            points_element = soup.find('span', class_='user-points')
            if points_element:
                points_text = points_element.get_text(strip=True)
            
            # 尝试查找签到信息
            sign_info = ""
            sign_elements = soup.select('.sign-info')
            for element in sign_elements:
                sign_info += element.get_text(strip=True) + " "
            
            # 使用正则表达式提取数字
            total_points = extract_number(points_text, "积分")
            total_signs = extract_number(sign_info, "总签到")
            consecutive_signs = extract_number(sign_info, "连续签到")
            
            # 构建积分信息字符串
            points_info = ""
            if total_points is not None:
                points_info += f"总积分: {total_points}\n"
            if total_signs is not None:
                points_info += f"总签到次数: {total_signs}\n"
            if consecutive_signs is not None:
                points_info += f"连续签到: {consecutive_signs}天"
            
            return points_info if points_info else "未能获取积分信息"
        else:
            return f"获取积分信息失败: HTTP {response.status_code}"
    except Exception as e:
        logger.error(f"❌ 获取积分信息失败: {str(e)}")
        return f"获取积分信息失败: {str(e)}"

def extract_number(text, keyword):
    """从文本中提取数字"""
    if not text:
        return None
    
    # 查找关键词位置
    idx = text.find(keyword)
    if idx == -1:
        return None
    
    # 提取数字部分
    num_text = text[idx + len(keyword):].strip()
    
    # 使用正则表达式匹配数字
    match = re.search(r'\d+', num_text)
    if match:
        return int(match.group())
    
    return None

def load_sign_stats():
    """加载签到统计数据"""
    if os.path.exists(SIGN_STATS_FILE):
        try:
            with open(SIGN_STATS_FILE, 'r') as f:
                return json.load(f)
        except:
            pass
    
    # 默认统计
    return {
        'total_signs': 0,
        'consecutive_signs': 0,
        'max_consecutive': 0,
        'last_success_date': None,
        'last_fail_date': None
    }

def save_sign_stats(stats):
    """保存签到统计数据"""
    try:
        with open(SIGN_STATS_FILE, 'w') as f:
            json.dump(stats, f, indent=2)
        return True
   极速返回 False

def update_sign_stats(success=True):
    """更新签到统计数据"""
    stats = load_sign_stats()
    today = datetime.now().strftime('%Y-%m-%d')
    
    if success:
        # 更新总签到次数
        stats['total_signs'] = stats.get('total_signs', 0) + 1
        
        # 更新连续签到次数
        last_success = stats.get('last_success_date')
        if last_success and (datetime.strptime(last_success, '%Y-%m-%d') + timedelta(days=1)).date() == datetime.now().date():
            stats['consecutive_sign极速递增 1
        else:
            stats['consecutive_signs'] = 1
        
        # 更新最大连续签到
        if stats['consecutive_signs'] > stats.get('max_consecutive', 0):
            stats['max_consecutive'] = stats['consecutive_signs']
        
        # 更新最后成功日期
        stats['极速设置 today
    else:
        # 重置连续签到
        stats['consecutive_signs'] = 0
        stats['last_fail_date'] = today
    
    save_sign_stats(stats)
    return stats

def check_sign_in():
    """检查并执行签到，发送通知"""
    # 获取当前日期
    today = datetime.now().strftime('%Y-%m-%d')
    
    # 检查今天是否已经签到
    if os.path.exists(SIGN_FILE):
        with open(SIGN_FILE, 'r') as f:
            last_sign_date = f.read().strip()
        if last_sign_date == today:
            logger.info("今天已经签到过了")
            return True, "今日已签到"
    
    # 执行签到
    success, message = mjjbox_sign_in()
    
    # 获取签到统计
    stats = load_sign_stats()
    
    # 准备通知内容
    title = "📅 MJJBOX签到成功" if success else "⚠️ MJJBOX签到失败"
    
    # 组合详细消息
    full_message = f"{message}\n\n"
    full_message += f"总签到次数: {stats['total_signs']}\n"
    full_message += f"连续签到: {stats['consecutive_signs']}天\n"
    full_message += f"最长连续: {stats['max_consecutive']}天\n"
    
    # 发送通知
    send_notification(title, full_message)
    
    # 记录签到日期
    if success:
        with open(SIGN_FILE, 'w') as f:
            f.write(today)
    
    return success, message

def check_cookie_validity():
    """检查Cookie有效性"""
    global cookie_valid_status
    
    # 检查MJJVM Cookie
    mjjvm_valid = check_mjjvm_cookie()
    # 检查MJJBOX Cookie
    mjjbox_valid = check_mjjbox_cookie()
    
    # 更新状态
    cookie_valid_status['mjjvm'] = mjjvm_valid
    cookie_valid_status['mjjbox'] = mjjbox_valid
    
    # 保存状态
    save_cookie_status()
    
    # 如果有Cookie失效，发送通知
    if not mjjvm_valid or not mjjbox_valid:
        send_cookie_invalid_notification(mjjvm_valid, mjjbox_valid)
    
    return mjjvm_valid and mjjbox_valid

def check_mjjvm_cookie():
    """检查MJJVM Cookie有效性"""
    if not MJJVM_COOKIE:
        logger.warning("未配置MJJVM_COOKIE，跳过检查")
        return True
    
    headers = {
        'Cookie': MJJVM_COOKIE,
        'User-Agent': random.choice(USER_AGENTS)
    }
    
    try:
        response = requests.get(MJJVM_STOCK_URL, headers=headers, timeout=15)
        
        # 检查是否被重定向到登录页面或显示错误
        if response.status_code == 200 and "登录" not in response.text and "错误" not in response.text:
            logger.info("✅ MJJVM Cookie有效")
            return True
        else:
            logger.warning("❌ MJJVM Cookie已失效")
            return False
    except Exception as e:
        logger.error(f"❌ 检查MJJVM Cookie时出错: {str(e)}")
        return False

def check_mjjbox_cookie():
    """检查MJJBOX Cookie有效性"""
    if not MJJBOX_COOKIE:
        logger.warning("未配置MJJBOX_COOKIE，跳过检查")
        return True
    
    headers = {
        'Cookie': MJJBOX_COOKIE,
        'User-Agent': random.choice(USER_AGENTS),
        'Referer': MJJBOX_PROFILE_URL
    }
    
    try:
        response = requests.get(MJJBOX_PROFILE_URL, headers=headers, timeout=15)
        
        # 检查是否包含用户信息而不是登录表单
        if response.status_code == 200 and "用户资料" in response.text and "登录" not in response.text:
            logger.info("✅ MJJBOX Cookie有效")
            return True
        else:
            logger.warning("❌ MJJBOX Cookie已失效")
            return False
    except Exception as e:
        logger.error(f"❌ 检查MJJBOX Cookie时出错: {str(e)}")
        return False

def save_cookie_status():
    """保存Cookie状态到文件"""
    try:
        with open(COOKIE_STATUS_FILE, 'w') as f:
            json.dump({
                'last_check': datetime.now().isoformat(),
                'status': cookie_valid_status
            }, f, indent=2)
        return True
    except Exception as e:
        logger.error(f"❌ 保存Cookie状态失败: {str(e)}")
        return False

def load_cookie_status():
    """从文件加载Cookie状态"""
    if os.path.exists(COOKIE_STATUS_FILE):
        try:
            with open(COOKIE_STATUS_FILE, 'r') as f:
                return json.load(f)
        except:
            pass
    return None

def send_cookie_invalid_notification(mjjvm_valid, mjjbox_valid):
    """发送Cookie失效通知"""
    title = "⚠️ Cookie失效警告"
    
    content = "## MJJVM Cookie状态检查\n\n"
    content += f"**检查时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
    content += "### Cookie状态:\n"
    content += f"- MJJVM Cookie: {'✅ 有效' if mjjvm_valid else '❌ 失效'}\n"
    content += f"- MJJBOX Cookie: {'✅ 有效' if mjjbox_valid else '❌ 失效'}\n\n"
    content += "### 建议操作:\n"
    content += "1. 请尽快更新失效的Cookie配置\n"
    content += "2. 重新运行安装脚本修改配置\n"
    content += "3. 检查账号状态是否正常\n\n"
    content += "如需帮助，请查看日志文件: /opt/mjjvm/stock_out.log"
    
    send_notification(title, content)

def main_loop():
    """主监控循环"""
    global last_cookie_check_time
    
    # 初始化错误计数
    error_count = 0
    max_errors = 5
    
    # 加载上次Cookie检查时间
    cookie_status = load_cookie_status()
    if cookie_status:
        try:
            last_check = datetime.fromisoformat(cookie_status['last_check'])
            last_cookie_check_time = last_check.timestamp()
        except:
            last_cookie_check_time = 0
    
    while True:
        try:
            # 获取当前时间
            now = datetime.now()
            current_time = time.time()
            logger.info(f"⏱️ 开始检查库存 [{now.strftime('%Y-%m-%d %H:%M:%S')}]")
            
            # 检查Cookie有效性（定期执行）
            if current_time - last_cookie_check_time >= COOKIE_CHECK_INTERVAL:
                logger.info("🔄 执行Cookie有效性检查...")
                check_cookie_validity()
                last_cookie_check_time = current_time
            
            # 获取库存页面HTML
            html = get_stock_data()
            
            if html:
                # 解析库存数据
                current_products = parse_stock_data(html)
                
                if current_products:
                    # 加载上次库存数据
                    previous_products = load_stock_data()
                    
                    # 保存当前库存数据
                    save_stock_data(current_products)
                    
                    # 比较库存变化
                    if previous_products:
                        changes = compare_stock(previous_products, current_products)
                        
                        if changes:
                            # 准备通知内容
                            title = "🛒 MJJVM库存变化通知"
                            content = ""
                            
                            for change in changes:
                                if change['type'] == '上架':
                                    content += f"🆕 新商品上架: {change['name']}\n"
                                elif change['type'] == '售罄':
                                    content += f"⛔ 商品售罄: {change['name']}\n"
                                elif change['type'] == '下架':
                                    content += f"⬇️ 商品下架: {change['name']}\n"
                                elif change['type'] == '库存变化':
                                    content += f"🔄 库存变化: {change['name']} ({change['old']} → {change['new']})\n"
                            
                            # 发送通知
                            send_notification(title, content)
                            logger.info(f"📤 发送库存变化通知: {len(changes)}处变化")
                        else:
                            logger.info("✅ 库存无变化")
                    else:
                        logger.info("✅ 首次运行，已记录初始库存状态")
                    
                    # 重置错误计数
                    error_count = 0
                else:
                    logger.warning("⚠️ 无法解析库存数据")
                    error_count += 1
            else:
                logger.warning("⚠️ 无法获取库存页面")
                error_count += 1
            
            # 检查错误计数
            if error_count >= max_errors:
                logger.error(f"❌ 连续 {max_errors} 次检查失败，发送警报")
                send_notification("⛔ MJJVM监控连续失败警报", 
                                 f"监控服务已连续 {max_errors} 次无法获取或解析库存数据，请检查系统状态！")
                # 重置错误计数
                error_count = 0
            
            # 每天早上8点执行签到
            if now.hour == 8 and now.minute < 5:  # 在8:00-8:05之间执行
                logger.info("⏰ 执行每日签到...")
                sign_success, sign_message = check_sign_in()
                logger.info(f"签到结果: {'成功' if sign_success else '失败'} - {sign_message}")
            
            # 随机延迟 55-65 秒
            delay = random.randint(55, 65)
            logger.info(f"⏳ 下次检查将在 {delay} 秒后...")
            time.sleep(delay)
            
        except KeyboardInterrupt:
            logger.info("🛑 用户中断，退出程序")
            sys.exit(0)
        except Exception as e:
            logger.error(f"❌ 主循环发生错误: {str(e)}")
            time.sleep(30)

def test_notification():
    """测试通知功能"""
    logger.info("🔔 发送测试通知...")
    success = send_notification("🔔 MJJVM测试通知", 
                              "这是一条测试通知，表明您的监控服务已正确配置并可以发送消息。")
    if success:
        logger.info("✅ 测试通知已发送")
    else:
        logger.error("❌ 测试通知发送失败")

def test_sign_in():
    """测试签到功能"""
    logger.info("🔔 测试签到功能...")
    success, message = mjjbox_sign_in()
    logger.info(f"签到测试结果: {'成功' if success else '失败'} - {message}")
    
    # 获取签到统计
    stats = load_sign_stats()
    
    # 准备通知内容
    title = "📅 MJJBOX签到测试成功" if success else "⚠️ MJJBOX签到测试失败"
    content = f"{message}\n\n"
    content += f"总签到次数: {stats['total_signs']}\n"
    content += f"连续签到: {stats['consecutive_sign极速返回 content

def test_cookie_check():
    """测试Cookie检查功能"""
    logger.info("🔔 测试Cookie检查功能...")
    result = check_cookie_validity()
    logger.info(f"Cookie检查结果: {'全部有效' if result else '有Cookie失效'}")
    
    # 准备通知内容
    title = "✅ Cookie检查测试" if result else "⚠️ Cookie检查测试"
    content = "## Cookie状态检查测试\n\n"
    content += f"**检查时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
    content += "### 检查结果:\n"
    content += f"- MJJVM Cookie: {'✅ 有效' if cookie_valid_status['mjjvm'] else '❌ 失效'}\n"
    content += f"- MJJBOX Cookie: {'✅ 有效' if cookie_valid_status['mjjbox'] else '❌ 失效'}\n\n"
    content += "### 详细状态:\n"
    content += f"MJJVM Cookie: {MJJVM_COOKIE[:50]}...\n" if MJJVM_COOKIE else "MJJVM Cookie: 未配置\n"
    content += f"MJJBOX Cookie: {MJJBOX_COOKIE[:50]}...\n" if MJJBOX_COOKIE else "MJJBOX Cookie: 未配置\n"
    
    send_notification(title, content)

if __name__ == "__main__":
    logger.info("🚀 MJJVM库存监控服务启动")
    
    # 检查命令行参数
    if len(sys.argv) > 1:
        if '--test' in sys.argv:
            test_notification()
            sys.exit(0)
        elif '--sign-test' in sys.argv:
            test_sign_in()
            sys.exit(0)
        elif '--cookie-test' in sys.argv:
            test_cookie_check()
            sys.exit(0)
        elif '--help' in sys.argv or '-h' in sys.argv:
            print("用法: python 2.py [选项]")
            print("选项:")
            print("  --test        测试通知功能")
            print("  --sign-test   测试签到功能")
            print("  --cookie-test 测试Cookie检查功能")
            print("  --help, -h    显示帮助信息")
            sys.exit(0)
    
    # 进入主循环
    main_loop()

