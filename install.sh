#!/bin/bash
set -euo pipefail

# MJJVM 监控与签到安装脚本
# 版本: v2.1 (修复语法错误，增加Cookie保活功能)

RUNNER_USER=${SUDO_USER:-$USER}

BOT_DIR="/opt/mjjvm"
ENV_FILE="$BOT_DIR/.env"
VENV_DIR="$BOT_DIR/mjjvm-venv"
SERVICE_FILE="/etc/systemd/system/mjjvm.service"
SCRIPT_URL="https://raw.githubusercontent.com/liaox321/mjjvm/main/2.py"
SCRIPT_PATH="$BOT_DIR/2.py"

# 检查并安装系统依赖
check_and_install() {
    if ! command -v python3 >/dev/null 2>&1; then
        echo "❌ 未找到 python3，正在安装..."
        apt-get update -y >/dev/null 2>&1
        apt-get install -y python3 python3-venv python3-pip >/dev/null 2>&1
        echo "✅ python3 安装完成"
    else
        echo "✅ python3 已安装"
    fi

    if ! command -v curl >/dev/null 2>&1; then
        echo "❌ 未找到 curl，正在安装..."
        apt-get install -y curl >/dev/null 2>&1
        echo "✅ curl 安装完成"
    else
        echo "✅ curl 已安装"
    fi
}

# 显示使用说明
show_usage() {
    echo "MJJVM 监控与签到管理脚本"
    echo "用法: $0 [install|config|uninstall]"
    echo "选项:"
    echo "  install       安装MJJVM监控与签到服务"
    echo "  config        修改配置"
    echo "  uninstall     卸载服务"
}

# 安装功能
install_service() {
    check_and_install

    echo "安装目录：$BOT_DIR"
    echo "脚本将以用户：$RUNNER_USER 来拥有并运行"

    mkdir -p "$BOT_DIR"
    chown -R "$RUNNER_USER:$RUNNER_USER" "$BOT_DIR"
    cd "$BOT_DIR" || { echo "无法切换到 $BOT_DIR"; exit 1; }

    echo "🔽 正在下载 MJJVM 脚本..."
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
    chown "$RUNNER_USER:$RUNNER_USER" "$SCRIPT_PATH"
    chmod +x "$SCRIPT_PATH"
    echo "✅ 脚本保存为 $SCRIPT_PATH"

    # 生成 .env 配置
    echo "📝 请按提示输入 ENV 配置"
    read -p "请输入方糖的 SendKey (空则跳过推送配置): " SCKEY
    read -p "请输入 MJJVM 的 Cookie (示例: PHPSESSID=xxxx; cf_clearance=xxxx) (可留空): " MJJVM_COOKIE
    read -p "请输入 MJJBOX 的 Cookie (用于签到功能) (示例: session=xxxx; token=xxxx) (可留空): " MJJBOX_COOKIE
    
    # 设置 Cookie 保活检查间隔
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
    } > "$ENV_FILE"
    
    chown "$RUNNER_USER:$RUNNER_USER" "$ENV_FILE"
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

    # 逐个安装依赖包
    echo "安装 cloudscraper..."
    sudo -u "$RUNNER_USER" "$VENV_DIR/bin/python" -m pip install --no-cache-dir cloudscraper
    echo "安装 beautifulsoup4..."
    sudo -u "$RUNNER_USER" "$VENV_DIR/bin/python" -m pip install --no-cache-dir beautifulsoup4
    echo "安装 python-dotenv..."
    sudo -u "$RUNNER_USER" "$VENV_DIR/bin/python" -m pip install --no-cache-dir python-dotenv
    echo "安装 requests..."
    sudo -u "$RUNNER_USER" "$VENV_DIR/bin/python" -m pip install --no-cache-dir requests
    echo "安装 playwright..."
    sudo -u "$RUNNER_USER" "$VENV_DIR/bin/python" -m pip install --no-cache-dir playwright

    echo "✅ Python 依赖安装完成"

    # 安装 Playwright 浏览器
    echo "⏳ 开始安装 Playwright 浏览器..."
    if sudo -u "$RUNNER_USER" "$VENV_DIR/bin/python" -m playwright install >/dev/null 2>&1; then
        echo "✅ Playwright 浏览器安装完成"
    else
        echo "⚠️ Playwright 浏览器安装遇到问题"
    fi

    # 写入 systemd 服务
    echo "⚙️ 写入 systemd 服务：$SERVICE_FILE"
    cat > "$SERVICE_FILE" << EOF
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
Environment=PATH=$VENV_DIR/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
EnvironmentFile=$ENV_FILE

