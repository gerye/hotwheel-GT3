#!/bin/bash
cd "$(dirname "$0")"
export PORT=8000

[ -d .venv ] || python3 -m venv .venv
source .venv/bin/activate
python -c "import fastapi, qrcode" 2>/dev/null || pip install -q -e .

# 关掉占用该端口的旧服务
lsof -ti tcp:$PORT | xargs kill -9 2>/dev/null
pkill -f "uvicorn app.main:app" 2>/dev/null

# 起来后自动打开浏览器
( sleep 2; open "http://localhost:$PORT" ) &

echo "====== 风火轮 GT3 正在运行 ======"
echo "本机访问: http://localhost:$PORT"
echo "手机访问: 扫描网页底部的二维码(需连同一 WiFi)"
echo "关闭此窗口即可停止服务。"

exec python -m uvicorn app.main:app --host 0.0.0.0 --port $PORT
