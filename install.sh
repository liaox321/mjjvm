#!/bin/bash
set -euo pipefail

# MJJVM 监控与签到安装脚本（修复版）
# 包含库存监控、签到功能和Cookie保活检查

RUNNER_USER=${SUDO_USER:-$USER}

BOT_DIR="/opt/mjjvm"
ENV_FILE="$BOT_DIR/.env"
VENV_DIR="$BOT_DIR/mjjvm-venv"
SERVICE_FILE="/etc/systemd/system/mjjvm.service"
SCRIPT_URL="https://raw.githubusercontent.com/liaox321/mjjvm/main/2.py"
SCRIPT_PATH="$BOT_DIR/2.py"

# 非交互 apt-get 安装选项
APT_NONINTERACTIVE="DEBIAN_FRONTEND=noninteractive"

# 检查并安装系统依赖
check_and_install() {
    if ! command -v python3 >/dev/null 2>&1; then
        echo "❌ 未找到 python3，正在安装..."
        sudo $APT_NONINTERACTIVE apt-get update -y >/dev/null 2>&1
        sudo $APT_NONINTERACTIVE apt-get install -y python3 python3-venv python3-pip >/dev/null 2>&1
        echo "✅ python3 安装完成"
    else
        echo "✅ python3 已安装"
    fi

    if ! command -v curl >/dev/null 2>&1; then
        echo "❌ 未找到 curl，正在安装..."
        sudo $APT_NONINTERACTIVE apt-get install -y curl >/dev/null 2>&1
        echo "✅ curl 安装完成"
    else
        echo "✅ curl 已安装"
    fi

    # 安装其他可能需要的依赖
    if ! dpkg -s ca-certificates >/dev/null 2>&1; then
        sudo $APT_NONINTERACTIVE apt-get install -y ca-certificates >/dev/null 2>&1 || true
    fi
}

# 交互菜单
echo "请选择操作："
echo "1) 安装 / 更新 MJJVM 监控（包含 Playwright）"
echo "2) 修改 .env 配置（SCKEY / MJJVM_COOKIE / MJJBOX_COOKIE）"
echo "3) 卸载 MJJVM 监控"
read -p "输入选项 [1-3]: " ACTION