[Install]
WantedBy=multi-user.target
EOF

    systemctl daemon-reload
    systemctl enable mjjvm
    systemctl restart mjjvm

    echo "✅ 安装完成，服务已启动"
    echo "查看服务状态： systemctl status mjjvm"
    echo "查看实时日志： journalctl -u mjjvm -f"
    
    echo -e "\n🔄 测试命令："
    echo "sudo -u $RUNNER_USER $VENV_DIR/bin/python $SCRIPT_PATH --test"
    echo "sudo -u $RUNNER_USER $VENV_DIR/bin/python $SCRIPT_PATH --sign-test"
    echo "sudo -u $RUNNER_USER $VENV_DIR/bin/python $SCRIPT_PATH --cookie-test"
}

# 修改配置功能
modify_config() {
    if [ ! -f "$ENV_FILE" ]; then
        echo "❌ 未找到 $ENV_FILE，请先安装"
        exit 1
    fi
    
    # 读取当前配置
    source "$ENV_FILE" || true

    echo -e "\n当前 SCKEY = ${SCKEY:-<未配置>}"
    read -p "是否修改 SCKEY? (y/n): " choice
    if [ "$choice" = "y" ]; then
        read -p "请输入新的 SCKEY (留空则清空): " new_sckey
        SCKEY="$new_sckey"
    fi

    echo -e "\n当前 MJJVM_COOKIE = ${MJJVM_COOKIE:-<未配置>}"
    read -p "是否修改 MJJVM_COOKIE? (y/n): " choice
    if [ "$choice" = "y" ]; then
        read -p "请输入新的 MJJVM_COOKIE (留空则清空): " new_cookie
        MJJVM_COOKIE="$new_cookie"
    fi
    
    echo -e "\n当前 MJJBOX_COOKIE = ${MJJBOX_COOKIE:-<未配置>}"
    read -p "是否修改 MJJBOX_COOKIE? (y/n): " choice
    if [ "$choice" = "y" ]; then
        read -p "请输入新的 MJJBOX_COOKIE (留空则清空): " new_mjjbox_cookie
        MJJBOX_COOKIE="$new_mjjbox_cookie"
    fi
    
    echo -e "\n当前 Cookie 保活检查间隔 = ${COOKIE_CHECK_INTERVAL:-14400} 秒"
    read -p "是否修改间隔时间? (y/n): " choice
    if [ "$choice" = "y" ]; then
        read -p "请输入新的间隔时间（秒）: " new_interval
        COOKIE_CHECK_INTERVAL="$new_interval"
    fi

    # 写入新配置
    {
        echo "SCKEY=${SCKEY}"
        echo "MJJVM_COOKIE=${MJJVM_COOKIE}"
        echo "MJJBOX_COOKIE=${MJJBOX_COOKIE}"
        echo "COOKIE_CHECK_INTERVAL=${COOKIE_CHECK_INTERVAL}"
    } > "$ENV_FILE"
    
    chown "$RUNNER_USER:$RUNNER_USER" "$ENV_FILE"
    chmod 600 "$ENV_FILE"
    systemctl restart mjjvm
    echo "✅ 配置已修改并重启服务"
}

# 卸载功能
uninstall_service() {
    echo "⚠️ 警告：此操作会停止服务并删除监控相关文件"
    read -p "是否继续卸载? (y/n): " choice
    if [ "$choice" != "y" ]; then
        echo "已取消"
        exit 1
    fi
    
    if [ -f "$SERVICE_FILE" ]; then
        systemctl stop mjjvm || true
        systemctl disable mjjvm || true
        rm -f "$SERVICE_FILE"
        systemctl daemon-reload
    fi
    
    rm -rf "$BOT_DIR"
    echo "✅ 已卸载并删除 $BOT_DIR 与 service 文件"
}

# 主程序
if [ $# -eq 0 ]; then
    show_usage
    exit 1
fi

case "$1" in
    install)
        install_service
        ;;
    config)
        modify_config
        ;;
    uninstall)
        uninstall_service
        ;;
    *)
        echo "❌ 无效选项: $1"
        show_usage
        exit 1
        ;;
esac

exit 0
