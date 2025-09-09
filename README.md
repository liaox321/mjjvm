# MJJVM 库存监控（方糖通知版）

这是一个用于监控 [MJJVM](https://www.mjjvm.com) 商品库存变化的 Python 工具。  
支持自动检测商品 **上架 / 售罄 / 库存变化**，并通过 **Server酱·方糖通知** 推送到微信。

---

## ✨ 功能特性
- 定时请求 MJJVM 库存页面（默认 **60 秒** 检查一次）
- 自动比对历史库存，检测变化并推送通知
- 推送内容包含：
  - 🟢 **上架通知**
  - 🔴 **售罄通知**
  - 🟡 **库存变化**
  - ⚠️ **连续失败报警**
- 运行日志保存到 `stock_out.log`
- 配置保存到 `.env`，支持一键修改
- 开机自启（systemd 管理）

---

## 🚀 安装步骤

一键安装：
```bash
bash <(curl -Ls https://raw.githubusercontent.com/liaox321/mjjvm/main/install.sh)


安装脚本会自动完成：

1.下载并部署脚本到 /opt/mjjvm

2.创建虚拟环境并安装依赖

3.配置 Server酱 SendKey

4.注册 systemd 服务并开机自启

⚙️ 配置
安装时会提示输入 方糖 SendKey，写入 /opt/mjjvm/.env 文件：
SCKEY=你的SendKey

获取方式：[Server酱官网](https://sct.ftqq.com/)

如需修改配置，重新运行安装脚本选择 2. 修改 .env 配置。

🛠 使用方法
·查看服务运行状态：
sudo systemctl status mjjvm
·查看实时日志：
sudo journalctl -u mjjvm -f
·重启服务：
sudo systemctl restart mjjvm
·停止服务：
sudo systemctl stop mjjvm


🔍 测试推送

·确认推送是否正常：
/opt/mjjvm/mjjvm-venv/bin/python /opt/mjjvm/2.py --test

·你会立刻在微信中收到一条「测试商品」的推送。
日志中会显示：✅ 测试推送已发送
❌ 卸载
卸载脚本：
bash <(curl -Ls https://raw.githubusercontent.com/liaox321/mjjvm/main/install.sh)
选择 3. 卸载 MJJVM 监控。

卸载内容包括：
/opt/mjjvm 目录（脚本与虚拟环境）
mjjvm.service systemd 服务


📄 License

本项目采用 MIT License 开源。
你可以自由使用、修改、分发此脚本。