case $ACTION in
1)
    check_and_install

    echo "安装目录：$BOT_DIR"
    echo "脚本将以用户：$RUNNER_USER 来拥有并运行"

    sudo mkdir -p "$BOT_DIR"
    sudo chown -R "$RUNNER_USER:$RUNNER_USER" "$BOT_DIR"
    cd "$BOT_DIR" || { echo "无法切换到 $BOT_DIR"; exit 1; }

    echo "🔽 正在下载 MJJVM 脚本（$SCRIPT_URL）..."
    if command -v curl >/dev/null 2>&1; then
        sudo -u "$RUNNER_USER" curl -fsSL "$SCRIPT_URL" -o "$SCRIPT_PATH" || { echo "下载失败"; exit 1; }
    elif command -v wget >/dev/null 2>&1; then
        sudo -u "$RUNNER_USER" wget -qO "$SCRIPT_PATH" "$SCRIPT_URL" || { echo "下载失败"; exit 1; }
    else
        echo "❌ 未找到 curl 或 wget，请先安装。"
        exit 1
    fi

    if [ ! -s "$SCRIPT_PATH" ]; then
        echo "❌ 下载失败或文件为空：$SCRIPT_PATH"
        exit 1
    fi
    sudo chown "$RUNNER_USER:$RUNNER_USER" "$SCRIPT_PATH"
    chmod +x "$SCRIPT_PATH"
    echo "✅ 脚本保存为 $SCRIPT_PATH"

    # 生成 .env，包含 SCKEY、MJJVM_COOKIE 和 MJJBOX_COOKIE
    echo "📝 请按提示输入 ENV 配置（将写入 $ENV_FILE）"
    read -p "请输入方糖的 SendKey (空则跳过推送配置): " SCKEY
    read -p "请输入 MJJVM 的 Cookie (示例: PHPSESSID=xxxx; cf_clearance=xxxx) (可留空): " MJJVM_COOKIE
    read -p "请输入 MJJBOX 的 Cookie (用于签到功能) (示例: session=xxxx; token=xxxx) (可留空): " MJJBOX_COOKIE

    # 设置 Cookie 保活检查间隔（秒），默认 4 小时
    COOKIE_CHECK_INTERVAL=14400
    echo -e "\n🔄 Cookie 保活检查间隔（秒）"
    echo "默认值 14400 秒（4 小时）"
    read -p "请输入间隔时间（直接回车使用默认值）: " input_interval
    if [ -n "$input_interval" ]; then
        COOKIE_CHECK_INTERVAL=$input_interval
    fi

    # 写入环境变量文件
    {
        echo "SCKEY=${SCKEY}"
        echo "MJJVM_COOKIE=${MJJVM_COOKIE}"
        echo "MJJBOX_COOKIE=${MJJBOX_COOKIE}"
        echo "COOKIE_CHECK_INTERVAL=${COOKIE_CHECK_INTERVAL}"
    } > /tmp/mjjvm_env.tmp
    
    sudo mv /tmp/mjjvm_env.tmp "$ENV_FILE"
    sudo chown "$RUNNER_USER:$RUNNER_USER" "$ENV_FILE"
    chmod 600 "$ENV_FILE"
    echo "✅ 写入 $ENV_FILE (权限 600)"

    # 创建虚拟环境
    if [ ! -d "$VENV_DIR" ]; then
        echo "🔧 创建虚拟环境..."
        sudo -u "$RUNNER_USER" python3 -m venv "$VENV_DIR"
        echo "✅ 虚拟环境已创建：$VENV_DIR"
    fi

    echo "📦 安装 Python 依赖到 venv..."
    sudo -u "$RUNNER_USER" "$VENV_DIR/bin/python" -m pip install --upgrade pip setuptools wheel >/dev/null 2>&1

    REQUIRED_PKG=("cloudscraper" "beautifulsoup4" "python-dotenv" "requests" "playwright")
    for pkg in "${REQUIRED_PKG[@]}"; do
        echo "安装 $pkg ..."
        sudo -u "$RUNNER_USER" "$VENV_DIR/bin/python" -m pip install --no-cache-dir "$pkg"
    done

    echo "✅ Python 依赖安装完成"

    # 安装 Playwright 浏览器
    echo "⏳ 开始安装 Playwright 浏览器二进制..."
    if sudo -u "$RUNNER_USER" "$VENV_DIR/bin/python" -m playwright install >/dev/null 2>&1; then
        echo "✅ Playwright 浏览器安装完成"
    else
        echo "⚠️ Playwright 浏览器安装遇到问题"
    fi

    # 写入 systemd 服务
    echo "⚙️ 写入 systemd 服务：$SERVICE_FILE"
    sudo tee "$SERVICE_FILE" > /dev/null <<EOF
[Unit]
Description=MJJVM Stock Monitor and Sign-in Service
After=network.target

[Service]
Type=simple
User=$RUNNER_USER
WorkingDirectory=$BOT_DIR
ExecStart=$VENV_DIR/bin/python $SCRIPT_PATH
Restart=on-failure
RestartSec=10
StartLimitIntervalSec=60
StartLimitBurst=6
StandardOutput=journal
StandardError=journal
Environment=PATH=$VENV_DIR/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
EnvironmentFile=$ENV_FILE
LimitNOFILE=65536

[Install]
WantedBy=multi-user.target
EOF

    sudo systemctl daemon-reload
    sudo systemctl enable mjjvm
    sudo systemctl restart mjjvm

    echo "✅ 安装/更新完成，服务已启动：mjjvm"
    echo "查看服务状态： sudo systemctl status mjjvm"
    echo "查看实时日志： sudo journalctl -u mjjvm -f"
    
    # 提供测试命令
    echo -e "\n🔄 您可以通过以下命令测试功能："
    echo "sudo -u $RUNNER_USER $VENV_DIR/bin/python $SCRIPT_PATH --test"
    echo "sudo -u $RUNNER_USER $VENV_DIR/bin/python $SCRIPT_PATH --sign-test"
    echo "sudo -u $RUNNER_USER $VENV_DIR/bin/python $SCRIPT_PATH --cookie-test"
    
    # 提醒用户关于签到和保活时间
    echo -e "\n⏰ 签到功能将在每天上午8点自动执行"
    echo "🔄 Cookie 保活检查每 $COOKIE_CHECK_INTERVAL 秒执行一次"
    ;;

