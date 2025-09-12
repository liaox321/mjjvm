# MJJVM 库存监控与签到服务

这是一个用于监控 MJJVM 商品库存变化的 Python 工具，同时集成了 MJJBOX 签到功能。支持自动检测商品上架/售罄/库存变化，并通过 Server酱·方糖通知推送到微信。新增 Cookie 保活功能，当 Cookie 失效时自动发送通知。

## ✨ 功能特性

- **库存监控**
  - 定时请求 MJJVM 库存页面（默认 60 秒检查一次）
  - 自动比对历史库存，检测变化并推送通知
  - 推送内容包含：🟢 上架通知 🔴 售罄通知 🟡 库存变化
  - ⚠️ 连续失败报警
  
- **签到功能**
  - 每天自动执行 MJJBOX 签到
  - 签到成功/失败均发送通知
  - 通知包含：总签到次数、连续签到天数、总积分
  
- **Cookie 保活**
  - 定期检查 Cookie 有效性（默认每 4 小时检查一次）
  - Cookie 失效时自动发送通知提醒
  - 支持自定义检查间隔
  
- **系统管理**
  - 运行日志保存到 `stock_out.log`
  - 配置保存到 `.env`，支持一键修改
  - 开机自启（systemd 管理）
  - 交互式安装脚本

## 🚀 安装步骤

### 一键安装
sudo bash <(curl -Ls https://raw.githubusercontent.com/liaox321/mjjvm/main/install.sh)

安装脚本会自动完成：
1. 下载并部署脚本到 `/opt/mjjvm`
2. 创建虚拟环境并安装依赖
3. 配置 Server酱 SendKey
4. 注册 systemd 服务并开机自启

### 安装过程说明

安装脚本提供交互式菜单：

1. **安装/更新服务**
   - 下载最新脚本
   - 配置环境变量（SCKEY, MJJVM_COOKIE, MJJBOX_COOKIE）
   - 设置 Cookie 保活检查间隔
   - 安装 Python 依赖
   - 安装 Playwright 浏览器
   - 创建并启动 systemd 服务

2. **修改配置**
   - 更新 SCKEY（方糖推送密钥）
   - 更新 MJJVM_COOKIE（库存监控 Cookie）
   - 更新 MJJBOX_COOKIE（签到功能 Cookie）
   - 调整 Cookie 保活检查间隔

3. **卸载服务**
   - 停止并禁用服务
   - 删除安装目录和服务文件

## ⚙️ 配置说明

安装时会提示输入以下配置项：

| 配置项 | 说明 | 获取方式 |
|--------|------|----------|
| `SCKEY` | 方糖 SendKey | [Server酱官网](https://sct.ftqq.com/) |
| `MJJVM_COOKIE` | MJJVM 网站 Cookie | 登录后通过浏览器开发者工具获取 |
| `MJJBOX_COOKIE` | MJJBOX 签到 Cookie | 登录后通过浏览器开发者工具获取 |
| `COOKIE_CHECK_INTERVAL` | Cookie 检查间隔（秒） | 默认 14400（4 小时） |

如需修改配置，重新运行安装脚本选择 **2. 修改 .env 配置**。

## 🛠 使用方法

### 服务管理
bash

查看服务状态
sudo systemctl status mjjvm

查看实时日志
sudo journalctl -u mjjvm -f

重启服务
sudo systemctl restart mjjvm

停止服务
sudo systemctl stop mjjvm

复制
### 测试功能
bash

测试通知功能
/opt/mjjvm/mjjvm-venv/bin/python /opt/mjjvm/2.py --test

测试签到功能
/opt/mjjvm/mjjvm-venv/bin/python /opt/mjjvm/2.py --sign-test

测试 Cookie 检查功能
/opt/mjjvm/mjjvm-venv/bin/python /opt/mjjvm/2.py --cookie-test


## ❌ 卸载
bash

sudo bash <(curl -Ls https://raw.githubusercontent.com/liaox321/mjjvm/main/install.sh)

选择 3. 卸载 MJJVM 监控

复制
卸载内容包括：
- `/opt/mjjvm` 目录（脚本与虚拟环境）
- `mjjvm.service` systemd 服务文件

## 📄 版本更新

### v2.0 (2025-09-12)
- 新增 MJJBOX 自动签到功能
- 增加 Cookie 保活检查机制
- 优化安装脚本为交互式菜单
- 完善测试命令和文档

### v1.0.5 (2025-09-10)
- 使用 Playwright 抓取产品页 HTML
- 整合依赖自动安装
- 修复 Cloudflare 绕过问题

## 📄 License

本项目采用 MIT License 开源。你可以自由使用、修改、分发此脚本。
