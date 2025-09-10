#!/bin/bash
set -euo pipefail

# 一键安装，创建 venv，安装依赖，注册 systemd
RUNNER_USER=${SUDO_USER:-$USER}

BOT_DIR="/opt/mjjvm"
ENV_FILE="$BOT_DIR/.env"
VENV_DIR="$BOT_DIR/mjjvm-venv"
SERVICE_FILE="/etc/systemd/system/mjjvm.service"
SCRIPT_URL="https://raw.githubusercontent.com/liaox321/mjjvm/main/2.py"
SCRIPT_PATH="$BOT_DIR/2.py"

# 安装前检查 Python 和 curl
check_and_install() {
    if ! command -v python3 >/dev/null 2>&1; then
        echo "❌ 未找到 Python3，正在安装..."
        sudo apt-get update -y >/dev/null 2>&1
        sudo apt-get install -y python3 python3-pip >/dev/null 2>&1
        echo "✅ Python3 安装完成"
    else
        echo "✅ Python3 已安装"
    fi

    if ! command -v curl >/dev/null 2>&1; then
        echo "❌ 未找到 curl，正在安装..."
        sudo apt-get install -y curl >/dev/null 2>&1
        echo "✅ curl 安装完成"
    else
        echo "✅ curl 已安装"
    fi
}

echo "请选择操作："
echo "1. 安装 MJJVM 监控"
echo "2. 修改 .env 配置"
echo "3. 卸载 MJJVM 监控"
read -p "输入选项 [1-3]: " ACTION

case $ACTION in
1)
    check_and_install
    
    echo "安装目录：$BOT_DIR"
    echo "脚本将以用户：$RUNNER_USER 来拥有并运行"

    sudo mkdir -p "$BOT_DIR"
    sudo chown -R "$RUNNER_USER:$RUNNER_USER" "$BOT_DIR"
    cd "$BOT_DIR" || { echo "无法切换到 $BOT_DIR"; exit 1; }

    echo "🔽 正在下载 MJJVM 脚本..."
    if command -v curl >/dev/null 2>&1; then
        sudo -u "$RUNNER_USER" curl -fsSL "$SCRIPT_URL" -o "$SCRIPT_PATH"
    elif command -v wget >/dev/null 2>&1; then
        sudo -u "$RUNNER_USER" wget -qO "$SCRIPT_PATH" "$SCRIPT_URL"
    else
        echo "❌ 未找到 curl 或 wget，请先安装其中一个工具。"
        exit 1
    fi

    if [ ! -s "$SCRIPT_PATH" ]; then
        echo "❌ 下载失败或文件为空：$SCRIPT_PATH"
        exit 1
    fi
    sudo chown "$RUNNER_USER:$RUNNER_USER" "$SCRIPT_PATH"
    chmod +x "$SCRIPT_PATH"
    echo "✅ 脚本下载并保存为 $SCRIPT_PATH"

    # 生成 .env，包含 SCKEY 和 MJJVM_COOKIE
    echo "📝 请按提示输入 ENV 配置（将写入 $ENV_FILE）"
    read -p "请输入方糖的 SendKey: " SCKEY
    read -p "请输入 MJJVM 的 Cookie (PHPSESSID=xxxx; other_cookie=xxxx): " MJJVM_COOKIE

    cat > "$ENV_FILE" <<EOF