2)
    if [ ! -f "$ENV_FILE" ]; then
        echo "❌ 未找到 $ENV_FILE，请先安装（选项 1）"
        exit 1
    fi
    echo "📝 修改 ENV 配置 ($ENV_FILE)"
    
    # 读取当前值
    if [ -f "$ENV_FILE" ]; then
        SCKEY=$(grep "^SCKEY=" "$ENV_FILE" | cut -d'=' -f2- || echo "")
        MJJVM_COOKIE=$(grep "^MJJVM_COOKIE=" "$ENV_FILE" | cut -d'=' -f2- || echo "")
        MJJBOX_COOKIE=$(grep "^MJJBOX_COOKIE=" "$ENV_FILE" | cut -d'=' -f2- || echo "")
        COOKIE_CHECK_INTERVAL=$(grep "^COOKIE_CHECK_INTERVAL=" "$ENV_FILE" | cut -d'=' -f2- || echo "14400")
    fi

    echo -e "\n当前 SCKEY = ${SCKEY:-<未配置>}"
    read -p "是否修改 SCKEY? (y/n): " choice
    if [[ "$choice" == "y" ]]; then
        read -p "请输入新的 SCKEY (留空则清空): " new_sckey
        SCKEY="$new_sckey"
    fi

    echo -e "\n当前 MJJVM_COOKIE = ${MJJVM_COOKIE:-<未配置>}"
    read -p "是否修改 MJJVM_COOKIE? (y/n): " choice
    if [[ "$choice" == "y" ]]; then
        read -p "请输入新的 MJJVM_COOKIE (示例: PHPSESSID=xxxx; cf_clearance=xxxx) (留空则清空): " new_cookie
        MJJVM_COOKIE="$new_cookie"
    fi
    
    echo -e "\n当前 MJJBOX_COOKIE = ${MJJBOX_COOKIE:-<未配置>}"
    read -p "是否修改 MJJBOX_COOKIE? (用于签到功能) (y/n): " choice
    if [[ "$choice" == "y" ]]; then
        read -p "请输入新的 MJJBOX_COOKIE (示例: session=xxxx; token=xxxx) (留空则清空): " new_mjjbox_cookie
        MJJBOX_COOKIE="$new_mjjbox_cookie"
    fi
    
    echo -e "\n当前 Cookie 保活检查间隔 = ${COOKIE_CHECK_INTERVAL:-14400} 秒"
    read -p "是否修改间隔时间? (y/n): " choice
    if [[ "$choice" == "y" ]]; then
        read -p "请输入新的间隔时间（秒）: " new_interval
        COOKIE_CHECK_INTERVAL="$new_interval"
    fi

    # 写入环境变量文件
    {
        echo "SCKEY=${SCKEY}"
        echo "MJJVM_COOKIE=${MJJVM_COOKIE}"
        echo "MJJBOX_COOKIE=${MJJBOX_COOKIE}"
        echo "COOKIE_CHECK_INTERVAL=${COOKIE_CHECK_INTERVAL}"
    } > /tmp/mjjvm_env.tmp
    
    sudo mv /tmp/mjjvm_env.tmp "$ENV_FILE"
    sudo chown "$RUNNER_USER:$RUNNER_USER" "$ENV_FILE"
    chmod 600 "$ENV_FILE"
    sudo systemctl restart mjjvm
    echo "✅ 配置已修改并重启服务"
    ;;

3)
    echo "⚠️ 警告：此操作会停止服务并删除监控相关文件（$BOT_DIR）"
    read -p "是否继续卸载? (y/n): " choice
    if [[ "$choice" != "y" ]]; then
        echo "已取消"
        exit 1
    fi
    if [ -f "$SERVICE_FILE" ]; then
        sudo systemctl stop mjjvm || true
        sudo systemctl disable mjjvm || true
        sudo rm -f "$SERVICE_FILE"
        sudo systemctl daemon-reload
    fi
    sudo rm -rf "$BOT_DIR"
    echo "✅ 已卸载并删除 $BOT_DIR 与 service 文件"
    ;;

*)
    echo "❌ 无效选项"
    exit 1
    ;;
esac

exit 0
