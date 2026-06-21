"""Docker 启动入口：等待数据库、执行迁移、种子数据、启动服务。"""
import os
import sys
import time

import pymysql


def wait_db():
    cfg = dict(
        host=os.getenv("DB_HOST", "db"),
        port=int(os.getenv("DB_PORT", "3306")),
        user=os.getenv("DB_USER", "show"),
        password=os.getenv("DB_PASSWORD", "show123"),
        database=os.getenv("DB_NAME", "show_ticketing"),
    )
    print("[entrypoint] 等待数据库就绪...", flush=True)
    for i in range(60):
        try:
            conn = pymysql.connect(**cfg)
            conn.close()
            print("数据库已就绪", flush=True)
            return
        except Exception as exc:
            print(f"等待数据库... ({i + 1}) {exc}", flush=True)
            time.sleep(2)
    raise SystemExit("数据库在超时时间内未就绪")


def run(cmd):
    print(f"\n[entrypoint] 执行: {cmd}", flush=True)
    ret = os.system(cmd)
    if ret != 0:
        raise SystemExit(f"命令失败: {cmd} (exit={ret})")


def main():
    wait_db()
    run("python manage.py makemigrations tickets --noinput")
    run("python manage.py migrate --noinput")
    run("python manage.py seed")
    print("\n[entrypoint] 启动服务...", flush=True)
    os.execvp(
        "gunicorn",
        ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:7652", "--workers", "2"],
    )


if __name__ == "__main__":
    main()
