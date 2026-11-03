#!/usr/bin/env python3
"""Start the read-only dashboard on localhost by default."""
import argparse
from backend.config import load_config


def main():
    parser = argparse.ArgumentParser(description='币安资金费率监控面板（交易已锁定）')
    parser.add_argument('--host')
    parser.add_argument('--port', type=int)
    parser.add_argument('--config', default='config.ini')
    args = parser.parse_args()
    config = load_config(args.config)
    from backend.app import create_app
    app = create_app(args.config)
    host = args.host or config.server.host
    port = args.port or config.server.port
    print(f'监控面板: http://{host}:{port}，不发送任何交易订单', flush=True)
    try:
        app.run(host=host, port=port, debug=False, use_reloader=False)
    finally:
        app.extensions['engine'].stop()


if __name__ == '__main__':
    main()
