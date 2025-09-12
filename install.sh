#!/bin/bash
set -euo pipefail

# MJJVM 监控与签到安装脚本（修复版）
# 修复语法错误，确保脚本可靠运行

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
        echo "安装 python3..."
        apt-get update -y
        apt-get install -y python3 python3-venv python3-pip
    fi

    if ! command -v curl >/dev/null 2>&1; then
        echo "安装 curl..."
        apt-get install -y curl
    fi
}

# 显示使用说明
show_usage() {
    echo "MJJVM 监控安装脚本"
    echo "用法: $0 [install|config|uninstall]"
}

# 主函数
main() {
    if [ $# -eq 0 ]; then
        show_usage
        exit 1
    fi

    case "$1" in
        "install")
            check_and_install

            echo "创建安装目录 $BOT_DIR"
            mkdir -p "$BOT_DIR"
            chown -R "$RUNNER_USER:$RUNNER_USER" "$BOT_DIR"
            cd "$BOT_DIR" || exit 1

            echo "下载脚本文件..."
            if command -v curl >/dev/null 2>&1; then
                curl -fsSL "$SCRIPT_URL" -o "$SCRIPT_PATH" || exit 1
            else
                echo "错误: 需要 curl 但未安装"
                exit 1
            fi

            chmod +x "$SCRIPT_PATH"
            echo "脚本下载完成: $SCRIPT_PATH"

            # 配置环境变量
            echo "配置环境变量..."
            read -p "请输入方糖 SendKey: " SCKEY
            read -p "请输入 MJJVM Cookie: " MJJVM_COOKIE
            read -p "请输入 MJJBOX Cookie: " MJJBOX_COOKIE

            cat > "$ENV_FILE" << EOF
SCKEY=$SCKEY
MJJVM_COOKIE=$MJJVM_COOKIE
MJJBOX_COOKIE=$MJJBOX_COOKIE
COOKIE_CHECK_INTERVAL=14400
EOF

            chmod 600 "$ENV_FILE"

            # 创建虚拟环境
            echo "创建虚拟环境..."
            python3 -m venv "$VENV_DIR"

            # 安装依赖
            echo "安装 Python 依赖..."
            "$VENV_DIR/bin/python" -m pip install --upgrade pip
            "$VENV_DIR/bin/python" -m pip install cloudscraper beautifulsoup4 python-dotenv requests playwright

            # 安装 Playwright
            echo "安装 Playwright 浏览器..."
            "$VENV_DIR/bin/python" -m playwright install

            # 创建 systemd 服务
            echo "创建 systemd 服务..."
            cat > "$SERVICE_FILE" << EOF
[Unit]
Description=MJJVM Stock Monitor
After=network.target

[Service]
Type=simple
User=$RUNNER_USER
WorkingDirectory=$BOT_DIR
ExecStart=$VENV_DIR/bin/python $SCRIPT_PATH
Restart=always
RestartSec=10
EnvironmentFile=$ENV_FILE

[Install]
WantedBy=multi-user.target
EOF

            systemctl daemon-reload
            systemctl enable mjjvm
            systemctl start mjjvm

            echo "安装完成！服务已启动。"
            ;;

        "config")
            if [ ! -f "$ENV_FILE" ]; then
                echo "错误: 未找到配置文件 $ENV_FILE"
                exit 1
            fi

            echo "修改配置..."
            read -p "请输入新的方糖 SendKey: " SCKEY
            read -p "请输入新的 MJJVM Cookie: " MJJVM_COOKIE
            read -p "请输入新的 MJJBOX Cookie: " MJJBOX_COOKIE

            cat > "$ENV_FILE" << EOF
SCKEY=$SCKEY
MJJVM_COOKIE=$MJJVM_COOKIE
MJJBOX_COOKIE=$MJJBOX_COOKIE
COOKIE_CHECK_INTERVAL=14400
EOF

            systemctl restart mjjvm
            echo "配置已更新，服务已重启。"
            ;;

        "uninstall")
            echo "卸载 MJJVM 监控..."
            systemctl stop mjjvm || true
            systemctl disable mjjvm || true
            rm -f "$SERVICE_FILE"
            systemctl daemon-reload
            rm -rf "$BOT_DIR"
            echo "卸载完成。"
            ;;

        *)
            echo "错误: 未知选项 $1"
            show_usage
            exit 1
            ;;
    esac
}

# 检查是否以 root 运行
if [ "$EUID" -ne 0 ]; then
    echo "请使用 root 权限运行此脚本 (sudo)"
    exit 1
fi

# 执行主函数
main "$@"