SCKEY=$SCKEY
MJJVM_COOKIE="$MJJVM_COOKIE"
EOF
    sudo chown "$RUNNER_USER:$RUNNER_USER" "$ENV_FILE"
    chmod 600 "$ENV_FILE"
    echo "✅ 已生成 $ENV_FILE (权限 600)"

    # 创建虚拟环境
    if [ ! -d "$VENV_DIR" ]; then
        echo "🔧 创建虚拟环境..."
        sudo -u "$RUNNER_USER" python3 -m venv "$VENV_DIR"
        echo "✅ 虚拟环境已创建：$VENV_DIR"
    fi

    echo "📦 安装依赖..."
    "$VENV_DIR/bin/python" -m pip install --upgrade pip >/dev/null 2>&1
    REQUIRED_PKG=("cloudscraper" "beautifulsoup4" "python-dotenv")
    for pkg in "${REQUIRED_PKG[@]}"; do
        if ! "$VENV_DIR/bin/python" -m pip show "$pkg" >/dev/null 2>&1; then
            echo "安装 $pkg ..."
            "$VENV_DIR/bin/python" -m pip install "$pkg" >/dev/null 2>&1
        else
            echo "已安装: $pkg （跳过）"
        fi
    done
    echo "✅ 依赖安装完成（均安装在 $VENV_DIR）"

    # systemd 服务
    echo "⚙️ 写入 systemd 服务：$SERVICE_FILE"
    sudo tee "$SERVICE_FILE" > /dev/null <<EOF
[Unit]
Description=MJJVM Stock Monitor
After=network.target

[Service]
Type=simple
User=$RUNNER_USER
WorkingDirectory=$BOT_DIR
ExecStart=$VENV_DIR/bin/python $SCRIPT_PATH
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal
Environment=PATH=$VENV_DIR/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin

[Install]
WantedBy=multi-user.target
EOF

    sudo systemctl daemon-reload
    sudo systemctl enable mjjvm
    sudo systemctl restart mjjvm

    echo "✅ 安装完成，服务已启动：mjjvm 监控"
    echo "查看状态： sudo systemctl status mjjvm"
    echo "查看日志： sudo journalctl -u mjjvm -f"
    ;;

2)
    if [ ! -f "$ENV_FILE" ]; then
        echo "❌ 未找到 .env 文件，请先安装 mjjvm 监控！"
        exit 1
    fi
    echo "📝 修改 ENV 配置（当前配置存储在 $ENV_FILE）"
    source "$ENV_FILE"
    CHANGED=0

    echo -e "\n当前 SendKey = $SCKEY"
    read -p "是否修改 SendKey? (y/n): " choice
    if [[ "$choice" == "y" ]]; then
        read -p "请输入新的 SendKey: " new_value
        SCKEY="$new_value"
        CHANGED=1
    fi

    echo -e "\n当前 MJJVM_COOKIE = $MJJVM_COOKIE"
    read -p "是否修改 MJJVM_COOKIE? (y/n): " choice
    if [[ "$choice" == "y" ]]; then
        read -p "请输入新的 MJJVM_COOKIE: " new_cookie
        MJJVM_COOKIE="$new_cookie"
        CHANGED=1
    fi

    if [[ $CHANGED -eq 1 ]]; then
        cat > "$ENV_FILE" <<EOF
SCKEY=$SCKEY
MJJVM_COOKIE="$MJJVM_COOKIE"
EOF
        sudo chown "$RUNNER_USER:$RUNNER_USER" "$ENV_FILE"
        chmod 600 "$ENV_FILE"
        sudo systemctl restart mjjvm
        echo "✅ 配置已修改并重启服务"
    else
        echo "ℹ️ 配置未修改，服务无需重启"
    fi
    ;;

3)
    echo "⚠️ 警告：此操作会删除 mjjvm 监控 服务和相关文件"
    read -p "是否继续卸载? (y/n): " choice
    if [[ "$choice" != "y" ]]; then
        echo "❌ 已取消卸载"
        exit 1
    fi
    if [ -f "$SERVICE_FILE" ]; then
        echo "🛑 停止 mjjvm 服务..."
        sudo systemctl stop mjjvm
        sudo systemctl disable mjjvm
    fi
    echo "🗑 删除监控文件..."
    sudo rm -rf "$BOT_DIR"
    echo "🗑 删除 systemd 服务文件..."
    sudo rm -f "$SERVICE_FILE"
    sudo systemctl daemon-reload
    echo "✅ 卸载完成"
    ;;

*)
    echo "❌ 无效选项"
    exit 1
    ;;
esac
