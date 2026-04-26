#!/usr/bin/env python3
"""
币安套利机器人启动脚本
"""
import os
import sys
import argparse

# 添加 backend 到路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'backend'))


def create_data_folders():
    """创建必要的数据目录"""
    folders = ['data', 'logs']
    for folder in folders:
        os.makedirs(os.path.join(os.path.dirname(__file__), folder), exist_ok=True)


def main():
    parser = argparse.ArgumentParser(description='BNB 永续合约套利机器人')
    parser.add_argument('--host', default='0.0.0.0', help='服务器地址')
    parser.add_argument('--port', type=int, default=5000, help='服务器端口')
    parser.add_argument('--debug', action='store_true', help='调试模式')
    parser.add_argument('--config', default='config.ini', help='配置文件路径')

    args = parser.parse_args()

    # 创建目录
    create_data_folders()

    # 导入并启动应用
    os.environ['CONFIG_PATH'] = args.config

    from backend.app import app

    print(f"""
╔════════════════════════════════════════════════════════════╗
║                                                            ║
║   🤖 BNB 永续合约套利机器人                                ║
║                                                            ║
║   启动中...                                                 ║
║   地址: http://{args.host}:{args.port}                         ║
║                                                            ║
╚════════════════════════════════════════════════════════════╝
    """)

    app.run(
        host=args.host,
        port=args.port,
        debug=args.debug
    )


if __name__ == '__main__':
    main()
